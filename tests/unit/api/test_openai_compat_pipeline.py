"""OpenAI 호환 /v1 경로의 RAG 파이프라인 재사용 회귀 테스트.

검증 대상(차용 #14):
- chat_service가 주입되면 /v1/chat/completions가 메인 채팅과 동일한 검색 체인
  (route_query → prepare_context → retrieve_documents → rerank_documents)을
  재사용한다(멀티쿼리·rerank 일관화).
- chat_service가 없으면 기존 retriever.search 단순 검색으로 폴백한다.
- 파이프라인 검색이 실패하면 단순 검색으로 폴백한다.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _build_pipeline_mock() -> MagicMock:
    """RAGPipeline 4단계 stage를 모두 구현한 Mock을 만든다."""
    pipeline = MagicMock()
    pipeline.route_query = AsyncMock(
        return_value=SimpleNamespace(
            should_continue=True,
            immediate_response=None,
            metadata={"data_source": "default"},
        )
    )
    pipeline.prepare_context = AsyncMock(
        return_value=SimpleNamespace(
            expanded_query="확장된 쿼리",
            expanded_queries=["확장1", "확장2"],
            query_weights=[1.0, 0.8],
            session_context=None,
        )
    )
    retrieved_doc = SimpleNamespace(content="검색된 문서", metadata={})
    pipeline.retrieve_documents = AsyncMock(
        return_value=SimpleNamespace(documents=[retrieved_doc], count=1)
    )
    reranked_doc = SimpleNamespace(content="리랭킹된 문서", metadata={})
    pipeline.rerank_documents = AsyncMock(
        return_value=SimpleNamespace(documents=[reranked_doc], count=1, reranked=True)
    )
    return pipeline


@pytest.fixture
def mock_modules_with_chat_service():
    """chat_service(파이프라인 포함)와 llm_factory를 주입하는 모듈 딕셔너리."""
    mock_llm_client = AsyncMock()
    mock_llm_client.generate_text = AsyncMock(return_value="RAG 답변")
    mock_factory = MagicMock()
    mock_factory.get_client = MagicMock(return_value=mock_llm_client)

    pipeline = _build_pipeline_mock()
    chat_service = SimpleNamespace(rag_pipeline=pipeline)

    # 폴백 검증용 retriever도 함께 둔다
    mock_retriever = AsyncMock()
    fallback_result = MagicMock()
    fallback_result.content = "폴백 문서"
    fallback_result.score = 0.5
    mock_retriever.search = AsyncMock(return_value=[fallback_result])

    return {
        "llm_factory": mock_factory,
        "chat_service": chat_service,
        "retrieval": mock_retriever,
        "_pipeline": pipeline,
        "_retriever": mock_retriever,
    }


def _client(modules: dict) -> TestClient:
    from app.api.routers.openai_compat_router import router, set_modules

    set_modules(modules)
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_pipeline_stages_reused_when_chat_service_present(mock_modules_with_chat_service):
    """chat_service 주입 시 rerank_documents까지 파이프라인 stage가 호출되어야 한다."""
    client = _client(mock_modules_with_chat_service)
    response = client.post(
        "/v1/chat/completions",
        json={"model": "gemini", "messages": [{"role": "user", "content": "RAG란?"}]},
    )
    assert response.status_code == 200

    pipeline = mock_modules_with_chat_service["_pipeline"]
    pipeline.prepare_context.assert_awaited_once()
    pipeline.retrieve_documents.assert_awaited_once()
    pipeline.rerank_documents.assert_awaited_once()
    # 단순 검색(retriever.search)은 호출되지 않아야 한다
    mock_modules_with_chat_service["_retriever"].search.assert_not_called()


def test_falls_back_to_retriever_when_no_chat_service():
    """chat_service가 없으면 retriever.search 단순 검색으로 폴백해야 한다."""
    mock_llm_client = AsyncMock()
    mock_llm_client.generate_text = AsyncMock(return_value="답변")
    mock_factory = MagicMock()
    mock_factory.get_client = MagicMock(return_value=mock_llm_client)

    mock_retriever = AsyncMock()
    result = MagicMock()
    result.content = "문서"
    result.score = 0.9
    mock_retriever.search = AsyncMock(return_value=[result])

    modules = {"llm_factory": mock_factory, "retrieval": mock_retriever}
    client = _client(modules)
    response = client.post(
        "/v1/chat/completions",
        json={"model": "gemini", "messages": [{"role": "user", "content": "질문"}]},
    )
    assert response.status_code == 200
    mock_retriever.search.assert_called_once()


def test_falls_back_to_retriever_when_pipeline_raises(mock_modules_with_chat_service):
    """파이프라인 검색이 실패하면 단순 검색으로 폴백해야 한다."""
    pipeline = mock_modules_with_chat_service["_pipeline"]
    pipeline.prepare_context = AsyncMock(side_effect=RuntimeError("pipeline boom"))

    client = _client(mock_modules_with_chat_service)
    response = client.post(
        "/v1/chat/completions",
        json={"model": "gemini", "messages": [{"role": "user", "content": "질문"}]},
    )
    assert response.status_code == 200
    # 파이프라인 실패 → retriever.search 폴백 호출
    mock_modules_with_chat_service["_retriever"].search.assert_called_once()


def test_streaming_reuses_pipeline_when_chat_service_present(mock_modules_with_chat_service):
    """스트리밍 경로도 chat_service 주입 시 파이프라인 stage를 재사용해야 한다."""
    async def mock_stream(*args, **kwargs):
        for token in ["안", "녕"]:
            yield token

    mock_modules_with_chat_service["llm_factory"].get_client().stream_text = mock_stream

    client = _client(mock_modules_with_chat_service)
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "gemini",
            "messages": [{"role": "user", "content": "질문"}],
            "stream": True,
        },
    )
    assert response.status_code == 200
    pipeline = mock_modules_with_chat_service["_pipeline"]
    pipeline.retrieve_documents.assert_awaited()
    pipeline.rerank_documents.assert_awaited()
