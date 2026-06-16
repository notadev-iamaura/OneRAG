"""OpenAI 호환 /v1 멀티턴 대화 히스토리 주입 테스트 (GAP #1 차용).

검증 대상:
- _build_chat_history_from_messages: messages 배열에서 마지막 user를 제외한
  user/assistant 교환을 {"messages":[{"type","content"}...]} 포맷으로 변환.
- stateless /v1 요청이 session 모듈에 직전 턴을 주입(add_conversation)해 파이프라인의
  standalone-rewrite/anchor 소비 배선이 직전 맥락을 참조하도록 한다.
- session 모듈이 없거나 단일 user 메시지면 주입 없이 기존 동작과 동일(회귀 0).
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routers.openai_compat_router import _build_chat_history_from_messages


def _msg(role: str, content: str) -> SimpleNamespace:
    return SimpleNamespace(role=role, content=content)


def test_build_chat_history_excludes_last_user() -> None:
    """마지막 user(현재 질문)는 제외하고 직전 교환만 담는다."""
    messages = [
        _msg("system", "you are helpful"),
        _msg("user", "RAG란?"),
        _msg("assistant", "검색 증강 생성입니다."),
        _msg("user", "그것의 장점은?"),  # 현재 질문(마지막 user) → 제외
    ]
    history = _build_chat_history_from_messages(messages)
    assert history == {
        "messages": [
            {"type": "user", "content": "RAG란?"},
            {"type": "assistant", "content": "검색 증강 생성입니다."},
        ]
    }


def test_build_chat_history_single_user_returns_none() -> None:
    """직전 교환이 없으면(단일 user) None을 반환한다."""
    messages = [_msg("system", "sys"), _msg("user", "안녕")]
    assert _build_chat_history_from_messages(messages) is None


def test_build_chat_history_ignores_system_in_history() -> None:
    """히스토리에는 user/assistant만 담고 system은 제외한다."""
    messages = [
        _msg("user", "첫 질문"),
        _msg("assistant", "첫 답변"),
        _msg("system", "중간 시스템"),
        _msg("user", "후속 질문"),
    ]
    history = _build_chat_history_from_messages(messages)
    assert history is not None
    types = [m["type"] for m in history["messages"]]
    assert "system" not in types
    assert types == ["user", "assistant"]


def _build_pipeline_mock() -> MagicMock:
    pipeline = MagicMock()
    pipeline.route_query = AsyncMock(
        return_value=SimpleNamespace(metadata={"data_source": "default"})
    )
    pipeline.prepare_context = AsyncMock(
        return_value=SimpleNamespace(
            expanded_query="확장된 쿼리",
            expanded_queries=["확장1"],
            query_weights=[1.0],
            session_context=None,
            anchor_sources=[],
        )
    )
    pipeline.retrieve_documents = AsyncMock(
        return_value=SimpleNamespace(
            documents=[SimpleNamespace(content="문서", metadata={})], count=1
        )
    )
    pipeline.rerank_documents = AsyncMock(
        return_value=SimpleNamespace(
            documents=[SimpleNamespace(content="문서", metadata={})], count=1
        )
    )
    return pipeline


def _client_with_session() -> tuple[TestClient, MagicMock, MagicMock]:
    """session 모듈을 가진 chat_service를 주입한 TestClient를 만든다."""
    from app.api.routers.openai_compat_router import router, set_modules

    pipeline = _build_pipeline_mock()

    session_module = MagicMock()
    session_module.create_session = AsyncMock(return_value={"session_id": "ephemeral"})
    session_module.add_conversation = AsyncMock()
    session_module.delete_session = AsyncMock()

    chat_service = SimpleNamespace(
        rag_pipeline=pipeline,
        modules={"session": session_module},
    )

    llm_client = AsyncMock()
    llm_client.generate_text = AsyncMock(return_value="답변")
    factory = MagicMock()
    factory.get_client = MagicMock(return_value=llm_client)

    set_modules({"llm_factory": factory, "chat_service": chat_service, "retrieval": MagicMock()})
    app = FastAPI()
    app.include_router(router)
    return TestClient(app), session_module, pipeline


def test_multiturn_history_seeded_into_session() -> None:
    """멀티턴 /v1 요청이 직전 교환을 session 모듈에 주입해야 한다."""
    client, session_module, _pipeline = _client_with_session()
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "gemini",
            "messages": [
                {"role": "user", "content": "RAG란?"},
                {"role": "assistant", "content": "검색 증강 생성입니다."},
                {"role": "user", "content": "그 장점은?"},
            ],
        },
    )
    assert response.status_code == 200
    # 직전 교환(user RAG란? / assistant 검색증강…)이 ephemeral 세션에 주입돼야 한다
    session_module.create_session.assert_awaited()
    session_module.add_conversation.assert_awaited()
    call = session_module.add_conversation.await_args
    assert call.kwargs.get("user_message") == "RAG란?" or call.args[1] == "RAG란?"


def test_single_user_message_no_session_seed() -> None:
    """단일 user 메시지면 세션 주입을 생략한다(기존 동작 보존)."""
    client, session_module, _pipeline = _client_with_session()
    response = client.post(
        "/v1/chat/completions",
        json={"model": "gemini", "messages": [{"role": "user", "content": "안녕"}]},
    )
    assert response.status_code == 200
    session_module.add_conversation.assert_not_awaited()
