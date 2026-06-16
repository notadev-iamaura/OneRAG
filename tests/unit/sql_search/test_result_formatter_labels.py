"""
SQL ResultFormatter LLM 컨텍스트 라벨 외부화 테스트 (12차 범용화)

format_for_context 등이 LLM 컨텍스트에 주입하는 엔티티명 폴백/빈결과
안내가 한국어로 하드코딩(entity_name_fields는 config화됐는데 폴백 라벨만
누락된 비대칭)이던 것을 sql_search.yaml formatter 키로 외부화한 변경을
검증한다(미설정/null 시 한국어 기본 → 회귀 0).
"""

from app.modules.core.sql_search.query_executor import QueryResult
from app.modules.core.sql_search.result_formatter import ResultFormatter


def _empty_result() -> QueryResult:
    return QueryResult(
        success=True, data=[], row_count=0, execution_time=0.0, sql_query="SELECT 1"
    )


def _error_result() -> QueryResult:
    return QueryResult(
        success=False,
        data=[],
        row_count=0,
        execution_time=0.0,
        sql_query="SELECT 1",
        error="syntax error",
    )


class TestDefaultKoreanLabels:
    def test_defaults_when_unset(self):
        f = ResultFormatter()
        assert f.unknown_entity_label == "알 수 없음"
        assert f.no_results_message == "검색 결과가 없습니다."

    def test_null_config_falls_back_to_default(self):
        """yaml null → 한국어 기본값 폴백 (회귀 0)."""
        f = ResultFormatter(
            {
                "unknown_entity_label": None,
                "no_results_message": None,
                "error_message_template": None,
                "no_match_message": None,
            }
        )
        assert f.unknown_entity_label == "알 수 없음"
        assert f.no_results_message == "검색 결과가 없습니다."

    def test_empty_result_uses_korean_default(self):
        f = ResultFormatter()
        assert f.format_as_list(_empty_result()) == "검색 결과가 없습니다."


class TestOverrideLabels:
    def test_override_unknown_entity_and_messages(self):
        f = ResultFormatter(
            {
                "unknown_entity_label": "Unknown",
                "no_results_message": "No results found.",
                "error_message_template": "[SQL error: {error}]",
                "no_match_message": "[No matching rows]",
            }
        )
        assert f.format_as_list(_empty_result()) == "No results found."
        assert f.format_for_context(_error_result(), "q") == "[SQL error: syntax error]"
        row = QueryResult(
            success=True,
            data=[{"value": 5}],
            row_count=1,
            execution_time=0.0,
            sql_query="SELECT 1",
        )
        # 엔티티명 필드가 없으면 폴백 라벨(영어)로 렌더
        assert "Unknown" in f.format_as_list(row)


class TestResultHeaderAndTruncation:
    def _rows(self, n: int, truncated: bool, total: int) -> QueryResult:
        return QueryResult(
            success=True,
            data=[{"value": i} for i in range(n)],
            row_count=n,
            execution_time=0.0,
            sql_query="SELECT 1",
            metadata={"truncated": truncated, "total_rows": total},
        )

    def test_default_korean_header_and_truncation(self):
        """미설정 시 한국어 헤더/truncation 안내 유지 (회귀 0)."""
        f = ResultFormatter({"max_items": 2})
        out = f.format_for_context(self._rows(2, True, 10), "q")
        assert out.startswith("[SQL 검색 결과]")
        assert "(총 10개 중 상위 2개 표시)" in out

    def test_override_header_and_truncation(self):
        f = ResultFormatter(
            {
                "max_items": 2,
                "result_header": "[SQL Results]",
                "truncation_notice_template": "\n(showing {shown} of {total})",
            }
        )
        out = f.format_for_context(self._rows(2, True, 10), "q")
        assert out.startswith("[SQL Results]")
        assert "(showing 2 of 10)" in out
        assert "총" not in out
