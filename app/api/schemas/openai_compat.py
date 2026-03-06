# app/api/schemas/openai_compat.py
"""
OpenAI 호환 API 스키마

OpenAI Chat Completions API 형식의 Request/Response를 정의합니다.
외부 도구(LangChain, Cursor 등)가 OpenAI SDK로 OneRAG에 연결할 수 있도록
표준 형식을 제공합니다.
"""

from __future__ import annotations

import time
import uuid
from typing import Literal

from pydantic import BaseModel, Field


# ─── Request ───────────────────────────────────────────

class OpenAIMessage(BaseModel):
    """OpenAI 메시지 형식"""
    role: Literal["system", "user", "assistant"] = Field(
        ..., description="메시지 역할"
    )
    content: str = Field(..., description="메시지 내용")


class OpenAICompletionRequest(BaseModel):
    """OpenAI Chat Completions 요청 형식"""
    model: str = Field(..., description="모델 식별자 (예: gemini, ollama/qwen2.5:3b)")
    messages: list[OpenAIMessage] = Field(
        ..., min_length=1, description="대화 메시지 배열"
    )
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, ge=1)
    stream: bool = Field(default=False, description="스트리밍 여부")
    top_p: float = Field(default=1.0, ge=0.0, le=1.0)


# ─── Response ──────────────────────────────────────────

class OpenAIUsage(BaseModel):
    """토큰 사용량"""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class OpenAIResponseMessage(BaseModel):
    """응답 메시지"""
    role: str = "assistant"
    content: str = ""


class OpenAIChoice(BaseModel):
    """응답 선택지"""
    index: int = 0
    message: OpenAIResponseMessage
    finish_reason: str = "stop"


class OpenAICompletionResponse(BaseModel):
    """OpenAI Chat Completions 응답 형식"""
    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: list[OpenAIChoice]
    usage: OpenAIUsage

    @classmethod
    def create(
        cls,
        model: str,
        content: str,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
    ) -> OpenAICompletionResponse:
        """편의 팩토리 메서드"""
        return cls(
            id=f"chatcmpl-{uuid.uuid4().hex[:24]}",
            created=int(time.time()),
            model=model,
            choices=[
                OpenAIChoice(
                    message=OpenAIResponseMessage(content=content),
                )
            ],
            usage=OpenAIUsage(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=prompt_tokens + completion_tokens,
            ),
        )


# ─── Streaming ─────────────────────────────────────────

class OpenAIDelta(BaseModel):
    """스트리밍 델타"""
    role: str | None = None
    content: str | None = None


class OpenAIStreamChoice(BaseModel):
    """스트리밍 선택지"""
    index: int = 0
    delta: OpenAIDelta
    finish_reason: str | None = None


class OpenAIStreamChunk(BaseModel):
    """OpenAI 스트리밍 청크 형식"""
    id: str
    object: str = "chat.completion.chunk"
    created: int
    model: str
    choices: list[OpenAIStreamChoice]

    @classmethod
    def create(
        cls,
        model: str,
        content: str,
        index: int,
        is_first: bool = False,
    ) -> OpenAIStreamChunk:
        """텍스트 청크 생성"""
        return cls(
            id=f"chatcmpl-{uuid.uuid4().hex[:24]}",
            created=int(time.time()),
            model=model,
            choices=[
                OpenAIStreamChoice(
                    delta=OpenAIDelta(
                        role="assistant" if is_first else None,
                        content=content,
                    ),
                )
            ],
        )

    @classmethod
    def create_finish(cls, model: str) -> OpenAIStreamChunk:
        """종료 청크 생성"""
        return cls(
            id=f"chatcmpl-{uuid.uuid4().hex[:24]}",
            created=int(time.time()),
            model=model,
            choices=[
                OpenAIStreamChoice(
                    delta=OpenAIDelta(),
                    finish_reason="stop",
                )
            ],
        )


# ─── Models Endpoint ───────────────────────────────────

class OpenAIModelInfo(BaseModel):
    """모델 정보"""
    id: str
    object: str = "model"
    created: int = Field(default_factory=lambda: int(time.time()))
    owned_by: str = "onerag"


class OpenAIModelList(BaseModel):
    """모델 목록"""
    object: str = "list"
    data: list[OpenAIModelInfo]
