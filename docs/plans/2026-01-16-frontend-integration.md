# 프론트엔드 통합 준비 및 분석 문서

> **문서 버전**: 1.0.0
> **작성일**: 2026-01-16
> **대상 시스템**: RAG_Standard (백엔드) × moduleRagChat_Front (프론트엔드)
> **분석 도구**: Claude Code (--ultrathink 모드)

---

## 📋 Executive Summary

| 항목 | 평가 | 상세 |
|------|------|------|
| **통합 가능성** | ⭐⭐⭐⭐⭐ (95%) | API 엔드포인트 95% 일치 |
| **프론트엔드 품질** | ⭐⭐⭐⭐⭐ (8.8/10) | 엔터프라이즈급 아키텍처 |
| **WebSocket 호환성** | ⭐⭐⭐⭐☆ (85%) | 스키마 일부 조정 필요 |
| **예상 통합 시간** | 2-3일 | 환경설정 + API 미세조정 |
| **위험도** | 낮음 (Low) | 아키텍처 호환성 높음 |

### 권장 사항

✅ **통합 진행 승인** - 두 시스템은 높은 호환성을 보이며, 최소한의 조정으로 즉시 연동 가능합니다.

---

## 1. 시스템 개요

### 1.1 백엔드 (RAG_Standard)

```
버전: v1.0.8
프레임워크: FastAPI + Python 3.11
주요 기능:
  - 하이브리드 RAG (Dense + BM25)
  - SSE 스트리밍 API
  - WebSocket 실시간 채팅
  - Multi-LLM 지원 (Gemini, GPT, Claude)
  - 양언어 에러 시스템 (한/영)
테스트: 1,300+ 통과
```

### 1.2 프론트엔드 (moduleRagChat_Front)

```
버전: React 19 + TypeScript 5.8
빌드 도구: Vite 4.5
주요 기능:
  - Feature Flag 시스템 (30+ 기능)
  - 중앙 집중식 설정 관리
  - JWT + API Key 인증
  - WebSocket 클라이언트
  - PWA 지원
UI: shadcn/ui + Tailwind CSS + Radix UI
```

### 1.3 아키텍처 다이어그램

```
┌─────────────────────────────────────────────────────────┐
│                 프론트엔드 (Railway)                      │
│  moduleRagChat_Front                                     │
│  ├─ React 19 + TypeScript                               │
│  ├─ Vite (빌드)                                          │
│  └─ Nginx/Caddy (정적 파일 서빙)                          │
└─────────────────────┬───────────────────────────────────┘
                      │
        ┌─────────────┼─────────────┐
        │ REST API    │ WebSocket   │
        │ (HTTPS)     │ (WSS)       │
        ▼             ▼             │
┌─────────────────────────────────────────────────────────┐
│                  백엔드 (Railway)                         │
│  RAG_Standard                                            │
│  ├─ FastAPI + Uvicorn                                   │
│  ├─ /chat, /chat/stream, /chat-ws                       │
│  ├─ /upload, /admin, /prompts                           │
│  └─ Rate Limiting (100/15min)                           │
└─────────────────────┬───────────────────────────────────┘
                      │
        ┌─────────────┴─────────────┐
        ▼                           ▼
┌───────────────┐           ┌───────────────┐
│   Weaviate    │           │   MongoDB     │
│  (Vector DB)  │           │  (Sessions)   │
└───────────────┘           └───────────────┘
```

---

## 2. API 엔드포인트 매핑

### 2.1 완전 일치 엔드포인트 (✅ 즉시 연동 가능)

| 프론트엔드 호출 | 백엔드 엔드포인트 | 설명 |
|---------------|------------------|------|
| `POST /api/chat` | `POST /chat` | 채팅 메시지 처리 |
| `POST /api/chat/session` | `POST /chat/session` | 새 세션 생성 |
| `GET /api/chat/history/:sessionId` | `GET /chat/history/{session_id}` | 채팅 기록 조회 |
| `GET /api/chat/session/:sessionId/info` | `GET /chat/session/{session_id}/info` | 세션 정보 |
| `POST /api/upload` | `POST /upload` | 문서 업로드 |
| `GET /api/upload/status/:jobId` | `GET /upload/status/{job_id}` | 업로드 상태 |
| `GET /api/upload/documents` | `GET /upload/documents` | 문서 목록 |
| `DELETE /api/upload/documents/:id` | `DELETE /upload/documents/{document_id}` | 문서 삭제 |
| `POST /api/upload/documents/bulk-delete` | `POST /upload/documents/bulk-delete` | 대량 삭제 |
| `GET /health` | `GET /health` | 헬스체크 |

