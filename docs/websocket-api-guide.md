# WebSocket API 사용 가이드

## 개요

OneRAG는 WebSocket 기반 양방향 실시간 채팅 API를 제공합니다.
SSE(Server-Sent Events) 방식과 달리 완전한 양방향 통신을 지원하며, 토큰 단위 스트리밍으로 더욱 부드러운 사용자 경험을 제공합니다.

### SSE vs WebSocket 비교

| 항목 | SSE (`/chat/stream`) | WebSocket (`/chat-ws`) |
|------|---------------------|------------------------|
| **통신 방향** | 단방향 (서버 → 클라이언트) | 양방향 (클라이언트 ↔ 서버) |
| **프로토콜** | HTTP/1.1 | WebSocket (ws://, wss://) |
| **연결 유지** | 자동 재연결 지원 | 수동 재연결 필요 |
| **메시지 형식** | SSE 이벤트 (청크 단위) | JSON 메시지 (토큰 단위) |
| **지연 시간** | ~100ms | ~10ms (더 낮은 지연) |
| **사용 사례** | 단순 스트리밍, 서버 푸시 | 실시간 채팅, 인터랙티브 앱 |

### 주요 특징

- **실시간 양방향 통신**: 클라이언트-서버 간 즉각적인 메시지 교환
- **토큰 단위 스트리밍**: 청크보다 더 세밀한 토큰 단위로 응답 전송
- **낮은 지연 시간**: WebSocket의 낮은 오버헤드로 더 빠른 응답
- **지속 연결**: 단일 연결로 여러 메시지 주고받기
- **구조화된 프로토콜**: 5가지 명확한 이벤트 타입

---

## 엔드포인트

### WS /chat-ws

양방향 실시간 채팅 WebSocket 엔드포인트입니다.

**URL:**
```
wss://{host}/chat-ws?session_id={session_id}
```

**쿼리 파라미터:**

| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| `session_id` | string | ✅ | 세션 식별자 (대화 컨텍스트 유지용) |

> **중요**: UUID4 형식이 아닌 커스텀 `session_id`(예: `my-session`)는 서버가 보안상 새 UUID4로 교체합니다. 서버가 확정한 세션 ID는 `stream_start` 이벤트의 `session_id` 필드로 회신되며, **대화 컨텍스트를 유지하려면 후속 메시지에 이 서버 확정 ID를 사용해야 합니다.**

**연결 방법:**

```javascript
// 브라우저 (WebSocket API)
const ws = new WebSocket('wss://your-domain.com/chat-ws?session_id=my-session-123');

// Node.js (ws 라이브러리)
const WebSocket = require('ws');
const ws = new WebSocket('wss://your-domain.com/chat-ws?session_id=my-session-123');

// Python (websockets 라이브러리)
import websockets
async with websockets.connect('wss://your-domain.com/chat-ws?session_id=my-session-123') as ws:
    ...
```

---

## 메시지 프로토콜

### 클라이언트 → 서버: ClientMessage

사용자가 질문을 전송할 때 사용하는 메시지입니다.

**형식:**
```json
{
  "type": "message",
  "message_id": "unique-message-id-123",
  "content": "RAG 시스템에 대해 설명해주세요",
  "session_id": "my-session-123"
}
```

**필드 설명:**

| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| `type` | string | ✅ | 메시지 타입 (항상 `"message"`) |
| `message_id` | string | ✅ | 메시지 고유 식별자 (클라이언트가 생성, UUID 권장) |
| `content` | string | ✅ | 사용자 질문 내용 (1~10,000자) |
| `session_id` | string | ✅ | 세션 식별자 (첫 메시지는 연결 시 사용한 값, 이후에는 `stream_start`로 회신된 서버 확정 ID 사용) |

**예시:**
```javascript
const message = {
  type: "message",
  message_id: crypto.randomUUID(), // 브라우저에서 UUID 생성
  content: "GraphRAG와 일반 RAG의 차이점은?",
  session_id: "session-abc-123"
};

ws.send(JSON.stringify(message));
```

---

### 서버 → 클라이언트: 이벤트

서버는 5가지 이벤트 타입을 전송합니다.

#### 1. stream_start - 스트리밍 시작

RAG 파이프라인이 시작되었음을 알립니다.

```json
{
  "type": "stream_start",
  "message_id": "unique-message-id-123",
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "timestamp": "2026-01-16T12:34:56.789Z"
}
```

| 필드 | 타입 | 설명 |
|------|------|------|
| `type` | string | 이벤트 타입 (`"stream_start"`) |
| `message_id` | string | 클라이언트가 보낸 메시지 ID |
| `session_id` | string | **서버 확정 세션 ID** (비-UUID4 커스텀 ID는 서버가 새 UUID4로 교체. 후속 메시지에 이 값을 사용해야 대화 컨텍스트 유지) |
| `timestamp` | string | 스트리밍 시작 시각 (ISO 8601 형식) |

> **참고**: `session_id`는 연결 시 전달한 값과 다를 수 있습니다. 클라이언트는 `stream_start.session_id`를 저장해 두고 이후 메시지의 `session_id`로 사용하세요.

#### 2. stream_token - 토큰 스트리밍

LLM이 생성한 텍스트를 토큰 단위로 전송합니다.

```json
{
  "type": "stream_token",
  "message_id": "unique-message-id-123",
  "token": "안녕하세요",
  "index": 0
}
```

| 필드 | 타입 | 설명 |
|------|------|------|
| `type` | string | 이벤트 타입 (`"stream_token"`) |
| `message_id` | string | 메시지 ID |
| `token` | string | 텍스트 토큰 (빈 문자열 가능) |
| `index` | number | 토큰 순서 (0부터 시작) |

**특징:**
- 토큰은 단어, 구두점, 또는 단어의 일부일 수 있습니다
- 클라이언트는 `index` 순서대로 토큰을 조합하여 전체 텍스트를 구성합니다
- SSE의 청크보다 더 세밀한 단위로 전송되어 부드러운 타이핑 효과를 제공합니다

#### 3. stream_sources - RAG 소스

검색된 문서 소스 정보를 전송합니다.

```json
{
  "type": "stream_sources",
  "message_id": "unique-message-id-123",
  "sources": [
    {
      "title": "GraphRAG 개요",
      "content": "GraphRAG는 지식 그래프를...",
      "score": 0.95,
      "metadata": {
        "source": "docs/graphrag.md",
        "chunk_id": "chunk-123"
      }
    }
  ]
}
```

| 필드 | 타입 | 설명 |
|------|------|------|
| `type` | string | 이벤트 타입 (`"stream_sources"`) |
| `message_id` | string | 메시지 ID |
| `sources` | array | 검색 소스 목록 (딕셔너리 배열) |

**sources 배열 항목:**
- `title`: 문서 제목
- `content`: 문서 내용 (검색된 부분)
- `score`: 관련성 점수 (0.0~1.0)
- `metadata`: 추가 메타데이터 (출처, 청크 ID 등)

#### 4. stream_end - 스트리밍 완료

모든 토큰 전송이 완료되었음을 알립니다.

```json
{
  "type": "stream_end",
  "message_id": "unique-message-id-123",
  "total_tokens": 150,
  "processing_time_ms": 2500
}
```

| 필드 | 타입 | 설명 |
|------|------|------|
| `type` | string | 이벤트 타입 (`"stream_end"`) |
| `message_id` | string | 메시지 ID |
| `total_tokens` | number | 전송된 총 토큰 수 |
| `processing_time_ms` | number | 전체 처리 시간 (밀리초) |

#### 5. stream_error - 에러 발생

스트리밍 중 에러가 발생했을 때 전송됩니다.

```json
{
  "type": "stream_error",
  "message_id": "unique-message-id-123",
  "error_code": "GEN-001",
  "message": "AI 모델 응답이 지연되고 있습니다",
  "solutions": [
    "잠시 후 다시 시도해주세요",
    "문제가 지속되면 관리자에게 문의해주세요"
  ]
}
```

| 필드 | 타입 | 설명 |
|------|------|------|
| `type` | string | 이벤트 타입 (`"stream_error"`) |
| `message_id` | string | 메시지 ID |
| `error_code` | string | 에러 코드 (예: `GEN-001`, `SEARCH-003`) |
| `message` | string | 사용자 친화적 에러 메시지 |
| `solutions` | array | 해결 방법 목록 |

---

## 프론트엔드 연동 예시

### JavaScript (Native WebSocket)

브라우저 네이티브 WebSocket API를 사용한 구현입니다.

```javascript
class RAGWebSocketClient {
  constructor(baseUrl, sessionId) {
    this.baseUrl = baseUrl;
    this.sessionId = sessionId;
    this.ws = null;
    this.onTokenCallback = null;
    this.onSourcesCallback = null;
    this.onCompleteCallback = null;
    this.onErrorCallback = null;
  }

  connect() {
    const wsUrl = `wss://${this.baseUrl}/chat-ws?session_id=${this.sessionId}`;
    this.ws = new WebSocket(wsUrl);

    this.ws.onopen = () => {
      console.log('WebSocket 연결됨');
    };

    this.ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      this.handleEvent(data);
    };

    this.ws.onerror = (error) => {
      console.error('WebSocket 에러:', error);
      if (this.onErrorCallback) {
        this.onErrorCallback({ message: 'WebSocket 연결 오류' });
      }
    };

    this.ws.onclose = () => {
      console.log('WebSocket 연결 종료');
    };
  }

  handleEvent(event) {
    switch (event.type) {
      case 'stream_start':
        console.log('스트리밍 시작:', event.timestamp);
        // 서버 확정 세션 ID 채택 (비-UUID4 커스텀 ID는 서버가 교체함)
        // 후속 메시지가 이 ID를 사용해야 대화 컨텍스트가 유지된다
        this.sessionId = event.session_id;
        break;

      case 'stream_token':
        if (this.onTokenCallback) {
          this.onTokenCallback(event.token);
        }
        break;

      case 'stream_sources':
        if (this.onSourcesCallback) {
          this.onSourcesCallback(event.sources);
        }
        break;

      case 'stream_end':
        console.log(`완료: ${event.total_tokens}토큰, ${event.processing_time_ms}ms`);
        if (this.onCompleteCallback) {
          this.onCompleteCallback({
            totalTokens: event.total_tokens,
            processingTime: event.processing_time_ms
          });
        }
        break;

      case 'stream_error':
        console.error('에러:', event.message);
        if (this.onErrorCallback) {
          this.onErrorCallback({
            code: event.error_code,
            message: event.message,
            solutions: event.solutions
          });
        }
        break;
    }
  }

  sendMessage(content) {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      console.error('WebSocket 미연결');
      return;
    }

    const message = {
      type: 'message',
      message_id: crypto.randomUUID(),
      content: content,
      session_id: this.sessionId
    };

    this.ws.send(JSON.stringify(message));
  }

  // 콜백 등록 메서드
  onToken(callback) {
    this.onTokenCallback = callback;
  }

  onSources(callback) {
    this.onSourcesCallback = callback;
  }

  onComplete(callback) {
    this.onCompleteCallback = callback;
  }

  onError(callback) {
    this.onErrorCallback = callback;
  }

  disconnect() {
    if (this.ws) {
      this.ws.close();
    }
  }
}

