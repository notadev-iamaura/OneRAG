# tests/unit/api/test_openai_compat_router.py
"""
OpenAI 호환 API 라우터 단위 테스트

/v1/chat/completions, /v1/models 엔드포인트를 테스트합니다.
LLM과 검색은 Mock으로 대체하여 격리된 환경에서 실행합니다.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def mock_modules():
    """테스트용 Mock 모듈 딕셔너리"""
    # LLM Factory Mock
    mock_llm_client = AsyncMock()
    mock_llm_client.generate_text = AsyncMock(return_value="RAG는 검색 증강 생성입니다.")

    mock_factory = MagicMock()
    mock_factory.get_client = MagicMock(return_value=mock_llm_client)

    # Retrieval Mock
    mock_retriever = AsyncMock()
    mock_result = MagicMock()
    mock_result.content = "RAG 관련 문서 내용"
    mock_result.score = 0.95
    mock_result.id = "doc-001"
    mock_result.metadata = {}
    mock_retriever.search = AsyncMock(return_value=[mock_result])

    return {
        "llm_factory": mock_factory,
        "retrieval": mock_retriever,
    }


@pytest.fixture
def client(mock_modules):
    """테스트 FastAPI 클라이언트"""
    from app.api.routers.openai_compat_router import router, set_modules

    set_modules(mock_modules)

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


class TestChatCompletionsNonStreaming:
    """비스트리밍 /v1/chat/completions 테스트"""

    def test_basic_completion(self, client, mock_modules):
        """기본 채팅 완료 요청"""
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "gemini",
                "messages": [{"role": "user", "content": "RAG란?"}],
            },
        )
        assert response.status_code == 200
        data = response.json()

        # OpenAI 응답 형식 검증
        assert data["object"] == "chat.completion"
        assert data["id"].startswith("chatcmpl-")
        assert len(data["choices"]) == 1
        assert data["choices"][0]["message"]["role"] == "assistant"
        assert len(data["choices"][0]["message"]["content"]) > 0
        assert data["choices"][0]["finish_reason"] == "stop"
        assert "usage" in data

    def test_model_passed_to_factory(self, client, mock_modules):
        """model 필드가 LLMClientFactory에 전달되는지 확인"""
        client.post(
            "/v1/chat/completions",
            json={
                "model": "ollama/qwen2.5:3b",
                "messages": [{"role": "user", "content": "테스트"}],
            },
        )
        # ollama provider로 get_client 호출 확인
        mock_modules["llm_factory"].get_client.assert_called()

    def test_retrieval_called(self, client, mock_modules):
        """검색 파이프라인이 호출되는지 확인"""
        client.post(
            "/v1/chat/completions",
            json={
                "model": "gemini",
                "messages": [{"role": "user", "content": "검색 질문"}],
            },
        )
        mock_modules["retrieval"].search.assert_called_once()

    def test_system_message_used(self, client, mock_modules):
        """system 메시지가 시스템 프롬프트로 전달"""
        client.post(
            "/v1/chat/completions",
            json={
                "model": "gemini",
                "messages": [
                    {"role": "system", "content": "너는 RAG 전문가야"},
                    {"role": "user", "content": "질문"},
                ],
            },
        )
        # generate_text에 system_prompt 전달 확인
        call_kwargs = mock_modules["llm_factory"].get_client().generate_text.call_args
        assert "system_prompt" in call_kwargs.kwargs or len(call_kwargs.args) >= 2

    def test_invalid_model_returns_error(self, client):
        """미지원 모델 시 에러 반환"""
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "unknown_provider",
                "messages": [{"role": "user", "content": "테스트"}],
            },
        )
        assert response.status_code == 400
        data = response.json()
        # FastAPI HTTPException은 detail 키 아래에 에러 정보를 담음
        assert "detail" in data
        assert "error" in data["detail"]

    def test_empty_messages_returns_422(self, client):
        """빈 messages 배열 시 422 반환"""
        response = client.post(
            "/v1/chat/completions",
            json={"model": "gemini", "messages": []},
        )
        assert response.status_code == 422


class TestModelsEndpoint:
    """/v1/models 엔드포인트 테스트"""

    def test_list_models(self, client):
        """모델 목록 반환"""
        response = client.get("/v1/models")
        assert response.status_code == 200
        data = response.json()
        assert data["object"] == "list"
        assert len(data["data"]) >= 4
        ids = [m["id"] for m in data["data"]]
        assert "gemini" in ids

    def test_model_info_structure(self, client):
        """모델 정보 구조 확인"""
        response = client.get("/v1/models")
        data = response.json()
        model = data["data"][0]
        assert "id" in model
        assert model["object"] == "model"
        assert "owned_by" in model