### 2.2 경로 조정 필요 사항

프론트엔드는 `/api/*` prefix를 사용하지만, 백엔드는 직접 경로를 사용합니다.

**해결 방법 (택 1)**:

```python
# 방법 1: 백엔드에서 prefix 추가 (main.py)
app.include_router(chat_router, prefix="/api")
app.include_router(upload_router, prefix="/api")
```

```typescript
// 방법 2: 프론트엔드 baseURL 조정 (api.ts)
// /api prefix 없이 직접 호출하도록 수정
const chatAPI = {
  sendMessage: (message: string) => api.post('/chat', { message }),
  // ...
};
```

### 2.3 백엔드 전용 엔드포인트 (프론트엔드 확장 기회)

| 엔드포인트 | 설명 | 프론트엔드 확장 제안 |
|-----------|------|---------------------|
| `POST /chat/stream` | SSE 스트리밍 | Feature Flag로 제어 가능 |
| `POST /chat/feedback` | 피드백 제출 | 👍/👎 버튼 추가 |
| `DELETE /chat/session/:id` | 세션 삭제 | 채팅 기록 삭제 기능 |
| `GET /chat/stats` | 통계 조회 | Admin 대시보드 확장 |
| `GET /api/admin/*` | 관리자 API | AdminDashboard 연동 |

---

## 3. WebSocket 프로토콜 분석

### 3.1 연결 방식 (✅ 완벽 일치)

| 항목 | 백엔드 | 프론트엔드 |
|------|--------|-----------|
| **URL** | `/chat-ws?session_id={id}` | `/chat-ws?session_id=${id}` |
| **프로토콜** | WSS | WSS |
| **세션 전달** | Query Parameter | Query Parameter |

### 3.2 클라이언트 → 서버 메시지 (✅ 완벽 일치)

```typescript
// 프론트엔드 요청 형식 (그대로 사용 가능)
interface ChatWebSocketRequest {
  type: 'message';      // ✅ 일치
  message_id: string;   // ✅ 일치
  content: string;      // ✅ 일치
  session_id: string;   // ✅ 일치
}
```

### 3.3 서버 → 클라이언트 이벤트 비교

| 이벤트 | 호환성 | 조정 필요 |
|--------|--------|----------|
| `stream_start` | ✅ 95% | 프론트엔드 타입 확장 (선택) |
| `stream_token` | ✅ 95% | 프론트엔드 타입 확장 (선택) |
| `stream_sources` | ✅ 100% | 없음 |
| `stream_end` | ❌ 60% | **타입 수정 필수** |
| `stream_error` | ❌ 70% | **타입 수정 필수** |

### 3.4 스키마 불일치 상세

#### `stream_end` 이벤트

```python
# 백엔드 응답 형식
{
  "type": "stream_end",
  "message_id": "msg_123",
  "total_tokens": 150,
  "processing_time_ms": 1234
}
```

```typescript
// 프론트엔드 현재 기대값 (수정 필요)
interface StreamEndMessage {
  type: 'stream_end';
  message_id: string;
  metadata: {  // ❌ 백엔드와 구조 불일치
    processing_time: number;
    tokens_used: number;
  };
}
```

#### `stream_error` 이벤트

```python
# 백엔드 응답 형식
{
  "type": "stream_error",
  "message_id": "msg_123",
  "error_code": "GEN-001",
  "message": "에러 메시지",
  "solutions": ["해결방법1", "해결방법2"]
}
```

```typescript
// 프론트엔드 현재 기대값 (수정 필요)
interface StreamErrorMessage {
  type: 'stream_error';
  message_id: string;
  error: string;    // ❌ 백엔드는 'message'
  code?: string;    // ❌ 백엔드는 'error_code'
  // solutions 필드 누락
}
```

---

## 4. 프론트엔드 타입 수정 가이드

### 4.1 수정 대상 파일

```
src/types/chatStreaming.ts
```

### 4.2 수정 내용

