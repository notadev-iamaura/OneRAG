# WebSocket 실시간 채팅 구현 계획

**생성일**: 2026-01-16
**상태**: 계획 완료
**우선순위**: 중간

---

## 1. 개요

### 1.1 목적
기존 SSE(Server-Sent Events) 기반 `/chat/stream` 엔드포인트를 보완하여 양방향 WebSocket 통신을 지원합니다.

### 1.2 왜 WebSocket인가?

| 특성 | SSE (현재) | WebSocket (신규) |
|------|-----------|-----------------|
| 통신 방향 | 서버 → 클라이언트 (단방향) | 양방향 |
| 타이핑 인디케이터 | ❌ 불가 | ✅ 가능 |
| 실시간 상태 동기화 | ❌ 제한적 | ✅ 완벽 |
| 연결 유지 | HTTP 기반 | 전용 소켓 |
| 브라우저 지원 | 모든 브라우저 | 모든 브라우저 |

### 1.3 핵심 요구사항

1. **엔드포인트**: `wss://{host}/chat-ws?session_id={session_id}`
2. **메시지 프로토콜**: JSON 기반 타입별 메시지
3. **기존 RAG 파이프라인 재사용**: `ChatService.stream_rag_pipeline()` 활용
4. **연결 관리**: 세션별 연결 추적, 비정상 종료 처리

---

## 2. 메시지 프로토콜

### 2.1 클라이언트 → 서버

```json
{
  "type": "message",
  "message_id": "uuid-1234",
  "content": "RAG 시스템에 대해 설명해주세요",
  "session_id": "session-abc"
}
```

### 2.2 서버 → 클라이언트

#### stream_start (스트리밍 시작)
```json
{
  "type": "stream_start",
  "message_id": "uuid-1234",
  "session_id": "session-abc",
  "timestamp": "2026-01-16T10:00:00Z"
}
```

#### stream_token (토큰 조각)
```json
{
  "type": "stream_token",
  "message_id": "uuid-1234",
  "token": "안녕",
  "index": 0
}
```

#### stream_sources (RAG 소스)
```json
{
  "type": "stream_sources",
  "message_id": "uuid-1234",
  "sources": [
    {"title": "RAG 가이드", "score": 0.95, "content_preview": "..."}
  ]
}
```

#### stream_end (스트리밍 완료)
```json
{
  "type": "stream_end",
  "message_id": "uuid-1234",
  "total_tokens": 150,
  "processing_time_ms": 2500
}
```

#### stream_error (에러)
```json
{
  "type": "stream_error",
  "message_id": "uuid-1234",
  "error_code": "GENERATION-001",
  "message": "LLM 응답 생성 실패",
  "solutions": ["잠시 후 다시 시도해주세요"]
}
```

---

## 3. 아키텍처

### 3.1 파일 구조

```
app/api/
├── routers/
│   └── websocket_router.py      # [신규] WebSocket 라우터
├── schemas/
│   └── websocket.py             # [신규] WebSocket 메시지 스키마
├── services/
│   └── chat_service.py          # [기존] stream_rag_pipeline 재사용
│   └── websocket_manager.py     # [신규] 연결 관리자
```

### 3.2 의존성 흐름

```
WebSocket Router
    ↓
WebSocket Manager (연결 관리)
    ↓
ChatService.stream_rag_pipeline() (기존 RAG 로직)
    ↓
LLM Factory → Generation Module → 스트리밍 응답
```

---

## 4. 구현 태스크 (TDD 방식)

### Task 1: WebSocket 메시지 스키마 정의
**파일**: `app/api/schemas/websocket.py`

**테스트 먼저** (`tests/unit/api/schemas/test_websocket_schemas.py`):
```python
def test_client_message_schema_valid():
    """클라이언트 메시지 스키마 유효성 검증"""
    msg = ClientMessage(
        type="message",
        message_id="uuid-1234",
        content="테스트 질문",
        session_id="session-abc"
    )
    assert msg.type == "message"
    assert msg.content == "테스트 질문"

def test_stream_token_event_schema():
    """스트림 토큰 이벤트 스키마 검증"""
    event = StreamTokenEvent(
        type="stream_token",
        message_id="uuid-1234",
        token="안녕",
        index=0
    )
    assert event.type == "stream_token"
```

**구현**:
```python
# app/api/schemas/websocket.py
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Literal

class ClientMessage(BaseModel):
    """클라이언트 → 서버 메시지"""
    type: Literal["message"] = "message"
    message_id: str = Field(..., description="메시지 고유 ID")
    content: str = Field(..., min_length=1, max_length=10000)
    session_id: str = Field(..., description="세션 ID")

class StreamStartEvent(BaseModel):
    """스트리밍 시작 이벤트"""
    type: Literal["stream_start"] = "stream_start"
    message_id: str
    session_id: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)

class StreamTokenEvent(BaseModel):
    """토큰 조각 이벤트"""
    type: Literal["stream_token"] = "stream_token"
    message_id: str
    token: str
    index: int

class StreamSourcesEvent(BaseModel):
    """RAG 소스 이벤트"""
    type: Literal["stream_sources"] = "stream_sources"
    message_id: str
    sources: list[dict]

class StreamEndEvent(BaseModel):
    """스트리밍 완료 이벤트"""
    type: Literal["stream_end"] = "stream_end"
    message_id: str
    total_tokens: int
    processing_time_ms: int

class StreamErrorEvent(BaseModel):
    """에러 이벤트"""
    type: Literal["stream_error"] = "stream_error"
    message_id: str
    error_code: str
    message: str
    solutions: list[str] = []
```

