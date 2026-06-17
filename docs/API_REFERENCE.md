# OneRAG API 참조

> 모든 API는 http://localhost:8000/docs (Swagger UI)에서 대화형으로 테스트 가능합니다.

---

## 인증

### API 키 인증
관리자 API (`/api/admin/*`)는 `X-API-Key` 헤더 인증이 필요합니다.

```bash
curl -H "X-API-Key: YOUR_FASTAPI_AUTH_KEY" \
  http://localhost:8000/api/admin/status
```

환경 변수 `FASTAPI_AUTH_KEY`에 설정된 값을 사용합니다.

---

## 핵심 API

### POST /chat
RAG 기반 채팅 요청. 질문에 대해 문서 검색 및 AI 답변을 생성합니다.

**Rate Limit**: 100회/15분

**Request:**
```json
{
  "message": "2026년 실적 전망은?",
  "session_id": "optional-session-id",
  "stream": false,
  "use_agent": false,
  "options": {}
}
```

| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| message | string | O | 사용자 메시지 (1-1000자) |
| session_id | string | X | 세션 ID (없으면 자동 생성) |
| stream | boolean | X | 스트리밍 응답 여부 (기본: false) |
| use_agent | boolean | X | Agentic RAG 모드 사용 (기본: false) |
| options | object | X | 추가 옵션 |

**Response:**
```json
{
  "answer": "2026년 실적 전망에 대해...",
  "sources": [
    {
      "id": 1,
      "source_id": "rag:doc-123:5:3",
      "document": "investment_report.pdf",
      "document_id": "doc-123",
      "document_name": "investment_report.pdf",
      "page": 5,
      "chunk": 3,
      "section": "2026 Outlook",
      "relevance": 0.95,
      "score": 0.95,
      "content_preview": "문서 기반 2026년 실적 전망 요약...",
      "source_type": "rag",
      "source_uri": "s3://reports/investment_report.pdf",
      "metadata": {
        "source_file": "investment_report.pdf",
        "page_number": 5,
        "chunk_index": 3
      }
    }
  ],
  "session_id": "abc123",
  "message_id": "msg-uuid-here",
  "processing_time": 1.234,
  "tokens_used": 512,
  "timestamp": "2026-01-09T15:30:00",
  "model_info": {"model": "gpt-4o", "provider": "openai"},
  "can_evaluate": true,
  "metadata": {
    "total_time": 1.5,
    "quality": {
      "score": 0.85,
      "confidence": "high",
      "self_rag_applied": true
    }
  }
}
```

---

### POST /chat/session
새 채팅 세션 생성

**Request:**
```json
{
  "metadata": {
    "user_id": "optional-user-id",
    "context": "추가 컨텍스트"
  }
}
```

**Response:**
```json
{
  "session_id": "new-session-uuid",
  "message": "Session created successfully",
  "timestamp": "2026-01-09T15:30:00"
}
```

---

### GET /chat/history/{session_id}
채팅 히스토리 조회

**Query Parameters:**
- `limit`: 반환할 메시지 수 (기본: 20)
- `offset`: 시작 위치 (기본: 0)

**Response:**
```json
{
  "session_id": "abc123",
  "messages": [
    {"role": "user", "content": "질문 내용..."},
    {"role": "assistant", "content": "답변 내용..."}
  ],
  "total_messages": 10,
  "limit": 20,
  "offset": 0,
  "has_more": false
}
```

---

### DELETE /chat/session/{session_id}
세션 삭제

**Response:**
```json
{
  "message": "Session deleted successfully",
  "session_id": "abc123",
  "timestamp": "2026-01-09T15:30:00"
}
```

---

### GET /chat/session/{session_id}/info
세션 상세 정보 조회

**Response:**
```json
{
  "session_id": "abc123",
  "messageCount": 10,
  "tokensUsed": 2048,
  "processingTime": 5.5,
  "modelInfo": {"model": "gpt-4o"},
  "timestamp": "2026-01-09T15:30:00"
}
```

---

### POST /chat/feedback
사용자 피드백 제출 (답변 평가)

**Request:**
```json
{
  "session_id": "abc123",
  "message_id": "msg-uuid",
  "rating": 1,
  "comment": "도움이 되었습니다",
  "query": "원본 질문",
  "response": "원본 답변"
}
```

| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| session_id | string | O | 세션 ID |
| message_id | string | O | 메시지 ID |
| rating | integer | O | 1 (좋아요) 또는 -1 (싫어요) |
| comment | string | X | 추가 코멘트 |
| query | string | X | 원본 질문 (Golden Dataset 후보용) |
| response | string | X | 원본 답변 (Golden Dataset 후보용) |