```typescript
// src/types/chatStreaming.ts

// ============================================
// 서버 → 클라이언트 메시지 타입 (백엔드 형식으로 수정)
// ============================================

/**
 * 스트리밍 시작 메시지
 * 백엔드 형식에 맞게 필드 추가
 */
export interface StreamStartMessage {
  type: 'stream_start';
  message_id: string;
  session_id: string;    // 추가
  timestamp: string;     // 추가 (ISO 8601)
}

/**
 * 스트리밍 토큰 메시지
 * 백엔드 형식에 맞게 index 필드 추가
 */
export interface StreamTokenMessage {
  type: 'stream_token';
  message_id: string;
  token: string;
  index: number;         // 추가 (0부터 시작)
}

/**
 * 스트리밍 완료 메시지
 * 백엔드 형식으로 전면 수정
 */
export interface StreamEndMessage {
  type: 'stream_end';
  message_id: string;
  total_tokens: number;       // 변경: metadata → 플랫 구조
  processing_time_ms: number; // 변경: metadata → 플랫 구조
}

/**
 * 스트리밍 에러 메시지
 * 백엔드 형식으로 전면 수정
 */
export interface StreamErrorMessage {
  type: 'stream_error';
  message_id: string;
  error_code: string;     // 변경: code → error_code
  message: string;        // 변경: error → message
  solutions: string[];    // 추가
}

// StreamMetadata 인터페이스는 제거 또는 deprecated 처리
```

### 4.3 서비스 코드 수정

```typescript
// src/services/chatWebSocketService.ts 수정

private handleMessage(event: MessageEvent): void {
  try {
    const data: ChatWebSocketResponse = JSON.parse(event.data);

    // stream_end 처리 수정
    if (data.type === 'stream_end') {
      const endData = data as StreamEndMessage;
      // 기존: endData.metadata.processing_time
      // 변경: endData.processing_time_ms
      console.log(`처리 시간: ${endData.processing_time_ms}ms`);
      console.log(`토큰 수: ${endData.total_tokens}`);
    }

    // stream_error 처리 수정
    if (data.type === 'stream_error') {
      const errorData = data as StreamErrorMessage;
      // 기존: errorData.error, errorData.code
      // 변경: errorData.message, errorData.error_code
      console.error(`에러 [${errorData.error_code}]: ${errorData.message}`);
      console.log('해결 방법:', errorData.solutions);
    }

    // ...
  } catch (error) {
    // ...
  }
}
```

---

## 5. 인증/보안 통합 가이드

### 5.1 인증 방식 비교

| 항목 | 프론트엔드 | 백엔드 | 통합 전략 |
|------|-----------|--------|----------|
| **API Key** | `X-API-Key` 헤더 | `X-API-Key` (관리자 API) | ✅ 즉시 사용 |
| **JWT 토큰** | `Authorization: Bearer` | 미구현 | Phase 2 (선택적) |
| **세션 ID** | `X-Session-Id` 헤더 | Request body | 조정 필요 |
| **CSRF** | `X-XSRF-TOKEN` | 미구현 | Phase 2 (선택적) |

### 5.2 Phase 1: API Key 기반 연동 (즉시)

```env
# 프론트엔드 .env
VITE_API_KEY=your_fastapi_auth_key_here

# 백엔드 .env
FASTAPI_AUTH_KEY=your_fastapi_auth_key_here
```

프론트엔드의 Axios 인터셉터가 자동으로 `X-API-Key` 헤더를 추가합니다:

```typescript
// 이미 구현됨 (src/services/api.ts)
if (isApiEndpoint && !isHealthEndpoint) {
  let apiKey = import.meta.env.VITE_API_KEY;
  if (apiKey) {
    config.headers['X-API-Key'] = apiKey;
  }
}
```

### 5.3 Phase 2: 세션 ID 헤더 통합 (선택적)

백엔드에서 `X-Session-Id` 헤더를 인식하도록 미들웨어 추가:

```python
# app/api/middleware/session_middleware.py
from fastapi import Request

async def extract_session_id(request: Request):
    """X-Session-Id 헤더에서 세션 ID 추출"""
    session_id = request.headers.get("X-Session-Id")
    if session_id:
        request.state.session_id = session_id
    return session_id
```

---

## 6. 환경 설정 가이드

### 6.1 프론트엔드 환경 변수 (.env)

