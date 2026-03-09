"""
Result Formatter 모듈

SQL 쿼리 결과를 Answer Generation LLM에 전달할 형식으로 포맷합니다.

주요 기능:
- 쿼리 결과를 사람이 읽기 쉬운 텍스트로 변환
- 비용 정보 포맷팅 (원 단위)
- RAG 컨텍스트 형식으로 변환
"""

from __future__ import annotations

from typing import Any

from ....lib.logger import get_logger
from .query_executor import QueryResult

logger = get_logger(__name__)


class ResultFormatter:
    """
    Result Formatter - SQL 결과 포맷터

    SQL 쿼리 결과를 Answer Generation LLM이 이해하기 쉬운
    형식으로 변환합니다.
    """

    # 기본 비용 관련 필드
    DEFAULT_NUMERIC_FIELDS = frozenset(
        [
            "value",
            "cost",
            "price",
            "amount",
        ]
    )

    def __init__(self, config: dict[str, Any] | None = None):
        """
        Result Formatter 초기화

        Args:
            config: 포맷팅 설정
        """
        self.config = config or {}
        self.max_items = self.config.get("max_items", 10)

        # 설정에서 수치형 필드 로드
        numeric_fields = self.config.get("numeric_fields", [])
        self.numeric_fields = self.DEFAULT_NUMERIC_FIELDS.union(numeric_fields)

    def format_for_context(self, query_result: QueryResult, user_query: str) -> str:
        """
        SQL 결과를 RAG 컨텍스트 형식으로 포맷합니다.

        Args:
            query_result: SQL 쿼리 실행 결과
            user_query: 원본 유저 쿼리 (참고용)

        Returns:
            str: 포맷된 컨텍스트 문자열
        """
        if not query_result.success:
            return f"[SQL 검색 결과 없음: {query_result.error}]"

        if query_result.is_empty:
            return "[SQL 검색 결과: 조건에 맞는 항목이 없습니다]"

        # 결과 포맷팅
        lines = ["[SQL 검색 결과]"]

        for i, row in enumerate(query_result.data[: self.max_items], 1):
            line = self._format_row(row, i)
            lines.append(line)

        # 추가 정보
        if query_result.metadata.get("truncated"):
            total = query_result.metadata.get("total_rows", 0)
            lines.append(f"\n(총 {total}개 중 상위 {self.max_items}개 표시)")

        return "\n".join(lines)

    def format_as_markdown(self, query_result: QueryResult) -> str:
        """
        SQL 결과를 마크다운 테이블 형식으로 포맷합니다.

        Args:
            query_result: SQL 쿼리 실행 결과

        Returns:
            str: 마크다운 테이블 문자열
        """
        if not query_result.success or query_result.is_empty:
            return "검색 결과가 없습니다."

        # 컬럼 헤더 추출
        if not query_result.data:
            return "검색 결과가 없습니다."

        columns = list(query_result.data[0].keys())

        # 헤더 생성
        header = "| " + " | ".join(str(col) for col in columns) + " |"
        separator = "| " + " | ".join("---" for _ in columns) + " |"

        # 데이터 행 생성
        rows = []
        for row in query_result.data[: self.max_items]:
            formatted_values = []
            for col in columns:
                value = row.get(col)
                if col in self.numeric_fields and isinstance(value, int | float):
                    formatted_values.append(self._format_cost(value))
                else:
                    formatted_values.append(str(value) if value is not None else "-")
            rows.append("| " + " | ".join(formatted_values) + " |")

        return "\n".join([header, separator, *rows])

    def format_as_list(self, query_result: QueryResult) -> str:
        """
        SQL 결과를 번호 목록 형식으로 포맷합니다.

        Args:
            query_result: SQL 쿼리 실행 결과

        Returns:
            str: 번호 목록 문자열
        """
        if not query_result.success or query_result.is_empty:
            return "검색 결과가 없습니다."

        lines = []
        for i, row in enumerate(query_result.data[: self.max_items], 1):
            line = self._format_row(row, i)
            lines.append(line)

        return "\n".join(lines)

    def _format_row(self, row: dict[str, Any], index: int) -> str:
        """
        단일 행을 포맷합니다. (범용 방식)

        Args:
            row: 데이터 행
            index: 행 번호

        Returns:
            str: 포맷된 행 문자열
        """
        # 설정에서 엔티티 이름 필드 목록 가져오기
        name_fields = self.config.get("entity_name_fields", ["name", "title", "entity_name"])

        # 첫 번째로 매칭되는 필드를 엔티티 이름으로 사용
        entity_name = "알 수 없음"
        for field in name_fields:
            if row.get(field):
                entity_name = str(row[field])
                break

        # value 찾기 (수치형 데이터)
        value = row.get("value")

        # 카테고리 찾기
        category = row.get("category", "")

        # 기본 형식: "1. 항목명: 값"
        if value is not None:
            if isinstance(value, int | float):
                return f"{index}. {entity_name}: {self._format_cost(value)}"
            return f"{index}. {entity_name}: {value}"

        # value가 없으면 모든 필드 나열
        parts = [f"{index}. {entity_name}"]

        # 제외할 시스템 필드 (이름 필드들 및 시스템 필드)
        exclude_fields = set(name_fields)
        exclude_fields.update(["category", "source_page_id", "id", "uuid"])

        for key, val in row.items():
            if key in exclude_fields:
                continue
            if val is not None:
                if key in self.numeric_fields and isinstance(val, int | float):
                    parts.append(f"{key}={self._format_cost(val)}")
                else:
                    parts.append(f"{key}={val}")

        if category:
            parts.insert(1, f"[{category}]")

        return " ".join(parts)

    def _format_cost(self, value: int | float) -> str:
        """
        비용을 한국어 형식으로 포맷합니다.

        Args:
            value: 비용 (원)

        Returns:
            str: 포맷된 비용 문자열
        """
        if value >= 10000:
            # 만원 단위
            man = int(value // 10000)
            remainder = int(value % 10000)
            if remainder == 0:
                return f"{man}만원"
            return f"{man}만{remainder:,}원"
        return f"{int(value):,}원"

    def get_summary(self, query_result: QueryResult) -> dict[str, Any]:
        """
        SQL 결과의 요약 정보를 반환합니다.

        Args:
            query_result: SQL 쿼리 실행 결과

        Returns:
            dict: 요약 정보
        """
        return {
            "success": query_result.success,
            "row_count": query_result.row_count,
            "execution_time": query_result.execution_time,
            "has_data": not query_result.is_empty,
            "error": query_result.error,
        }
