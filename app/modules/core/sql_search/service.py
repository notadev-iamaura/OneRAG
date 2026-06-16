"""
SQL Search Service 모듈

SQL Generator, Query Executor, Result Formatter를 통합하여
SQL 검색 파이프라인을 제공합니다.

주요 기능:
- 유저 쿼리 → SQL 생성 → 실행 → 포맷팅 전체 파이프라인
- RAG 파이프라인과 병렬 실행 지원
- 활성화/비활성화 설정
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from ....lib.logger import get_logger

if TYPE_CHECKING:
    from ....infrastructure.persistence.connection import DatabaseManager
    from .query_executor import QueryResult
    from .sql_generator import SingleSQLQuery, SQLGenerationResult

logger = get_logger(__name__)


@dataclass
class SingleQueryResult:
    """멀티 쿼리 중 개별 쿼리 실행 결과"""

    query: SingleSQLQuery
    result: QueryResult | None
    formatted_context: str
    success: bool
    error: str | None = None


@dataclass
class SQLSearchResult:
    """SQL 검색 전체 파이프라인 결과 (멀티 쿼리 지원)"""

    # 성공 여부
    success: bool

    # SQL 생성 결과
    generation_result: SQLGenerationResult | None

    # 쿼리 실행 결과 (단일 쿼리 - 하위 호환성)
    query_result: QueryResult | None

    # 포맷된 컨텍스트 (Answer Generation에 전달)
    formatted_context: str

    # 메타데이터
    total_time: float
    used: bool  # SQL이 실제로 사용되었는지
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    # 멀티 쿼리 지원 필드
    is_multi_query: bool = False
    query_results: list[SingleQueryResult] = field(default_factory=list)

    @property
    def total_row_count(self) -> int:
        """전체 결과 행 수 (멀티 쿼리 포함)"""
        if self.is_multi_query:
            return sum(qr.result.row_count if qr.result else 0 for qr in self.query_results)
        return self.query_result.row_count if self.query_result else 0

    @property
    def all_query_results(self) -> list[QueryResult]:
        """모든 QueryResult 반환 (멀티 쿼리 지원)"""
        if self.is_multi_query:
            return [qr.result for qr in self.query_results if qr.result]
        return [self.query_result] if self.query_result else []

    def to_dict(self) -> dict[str, Any]:
        """딕셔너리로 변환"""
        result = {
            "success": self.success,
            "used": self.used,
            "formatted_context": self.formatted_context,
            "total_time": self.total_time,
            "error": self.error,
            "is_multi_query": self.is_multi_query,
            "generation": (
                {
                    "needs_sql": (
                        self.generation_result.needs_sql if self.generation_result else False
                    ),
                    "template_used": (
                        self.generation_result.template_used if self.generation_result else None
                    ),
                    "query_count": (
                        self.generation_result.query_count if self.generation_result else 0
                    ),
                }
                if self.generation_result
                else None
            ),
            "query": self.query_result.to_dict() if self.query_result else None,
        }

        # 멀티 쿼리 결과 추가
        if self.is_multi_query and self.query_results:
            result["multi_query_results"] = [
                {
                    "target_category": qr.query.target_category,
                    "sql_query": qr.query.sql_query,
                    "success": qr.success,
                    "row_count": qr.result.row_count if qr.result else 0,
                    "error": qr.error,
                }
                for qr in self.query_results
            ]

        return result


class SQLSearchService:
    """
    SQL Search Service - SQL 검색 통합 서비스

    SQL 생성, 실행, 포맷팅을 하나의 파이프라인으로 통합합니다.
    RAG 파이프라인에서 병렬로 실행되어 결과를 제공합니다.
    """

    def __init__(
        self,
        config: dict[str, Any],
        db_manager: DatabaseManager,
        api_key: str | None = None,
    ):
        """
        SQL Search Service 초기화

        Args:
            config: SQL 검색 설정
            db_manager: DatabaseManager 인스턴스
        api_key: OpenRouter API 키
        """
        from .query_executor import QueryExecutor
        from .result_formatter import ResultFormatter
        from .sql_generator import SQLGenerator

        self.config = config
        self.enabled: bool = bool(config.get("enabled", True))

        # 컴포넌트 초기화
        self.generator = SQLGenerator(
            config=config.get("generator", {}),
            api_key=api_key,
        )
        self.executor = QueryExecutor(
            db_manager=db_manager,
            config=config.get("executor", {}),
        )
        self.formatter = ResultFormatter(
            config=config.get("formatter", {}),
        )

        # 멀티쿼리 LLM 컨텍스트 라벨(출력 언어 일관성용 — formatter 라벨과 동일 패턴 외부화).
        # 미설정 시 한국어 기본값(회귀 0). 비한국어 운영자는 sql_search.yaml의
        # multi_query.* 로 자국어/영어 라벨을 주입한다.
        multi_query_cfg = config.get("multi_query", {})
        self.category_section_header_template: str = (
            multi_query_cfg.get("category_section_header_template")
            or "=== {category} 검색 결과 ==="
        )
        self.all_category_label: str = multi_query_cfg.get("all_category_label") or "전체"

        logger.info(f"SQLSearchService 초기화: enabled={self.enabled}")

    async def search(self, user_query: str) -> SQLSearchResult:
        """
        유저 쿼리에 대한 SQL 검색을 수행합니다.
        단일 쿼리와 멀티 쿼리 모두 지원합니다.

        전체 파이프라인:
        1. LLM이 SQL 생성 (단일 또는 멀티 쿼리)
        2. SQL 실행 (멀티 쿼리는 병렬 실행)
        3. 결과 포맷팅

        Args:
            user_query: 유저의 원본 질문

        Returns:
            SQLSearchResult: 전체 파이프라인 결과
        """
        start_time = time.time()

        # 비활성화된 경우
        if not self.enabled:
            return SQLSearchResult(
                success=False,
                generation_result=None,
                query_result=None,
                formatted_context="",
                total_time=0,
                used=False,
                error="SQL 검색이 비활성화되어 있습니다",
            )

        try:
            # 1. SQL 생성
            logger.info(f"SQL 검색 시작: {user_query[:50]}...")
            generation_result = await self.generator.generate(user_query)

            if not generation_result.is_success:
                return SQLSearchResult(
                    success=False,
                    generation_result=generation_result,
                    query_result=None,
                    formatted_context="",
                    total_time=time.time() - start_time,
                    used=False,
                    error=generation_result.error or "SQL 생성 실패",
                )

            # SQL이 필요 없는 경우
            if not generation_result.needs_sql:
                return SQLSearchResult(
                    success=True,
                    generation_result=generation_result,
                    query_result=None,
                    formatted_context="",
                    total_time=time.time() - start_time,
                    used=False,
                    metadata={"reason": generation_result.explanation},
                )

            # 2. SQL 실행 (멀티 쿼리 분기)
            if generation_result.is_multi_query and generation_result.queries:
                return await self._execute_multi_query(user_query, generation_result, start_time)
            else:
                return await self._execute_single_query(user_query, generation_result, start_time)

        except Exception as e:
            logger.error(f"SQL 검색 중 오류: {e}")
            return SQLSearchResult(
                success=False,
                generation_result=None,
                query_result=None,
                formatted_context="",
                total_time=time.time() - start_time,
                used=False,
                error=str(e),
            )

    async def _execute_single_query(
        self,
        user_query: str,
        generation_result: SQLGenerationResult,
        start_time: float,
    ) -> SQLSearchResult:
        """
        단일 SQL 쿼리 실행 (기존 로직)

        Args:
            user_query: 유저의 원본 질문
            generation_result: SQL 생성 결과
            start_time: 시작 시간

        Returns:
            SQLSearchResult: 실행 결과
        """
        if not generation_result.sql_query:
            return SQLSearchResult(
                success=False,
                generation_result=generation_result,
                query_result=None,
                formatted_context="",
                total_time=time.time() - start_time,
                used=False,
                error="SQL 쿼리가 생성되지 않았습니다",
            )

        query_result = await self.executor.execute_safe(generation_result.sql_query)

        if not query_result.success:
            return SQLSearchResult(
                success=False,
                generation_result=generation_result,
                query_result=query_result,
                formatted_context="",
                total_time=time.time() - start_time,
                used=False,
                error=query_result.error or "SQL 실행 실패",
            )

        # 결과 포맷팅
        formatted_context = self.formatter.format_for_context(query_result, user_query)

        total_time = time.time() - start_time
        logger.info(
            f"SQL 검색 완료: {query_result.row_count}개 결과, "
            f"template={generation_result.template_used}, "
            f"time={total_time:.3f}s"
        )

        return SQLSearchResult(
            success=True,
            generation_result=generation_result,
            query_result=query_result,
            formatted_context=formatted_context,
            total_time=total_time,
            used=not query_result.is_empty,
            is_multi_query=False,
            metadata={
                "template_used": generation_result.template_used,
                "row_count": query_result.row_count,
            },
        )

    async def _execute_multi_query(
        self,
        user_query: str,
        generation_result: SQLGenerationResult,
        start_time: float,
    ) -> SQLSearchResult:
        """
        멀티 SQL 쿼리 병렬 실행

        Args:
            user_query: 유저의 원본 질문
            generation_result: SQL 생성 결과 (멀티 쿼리)
            start_time: 시작 시간

        Returns:
            SQLSearchResult: 전체 실행 결과 (모든 쿼리 결과 포함)
        """
        logger.info(f"멀티 쿼리 실행 시작: {len(generation_result.queries)}개 쿼리")

        # 병렬 실행을 위한 태스크 생성
        async def execute_single(query: SingleSQLQuery) -> SingleQueryResult:
            """개별 쿼리 실행"""
            try:
                result = await self.executor.execute_safe(query.sql_query)
                if result.success:
                    formatted = self.formatter.format_for_context(
                        result,
                        f"{user_query} ({query.target_category or self.all_category_label})",
                    )
                    return SingleQueryResult(
                        query=query,
                        result=result,
                        formatted_context=formatted,
                        success=True,
                    )
                else:
                    return SingleQueryResult(
                        query=query,
                        result=result,
                        formatted_context="",
                        success=False,
                        error=result.error,
                    )
            except Exception as e:
                logger.error(f"멀티 쿼리 개별 실행 오류: {e}")
                return SingleQueryResult(
                    query=query,
                    result=None,
                    formatted_context="",
                    success=False,
                    error=str(e),
                )

        # 모든 쿼리 병렬 실행
        tasks = [execute_single(q) for q in generation_result.queries]
        query_results = await asyncio.gather(*tasks, return_exceptions=False)

        # 성공한 결과만 필터링
        successful_results = [qr for qr in query_results if qr.success]
        total_row_count = sum(qr.result.row_count if qr.result else 0 for qr in successful_results)

        # 전체 컨텍스트 합치기 (카테고리별 구분)
        combined_contexts = []
        for qr in successful_results:
            if qr.formatted_context:
                category = qr.query.target_category or self.all_category_label
                header = self.category_section_header_template.format(
                    category=category.upper()
                )
                combined_contexts.append(f"{header}\n{qr.formatted_context}")

        formatted_context = "\n\n".join(combined_contexts)

        total_time = time.time() - start_time
        logger.info(
            f"멀티 쿼리 완료: {len(successful_results)}/{len(query_results)}개 성공, "
            f"총 {total_row_count}개 결과, time={total_time:.3f}s"
        )

        # 첫 번째 성공 결과를 하위 호환성용으로 사용
        first_result = successful_results[0].result if successful_results else None

        return SQLSearchResult(
            success=len(successful_results) > 0,
            generation_result=generation_result,
            query_result=first_result,  # 하위 호환성
            formatted_context=formatted_context,
            total_time=total_time,
            used=total_row_count > 0,
            is_multi_query=True,
            query_results=list(query_results),
            metadata={
                "query_count": len(generation_result.queries),
                "success_count": len(successful_results),
                "total_row_count": total_row_count,
            },
        )

    async def health_check(self) -> dict[str, Any]:
        """
        서비스 상태를 확인합니다.

        Returns:
            dict: 상태 정보
        """
        result = {
            "enabled": self.enabled,
            "db_connected": False,
            "table_stats": {},
        }

        if self.enabled:
            result["db_connected"] = await self.executor.test_connection()
            if result["db_connected"]:
                result["table_stats"] = await self.executor.get_table_stats()

        return result

    def is_enabled(self) -> bool:
        """서비스 활성화 여부"""
        return self.enabled

    def enable(self) -> None:
        """서비스 활성화"""
        self.enabled = True
        logger.info("SQL 검색 서비스 활성화")

    def disable(self) -> None:
        """서비스 비활성화"""
        self.enabled = False
        logger.info("SQL 검색 서비스 비활성화")