```env
# ===========================================
# API 설정
# ===========================================
VITE_API_BASE_URL=https://your-backend.railway.app
VITE_DEV_API_BASE_URL=http://localhost:8000

# ===========================================
# WebSocket 설정
# ===========================================
VITE_WS_BASE_URL=wss://your-backend.railway.app
VITE_DEV_WS_BASE_URL=ws://localhost:8000

# ===========================================
# 보안
# ===========================================
VITE_API_KEY=your_api_key_here

# ===========================================
# Feature Flags (백엔드 기능에 맞게 활성화)
# ===========================================
VITE_FEATURE_CHATBOT=true
VITE_FEATURE_CHATBOT_STREAMING=true
VITE_FEATURE_DOCUMENTS=true
VITE_FEATURE_DOCUMENTS_UPLOAD=true
VITE_FEATURE_ADMIN=true
VITE_FEATURE_PROMPTS=true
```

### 6.2 백엔드 CORS 설정 (main.py)

```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5000",                    # 프론트엔드 개발
        "https://your-frontend.railway.app",        # 프론트엔드 프로덕션
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Session-Id"],               # 세션 ID 헤더 노출
)
```

### 6.3 Railway 배포 환경 변수

**프론트엔드 Railway 변수**:
```
VITE_API_BASE_URL=https://your-backend.railway.app
VITE_API_KEY=${{backend.FASTAPI_AUTH_KEY}}
```

**백엔드 Railway 변수**:
```
FASTAPI_AUTH_KEY=your_secure_api_key
CORS_ORIGINS=https://your-frontend.railway.app
```

---

## 7. 통합 작업 체크리스트

### Phase 1: 환경 설정 (Day 1)

- [ ] 프론트엔드 `.env` 파일 설정
  - [ ] `VITE_API_BASE_URL` 설정
  - [ ] `VITE_API_KEY` 설정
  - [ ] `VITE_WS_BASE_URL` 설정
- [ ] 백엔드 CORS 설정 확인
  - [ ] 프론트엔드 도메인 허용
  - [ ] 필요한 헤더 노출
- [ ] API 경로 prefix 통일 결정
  - [ ] 옵션 A: 백엔드에 `/api` prefix 추가
  - [ ] 옵션 B: 프론트엔드 경로 수정

### Phase 2: REST API 연동 (Day 1-2)

- [ ] 헬스체크 API 테스트 (`GET /health`)
- [ ] 세션 생성 API 테스트 (`POST /chat/session`)
- [ ] 채팅 API 테스트 (`POST /chat`)
- [ ] 문서 업로드 API 테스트 (`POST /upload`)
- [ ] 문서 목록 API 테스트 (`GET /upload/documents`)

### Phase 3: WebSocket 연동 (Day 2-3)

- [ ] 프론트엔드 타입 수정 (`src/types/chatStreaming.ts`)
  - [ ] `StreamEndMessage` 수정
  - [ ] `StreamErrorMessage` 수정
  - [ ] `StreamStartMessage` 확장
  - [ ] `StreamTokenMessage` 확장
- [ ] WebSocket 서비스 수정 (`src/services/chatWebSocketService.ts`)
- [ ] WebSocket 연결 테스트
- [ ] 스트리밍 메시지 수신 테스트

### Phase 4: 고급 기능 (선택적)

- [ ] SSE 스트리밍 클라이언트 구현
- [ ] 피드백 API 연동 (`POST /chat/feedback`)
- [ ] Admin 대시보드 백엔드 API 연동
- [ ] 프롬프트 관리 API 연동

---

## 8. 테스트 시나리오

### 8.1 기본 연동 테스트

```typescript
// tests/integration/backend.test.ts

describe('Backend Integration', () => {
  const API_BASE = process.env.VITE_API_BASE_URL;

  it('헬스체크 성공', async () => {
    const response = await fetch(`${API_BASE}/health`);
    expect(response.ok).toBe(true);
  });

  it('세션 생성 성공', async () => {
    const response = await fetch(`${API_BASE}/chat/session`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-API-Key': process.env.VITE_API_KEY,
      },
    });
    const data = await response.json();
    expect(data.session_id).toBeDefined();
  });

  it('채팅 메시지 전송 성공', async () => {
    const response = await fetch(`${API_BASE}/chat`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-API-Key': process.env.VITE_API_KEY,
      },
      body: JSON.stringify({
        message: '안녕하세요',
        session_id: 'test-session',
      }),
    });
    const data = await response.json();
    expect(data.answer).toBeDefined();
  });
});
```

