"""
Query Executor 모듈

생성된 SQL 쿼리를 PostgreSQL에서 실행하고 결과를 반환합니다.
기존 DatabaseManager를 활용하여 연결을 관리합니다.

주요 기능:
- SQL 쿼리 실행 (SELECT만 허용)
- 결과를 딕셔너리 리스트로 변환
- 쿼리 타임아웃 및 에러 핸들링
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import text

from ....infrastructure.persistence.connection import DatabaseManager
from ....lib.logger import get_logger

logger = get_logger(__name__)


@dataclass
class QueryResult:
    """쿼리 실행 결과 데이터 클래스"""

    success: bool
    data: list[dict[str, Any]]
    row_count: int
    execution_time: float
    sql_query: str
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_empty(self) -> bool:
        """결과가 비어있는지 확인"""
        return self.row_count == 0

    def to_dict(self) -> dict[str, Any]:
        """딕셔너리로 변환"""
        return {
            "success": self.success,
            "data": self.data,
            "row_count": self.row_count,
            "execution_time": self.execution_time,
            "error": self.error,
        }


class QueryExecutor:
    """
    Query Executor - SQL 쿼리 실행기

    기존 DatabaseManager의 세션을 사용하여 SQL을 실행합니다.
    SELECT 쿼리만 허용하며, 타임아웃 처리를 제공합니다.
    """

    def __init__(
        self,
        db_manager: DatabaseManager,
        config: dict[str, Any] | None = None,
    ):
        """
        Query Executor 초기화

        Args:
            db_manager: DatabaseManager 인스턴스
            config: 실행 설정 (timeout 등)
        """
        self.db_manager = db_manager
        self.config = config or {}

        # 설정값
        self.timeout = self.config.get("timeout", 10)  # 초
        self.max_rows = self.config.get("max_rows", 100)  # 최대 반환 행 수

        logger.info(f"QueryExecutor 초기화: timeout={self.timeout}s, max_rows={self.max_rows}")

    async def execute(self, sql_query: str) -> QueryResult:
        """
        SQL 쿼리를 실행하고 결과를 반환합니다.

        Args:
            sql_query: 실행할 SQL 쿼리 (SELECT만 허용)

        Returns:
            QueryResult: 실행 결과
        """
        start_time = time.time()

        # SELECT 쿼리인지 재확인 (안전 검증)
        if not sql_query.strip().upper().startswith("SELECT"):
            return QueryResult(
                success=False,
                data=[],
                row_count=0,
                execution_time=0,
                sql_query=sql_query,
                error="SELECT 쿼리만 허용됩니다",
            )

        try:
            logger.info(f"SQL 실행: {sql_query[:100]}...")

            async with self.db_manager.get_session() as session:
                # text()로 감싸서 raw SQL 실행
                result = await session.execute(text(sql_query))

                # 결과를 딕셔너리 리스트로 변환
                rows = result.fetchall()
                columns = result.keys()

                data = []
                for row in rows[: self.max_rows]:  # 최대 행 수 제한
                    row_dict = dict(zip(columns, row, strict=False))
                    data.append(row_dict)

                execution_time = time.time() - start_time

                logger.info(f"SQL 실행 완료: {len(data)}행, {execution_time:.3f}초")

                return QueryResult(
                    success=True,
                    data=data,
                    row_count=len(data),
                    execution_time=execution_time,
                    sql_query=sql_query,
                    metadata={"total_rows": len(rows), "truncated": len(rows) > self.max_rows},
                )

        except Exception as e:
            execution_time = time.time() - start_time
            logger.error(f"SQL 실행 실패: {e}")

            return QueryResult(
                success=False,
                data=[],
                row_count=0,
                execution_time=execution_time,
                sql_query=sql_query,
                error=str(e),
            )

    async def execute_safe(self, sql_query: str) -> QueryResult:
        """
        SQL 쿼리를 안전하게 실행합니다 (타임아웃 포함).

        Args:
            sql_query: 실행할 SQL 쿼리

        Returns:
            QueryResult: 실행 결과
        """
        import asyncio

        try:
            return await asyncio.wait_for(
                self.execute(sql_query),
                timeout=self.timeout,
            )
        except TimeoutError:
            logger.warning(f"SQL 실행 타임아웃: {self.timeout}초 초과")
            return QueryResult(
                success=False,
                data=[],
                row_count=0,
                execution_time=self.timeout,
                sql_query=sql_query,
                error=f"쿼리 실행 타임아웃 ({self.timeout}초 초과)",
            )

    async def test_connection(self) -> bool:
        """
        데이터베이스 연결을 테스트합니다.

        Returns:
            bool: 연결 성공 여부
        """
        try:
            result = await self.execute("SELECT 1 AS test")
            return result.success and result.row_count == 1
        except Exception as e:
            logger.error(f"연결 테스트 실패: {e}")
            return False

    async def get_table_stats(self) -> dict[str, int]:
        """
        메타데이터 테이블의 통계를 조회합니다.

        Returns:
            dict: 테이블별 행 수
        """
        stats = {}
        tables = self.config.get("tables", [])

        for table in tables:
            # SQL Injection 방어: 테이블명 화이트리스트 검증
            if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", table):
                logger.warning(f"유효하지 않은 테이블명 차단: {table}")
                stats[table] = -1
                continue
            result = await self.execute(f"SELECT COUNT(*) AS count FROM {table}")
            if result.success and result.data:
                stats[table] = result.data[0].get("count", 0)
            else:
                stats[table] = -1  # 에러 표시

        return stats
