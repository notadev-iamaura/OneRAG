# Streaming API 사용 가이드

## 개요

RAG_Standard는 SSE(Server-Sent Events) 기반 스트리밍 API를 제공합니다.
LLM 응답을 실시간으로 수신하여 사용자 경험을 대폭 개선할 수 있습니다.

### 주요 특징

- **실시간 응답**: 답변 생성 즉시 클라이언트로 전송
- **Multi-LLM 지원**: Google Gemini, OpenAI GPT, Anthropic Claude 모두 스트리밍 가능
- **구조화된 이벤트**: `metadata`, `chunk`, `done`, `error` 4가지 이벤트 타입
- **Rate Limiting**: 100회/15분 제한으로 서버 안정성 보장

---

## 엔드포인트

### POST /chat/stream

스트리밍 채팅 응답을 반환합니다.

**Request:**
```json
{
  "message": "안녕하세요, RAG 시스템에 대해 설명해주세요",
  "session_id": "optional-session-id",
  "options": {
    "temperature": 0.7,
    "max_tokens": 2000
  }
}
```

| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| `message` | string | ✅ | 사용자 메시지 (1~10,000자) |
| `session_id` | string | ❌ | 세션 ID (없으면 새로 생성) |
| `options` | object | ❌ | LLM 생성 옵션 |

**Response Headers:**
```
Content-Type: text/event-stream
Cache-Control: no-cache
Connection: keep-alive
X-Accel-Buffering: no
```

---

## SSE 이벤트 형식

### 1. metadata 이벤트

검색 및 리랭킹 완료 시 전송됩니다.

```
event: metadata
data: {"event": "metadata", "session_id": "abc-123", "search_results": 5, "ranked_results": 3}
```

| 필드 | 타입 | 설명 |
|------|------|------|
| `session_id` | string | 세션 ID |
| `search_results` | number | 검색된 문서 수 |
| `ranked_results` | number | 리랭킹 후 문서 수 |

### 2. chunk 이벤트

LLM이 텍스트 청크를 생성할 때마다 전송됩니다.

```
event: chunk
data: {"event": "chunk", "data": "안녕하세요", "chunk_index": 0}
```

| 필드 | 타입 | 설명 |
|------|------|------|
| `data` | string | 텍스트 청크 |
| `chunk_index` | number | 청크 순서 (0부터 시작) |

### 3. done 이벤트

스트리밍 완료 시 전송됩니다.

```
event: done
data: {"event": "done", "session_id": "abc-123", "total_chunks": 15, "tokens_used": 150, "processing_time": 2.5}
```

| 필드 | 타입 | 설명 |
|------|------|------|
| `session_id` | string | 세션 ID |
| `total_chunks` | number | 총 청크 수 |
| `tokens_used` | number | 사용된 토큰 수 |
| `processing_time` | number | 처리 시간 (초) |

### 4. error 이벤트

에러 발생 시 전송됩니다.

```
event: error
data: {"event": "error", "error_code": "GENERAL-004", "message": "스트리밍 처리 중 오류가 발생했습니다"}
```

| 필드 | 타입 | 설명 |
|------|------|------|
| `error_code` | string | 에러 코드 |
| `message` | string | 사용자 친화적 에러 메시지 |
| `suggestion` | string | 해결 방법 (선택적) |

---

## 프론트엔드 연동 예시

### JavaScript (Fetch API)

```javascript
async function streamChat(message) {
  const response = await fetch('/api/chat/stream', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Accept': 'text/event-stream',
    },
    body: JSON.stringify({ message }),
  });

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop() || '';

    for (const line of lines) {
      if (line.startsWith('data: ')) {
        const data = JSON.parse(line.slice(6));

        switch (data.event) {
          case 'metadata':
            console.log('검색 완료:', data.search_results, '건');
            break;
          case 'chunk':
            // UI에 텍스트 추가
            appendToChat(data.data);
            break;
          case 'done':
            console.log('완료:', data.total_chunks, '청크');
            break;
          case 'error':
            console.error('에러:', data.message);
            break;
        }
      }
    }
  }
}

function appendToChat(text) {
  const chatContainer = document.getElementById('chat');
  chatContainer.textContent += text;
}
```