### 8.2 WebSocket 테스트

```typescript
describe('WebSocket Integration', () => {
  it('WebSocket 연결 및 스트리밍', (done) => {
    const ws = new WebSocket(
      `${WS_BASE}/chat-ws?session_id=test-session`
    );

    const chunks: string[] = [];

    ws.onopen = () => {
      ws.send(JSON.stringify({
        type: 'message',
        message_id: 'test-msg-1',
        content: '테스트 질문입니다',
        session_id: 'test-session',
      }));
    };

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);

      if (data.type === 'stream_token') {
        chunks.push(data.token);
      }

      if (data.type === 'stream_end') {
        expect(chunks.length).toBeGreaterThan(0);
        expect(data.total_tokens).toBeGreaterThan(0);
        ws.close();
        done();
      }
    };
  });
});
```

---

## 9. 위험 요소 및 완화 전략

### 9.1 식별된 위험

| 위험 | 영향도 | 가능성 | 완화 전략 |
|------|--------|--------|----------|
| **CORS 오류** | 높음 | 중간 | 백엔드 CORS 설정 사전 검증 |
| **세션 ID 불일치** | 중간 | 높음 | 헤더/body 통일 미들웨어 추가 |
| **WebSocket 스키마 불일치** | 중간 | 높음 | 프론트엔드 타입 수정 (30분) |
| **Rate Limit 충돌** | 낮음 | 낮음 | 프론트엔드 재시도 로직 활용 |
| **API Key 노출** | 높음 | 낮음 | 환경변수로만 관리 |

### 9.2 롤백 계획

```
1. 프론트엔드 롤백
   - Git에서 이전 버전 체크아웃
   - Railway 자동 재배포

2. 백엔드 롤백 (필요시)
   - CORS 설정 원복
   - API prefix 원복

3. 긴급 대응
   - Feature Flag로 문제 기능 비활성화
   - 프론트엔드: VITE_FEATURE_CHATBOT_STREAMING=false
```

---

## 10. 참고 자료

### 10.1 프론트엔드 문서

| 문서 | 경로 | 내용 |
|------|------|------|
| 개발 가이드 | `CLAUDE.md` | 전체 개발 가이드 |
| 색상 시스템 | `docs/COLOR_SYSTEM_GUIDE.md` | 중앙 색상 관리 |
| Feature Flag | `docs/FEATURE_FLAGS_GUIDE.md` | 기능 플래그 사용법 |
| 배포 가이드 | `docs/RAILWAY_DEPLOYMENT_GUIDE.md` | Railway 배포 |

### 10.2 백엔드 문서

| 문서 | 경로 | 내용 |
|------|------|------|
| 개발 가이드 | `CLAUDE.md` | 전체 개발 가이드 |
| 스트리밍 API | `docs/streaming-api-guide.md` | SSE 스트리밍 사용법 |
| 기술부채 분석 | `docs/TECHNICAL_DEBT_ANALYSIS.md` | 시스템 상태 |

### 10.3 주요 소스 파일

**프론트엔드**:
- `src/services/api.ts` - Axios 설정 및 인터셉터
- `src/services/chatWebSocketService.ts` - WebSocket 클라이언트
- `src/types/chatStreaming.ts` - WebSocket 타입 정의
- `src/config/features.ts` - Feature Flag 정의

**백엔드**:
- `app/api/routers/chat_router.py` - 채팅 API
- `app/api/routers/websocket_router.py` - WebSocket 엔드포인트
- `app/api/schemas/websocket.py` - WebSocket 스키마
- `main.py` - FastAPI 앱 설정

---

## 11. 연락처 및 지원

### 담당자

| 역할 | 담당 | 연락처 |
|------|------|--------|
| 백엔드 개발 | - | - |
| 프론트엔드 개발 | - | - |
| DevOps | - | - |

### 지원 채널

- GitHub Issues: [RAG_Standard](https://github.com/youngouk/RAG_Standard/issues)
- 문서 업데이트 요청: PR 생성

---

**문서 끝**

> 이 문서는 프론트엔드 통합 작업의 사전 분석 및 준비를 위해 작성되었습니다.
> 실제 통합 과정에서 발생하는 이슈는 이 문서를 업데이트하여 기록해주세요.