// 사용 예시
const client = new RAGWebSocketClient('your-domain.com', 'session-123');

// 콜백 등록
client.onToken((token) => {
  // UI에 토큰 추가
  document.getElementById('response').textContent += token;
});

client.onSources((sources) => {
  console.log('검색 소스:', sources);
  // UI에 소스 표시
});

client.onComplete((stats) => {
  console.log('완료:', stats);
});

client.onError((error) => {
  alert(`에러: ${error.message}`);
});

// 연결 및 메시지 전송
client.connect();
setTimeout(() => {
  client.sendMessage('GraphRAG에 대해 설명해주세요');
}, 1000);
```

---

### React Hook 예시

React 애플리케이션에서 사용할 수 있는 커스텀 훅입니다.

```typescript
import { useState, useEffect, useRef, useCallback } from 'react';

interface WebSocketState {
  tokens: string[];          // 토큰 배열
  sources: any[];           // 검색 소스
  isStreaming: boolean;     // 스트리밍 중 여부
  isConnected: boolean;     // 연결 상태
  error: string | null;     // 에러 메시지
  stats: {
    totalTokens: number;
    processingTime: number;
  } | null;
}

export function useWebSocketRAG(baseUrl: string, sessionId: string) {
  const [state, setState] = useState<WebSocketState>({
    tokens: [],
    sources: [],
    isStreaming: false,
    isConnected: false,
    error: null,
    stats: null,
  });

  const wsRef = useRef<WebSocket | null>(null);
  // 서버 확정 세션 ID (비-UUID4 커스텀 ID는 서버가 새 UUID4로 교체함)
  const serverSessionIdRef = useRef<string>(sessionId);

  // WebSocket 연결
  useEffect(() => {
    const wsUrl = `wss://${baseUrl}/chat-ws?session_id=${sessionId}`;
    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onopen = () => {
      console.log('WebSocket 연결됨');
      setState(prev => ({ ...prev, isConnected: true, error: null }));
    };

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);

      switch (data.type) {
        case 'stream_start':
          // 서버 확정 세션 ID 채택 — 후속 메시지가 이 ID를 사용해야
          // 대화 컨텍스트가 유지된다
          serverSessionIdRef.current = data.session_id;
          setState(prev => ({
            ...prev,
            tokens: [],
            sources: [],
            isStreaming: true,
            error: null,
            stats: null,
          }));
          break;

        case 'stream_token':
          setState(prev => ({
            ...prev,
            tokens: [...prev.tokens, data.token],
          }));
          break;

        case 'stream_sources':
          setState(prev => ({
            ...prev,
            sources: data.sources,
          }));
          break;

        case 'stream_end':
          setState(prev => ({
            ...prev,
            isStreaming: false,
            stats: {
              totalTokens: data.total_tokens,
              processingTime: data.processing_time_ms,
            },
          }));
          break;

        case 'stream_error':
          setState(prev => ({
            ...prev,
            isStreaming: false,
            error: data.message,
          }));
          break;
      }
    };

    ws.onerror = (error) => {
      console.error('WebSocket 에러:', error);
      setState(prev => ({
        ...prev,
        error: 'WebSocket 연결 오류',
        isConnected: false,
      }));
    };

    ws.onclose = () => {
      console.log('WebSocket 연결 종료');
      setState(prev => ({ ...prev, isConnected: false }));
    };

    // 클린업
    return () => {
      ws.close();
    };
  }, [baseUrl, sessionId]);

  // 메시지 전송
  const sendMessage = useCallback((content: string) => {
    const ws = wsRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      console.error('WebSocket 미연결');
      setState(prev => ({
        ...prev,
        error: 'WebSocket이 연결되지 않았습니다',
      }));
      return;
    }

    const message = {
      type: 'message',
      message_id: crypto.randomUUID(),
      content,
      // 서버 확정 세션 ID 사용 (stream_start로 회신된 값)
      session_id: serverSessionIdRef.current,
    };

    ws.send(JSON.stringify(message));
  }, []);

  // 전체 텍스트 반환 (토큰 조합)
  const fullText = state.tokens.join('');

  return {
    fullText,
    tokens: state.tokens,
    sources: state.sources,
    isStreaming: state.isStreaming,
    isConnected: state.isConnected,
    error: state.error,
    stats: state.stats,
    sendMessage,
  };
}
```

---

### React 컴포넌트 사용 예시

```tsx
import React, { useState } from 'react';
import { useWebSocketRAG } from './hooks/useWebSocketRAG';

