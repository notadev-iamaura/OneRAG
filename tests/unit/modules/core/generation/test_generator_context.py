"""GenerationModule._build_context 컨텍스트 문서 한도 테스트.

#3 회귀 방지: 기본 한도는 5(비용 최적화)이지만 인접 청크 확장으로 문서가 늘면
호출부가 max_context_documents를 올려 실제 히트가 프롬프트에서 밀려나지 않게 한다.
"""

from unittest.mock import MagicMock

from app.modules.core.generation.generator import (
    DEFAULT_CONTEXT_DOCUMENT_LIMIT,
    MAX_CONTEXT_DOCUMENT_LIMIT,
    GenerationModule,
)


def _module() -> GenerationModule:
    return GenerationModule(config={}, prompt_manager=MagicMock())


def test_build_context_uses_default_limit() -> None:
    mod = _module()
    docs = [f"문서{i}" for i in range(10)]
    text = mod._build_context(docs)
    assert text.count("[문서") == DEFAULT_CONTEXT_DOCUMENT_LIMIT


def test_build_context_honors_expanded_budget() -> None:
    mod = _module()
    docs = [f"문서{i}" for i in range(20)]
    text = mod._build_context(docs, options={"max_context_documents": 20})
    # 확장 예산(최대 20)까지 실제 히트가 보존되어야 한다.
    assert text.count("[문서") == MAX_CONTEXT_DOCUMENT_LIMIT


def test_build_context_preserves_lower_ranked_hit_under_expanded_budget() -> None:
    mod = _module()
    docs = [f"문서{i}" for i in range(8)]  # index 5~7은 기존 [:5] 캡에서 잘리던 히트
    text = mod._build_context(docs, options={"max_context_documents": 20})
    assert "문서7" in text  # 6번째 이후 히트도 프롬프트에 포함되어야 함


def test_context_document_limit_clamps_and_defaults() -> None:
    mod = _module()
    assert mod._context_document_limit(None) == DEFAULT_CONTEXT_DOCUMENT_LIMIT
    assert mod._context_document_limit({}) == DEFAULT_CONTEXT_DOCUMENT_LIMIT
    assert mod._context_document_limit({"max_context_documents": 999}) == MAX_CONTEXT_DOCUMENT_LIMIT
    assert mod._context_document_limit({"max_context_documents": "bad"}) == (
        DEFAULT_CONTEXT_DOCUMENT_LIMIT
    )
