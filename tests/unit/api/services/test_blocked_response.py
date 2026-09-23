"""Shared refusal text used by blocked routing paths."""

from app.api.routers import openai_compat_router
from app.api.services.blocked_response import DEFAULT_BLOCKED_ANSWER
from app.api.services.rag_pipeline import RAGPipeline


def test_blocked_response_has_single_default() -> None:
    assert RAGPipeline._DEFAULT_BLOCKED_ANSWER == DEFAULT_BLOCKED_ANSWER
    assert not hasattr(openai_compat_router, "_DEFAULT_BLOCKED_ANSWER")