function ChatComponent() {
  const {
    fullText,
    sources,
    isStreaming,
    isConnected,
    error,
    stats,
    sendMessage,
  } = useWebSocketRAG('your-domain.com', 'session-123');

  const [input, setInput] = useState('');

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (input.trim() && isConnected) {
      sendMessage(input);
      setInput('');
    }
  };

  return (
    <div className="chat-container">
      {/* 연결 상태 표시 */}
      <div className="status">
        {isConnected ? (
          <span className="connected">🟢 연결됨</span>
        ) : (
          <span className="disconnected">🔴 연결 안됨</span>
        )}
      </div>

      {/* 응답 표시 */}
      <div className="response">
        <pre>{fullText}</pre>
        {isStreaming && <span className="cursor">▌</span>}
      </div>

      {/* 검색 소스 표시 */}
      {sources.length > 0 && (
        <div className="sources">
          <h3>참고 문서</h3>
          <ul>
            {sources.map((source, idx) => (
              <li key={idx}>
                <strong>{source.title}</strong>
                <span className="score">관련도: {(source.score * 100).toFixed(0)}%</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* 통계 표시 */}
      {stats && (
        <div className="stats">
          총 {stats.totalTokens}토큰, {stats.processingTime}ms 소요
        </div>
      )}

      {/* 에러 표시 */}
      {error && (
        <div className="error">
          ❌ {error}
        </div>
      )}

      {/* 입력 폼 */}
      <form onSubmit={handleSubmit}>
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="메시지를 입력하세요..."
          disabled={!isConnected || isStreaming}
        />
        <button
          type="submit"
          disabled={!isConnected || isStreaming || !input.trim()}
        >
          {isStreaming ? '생성 중...' : '전송'}
        </button>
      </form>
    </div>
  );
}

export default ChatComponent;
```

---

### Python (websockets) 예시

Python 애플리케이션에서 WebSocket을 사용하는 예시입니다.

```python
import asyncio
import json
import uuid
from typing import Callable

import websockets


class RAGWebSocketClient:
    """RAG WebSocket 클라이언트"""

    def __init__(self, base_url: str, session_id: str):
        """
        Args:
            base_url: 서버 URL (예: 'localhost:8000')
            session_id: 세션 ID
        """
        self.base_url = base_url
        self.session_id = session_id
        self.ws_url = f"ws://{base_url}/chat-ws?session_id={session_id}"

        # 콜백 함수
        self.on_token: Callable[[str], None] | None = None
        self.on_sources: Callable[[list], None] | None = None
        self.on_complete: Callable[[dict], None] | None = None
        self.on_error: Callable[[dict], None] | None = None

    async def connect_and_chat(self, message: str) -> None:
        """
        WebSocket에 연결하고 메시지를 전송합니다.

        Args:
            message: 전송할 메시지
        """
        async with websockets.connect(self.ws_url) as websocket:
            print(f"WebSocket 연결됨: {self.ws_url}")

            # 메시지 전송
            client_message = {
                "type": "message",
                "message_id": str(uuid.uuid4()),
                "content": message,
                "session_id": self.session_id,
            }
            await websocket.send(json.dumps(client_message))
            print(f"메시지 전송: {message}")

            # 응답 수신
            tokens = []
            async for raw_message in websocket:
                event = json.loads(raw_message)
                event_type = event.get("type")

                if event_type == "stream_start":
                    print(f"스트리밍 시작: {event.get('timestamp')}")
                    # 서버 확정 세션 ID 채택 (비-UUID4 커스텀 ID는 서버가 교체함)
                    # 후속 메시지가 이 ID를 사용해야 대화 컨텍스트가 유지된다
                    self.session_id = event.get("session_id", self.session_id)

                elif event_type == "stream_token":
                    token = event.get("token", "")
                    tokens.append(token)
                    print(token, end="", flush=True)
                    if self.on_token:
                        self.on_token(token)

                elif event_type == "stream_sources":
                    sources = event.get("sources", [])
                    print(f"\n\n검색 소스: {len(sources)}개")
                    if self.on_sources:
                        self.on_sources(sources)

                elif event_type == "stream_end":
                    print(f"\n\n완료: {event.get('total_tokens')}토큰, "
                          f"{event.get('processing_time_ms')}ms")
                    if self.on_complete:
                        self.on_complete({
                            "total_tokens": event.get("total_tokens"),
                            "processing_time_ms": event.get("processing_time_ms"),
                        })
                    break

                elif event_type == "stream_error":
                    error_info = {
                        "code": event.get("error_code"),
                        "message": event.get("message"),
                        "solutions": event.get("solutions", []),
                    }
                    print(f"\n에러: {error_info['message']}")
                    if self.on_error:
                        self.on_error(error_info)
                    break


# 사용 예시 1: 기본 사용
async def basic_example():
    """기본 사용 예시"""
    client = RAGWebSocketClient("localhost:8000", "python-session-123")
    await client.connect_and_chat("GraphRAG에 대해 설명해주세요")


# 사용 예시 2: 콜백 활용
async def callback_example():
    """콜백 활용 예시"""
    client = RAGWebSocketClient("localhost:8000", "python-session-456")

    # 콜백 함수 등록
    def on_token_handler(token: str) -> None:
        # 토큰 처리 (예: 데이터베이스 저장, UI 업데이트 등)
        pass

    def on_sources_handler(sources: list) -> None:
        print("\n참고 문서:")
        for source in sources:
            print(f"  - {source.get('title')} (점수: {source.get('score')})")

    def on_complete_handler(stats: dict) -> None:
        print(f"\n처리 완료: {stats}")

    def on_error_handler(error: dict) -> None:
        print(f"\n에러 발생: {error['message']}")
        print("해결 방법:")
        for solution in error.get("solutions", []):
            print(f"  - {solution}")

    client.on_token = on_token_handler
    client.on_sources = on_sources_handler
    client.on_complete = on_complete_handler
    client.on_error = on_error_handler

    await client.connect_and_chat("RAG 시스템의 장점은 무엇인가요?")


# 실행
if __name__ == "__main__":
    # 기본 예시 실행
    asyncio.run(basic_example())

    # 또는 콜백 예시 실행
    # asyncio.run(callback_example())
```

---

## 에러 처리

### 에러 코드 목록

WebSocket API는 다음과 같은 에러 코드를 반환할 수 있습니다.

| 에러 코드 | 설명 | 대응 방법 |
|-----------|------|-----------|
| `WS-001-INVALID_JSON` | 잘못된 JSON 형식 | JSON 형식 확인 및 재전송 |
| `WS-002-VALIDATION_ERROR` | 메시지 검증 실패 | 필수 필드 확인 (type, message_id, content, session_id) |
| `WS-003-SERVICE_NOT_INITIALIZED` | 채팅 서비스 미초기화 | 서버 관리자에게 문의 |
| `WS-999-INTERNAL_ERROR` | 내부 서버 에러 | 잠시 후 재시도 |
| `GEN-001` ~ `GEN-999` | LLM 생성 관련 에러 | 에러 메시지 및 solutions 참고 |
| `SEARCH-001` ~ `SEARCH-999` | 검색 관련 에러 | 에러 메시지 및 solutions 참고 |

전체 에러 코드는 [에러 시스템 가이드](../CLAUDE.md#4-에러-시스템-v20-bilingual)를 참고하세요.

### 재연결 전략

WebSocket 연결이 끊어질 수 있으므로 자동 재연결 로직을 구현하는 것이 좋습니다.

```javascript
class AutoReconnectWebSocket {
  constructor(url, options = {}) {
    this.url = url;
    this.maxRetries = options.maxRetries || 5;
    this.retryDelay = options.retryDelay || 1000;
    this.retryCount = 0;
    this.ws = null;
    this.shouldReconnect = true;
  }

  connect() {
    this.ws = new WebSocket(this.url);

    this.ws.onopen = () => {
      console.log('WebSocket 연결됨');
      this.retryCount = 0; // 성공 시 재시도 카운터 초기화
    };

    this.ws.onclose = (event) => {
      console.log('WebSocket 연결 종료:', event.code);

      if (this.shouldReconnect && this.retryCount < this.maxRetries) {
        this.retryCount++;
        const delay = this.retryDelay * Math.pow(2, this.retryCount - 1); // 지수 백오프
        console.log(`${delay}ms 후 재연결 시도 (${this.retryCount}/${this.maxRetries})`);

        setTimeout(() => {
          this.connect();
        }, delay);
      } else if (this.retryCount >= this.maxRetries) {
        console.error('최대 재연결 시도 횟수 초과');
      }
    };

    this.ws.onerror = (error) => {
      console.error('WebSocket 에러:', error);
    };

    this.ws.onmessage = (event) => {
      // 메시지 처리 로직
      const data = JSON.parse(event.data);
      console.log('메시지 수신:', data);
    };
  }

  send(message) {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(message);
    } else {
      console.error('WebSocket 미연결');
    }
  }

  disconnect() {
    this.shouldReconnect = false;
    if (this.ws) {
      this.ws.close();
    }
  }
}

// 사용 예시
const ws = new AutoReconnectWebSocket(
  'wss://your-domain.com/chat-ws?session_id=session-123',
  {
    maxRetries: 5,
    retryDelay: 1000
  }
);

ws.connect();
```

### 타임아웃 처리

장시간 응답이 없을 경우를 대비한 타임아웃 처리입니다.

```javascript
class TimeoutWebSocket {
  constructor(url, timeout = 30000) {
    this.url = url;
    this.timeout = timeout;
    this.ws = null;
    this.timeoutId = null;
  }

  connect() {
    this.ws = new WebSocket(this.url);

    this.ws.onopen = () => {
      console.log('WebSocket 연결됨');
    };

    this.ws.onmessage = (event) => {
      // 메시지 수신 시 타임아웃 초기화
      this.resetTimeout();

      const data = JSON.parse(event.data);

      if (data.type === 'stream_end' || data.type === 'stream_error') {
        // 스트리밍 완료 또는 에러 시 타임아웃 해제
        this.clearTimeout();
      }
    };

    this.ws.onerror = (error) => {
      console.error('WebSocket 에러:', error);
      this.clearTimeout();
    };

    this.ws.onclose = () => {
      console.log('WebSocket 연결 종료');
      this.clearTimeout();
    };
  }

  startTimeout() {
    this.timeoutId = setTimeout(() => {
      console.error('타임아웃: 응답이 없습니다');
      this.ws.close();
    }, this.timeout);
  }

  resetTimeout() {
    this.clearTimeout();
    this.startTimeout();
  }

  clearTimeout() {
    if (this.timeoutId) {
      clearTimeout(this.timeoutId);
      this.timeoutId = null;
    }
  }

  sendMessage(message) {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(message);
      this.startTimeout(); // 메시지 전송 시 타임아웃 시작
    }
  }
}
```

---

## 보안 고려사항

### 1. HTTPS/WSS 사용

프로덕션 환경에서는 반드시 암호화된 연결(WSS)을 사용하세요.

```javascript
// 개발 환경
const wsUrl = 'ws://localhost:8000/chat-ws';

// 프로덕션 환경
const wsUrl = 'wss://your-domain.com/chat-ws';
```

### 2. 세션 ID 보안

세션 ID는 예측 불가능한 값을 사용하고, 클라이언트 측에서 안전하게 관리하세요.

```javascript
// UUID v4 사용 권장
const sessionId = crypto.randomUUID();
sessionStorage.setItem('rag_session_id', sessionId);
```

### 3. 메시지 크기 제한

너무 큰 메시지는 서버 부하를 일으킬 수 있습니다. 클라이언트에서 크기를 제한하세요.

```javascript
const MAX_MESSAGE_LENGTH = 10000;

function sendMessage(content) {
  if (content.length > MAX_MESSAGE_LENGTH) {
    alert(`메시지는 ${MAX_MESSAGE_LENGTH}자를 초과할 수 없습니다`);
    return;
  }

  ws.send(JSON.stringify({
    type: 'message',
    message_id: crypto.randomUUID(),
    content: content,
    session_id: sessionId
  }));
}
```

---

## FAQ

### Q1: SSE(`/chat/stream`)와 WebSocket(`/chat-ws`)을 언제 사용해야 하나요?

**SSE 사용 권장:**
- 단방향 스트리밍만 필요한 경우
- 간단한 구현이 필요한 경우
- 자동 재연결이 필요한 경우
- HTTP/2 서버 푸시를 활용하고 싶은 경우

**WebSocket 사용 권장:**
- 양방향 실시간 통신이 필요한 경우
- 더 낮은 지연 시간이 필요한 경우
- 토큰 단위의 세밀한 스트리밍이 필요한 경우
- 여러 메시지를 주고받는 채팅 앱

### Q2: 세션은 얼마나 유지되나요?

기본적으로 세션은 **30분**간 유지됩니다. **서버가 확정한** `session_id`를 사용하면 대화 컨텍스트가 유지됩니다.

> **주의**: UUID4 형식이 아닌 커스텀 ID(예: `my-session`)는 서버가 새 UUID4로 교체합니다. 교체된 ID는 `stream_start.session_id`로 회신되므로, 커스텀 ID를 그대로 재사용하면 매번 새 세션이 생성되어 컨텍스트가 유지되지 않습니다.

```javascript
// 서버 확정 세션 ID를 저장해서 재사용
let serverSessionId = null;

ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  if (data.type === 'stream_start') {
    // 서버가 확정(필요 시 교체)한 세션 ID 저장
    serverSessionId = data.session_id;
  }
  // ... 다른 이벤트 처리
};

