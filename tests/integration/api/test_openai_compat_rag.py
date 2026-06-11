"""
OpenAI 호환 API의 RAG 검색 호출 정합성 통합 테스트 (Phase 2.1 / Phase 0.3)

목적:
    /v1/chat/completions가 실제로 문서 검색을 수행하는지 검증한다.
    핵심: FakeRetriever는 실제 주입체(RetrievalOrchestrator)와 동일한
    search(query, options) 시그니처를 가진다. AsyncMock과 달리 시그니처가
    엄격하므로, 라우터가 top_k= 키워드로 잘못 호출하면 TypeError가 발생해
    검색이 무력화되는 회귀를 잡아낸다.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routers import openai_compat_router
from app.modules.core.retrieval.interfaces import SearchResult

# integration 마커: 기본 CI test 잡은 tests/integration을 ignore하므로
# 별도 P0 회귀 스텝(ci.yml) 또는 `-m integration`으로 실행된다.
pytestmark = pytest.mark.integration


class FakeRetriever:
    """RetrievalOrchestrator.search(query, options)와 동일한 시그니처 stub."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any] | None]] = []

    async def search(
        self, query: str, options: dict[str, Any] | None = None
    ) -> list[SearchResult]:
        self.calls.append((query, options))
        return [
            SearchResult(
                id="doc-1",
                content="OneRAG는 범용 RAG 베이스 시스템입니다",
                score=0.95,
                metadata={},
            )
        ]


class FakeLLMClient:
    def __init__(self) -> None:
        self.last_prompt: str | None = None

    async def generate_text(
        self,
        prompt: str,
        system_prompt: str | None = None,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        self.last_prompt = prompt
        return "검색 문서를 반영한 답변"


class FakeLLMFactory:
    def __init__(self) -> None:
        self.client = FakeLLMClient()

    def get_client(self, provider: str) -> FakeLLMClient:
        return self.client


@pytest.fixture
def client_and_fakes() -> Any:
    app = FastAPI()
    app.include_router(openai_compat_router.router)
    retriever = FakeRetriever()
    llm_factory = FakeLLMFactory()
    openai_compat_router.set_modules(
        {"retrieval": retriever, "llm_factory": llm_factory}
    )
    try:
        yield TestClient(app), retriever, llm_factory
    finally:
        openai_compat_router.set_modules({})


def test_v1_completions_invokes_retrieval_with_correct_signature(
    client_and_fakes: Any,
) -> None:
    """검색이 (query, options) 형태로 정확히 호출되고 문서가 프롬프트에 반영돼야 한다."""
    client, retriever, llm_factory = client_and_fakes
    resp = client.post(
        "/v1/chat/completions",
        json={
            "model": "gemini",
            "messages": [{"role": "user", "content": "OneRAG가 뭐야?"}],
        },
    )
    assert resp.status_code == 200, resp.text

    # 검색이 실제로 1회 호출됐는지 (시그니처 불일치면 TypeError로 0회)
    assert len(retriever.calls) == 1, "검색이 호출되지 않음 (시그니처 불일치로 무력화)"
    query, options = retriever.calls[0]
    assert query == "OneRAG가 뭐야?"
    assert options == {"limit": 5}

    # 검색 문서가 LLM 프롬프트에 반영됐는지
    assert llm_factory.client.last_prompt is not None
    assert "OneRAG는 범용 RAG 베이스 시스템입니다" in llm_factory.client.last_prompt