**Response:**
```json
{
  "success": true,
  "feedback_id": "feedback-uuid",
  "message": "피드백이 저장되었습니다",
  "golden_candidate": true
}
```

---

### GET /chat/stats
채팅 통계 조회

**Response:**
```json
{
  "chat": {
    "total_requests": 1000,
    "success_rate": 0.98,
    "avg_latency": 1.2
  },
  "session": {
    "active_sessions": 50,
    "total_sessions": 500
  },
  "timestamp": "2026-01-09T15:30:00"
}
```

---

## Health Check API

### GET /health
기본 liveness 체크. API 프로세스가 살아 있으면 응답합니다.

**Response:**
```json
{
  "status": "OK",
  "timestamp": "2026-01-09T15:30:00",
  "uptime": 3600.5,
  "version": "2.0.0",
  "environment": "production"
}
```

---

### GET /ready
배포 readiness 체크. startup 상태와 검색 모듈 상태를 함께 확인합니다.
Docker API healthcheck와 운영 배포 readiness probe는 이 엔드포인트를 사용합니다.

**Response:**
```json
{
  "status": "ready",
  "timestamp": "2026-05-13T09:00:00",
  "uptime": 3600.5,
  "environment": "production",
  "checks": {
    "startup": {
      "ready": true,
      "status": "ready",
      "details": {}
    },
    "retrieval": {
      "status": "checked",
      "components": {
        "weaviate": {
          "healthy": true
        }
      }
    }
  }
}
```

**Status semantics:**

| HTTP | `status` | 의미 |
|---|---|---|
| 200 | `ready` | startup 및 필수 retrieval 의존성이 준비됨 |
| 200 | `degraded` | retrieval 일부가 비정상이지만 `RETRIEVAL_STARTUP_POLICY=degraded`라서 degraded 운영 허용 |
| 503 | `not_ready` | startup 미완료 또는 `RETRIEVAL_STARTUP_POLICY=required`에서 retrieval 비정상 |

---

### GET /stats
시스템 통계 (CPU, 메모리, 디스크)

**Response:**
```json
{
  "uptime": 3600.5,
  "uptime_human": "1h 0m 0s",
  "cpu_percent": 25.5,
  "memory_usage": {
    "total_gb": 16.0,
    "used_gb": 8.5,
    "available_gb": 7.5,
    "percentage": 53.1
  },
  "disk_usage": {
    "total_gb": 500.0,
    "used_gb": 200.0,
    "free_gb": 300.0,
    "percentage": 40.0
  },
  "system_info": {
    "platform": "posix",
    "python_version": "3.11.0",
    "cpu_count": 8
  }
}
```

---

### GET /ping
간단한 연결 확인

**Response:**
```json
{
  "message": "pong",
  "timestamp": "2026-01-09T15:30:00"
}
```

---

### GET /cache-stats
리랭킹 캐시 통계

**Response:**
```json
{
  "status": "ok",
  "timestamp": "2026-01-09T15:30:00",
  "cache_size": 100,
  "max_size": 1000,
  "hit_rate": 0.65,
  "total_requests": 500,
  "hits": 325,
  "misses": 175,
  "saved_time_ms": 12500.0,
  "avg_rerank_time_ms": 50.0
}
```

---

## 관리자 API (인증 필요)

> 모든 `/api/admin/*` 엔드포인트는 `X-API-Key` 헤더 인증이 필요합니다.

### GET /api/admin/status
시스템 전체 상태 조회

**Response:**
```json
{
  "status": "healthy",
  "uptime": 3600.5,
  "modules": {
    "session": true,
    "document_processor": true,
    "retrieval": true,
    "generation": true
  },
  "memory_usage": {
    "system_total_mb": 16384,
    "system_used_mb": 8192,
    "process_memory_mb": 512,
    "process_percent": 3.1
  },
  "active_sessions": 5,
  "total_documents": 1000,
  "vector_count": 50000,
  "timestamp": "2026-01-09T15:30:00"
}
```

---

### GET /api/admin/realtime-metrics
실시간 모니터링 메트릭

**Response:**
```json
{
  "timestamp": "2026-01-09T15:30:00",
  "chat_requests_per_minute": 10,
  "average_response_time": 1.5,
  "active_sessions": 5,
  "memory_usage_mb": 512.0,
  "cpu_usage_percent": 25.5,
  "error_rate": 0.01
}
```

---

### GET /api/admin/modules
모듈 정보 조회

**Response:**
```json
[
  {
    "name": "session",
    "status": "active",
    "initialized": true,
    "config": {},
    "stats": {"active_sessions": 5}
  },
  {
    "name": "retrieval",
    "status": "active",
    "initialized": true,
    "config": {},
    "stats": {"total_documents": 1000}
  }
]
```

---