// 첫 번째 질문 (연결 시 사용한 ID 그대로)
ws.send(JSON.stringify({
  type: 'message',
  message_id: 'msg-1',
  content: '첫 번째 질문',
  session_id: sessionId
}));

// 잠시 후 — 서버 확정 ID로 후속 질문 (대화 컨텍스트 유지)
ws.send(JSON.stringify({
  type: 'message',
  message_id: 'msg-2',
  content: '이전 답변에 대한 추가 질문',
  session_id: serverSessionId // stream_start로 회신된 서버 확정 ID
}));
```

### Q3: 동시에 여러 메시지를 보낼 수 있나요?

기술적으로는 가능하지만, **권장하지 않습니다**.

WebSocket은 순차적으로 메시지를 처리하므로, 이전 응답이 완료(`stream_end` 이벤트)되기 전에 새 메시지를 보내면 혼란이 발생할 수 있습니다.

```javascript
// ❌ 나쁜 예: 동시에 여러 메시지
ws.send(message1);
ws.send(message2); // 이전 응답이 완료되지 않음

// ✅ 좋은 예: 순차 전송
ws.send(message1);
// stream_end 이벤트 수신 후
ws.send(message2);
```

### Q4: WebSocket 연결이 자주 끊어집니다. 왜 그런가요?

가능한 원인:
1. **네트워크 불안정**: 모바일 환경에서 흔함
2. **프록시/방화벽**: WebSocket을 차단하는 경우
3. **서버 타임아웃**: 일정 시간 메시지가 없으면 연결 종료
4. **클라이언트 탭 비활성화**: 브라우저가 비활성 탭의 WebSocket을 종료

해결 방법:
- 자동 재연결 로직 구현 (위 "재연결 전략" 참고)
- 주기적인 핑/퐁 메시지로 연결 유지
- 연결 품질 모니터링

### Q5: Rate Limit은 어떻게 되나요?

현재 WebSocket API에는 별도의 Rate Limit이 없습니다. 다만, 각 메시지는 일반 API와 동일한 처리 시간이 소요되므로, 너무 빠르게 메시지를 보내면 서버 부하가 발생할 수 있습니다.

적절한 사용 예시:
```javascript
// 이전 응답이 완료된 후에만 새 메시지 전송
let isProcessing = false;

