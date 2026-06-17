"""
LLM 컨텍스트 라벨 외부화 테스트 (18차 범용화)

LLM 입력에 섞여 들어가는 한국어 라벨(문서 블록 '[문서 N]', SQL 멀티쿼리
카테고리 헤더/폴백 '전체', SQL Source 폴백)을 언어 프로파일/config로
외부화한 변경을 검증한다. 미설정 시 한국어 기본(회귀 0), 영어 프로파일/
config 시 영어 라벨 → 비한국어 운영자 출력 언어 일관성.
"""

from typing import Any
from unittest.mock import MagicMock

from app.api.services.rag_pipeline import RAGPipeline
from app.modules.core.generation.generator import (
    _CONTEXT_BLOCK_LABEL,
    GenerationModule,
)
from app.modules.core.sql_search.service import SQLSearchService


def _gen() -> GenerationModule:
    g = GenerationModule.__new__(GenerationModule)
    g.gen_config = {}  # type: ignore[attr-defined]
    return g


class TestContextBlockLabel:
    def test_default_korean(self):
        g = _gen()
        assert g._resolve_context_block_label(None) == "[문서"
        assert g._resolve_context_block_label(None) == _CONTEXT_BLOCK_LABEL

    def test_english_profile(self):
        g = _gen()
        assert g._resolve_context_block_label({"response_language": "en"}) == "[Document"

    def test_write_parse_sync_korean(self):
        """ko: 쓰기 '[문서 N]' + 파싱이 같은 라벨로 헤더 라인을 스킵(회귀 0)."""
        g = _gen()
        ctx = g._build_context([{"content": "값 100원"}], None)
        assert "[문서 1]" in ctx
        # 파싱(체크리스트)은 '[문서' 라벨 라인을 스킵하므로 헤더가 후보에 안 들어감
        checklist = g._format_answer_checklist("질문", ctx, context_block_label="[문서")
        assert "[문서 1]" not in checklist

    def test_write_parse_sync_english(self):
        """en: 쓰기 '[Document N]' + 파싱이 동일 영어 라벨로 스킵(desync 없음)."""
        g = _gen()
        opts = {"response_language": "en"}
        ctx = g._build_context([{"content": "value 100 usd"}], opts)
        assert "[Document 1]" in ctx
        label = g._resolve_context_block_label(opts)
        checklist = g._format_answer_checklist("question", ctx, context_block_label=label)
        assert "[Document 1]" not in checklist


class TestSqlMultiQueryLabels:
    def _service(self, config: dict[str, Any]) -> SQLSearchService:
        return SQLSearchService(config=config, db_manager=MagicMock())

    def test_defaults_korean(self):
        s = self._service({})
        assert s.all_category_label == "전체"
        assert s.category_section_header_template == "=== {category} 검색 결과 ==="

    def test_override(self):
        s = self._service(
            {
                "multi_query": {
                    "all_category_label": "All",
                    "category_section_header_template": "=== {category} results ===",
                }
            }
        )
        assert s.all_category_label == "All"
        assert s.category_section_header_template.format(category="FAQ") == "=== FAQ results ==="


class TestRagSqlSourceLabels:
    def _pipeline_with_labels(self, sql_multi_query: dict[str, Any]) -> RAGPipeline:
        p = RAGPipeline.__new__(RAGPipeline)
        cfg = {"sql_search": {"multi_query": sql_multi_query}}
        # __init__의 라벨 해소 로직만 재현(전체 생성자는 무거움)
        mq = cfg.get("sql_search", {}).get("multi_query", {})
        p._sql_all_category_label = mq.get("all_category_label") or "전체"
        p._sql_entity_name_fallback_template = (
            mq.get("entity_name_fallback_template") or "결과 {index}"
        )
        p._sql_preview_fallback = mq.get("preview_fallback") or "SQL 쿼리 결과"
        p.privacy_masker = None  # type: ignore[attr-defined]
        return p

    def test_default_entity_fallback(self):
        """엔티티명 없는 행 → 한국어 폴백 '결과 1' + 미리보기 폴백 'SQL 쿼리 결과'(회귀 0)."""
        p = self._pipeline_with_labels({})
        src = p._format_sql_row(row={}, row_idx=0, source_id=1, sql_query=None, category=None)
        # 정규화 페이로드 어딘가에 폴백 라벨이 사용됨(키 구조 무관)
        assert "결과 1" in str(src)
        assert "SQL 쿼리 결과" in str(src)

    def test_override_entity_fallback(self):
        p = self._pipeline_with_labels(
            {"entity_name_fallback_template": "Result {index}", "preview_fallback": "SQL result"}
        )
        src = p._format_sql_row(row={}, row_idx=2, source_id=1, sql_query=None, category=None)
        assert "Result 3" in str(src)
        assert "SQL result" in str(src)
        assert "결과 3" not in str(src)