### GET /api/admin/config
설정 정보 조회 (민감 정보 마스킹)

**Response:**
```json
{
  "config": {
    "models": {"api_key": "sk-****"},
    "session": {"timeout": 3600}
  },
  "environment": "production",
  "version": "2.0.0",
  "timestamp": "2026-01-09T15:30:00"
}
```

---

### POST /api/admin/cache/clear
캐시 클리어

**Response:**
```json
{
  "message": "Cache cleared successfully",
  "timestamp": "2026-01-09T15:30:00"
}
```

---

### POST /api/admin/modules/{module_name}/restart
특정 모듈 재시작

**Response:**
```json
{
  "message": "Module session restarted successfully",
  "timestamp": "2026-01-09T15:30:00"
}
```

---

### GET /api/admin/sessions
세션 목록 조회

**Query Parameters:**
- `status`: 필터 (all, active, expired)
- `limit`: 반환 수 (기본: 50)
- `offset`: 시작 위치 (기본: 0)

---

### GET /api/admin/sessions/{session_id}
세션 상세 정보

---

### DELETE /api/admin/sessions/{session_id}
세션 강제 종료

---

### GET /api/admin/documents
문서 목록 조회

**Query Parameters:**
- `page`: 페이지 번호 (기본: 1)
- `page_size`: 페이지 크기 (기본: 20)

---

### GET /api/admin/documents/{document_id}
문서 상세 정보

---

### DELETE /api/admin/documents/{document_id}
문서 삭제

---

### POST /api/admin/test
RAG 시스템 테스트

**Request:**
```json
{
  "query": "테스트 질문"
}
```

---

### POST /api/admin/database/optimize
데이터베이스 최적화 (PostgreSQL ANALYZE 실행)

---

### GET /api/admin/logs/download
로그 파일 다운로드

**Query Parameters:**
- `lines`: 반환할 줄 수 (기본: 1000)

---

### GET /api/admin/recent-chats
최근 채팅 로그 조회

**Query Parameters:**
- `limit`: 반환 수 (기본: 20)

---

### GET /api/admin/analytics/countries
국가별 접속 통계

**Query Parameters:**
- `days`: 조회 기간 (기본: 30)
- `limit`: 반환 수 (기본: 20)

---

### GET /api/admin/analytics/cities
도시별 접속 통계

**Query Parameters:**
- `country_code`: 국가 코드 필터 (예: KR)
- `days`: 조회 기간 (기본: 30)
- `limit`: 반환 수 (기본: 20)

---

### WebSocket /api/admin/ws
관리자 실시간 WebSocket 연결

실시간 메트릭 브로드캐스트를 수신합니다.

---

## Ingestion API

### POST /ingest/notion
Notion 데이터베이스 적재 (비동기)

**Request:**
```json
{
  "database_id": "notion-database-id",
  "category_name": "카테고리명"
}
```

**Response (202 Accepted):**
```json
{
  "status": "accepted",
  "message": "Ingestion started in background",
  "target": {
    "database_id": "notion-database-id",
    "category": "카테고리명"
  }
}
```

---

### POST /ingest/web
웹 사이트맵 적재 (비동기)

**Request:**
```json
{
  "sitemap_url": "https://example.com/sitemap.xml",
  "category_name": "카테고리명"
}
```

**Response (202 Accepted):**
```json
{
  "status": "accepted",
  "message": "Web ingestion started in background",
  "target": {
    "sitemap_url": "https://example.com/sitemap.xml",
    "category": "카테고리명"
  }
}
```

---

## Monitoring API

### GET /monitoring/metrics
성능 메트릭 조회

**Response:**
```json
{
  "success": true,
  "data": {
    "metrics": {
      "chat_handler": {
        "avg": 1.2,
        "min": 0.5,
        "max": 3.0,
        "p95": 2.5,
        "errors": 2
      }
    }
  },
  "message": "5개 함수의 성능 메트릭"
}
```

---

### GET /monitoring/costs
LLM API 비용 조회

**Response:**
```json
{
  "success": true,
  "data": {
    "total_cost_usd": 15.50,
    "total_requests": 1000,
    "providers": {
      "openai": {"tokens": 50000, "cost_usd": 10.0},
      "anthropic": {"tokens": 20000, "cost_usd": 5.5}
    }
  },
  "message": "총 비용: $15.50"
}
```

---

### GET /monitoring/circuit-breakers
Circuit Breaker 상태 조회

**Response:**
```json
{
  "success": true,
  "data": {
    "circuit_breakers": {
      "openai_api": {"state": "closed", "failures": 0},
      "weaviate": {"state": "closed", "failures": 0}
    },
    "state_counts": {"closed": 2, "open": 0, "half_open": 0},
    "total_count": 2
  },
  "message": "총 2개 Circuit Breaker 활성"
}
```