ws.onmessage = (event) => {
  const data = JSON.parse(event.data);

  if (data.type === 'stream_start') {
    isProcessing = true;
  } else if (data.type === 'stream_end' || data.type === 'stream_error') {
    isProcessing = false;
  }
};

function sendMessage(content) {
  if (isProcessing) {
    alert('이전 응답을 처리 중입니다. 잠시만 기다려주세요.');
    return;
  }

  ws.send(JSON.stringify({...}));
}
```

### Q6: 프록시(Nginx, Apache) 뒤에서 WebSocket을 사용할 때 주의사항은?

WebSocket은 HTTP 업그레이드 헤더를 사용하므로, 프록시 설정이 필요합니다.

**Nginx 설정 예시:**
```nginx
location /chat-ws {
    proxy_pass http://backend;

    # WebSocket 필수 헤더
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";

    # 타임아웃 설정 (긴 연결 유지)
    proxy_connect_timeout 7d;
    proxy_send_timeout 7d;
    proxy_read_timeout 7d;

    # 버퍼링 비활성화
    proxy_buffering off;
}
```

**Apache 설정 예시:**
```apache
<Location /chat-ws>
    ProxyPass ws://backend/chat-ws
    ProxyPassReverse ws://backend/chat-ws
</Location>

# WebSocket 프록시 모듈 활성화
LoadModule proxy_wstunnel_module modules/mod_proxy_wstunnel.so
```

---

## cURL 테스트

WebSocket은 cURL로 직접 테스트하기 어렵습니다. 대신 `websocat` 도구를 사용하세요.

### websocat 설치

```bash
# macOS
brew install websocat