---

### Task 2: WebSocket 연결 관리자 구현
**파일**: `app/api/services/websocket_manager.py`

**테스트 먼저** (`tests/unit/api/services/test_websocket_manager.py`):
```python
@pytest.mark.asyncio
async def test_manager_connect_and_disconnect():
    """연결/해제 테스트"""
    manager = WebSocketManager()
    mock_ws = AsyncMock()

    await manager.connect("session-123", mock_ws)
    assert manager.is_connected("session-123")

    await manager.disconnect("session-123")
    assert not manager.is_connected("session-123")

@pytest.mark.asyncio
async def test_manager_send_message():
    """메시지 전송 테스트"""
    manager = WebSocketManager()
    mock_ws = AsyncMock()

    await manager.connect("session-123", mock_ws)
    await manager.send_json("session-123", {"type": "test"})

    mock_ws.send_json.assert_called_once_with({"type": "test"})
```

**구현**:
```python
# app/api/services/websocket_manager.py
from fastapi import WebSocket
from app.lib.logger import get_logger

logger = get_logger(__name__)

class WebSocketManager:
    """WebSocket 연결 관리자"""

    def __init__(self):
        self._connections: dict[str, WebSocket] = {}

    async def connect(self, session_id: str, websocket: WebSocket) -> None:
        """WebSocket 연결 수락 및 등록"""
        await websocket.accept()
        self._connections[session_id] = websocket
        logger.info(f"WebSocket 연결됨: {session_id}")

    async def disconnect(self, session_id: str) -> None:
        """WebSocket 연결 해제"""
        if session_id in self._connections:
            del self._connections[session_id]
            logger.info(f"WebSocket 연결 해제: {session_id}")

    def is_connected(self, session_id: str) -> bool:
        """연결 상태 확인"""
        return session_id in self._connections

    async def send_json(self, session_id: str, data: dict) -> None:
        """JSON 메시지 전송"""
        if session_id in self._connections:
            await self._connections[session_id].send_json(data)

    async def broadcast(self, data: dict) -> None:
        """모든 연결에 브로드캐스트"""
        for ws in self._connections.values():
            await ws.send_json(data)
```

---

### Task 3: WebSocket 라우터 구현
**파일**: `app/api/routers/websocket_router.py`

**테스트 먼저** (`tests/unit/api/routers/test_websocket_router.py`):
```python
@pytest.mark.asyncio
async def test_websocket_endpoint_exists():
    """WebSocket 엔드포인트 존재 확인"""
    from app.api.routers.websocket_router import router

    routes = [r.path for r in router.routes]
    assert "/chat-ws" in routes

@pytest.mark.asyncio
async def test_websocket_requires_session_id():
    """session_id 파라미터 필수 확인"""
    # WebSocket 테스트는 TestClient 대신 직접 테스트
    pass
```

