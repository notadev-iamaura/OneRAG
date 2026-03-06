# tests/unit/api/test_openai_compat_schemas.py
"""
OpenAI 호환 API 스키마 단위 테스트

OpenAI Chat Completions API 형식의 Request/Response 스키마를 검증합니다.
"""

import time

import pytest
from pydantic import ValidationError


class TestOpenAICompletionRequest:
    """OpenAI 호환 요청 스키마 테스트"""

    def test_minimal_request(self):
        """최소 필수 필드만으로 요청 생성"""
        from app.api.schemas.openai_compat import OpenAICompletionRequest

        req = OpenAICompletionRequest(
            model="gemini",
            messages=[{"role": "user", "content": "안녕"}],
        )
        assert req.model == "gemini"
        assert len(req.messages) == 1
        assert req.stream is False

    def test_full_request(self):
        """모든 필드 포함 요청 생성"""
        from app.api.schemas.openai_compat import OpenAICompletionRequest

        req = OpenAICompletionRequest(
            model="openrouter/google/gemini-2.0-flash",
            messages=[
                {"role": "system", "content": "너는 도우미야"},
                {"role": "user", "content": "RAG란?"},
            ],
            temperature=0.5,
            max_tokens=1000,
            stream=True,
            top_p=0.9,
        )
        assert req.temperature == 0.5
        assert req.stream is True

    def test_empty_messages_rejected(self):
        """빈 messages 배열 거부"""
        from app.api.schemas.openai_compat import OpenAICompletionRequest

        with pytest.raises(ValidationError):
            OpenAICompletionRequest(model="gemini", messages=[])

    def test_invalid_role_rejected(self):
        """유효하지 않은 role 거부"""
        from app.api.schemas.openai_compat import OpenAICompletionRequest

        with pytest.raises(ValidationError):
            OpenAICompletionRequest(
                model="gemini",
                messages=[{"role": "invalid_role", "content": "test"}],
            )


class TestOpenAICompletionResponse:
    """OpenAI 호환 응답 스키마 테스트"""

    def test_response_structure(self):
        """응답 구조가 OpenAI 형식과 일치하는지 확인"""
        from app.api.schemas.openai_compat import OpenAICompletionResponse

        resp = OpenAICompletionResponse.create(
            model="gemini",
            content="RAG는 검색 증강 생성입니다.",
            prompt_tokens=10,
            completion_tokens=20,
        )
        assert resp.object == "chat.completion"
        assert resp.id.startswith("chatcmpl-")
        assert len(resp.choices) == 1
        assert resp.choices[0].message.role == "assistant"
        assert resp.choices[0].message.content == "RAG는 검색 증강 생성입니다."
        assert resp.choices[0].finish_reason == "stop"
        assert resp.usage.total_tokens == 30

    def test_response_json_serialization(self):
        """JSON 직렬화가 OpenAI 형식과 일치"""
        from app.api.schemas.openai_compat import OpenAICompletionResponse

        resp = OpenAICompletionResponse.create(
            model="ollama/qwen2.5:3b",
            content="테스트 답변",
        )
        data = resp.model_dump()
        assert "id" in data
        assert "choices" in data
        assert "usage" in data
        assert data["object"] == "chat.completion"


class TestOpenAIStreamChunk:
    """OpenAI 스트리밍 청크 스키마 테스트"""

    def test_first_chunk_has_role(self):
        """첫 번째 청크에 role 포함"""
        from app.api.schemas.openai_compat import OpenAIStreamChunk

        chunk = OpenAIStreamChunk.create(
            model="gemini", content="안녕", index=0, is_first=True
        )
        assert chunk.choices[0].delta.role == "assistant"
        assert chunk.choices[0].delta.content == "안녕"

    def test_subsequent_chunk_no_role(self):
        """후속 청크에는 role 없음"""
        from app.api.schemas.openai_compat import OpenAIStreamChunk

        chunk = OpenAIStreamChunk.create(
            model="gemini", content="하세요", index=1, is_first=False
        )
        assert chunk.choices[0].delta.role is None
        assert chunk.choices[0].delta.content == "하세요"

    def test_finish_chunk(self):
        """종료 청크 테스트"""
        from app.api.schemas.openai_compat import OpenAIStreamChunk

        chunk = OpenAIStreamChunk.create_finish(model="gemini")
        assert chunk.choices[0].finish_reason == "stop"
        assert chunk.choices[0].delta.content is None


class TestOpenAIModelList:
    """모델 목록 스키마 테스트"""

    def test_model_list_structure(self):
        """모델 목록 응답 구조"""
        from app.api.schemas.openai_compat import OpenAIModelInfo, OpenAIModelList

        models = OpenAIModelList(
            data=[
                OpenAIModelInfo(id="gemini", owned_by="onerag"),
                OpenAIModelInfo(id="ollama", owned_by="onerag"),
            ]
        )
        assert models.object == "list"
        assert len(models.data) == 2
        assert models.data[0].id == "gemini"