### React Hook 예시

```typescript
import { useState, useCallback } from 'react';

interface StreamState {
  chunks: string[];
  isStreaming: boolean;
  metadata: { sessionId: string; searchResults: number } | null;
  error: string | null;
}

export function useStreamChat() {
  const [state, setState] = useState<StreamState>({
    chunks: [],
    isStreaming: false,
    metadata: null,
    error: null,
  });

  const sendMessage = useCallback(async (message: string) => {
    setState({ chunks: [], isStreaming: true, metadata: null, error: null });

    try {
      const response = await fetch('/api/chat/stream', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'text/event-stream',
        },
        body: JSON.stringify({ message }),
      });

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }

      const reader = response.body?.getReader();
      if (!reader) throw new Error('스트림을 읽을 수 없습니다');

      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            const data = JSON.parse(line.slice(6));

            if (data.event === 'metadata') {
              setState(prev => ({
                ...prev,
                metadata: {
                  sessionId: data.session_id,
                  searchResults: data.search_results,
                },
              }));
            } else if (data.event === 'chunk') {
              setState(prev => ({
                ...prev,
                chunks: [...prev.chunks, data.data],
              }));
            } else if (data.event === 'error') {
              setState(prev => ({
                ...prev,
                error: data.message,
              }));
            }
          }
        }
      }
    } catch (err) {
      setState(prev => ({
        ...prev,
        error: err instanceof Error ? err.message : '알 수 없는 에러',
      }));
    } finally {
      setState(prev => ({ ...prev, isStreaming: false }));
    }
  }, []);

  // 전체 텍스트 반환
  const fullText = state.chunks.join('');

  return {
    fullText,
    chunks: state.chunks,
    isStreaming: state.isStreaming,
    metadata: state.metadata,
    error: state.error,
    sendMessage,
  };
}
```

### React 컴포넌트 사용 예시

```tsx
function ChatComponent() {
  const { fullText, isStreaming, metadata, error, sendMessage } = useStreamChat();
  const [input, setInput] = useState('');

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (input.trim()) {
      sendMessage(input);
      setInput('');
    }
  };

  return (
    <div className="chat-container">
      {/* 메타데이터 표시 */}
      {metadata && (
        <div className="metadata">
          검색 결과: {metadata.searchResults}건
        </div>
      )}

      {/* 스트리밍 응답 표시 */}
      <div className="response">
        {fullText}
        {isStreaming && <span className="cursor">▌</span>}
      </div>

      {/* 에러 표시 */}
      {error && <div className="error">{error}</div>}

      {/* 입력 폼 */}
      <form onSubmit={handleSubmit}>
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="메시지를 입력하세요..."
          disabled={isStreaming}
        />
        <button type="submit" disabled={isStreaming}>
          {isStreaming ? '생성 중...' : '전송'}
        </button>
      </form>
    </div>
  );
}
```

### Python (httpx) 예시

```python
import httpx
import json


async def stream_chat(message: str, base_url: str = "http://localhost:8000"):
    """스트리밍 채팅 API 호출"""
    async with httpx.AsyncClient() as client:
        async with client.stream(
            "POST",
            f"{base_url}/api/chat/stream",
            json={"message": message},
            headers={"Accept": "text/event-stream"},
        ) as response:
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    data = json.loads(line[6:])

                    if data["event"] == "metadata":
                        print(f"검색 완료: {data['search_results']}건")
                    elif data["event"] == "chunk":
                        print(data["data"], end="", flush=True)
                    elif data["event"] == "done":
                        print(f"\n\n완료: {data['total_chunks']}청크")
                    elif data["event"] == "error":
                        print(f"\n에러: {data['message']}")


# 사용 예시
import asyncio
asyncio.run(stream_chat("RAG 시스템이란 무엇인가요?"))
```

