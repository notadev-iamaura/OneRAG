"""
리랭커 v2.1 설정 배선 테스트 (Phase 2.3)

목적:
    reranking.yaml의 approach/provider/model 3단계 구조가 실제로 반영되는지
    검증한다. 레거시 경로는 존재하지 않는 default_provider 키를 참조해 항상
    gemini_flash로 폴백했다.
"""

from __future__ import annotations

import pytest

from app.modules.core.retrieval.rerankers.factory import RerankerFactoryV2


def test_factory_honors_llm_google_approach(monkeypatch: pytest.MonkeyPatch) -> None:
    """approach=llm/provider=google 설정 시 GeminiFlashReranker를 생성해야 한다."""
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")
    config = {
        "reranking": {
            "enabled": True,
            "approach": "llm",
            "provider": "google",
            "google": {"model": "gemini-flash-lite-latest"},
        }
    }
    reranker = RerankerFactoryV2.create(config)
    assert reranker.__class__.__name__ == "GeminiFlashReranker"


def test_factory_rejects_invalid_approach_provider_combo() -> None:
    """approach-provider 조합이 유효하지 않으면 ValueError를 던져야 한다."""
    config = {
        "reranking": {
            "enabled": True,
            "approach": "llm",
            "provider": "jina",  # jina는 llm approach에서 유효하지 않음
        }
    }
    with pytest.raises(ValueError):
        RerankerFactoryV2.create(config)


def test_container_base_reranker_uses_v2() -> None:
    """di_container의 base_reranker가 v2 생성 함수에 배선돼 있어야 한다."""
    import inspect

    from app.core import di_container

    source = inspect.getsource(di_container.AppContainer)
    # base_reranker가 create_reranker_instance_v2를 사용해야 함
    assert "create_reranker_instance_v2, config=config" in source