**구현**:
```python
# app/api/routers/websocket_router.py
import uuid
from datetime import datetime
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query

from app.api.schemas.websocket import (
    ClientMessage,
    StreamStartEvent,
    StreamTokenEvent,
    StreamSourcesEvent,
    StreamEndEvent,
    StreamErrorEvent,
)
from app.api.services.websocket_manager import WebSocketManager
from app.lib.logger import get_logger

logger = get_logger(__name__)
router = APIRouter()

# 전역 WebSocket 매니저
ws_manager = WebSocketManager()

# ChatService 의존성 주입용
_chat_service = None

def set_chat_service(service) -> None:
    """ChatService 의존성 주입"""
    global _chat_service
    _chat_service = service

@router.websocket("/chat-ws")
async def websocket_chat(
    websocket: WebSocket,
    session_id: str = Query(..., description="세션 ID"),
):
    """
    WebSocket 실시간 채팅 엔드포인트

    연결: wss://{host}/chat-ws?session_id={session_id}
    """
    await ws_manager.connect(session_id, websocket)

    try:
        while True:
            # 클라이언트 메시지 수신
            data = await websocket.receive_json()

            try:
                client_msg = ClientMessage(**data)
            except Exception as e:
                await websocket.send_json(
                    StreamErrorEvent(
                        message_id=data.get("message_id", str(uuid.uuid4())),
                        error_code="WS-001",
                        message="잘못된 메시지 형식",
                        solutions=["메시지 형식을 확인해주세요"],
                    ).model_dump()
                )
                continue

            # ChatService 확인
            if _chat_service is None:
                await websocket.send_json(
                    StreamErrorEvent(
                        message_id=client_msg.message_id,
                        error_code="WS-002",
                        message="서비스가 초기화되지 않았습니다",
                        solutions=["잠시 후 다시 시도해주세요"],
                    ).model_dump()
                )
                continue

            # 스트리밍 시작 이벤트
            await websocket.send_json(
                StreamStartEvent(
                    message_id=client_msg.message_id,
                    session_id=session_id,
                    timestamp=datetime.utcnow(),
                ).model_dump(mode="json")
            )

            # RAG 파이프라인 스트리밍 실행
            start_time = datetime.utcnow()
            token_index = 0
            total_tokens = 0
            sources_sent = False

            try:
                async for event in _chat_service.stream_rag_pipeline(
                    message=client_msg.content,
                    session_id=session_id,
                ):
                    if event.get("event") == "metadata" and not sources_sent:
                        # RAG 소스 전송
                        await websocket.send_json(
                            StreamSourcesEvent(
                                message_id=client_msg.message_id,
                                sources=event.get("data", {}).get("sources", []),
                            ).model_dump()
                        )
                        sources_sent = True

                    elif event.get("event") == "chunk":
                        # 토큰 조각 전송
                        token = event.get("data", "")
                        if token:
                            await websocket.send_json(
                                StreamTokenEvent(
                                    message_id=client_msg.message_id,
                                    token=token,
                                    index=token_index,
                                ).model_dump()
                            )
                            token_index += 1
                            total_tokens += len(token)

                    elif event.get("event") == "done":
                        # 완료 이벤트
                        processing_time = (datetime.utcnow() - start_time).total_seconds() * 1000
                        await websocket.send_json(
                            StreamEndEvent(
                                message_id=client_msg.message_id,
                                total_tokens=total_tokens,
                                processing_time_ms=int(processing_time),
                            ).model_dump()
                        )
                        break

                    elif event.get("event") == "error":
                        # 에러 이벤트
                        await websocket.send_json(
                            StreamErrorEvent(
                                message_id=client_msg.message_id,
                                error_code=event.get("error_code", "STREAM-001"),
                                message=event.get("message", "스트리밍 중 오류 발생"),
                                solutions=event.get("solutions", []),
                            ).model_dump()
                        )
                        break

            except Exception as e:
                logger.error(f"RAG 파이프라인 오류: {e}")
                await websocket.send_json(
                    StreamErrorEvent(
                        message_id=client_msg.message_id,
                        error_code="RAG-001",
                        message="RAG 처리 중 오류가 발생했습니다",
                        solutions=["잠시 후 다시 시도해주세요"],
                    ).model_dump()
                )

    except WebSocketDisconnect:
        logger.info(f"WebSocket 연결 종료: {session_id}")
    finally:
        await ws_manager.disconnect(session_id)
```

---

### Task 4: main.py에 WebSocket 라우터 등록
**파일**: `main.py`

**테스트 먼저** (`tests/integration/test_websocket_integration.py`):
```python
@pytest.mark.asyncio
async def test_websocket_route_registered():
    """WebSocket 라우터가 main.py에 등록되었는지 확인"""
    from main import app

    routes = [r.path for r in app.routes]
    assert "/chat-ws" in routes
```

**구현** (main.py에 추가):
```python
# main.py 상단 import 추가
from app.api.routers import websocket_router

# 라우터 등록 섹션에 추가 (line ~593 근처)
app.include_router(websocket_router.router, tags=["WebSocket"])

# lifespan 함수 내 ChatService 주입 부분에 추가
websocket_router.set_chat_service(chat_service_instance)
```

---

### Task 5: 문서화
**파일**: `docs/websocket-api-guide.md`

WebSocket API 사용 가이드 문서 작성:
- 연결 방법
- 메시지 프로토콜
- 에러 처리
- JavaScript/Python 클라이언트 예시

---

## 5. 테스트 전략

### 5.1 단위 테스트
- 스키마 유효성 검증
- WebSocketManager 연결/해제
- 메시지 파싱 및 직렬화

### 5.2 통합 테스트
- WebSocket 엔드포인트 연결
- ChatService와의 통합
- 에러 시나리오

### 5.3 E2E 테스트
- 실제 WebSocket 클라이언트로 전체 흐름 검증

---

## 6. 체크리스트

- [ ] Task 1: WebSocket 스키마 정의 + 테스트
- [ ] Task 2: WebSocketManager 구현 + 테스트
- [ ] Task 3: WebSocket 라우터 구현 + 테스트
- [ ] Task 4: main.py 라우터 등록 + 통합 테스트
- [ ] Task 5: API 문서화
- [ ] 코드 리뷰 및 린트/타입 체크 통과
- [ ] CLAUDE.md 버전 업데이트 (1.0.8 → 1.0.9)

---

## 7. 예상 결과

구현 완료 후:
1. `wss://{host}/chat-ws?session_id=xxx`로 WebSocket 연결 가능
2. 기존 SSE와 동일한 RAG 파이프라인 사용
3. 양방향 실시간 통신 지원
4. 프론트엔드에서 타이핑 인디케이터 등 구현 가능