---

### GET /monitoring/health
종합 헬스 체크

**Response:**
```json
{
  "success": true,
  "data": {
    "healthy": true,
    "circuit_breakers_open": 0,
    "open_breakers": [],
    "total_cost_usd": 15.50,
    "total_errors": 5,
    "total_requests": 1000
  },
  "message": "시스템 정상"
}
```

---

### POST /monitoring/reset
모니터링 통계 리셋

**Response:**
```json
{
  "success": true,
  "data": {},
  "message": "모니터링 통계가 리셋되었습니다"
}
```

---

## 전체 엔드포인트 목록

| 메서드 | 경로 | 설명 | 인증 |
|--------|------|------|------|
| **Health** ||||
| GET | /health | liveness 체크 | - |
| GET | /ready | readiness 체크 | - |
| GET | /stats | 시스템 통계 | - |
| GET | /ping | 연결 확인 | - |
| GET | /cache-stats | 캐시 통계 | - |
| **Chat** ||||
| POST | /chat | 채팅 요청 | - |
| POST | /chat/session | 세션 생성 | - |
| GET | /chat/history/{session_id} | 히스토리 조회 | - |
| DELETE | /chat/session/{session_id} | 세션 삭제 | - |
| GET | /chat/session/{session_id}/info | 세션 정보 | - |
| POST | /chat/feedback | 피드백 제출 | - |
| GET | /chat/stats | 채팅 통계 | - |
| **Admin** ||||
| GET | /api/admin/status | 시스템 상태 | X-API-Key |
| GET | /api/admin/realtime-metrics | 실시간 메트릭 | X-API-Key |
| GET | /api/admin/modules | 모듈 정보 | X-API-Key |
| GET | /api/admin/config | 설정 정보 | X-API-Key |
| POST | /api/admin/cache/clear | 캐시 클리어 | X-API-Key |
| POST | /api/admin/modules/{name}/restart | 모듈 재시작 | X-API-Key |
| GET | /api/admin/sessions | 세션 목록 | X-API-Key |
| GET | /api/admin/sessions/{id} | 세션 상세 | X-API-Key |
| DELETE | /api/admin/sessions/{id} | 세션 종료 | X-API-Key |
| GET | /api/admin/documents | 문서 목록 | X-API-Key |
| GET | /api/admin/documents/{id} | 문서 상세 | X-API-Key |
| DELETE | /api/admin/documents/{id} | 문서 삭제 | X-API-Key |
| POST | /api/admin/test | RAG 테스트 | X-API-Key |
| POST | /api/admin/database/optimize | DB 최적화 | X-API-Key |
| GET | /api/admin/logs/download | 로그 다운로드 | X-API-Key |
| GET | /api/admin/recent-chats | 최근 채팅 | X-API-Key |
| GET | /api/admin/analytics/countries | 국가 통계 | X-API-Key |
| GET | /api/admin/analytics/cities | 도시 통계 | X-API-Key |
| GET | /api/admin/metrics | 시계열 메트릭 | X-API-Key |
| GET | /api/admin/keywords | 키워드 분석 | X-API-Key |
| GET | /api/admin/chunks | 청크 분석 | X-API-Key |
| GET | /api/admin/countries | 접속 국가 | X-API-Key |
| WS | /api/admin/ws | 실시간 WebSocket | X-API-Key |
| **Ingestion** ||||
| POST | /ingest/notion | Notion 적재 | - |
| POST | /ingest/web | 웹 적재 | - |
| **Monitoring** ||||
| GET | /monitoring/metrics | 성능 메트릭 | - |
| GET | /monitoring/costs | API 비용 | - |
| GET | /monitoring/circuit-breakers | CB 상태 | - |
| GET | /monitoring/health | 종합 헬스 | - |
| POST | /monitoring/reset | 통계 리셋 | - |

---

## 에러 응답 형식

모든 API는 일관된 에러 응답 형식을 사용합니다:

```json
{
  "error": "에러 유형",
  "message": "사용자 친화적 메시지",
  "suggestion": "해결 방법 안내",
  "retry_after": 10,
  "technical_error": "기술적 상세 (디버깅용)",
  "support_email": "support@example.com"
}
```

### HTTP 상태 코드

| 코드 | 설명 |
|------|------|
| 200 | 성공 |
| 202 | 비동기 작업 수락 |
| 400 | 잘못된 요청 |
| 401 | 인증 실패 |
| 404 | 리소스 없음 |
| 429 | 요청 한도 초과 (Rate Limit) |
| 500 | 서버 내부 오류 |
| 503 | 서비스 초기화 중 |

---

> 상세 스키마 및 모든 파라미터: [Swagger UI](/docs)
