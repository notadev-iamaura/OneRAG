# tests/unit/api/test_openai_compat_prompt_override.py
"""
OpenAI 호환 API RAG 프롬프트 외부화 단위 테스트

/v1/chat/completions RAG 모드의 래퍼 프롬프트('다음 참고문서를 기반으로...', '## 참고문서',
'## 질문', '[문서 N]')를 config/env로 오버라이드하는 경로를 검증한다.

핵심 철칙:
- 회귀 0: 아무것도 주입하지 않으면 기존 한국어 프롬프트와 byte-identical.
- 데드키 금지: 추가한 env/config 키를 _build_rag_prompt가 실제로 읽음을 증명.
- 우선순위: config(_modules["config"]) > env > 코드 내장 기본값.
"""

from __future__ import annotations

import pytest

from app.api.routers import openai_compat_router as oc


@pytest.fixture
def restore_modules():
    """테스트 종료 시 라우터의 전역 _modules를 원복한다(테스트 격리)."""
    original = oc._modules
    yield
    oc.set_modules(original)


# 검색된 문서 fixture(2건) — context 조립 검증용
DOCS: list[dict[str, str]] = [
    {"content": "RAG는 검색 증강 생성입니다."},
    {"content": "Weaviate는 하이브리드 검색을 지원합니다."},
]

QUERY = "RAG란 무엇인가요?"


# 기대되는 한국어 기본 프롬프트(외부화 이전과 byte-identical해야 하는 정답지).
# 절대 _build_rag_prompt 구현으로 계산하지 않고, 하드코딩하여 회귀를 잡는다.
EXPECTED_DEFAULT_PROMPT = (
    "다음 참고문서를 기반으로 질문에 답변하세요.\n\n"
    "## 참고문서\n"
    "[문서 1]\n"
    "RAG는 검색 증강 생성입니다.\n\n"
    "[문서 2]\n"
    "Weaviate는 하이브리드 검색을 지원합니다.\n\n"
    "## 질문\n"
    "RAG란 무엇인가요?"
)


class TestDefaultKoreanPrompt:
    """미설정 시 기존 한국어 동작 유지(회귀 0)"""

    def test_no_override_is_byte_identical(self, restore_modules, monkeypatch):
        """env/config 미설정 시 한국어 기본 프롬프트와 byte-identical."""
        monkeypatch.delenv(oc.ENV_RAG_PROMPT_TEMPLATE, raising=False)
        monkeypatch.delenv(oc.ENV_RAG_DOC_ITEM_TEMPLATE, raising=False)
        oc.set_modules({})  # config 미주입

        result = oc._build_rag_prompt(QUERY, DOCS)

        assert result == EXPECTED_DEFAULT_PROMPT

    def test_no_override_empty_docs_returns_query(self, restore_modules, monkeypatch):
        """문서가 없으면 질문 원문 그대로 반환(외부화 영향 없음)."""
        monkeypatch.delenv(oc.ENV_RAG_PROMPT_TEMPLATE, raising=False)
        monkeypatch.delenv(oc.ENV_RAG_DOC_ITEM_TEMPLATE, raising=False)
        oc.set_modules({})

        assert oc._build_rag_prompt(QUERY, []) == QUERY

    def test_blank_env_falls_back_to_default(self, restore_modules, monkeypatch):
        """공백 env는 무시하고 기본값으로 폴백(byte-identical)."""
        monkeypatch.setenv(oc.ENV_RAG_PROMPT_TEMPLATE, "   ")
        monkeypatch.setenv(oc.ENV_RAG_DOC_ITEM_TEMPLATE, "")
        oc.set_modules({})

        assert oc._build_rag_prompt(QUERY, DOCS) == EXPECTED_DEFAULT_PROMPT


