"""Self-RAG 평가기의 Gemini 어댑터 테스트.

langchain-google-genai 를 걷어내고 프로젝트 공용 GoogleLLMClient(llm_factory 계층)로 바꾼 뒤에도
평가기 호출부가 기대하는 모양(`await llm.ainvoke(prompt)` → `.content`)을 유지해야 한다.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.modules.core.self_rag.evaluator import LLMQualityEvaluator, _GoogleEvaluatorLLM


@pytest.mark.asyncio
async def test_adapter_calls_project_google_client_and_returns_content() -> None:
    with patch("app.modules.core.self_rag.evaluator.GoogleLLMClient") as client_cls:
        client_cls.return_value.generate_text = AsyncMock(return_value='{"relevance": 0.9}')
        adapter = _GoogleEvaluatorLLM(
            model="gemini-2.0-flash", api_key="k", temperature=0.0, timeout_seconds=7.5
        )
        response = await adapter.ainvoke("prompt")

    client_cls.assert_called_once_with(
        {"api_key": "k", "model": "gemini-2.0-flash", "temperature": 0.0, "timeout": 7.5}
    )
    client_cls.return_value.generate_text.assert_awaited_once_with(
        "prompt", model="gemini-2.0-flash", temperature=0.0
    )
    assert response.content == '{"relevance": 0.9}'
    assert adapter.model == "gemini-2.0-flash"


def test_evaluator_builds_adapter_when_google_key_present() -> None:
    with patch("app.modules.core.self_rag.evaluator.GoogleLLMClient"):
        evaluator = LLMQualityEvaluator(llm_provider="google", model_name="gemini-x", api_key="k")
    assert isinstance(evaluator.llm, _GoogleEvaluatorLLM)
    assert evaluator.is_available


def test_evaluator_without_key_is_unavailable() -> None:
    evaluator = LLMQualityEvaluator(llm_provider="google", api_key=None)
    assert evaluator.llm is None
    assert not evaluator.is_available


def test_adapter_warns_when_evaluation_key_differs_from_global(monkeypatch, caplog) -> None:
    """평가용 키가 GOOGLE_API_KEY 와 다르면 SDK 전역 키가 바뀐다는 경고를 남긴다."""
    monkeypatch.setenv("GOOGLE_API_KEY", "main-key")
    with patch("app.modules.core.self_rag.evaluator.GoogleLLMClient"):
        with caplog.at_level("WARNING"):
            _GoogleEvaluatorLLM(model="m", api_key="other-key")
    assert "self_rag_evaluator_key_overrides_global_sdk_key" in caplog.text
