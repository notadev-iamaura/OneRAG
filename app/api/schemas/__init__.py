"""
API Schemas - Pydantic 데이터 검증 모델

Phase 3.1: chat.py에서 추출한 검증된 스키마 모듈
"""

from .chat_schemas import (
    ChatHistoryResponse,
    ChatRequest,
    ChatResponse,
    SessionCreateRequest,
    SessionInfoResponse,
    SessionResponse,
    Source,
    StatsResponse,
)
from .streaming import (
    StreamChatRequest,
    StreamChunkEvent,
    StreamDoneEvent,
    StreamErrorEvent,
)
from .websocket import (
    ClientMessage,
    StreamEndEvent,
    StreamSourcesEvent,
    StreamStartEvent,
    StreamTokenEvent,
    WSStreamErrorEvent,
)

__all__ = [
    # 채팅 스키마
    "ChatRequest",
    "ChatResponse",
    "Source",
    "SessionCreateRequest",
    "SessionResponse",
    "ChatHistoryResponse",
    "SessionInfoResponse",
    "StatsResponse",
    # 스트리밍 스키마 (SSE)
    "StreamChatRequest",
    "StreamChunkEvent",
    "StreamDoneEvent",
    "StreamErrorEvent",
    # WebSocket 스키마
    "ClientMessage",
    "StreamStartEvent",
    "StreamTokenEvent",
    "StreamSourcesEvent",
    "StreamEndEvent",
    "WSStreamErrorEvent",
]