# Linux
cargo install websocat

# Windows
# https://github.com/vi/websocat/releases 에서 다운로드
```

### 테스트 예시

```bash
# WebSocket 연결 및 메시지 전송
echo '{"type":"message","message_id":"test-123","content":"안녕하세요","session_id":"test-session"}' | \
  websocat ws://localhost:8000/chat-ws?session_id=test-session

# 또는 인터랙티브 모드
websocat ws://localhost:8000/chat-ws?session_id=test-session
# 연결 후 JSON 메시지 입력:
# {"type":"message","message_id":"test-123","content":"GraphRAG란?","session_id":"test-session"}
```

---

## 성능 최적화 팁

### 1. 토큰 버퍼링

토큰을 개별적으로 렌더링하면 성능 문제가 발생할 수 있습니다. 작은 버퍼에 모았다가 한 번에 렌더링하세요.

```javascript
class TokenBuffer {
  constructor(flushInterval = 50) {
    this.buffer = [];
    this.flushInterval = flushInterval;
    this.timerId = null;
  }

  add(token) {
    this.buffer.push(token);

    if (!this.timerId) {
      this.timerId = setTimeout(() => {
        this.flush();
      }, this.flushInterval);
    }
  }

  flush() {
    if (this.buffer.length > 0) {
      const text = this.buffer.join('');
      // UI 업데이트
      document.getElementById('response').textContent += text;
      this.buffer = [];
    }
    this.timerId = null;
  }
}