class TestEnvOverride:
    """환경 변수 오버라이드(영어/타도메인 전환)"""

    def test_env_prompt_template_override(self, restore_modules, monkeypatch):
        """OPENAI_COMPAT_RAG_PROMPT_TEMPLATE로 래퍼 문구 영어화."""
        monkeypatch.setenv(
            oc.ENV_RAG_PROMPT_TEMPLATE,
            "Answer using the docs.\n\n## Docs\n{context}\n\n## Q\n{query}",
        )
        monkeypatch.delenv(oc.ENV_RAG_DOC_ITEM_TEMPLATE, raising=False)
        oc.set_modules({})

        result = oc._build_rag_prompt(QUERY, DOCS)

        assert result.startswith("Answer using the docs.")
        assert "## Docs" in result
        assert "## Q" in result
        # 항목 템플릿은 미오버라이드 → 기본 '[문서 N]' 라벨 유지
        assert "[문서 1]" in result
        assert QUERY in result
        # 한국어 기본 래퍼 문구는 사라져야 함(실제 오버라이드 증명)
        assert "다음 참고문서를 기반으로" not in result

    def test_env_doc_item_template_override(self, restore_modules, monkeypatch):
        """OPENAI_COMPAT_RAG_DOC_ITEM_TEMPLATE로 항목 라벨 영어화."""
        monkeypatch.delenv(oc.ENV_RAG_PROMPT_TEMPLATE, raising=False)
        monkeypatch.setenv(
            oc.ENV_RAG_DOC_ITEM_TEMPLATE, "[Document {index}]\n{content}"
        )
        oc.set_modules({})

        result = oc._build_rag_prompt(QUERY, DOCS)

        assert "[Document 1]" in result
        assert "[Document 2]" in result
        assert "[문서 1]" not in result
        # 래퍼는 미오버라이드 → 한국어 기본 유지
        assert result.startswith("다음 참고문서를 기반으로 질문에 답변하세요.")


class TestConfigOverride:
    """config(_modules["config"]) 오버라이드 및 우선순위"""

    def test_config_prompt_template_override(self, restore_modules, monkeypatch):
        """주입된 config의 openai_compat.rag_prompt_template를 읽음(데드키 아님)."""
        monkeypatch.delenv(oc.ENV_RAG_PROMPT_TEMPLATE, raising=False)
        monkeypatch.delenv(oc.ENV_RAG_DOC_ITEM_TEMPLATE, raising=False)

        config = {
            "openai_compat": {
                "rag_prompt_template": "CFG:\n{context}\n---\n{query}",
            }
        }
        oc.set_modules({"config": config})

        result = oc._build_rag_prompt(QUERY, DOCS)

        assert result.startswith("CFG:")
        assert "---" in result
        assert QUERY in result
        assert "다음 참고문서를 기반으로" not in result

    def test_config_beats_env(self, restore_modules, monkeypatch):
        """우선순위: config > env (config 주입 시 env는 무시)."""
        monkeypatch.setenv(oc.ENV_RAG_PROMPT_TEMPLATE, "ENV:\n{context}\n{query}")

        config = {
            "openai_compat": {
                "rag_prompt_template": "CONFIG_WINS:\n{context}\n{query}",
            }
        }
        oc.set_modules({"config": config})

        result = oc._build_rag_prompt(QUERY, DOCS)

        assert result.startswith("CONFIG_WINS:")
        assert "ENV:" not in result

    def test_config_object_with_get_method(self, restore_modules, monkeypatch):
        """config가 dict가 아닌 .get()을 지원하는 객체여도 동작(실 배선 호환)."""
        monkeypatch.delenv(oc.ENV_RAG_PROMPT_TEMPLATE, raising=False)

        class ConfigLike:
            """rag_app.config 처럼 .get(section)이 dict를 반환하는 객체."""

            def get(self, key: str, default=None):
                if key == "openai_compat":
                    return {"rag_prompt_template": "OBJ:\n{context}\n{query}"}
                return default

        oc.set_modules({"config": ConfigLike()})

        result = oc._build_rag_prompt(QUERY, DOCS)

        assert result.startswith("OBJ:")

    def test_missing_config_section_falls_back(self, restore_modules, monkeypatch):
        """config에 openai_compat 섹션이 없으면 env/기본값으로 폴백(회귀 0)."""
        monkeypatch.delenv(oc.ENV_RAG_PROMPT_TEMPLATE, raising=False)
        monkeypatch.delenv(oc.ENV_RAG_DOC_ITEM_TEMPLATE, raising=False)
        oc.set_modules({"config": {"other_section": {}}})

        assert oc._build_rag_prompt(QUERY, DOCS) == EXPECTED_DEFAULT_PROMPT