---

## 에러 처리

| 에러 코드 | HTTP 상태 | 설명 | 대응 방법 |
|-----------|----------|------|-----------|
| `SESSION-001` | 200 (SSE) | 세션 처리 실패 | 새 세션으로 재시도 |
| `GENERAL-004` | 200 (SSE) | 스트리밍 중 오류 | 잠시 후 재시도 |
| `422` | 422 | 요청 유효성 검사 실패 | 요청 형식 확인 |
| `429` | 429 | Rate Limit 초과 | 15분 후 재시도 |
| `503` | 503 | 서비스 초기화 안됨 | 서버 상태 확인 |

### 에러 복구 전략

```javascript
async function streamChatWithRetry(message, maxRetries = 3) {
  for (let i = 0; i < maxRetries; i++) {
    try {
      await streamChat(message);
      return; // 성공 시 종료
    } catch (error) {
      if (error.status === 429) {
        // Rate Limit: 지수 백오프
        const delay = Math.pow(2, i) * 1000;
        console.log(`Rate limit, ${delay}ms 후 재시도...`);
        await new Promise(resolve => setTimeout(resolve, delay));
      } else if (error.status >= 500) {
        // 서버 에러: 짧은 대기 후 재시도
        await new Promise(resolve => setTimeout(resolve, 1000));
      } else {
        // 클라이언트 에러: 재시도 불가
        throw error;
      }
    }
  }
  throw new Error('최대 재시도 횟수 초과');
}
```

---

## cURL 테스트

```bash
# 기본 스트리밍 요청
curl -X POST http://localhost:8000/api/chat/stream \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream" \
  -d '{"message": "안녕하세요, RAG 시스템에 대해 설명해주세요"}'

# 세션 ID 지정
curl -X POST http://localhost:8000/api/chat/stream \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream" \
  -d '{"message": "이전 대화를 기억하나요?", "session_id": "my-session-123"}'

# 옵션 포함
curl -X POST http://localhost:8000/api/chat/stream \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream" \
  -d '{
    "message": "자세히 설명해주세요",
    "options": {"temperature": 0.7, "max_tokens": 2000}
  }'
```

---

## FAQ

### Q: 스트리밍과 일반 `/chat` 엔드포인트의 차이점은?

| 항목 | `/chat` | `/chat/stream` |
|------|---------|----------------|
| 응답 형식 | JSON | SSE |
| 첫 응답 시간 | 전체 생성 후 | 즉시 (청크 단위) |
| 사용자 경험 | 대기 시간 있음 | 실시간 타이핑 효과 |
| 네트워크 효율 | 단일 요청/응답 | 지속 연결 |

### Q: 세션은 얼마나 유지되나요?

기본 30분입니다. `session_id`를 저장해두면 대화 컨텍스트를 유지할 수 있습니다.

### Q: Rate Limit에 걸리면?

429 응답을 받습니다. 15분 후 다시 시도하거나, 지수 백오프로 재시도하세요.

### Q: Nginx 프록시 뒤에서 사용 시 주의사항은?

`X-Accel-Buffering: no` 헤더가 자동으로 포함됩니다. Nginx 설정에서 `proxy_buffering off;`를 추가하면 더 확실합니다.

```nginx
location /api/chat/stream {
    proxy_pass http://backend;
    proxy_buffering off;
    proxy_cache off;
    proxy_set_header Connection '';
    proxy_http_version 1.1;
    chunked_transfer_encoding off;
}
```

---

## 버전 히스토리

| 버전 | 날짜 | 변경사항 |
|------|------|----------|
| v1.0.8 | 2026-01-15 | 초기 Streaming API 릴리즈 |

---

## 관련 문서

- [CLAUDE.md](../CLAUDE.md) - 프로젝트 개요
- [API Reference](./api-reference.md) - 전체 API 문서
- [에러 시스템 가이드](./error-system-guide.md) - ErrorCode 설명