const buffer = new TokenBuffer(50); // 50ms마다 플러시

ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  if (data.type === 'stream_token') {
    buffer.add(data.token);
  } else if (data.type === 'stream_end') {
    buffer.flush(); // 즉시 플러시
  }
};
```

### 2. Virtual Scrolling

긴 응답의 경우 전체를 렌더링하지 말고, 보이는 부분만 렌더링하세요.

```javascript
// react-window 라이브러리 활용 권장
import { FixedSizeList } from 'react-window';

function VirtualizedResponse({ tokens }) {
  const Row = ({ index, style }) => (
    <div style={style}>{tokens[index]}</div>
  );

  return (
    <FixedSizeList
      height={600}
      itemCount={tokens.length}
      itemSize={20}
      width="100%"
    >
      {Row}
    </FixedSizeList>
  );
}
```

### 3. 연결 풀링

여러 사용자를 위한 서버 사이드 구현에서는 연결을 재사용하세요.

```python
# FastAPI 서버에서 WebSocket 연결 관리
class ConnectionManager:
    def __init__(self):
        self.active_connections: dict[str, WebSocket] = {}

    async def connect(self, session_id: str, websocket: WebSocket):
        await websocket.accept()
        self.active_connections[session_id] = websocket

    def disconnect(self, session_id: str):
        self.active_connections.pop(session_id, None)

    async def send_personal_message(self, message: str, session_id: str):
        websocket = self.active_connections.get(session_id)
        if websocket:
            await websocket.send_text(message)
```

---

## 버전 히스토리

| 버전 | 날짜 | 변경사항 |
|------|------|----------|
| v1.0.9 | 2026-01-16 | 초기 WebSocket API 릴리즈 |

---

## 관련 문서

- [Streaming API 사용 가이드](./streaming-api-guide.md) - SSE 기반 스트리밍 API
- [CLAUDE.md](../CLAUDE.md) - 프로젝트 개요
- [API Reference](./API_REFERENCE.md) - 전체 API 문서
- [에러 시스템 가이드](../CLAUDE.md#4-에러-시스템-v20-bilingual) - ErrorCode 설명
