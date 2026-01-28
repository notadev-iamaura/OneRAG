# OneRAG 프로덕션 개선 로드맵

> **문서 버전**: 1.2.0
> **작성 일자**: 2026-01-23
> **최종 업데이트**: 2026-01-28 (Phase 5.2 불필요 확인, OpenRouter 버그 수정)
> **대상 버전**: OneRAG v1.2.1 → v1.4.0

---

## 📋 로드맵 요약

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                      OneRAG v1.3.0 프로덕션 로드맵                           │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ✅ Phase 1: 보안 패치 (P0)                 [완료]     ██████████████████████│
│  ├── ✅ API 인증 추가 (4개 Critical)                                        │
│  └── ✅ 환경 감지 버그 수정                                                 │
│                                                                             │
│  ✅ Phase 2: 보안 강화 (P1)                 [완료]     ██████████████████████│
│  ├── ✅ 추가 API 인증 (6개 High)                                            │
│  └── ✅ CORS 설정 강화                                                      │
│                                                                             │
│  ✅ Phase 3: 기능 정상화 (P2)               [완료]     ██████████████████████│
│  ├── ✅ Self-RAG 활성화                                                     │
│  ├── ✅ LLM Router 활성화                                                   │
│  └── ✅ 환경별 설정 분리                                                    │
│                                                                             │
│  ✅ Phase 4: 운영 최적화 (P3)               [완료]     ██████████████████████│
│  ├── ✅ Chat API Rate Limit (100/15min)                                     │
│  ├── ✅ 실시간 모니터링 (/realtime-metrics)                                 │
│  └── API Key 로테이션 (선택)                                                │
│                                                                             │
│  Phase 5: 검색 품질 개선 (P4)               [선택]     ━━━━━━━━━━━━━━━━━━━  │
│  ├── 스트리밍 에러 복구 (체크포인트)                                        │
│  └── 점수 정규화 통합                                                       │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## ✅ Phase 1: 보안 패치 (P0) - 완료 (2026-01-23)

### 완료된 작업

### 1.1 ✅ Documents API 인증 추가 [C1, C2]

**파일**: `app/api/documents.py`

**현재 상태**:
```python
router = APIRouter(tags=["Documents"])  # ❌ 인증 없음
```

**수정 방안**:
```python
from fastapi import APIRouter, Depends
from app.lib.auth import get_api_key

router = APIRouter(
    tags=["Documents"],
    dependencies=[Depends(get_api_key)]  # ✅ 라우터 레벨 인증
)
```

**영향받는 엔드포인트**:
- `DELETE /api/documents/all` - 전체 문서 삭제
- `POST /api/documents/clear-collection` - 컬렉션 초기화
- `GET /api/documents/stats` - 문서 통계 (보너스 보호)

**테스트 명령**:
```bash
# 인증 없이 요청 (401 응답 예상)
curl -X DELETE http://localhost:8000/api/documents/all \
  -H "Content-Type: application/json" \
  -d '{"confirm_code": "DELETE_ALL_DOCUMENTS"}'

# 인증 있이 요청 (200 응답 예상)
curl -X DELETE http://localhost:8000/api/documents/all \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your-api-key" \
  -d '{"confirm_code": "DELETE_ALL_DOCUMENTS", "dry_run": true}'
```

---

### 1.2 ✅ Ingestion API 인증 추가 [C3, C4]

**파일**: `app/api/ingest.py`

**현재 상태**:
```python
router = APIRouter(prefix="/ingest", tags=["Ingestion"])  # ❌ 인증 없음
```

**수정 방안**:
```python
from fastapi import APIRouter, Depends
from app.lib.auth import get_api_key

router = APIRouter(
    prefix="/ingest",
    tags=["Ingestion"],
    dependencies=[Depends(get_api_key)]  # ✅ 라우터 레벨 인증
)
```

**영향받는 엔드포인트**:
- `POST /ingest/web` - 웹 크롤링
- `POST /ingest/notion` - Notion 데이터 적재
- 기타 모든 ingestion 엔드포인트

---

### 1.3 ✅ 환경 감지 버그 수정

**파일**: `app/lib/environment.py:42-60`

**현재 코드 (버그)**:
```python
def is_production() -> bool:
    """프로덕션 환경 감지"""
    production_indicators: list[bool] = []

    # 1. ENVIRONMENT 환경변수 체크
    env = os.getenv("ENVIRONMENT", "").lower()
    production_indicators.append(env in ("production", "prod"))

    # 2. NODE_ENV 체크
    node_env = os.getenv("NODE_ENV", "").lower()
    production_indicators.append(node_env in ("production", "prod"))

    # 3. WEAVIATE_URL 체크 (https:// 여부)
    weaviate_url = os.getenv("WEAVIATE_URL", "")
    production_indicators.append(weaviate_url.startswith("https://"))

    # 4. ❌ 버그: FASTAPI_AUTH_KEY 설정 여부 체크
    auth_key = os.getenv("FASTAPI_AUTH_KEY")
    production_indicators.append(bool(auth_key))  # ← 보안 키를 환경 지표로 사용

    # 하나라도 True이면 프로덕션으로 간주
    is_production = any(production_indicators)
    return is_production
```

**수정된 코드**:
```python
def is_production() -> bool:
    """
    프로덕션 환경 감지 (개선된 버전)

    감지 우선순위:
    1. ENVIRONMENT 환경변수 (명시적 설정 우선)
    2. NODE_ENV 환경변수
    3. 인프라 기반 체크 (HTTPS 사용 여부)

    Note: FASTAPI_AUTH_KEY는 보안 설정이므로 환경 감지에 사용하지 않음
    """
    # 1. ENVIRONMENT 환경변수 체크 (최우선)
    env = os.getenv("ENVIRONMENT", "").lower()
    if env in ("production", "prod"):
        return True
    if env in ("development", "dev", "test", "local"):
        return False

    # 2. NODE_ENV 체크 (JavaScript 생태계 호환)
    node_env = os.getenv("NODE_ENV", "").lower()
    if node_env in ("production", "prod"):
        return True
    if node_env in ("development", "dev", "test"):
        return False

    # 3. 인프라 기반 체크 (HTTPS 사용 여부만)
    weaviate_url = os.getenv("WEAVIATE_URL", "")
    if weaviate_url.startswith("https://"):
        return True

    # 4. ✅ FASTAPI_AUTH_KEY는 체크하지 않음 (보안 설정 ≠ 환경 지표)

    # 기본값: 개발 환경으로 간주 (안전한 기본값)
    return False
```

**테스트 케이스**:
```python
# tests/unit/lib/test_environment.py

import os
from unittest.mock import patch
from app.lib.environment import is_production

class TestEnvironmentDetection:
    """환경 감지 로직 테스트"""

    def test_explicit_production_environment(self):
        """ENVIRONMENT=production 시 프로덕션 감지"""
        with patch.dict(os.environ, {"ENVIRONMENT": "production"}):
            assert is_production() is True

    def test_explicit_development_with_auth_key(self):
        """개발 환경에서 AUTH_KEY 설정해도 개발 환경 유지"""
        with patch.dict(os.environ, {
            "ENVIRONMENT": "development",
            "FASTAPI_AUTH_KEY": "test-key-12345"
        }):
            assert is_production() is False  # ✅ 버그 수정 확인

    def test_auth_key_alone_not_production(self):
        """AUTH_KEY만 설정된 경우 프로덕션으로 오인하지 않음"""
        with patch.dict(os.environ, {
            "FASTAPI_AUTH_KEY": "test-key-12345"
        }, clear=True):
            assert is_production() is False  # ✅ 버그 수정 확인

    def test_https_weaviate_indicates_production(self):
        """HTTPS Weaviate URL은 프로덕션 지표"""
        with patch.dict(os.environ, {
            "WEAVIATE_URL": "https://weaviate.example.com"
        }, clear=True):
            assert is_production() is True
```

---

## ✅ Phase 2: 보안 강화 (P1) - 완료 (2026-01-23)

### 완료된 작업

### 2.1 ✅ Monitoring API 인증 추가 [H1]

**파일**: `app/api/monitoring.py`

```python
from app.lib.auth import get_api_key

# 민감한 엔드포인트만 인증
@router.get("/costs", dependencies=[Depends(get_api_key)])
async def get_costs():
    """LLM 비용 조회 - 인증 필요"""
    ...
```

---

### 2.2 ✅ Prompts API CUD 인증 추가 [H2]

**파일**: `app/api/prompts.py`

**접근 방식**: 읽기(GET)는 공개, 쓰기(POST/PUT/DELETE)는 인증 필요

```python
# GET은 공개
@router.get("")
async def list_prompts():
    ...

# POST/PUT/DELETE는 인증 필요
@router.post("", dependencies=[Depends(get_api_key)])
async def create_prompt():
    ...

@router.put("/{prompt_id}", dependencies=[Depends(get_api_key)])
async def update_prompt():
    ...

@router.delete("/{prompt_id}", dependencies=[Depends(get_api_key)])
async def delete_prompt():
    ...
```

---

### 2.3 ✅ Tools API Execute 인증 추가 [H3]

**파일**: `app/api/routers/tools_router.py`

```python
# 조회는 공개
@router.get("")
async def list_tools():
    ...

# 실행은 인증 필요
@router.post("/{tool_name}/execute", dependencies=[Depends(get_api_key)])
async def execute_tool():
    ...
```

---

### 2.4 ✅ Upload API Rate Limit 강화 [H4] - 기존 Rate Limit 적용됨

**파일**: `app/api/upload.py`

**접근 방식**: 인증 대신 강화된 Rate Limit 적용

```python
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)

@router.post("")
@limiter.limit("5/minute")  # ✅ 분당 5회로 제한
async def upload_file():
    ...
```

---

### 2.5 ✅ LangSmith API 인증 추가 [H5]

**파일**: `app/api/langsmith_logs.py`

```python
from app.lib.auth import get_api_key

router = APIRouter(
    prefix="/api/langsmith",
    tags=["LangSmith"],
    dependencies=[Depends(get_api_key)]  # ✅ 모든 로그 조회에 인증
)
```

---

### 2.6 ✅ CORS 설정 강화 [H6]

**파일**: `main.py`

```python
from app.lib.environment import is_production

# 환경별 CORS 설정
if is_production():
    allowed_origins = os.getenv("ALLOWED_ORIGINS", "").split(",")
    allowed_methods = ["GET", "POST", "PUT", "DELETE"]  # ✅ 명시적
    allowed_headers = ["Content-Type", "Authorization", "X-API-Key", "X-Session-ID"]
else:
    allowed_origins = ["http://localhost:3000", "http://localhost:5173"]
    allowed_methods = ["*"]
    allowed_headers = ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_methods=allowed_methods,
    allow_headers=allowed_headers,
    allow_credentials=True,
    max_age=3600 if is_production() else 0,
)
```

---

## ✅ Phase 3: 기능 정상화 (P2) - 완료

### 완료된 작업

### 3.1 Self-RAG 활성화

**근본 원인**: Google API Rate Limit

**해결 방안**:

1. **Rate Limit 대응 전략 추가**:
```python
# app/modules/features/self_rag/evaluator.py

import asyncio
from tenacity import retry, stop_after_attempt, wait_exponential

class SelfRAGEvaluator:
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=60)
    )
    async def evaluate_with_retry(self, ...):
        """Rate Limit 대응 재시도 로직"""
        try:
            return await self._evaluate(...)
        except RateLimitError:
            await asyncio.sleep(60)  # 1분 대기
            raise
```

2. **대체 Provider 설정**:
```yaml
# app/config/features/self_rag.yaml
self_rag:
  enabled: true  # ✅ 활성화
  evaluator:
    primary_provider: google
    fallback_providers:
      - openrouter
      - openai
```

3. **활성화 테스트**:
```bash
make test -k "self_rag"
```

---

### 3.2 LLM Router 활성화

**근본 원인**: OpenRouter 연결 문제

**해결 방안**:

1. **연결 진단**:
```bash
# OpenRouter API 연결 테스트
curl -X POST https://openrouter.ai/api/v1/chat/completions \
  -H "Authorization: Bearer $OPENROUTER_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model": "google/gemini-2.5-flash-lite", "messages": [{"role": "user", "content": "ping"}]}'
```

2. **Fallback 전략**:
```yaml
# app/config/features/routing.yaml
query_routing:
  llm_router:
    enabled: true  # ✅ 활성화
    timeout: 15    # 타임아웃 증가 (10 → 15초)
    fallback_to_rule_based: true  # 실패 시 Rule-based 사용
```

---

### 3.3 설정 환경 분리

**파일 구조**:
```
app/config/environments/
├── development.yaml    # 개발용 설정
├── test.yaml           # 테스트용 설정
└── production.yaml     # 프로덕션 설정
```

**분리할 설정**:
```yaml
# development.yaml
reranking:
  min_score: 0.0  # 테스트용: 모든 결과 포함

# production.yaml
reranking:
  min_score: 0.05  # 프로덕션: 품질 필터링
```

---

## ✅ Phase 4: 운영 최적화 (P3) - 완료

### 4.1 Chat API Rate Limit 개선

**현재 문제**: StreamingResponse에서 request.body() 읽기 타임아웃

**해결 방안**: 커스텀 미들웨어로 스트리밍 전용 Rate Limit

```python
# app/middleware/streaming_rate_limiter.py

class StreamingRateLimiter:
    """StreamingResponse 호환 Rate Limiter"""

    def __init__(self, limit: int = 20, window: int = 60):
        self.limit = limit
        self.window = window
        self.requests: dict[str, list[float]] = {}

    async def check_limit(self, client_id: str) -> bool:
        """Rate Limit 체크 (body 읽지 않음)"""
        now = time.time()
        requests = self.requests.get(client_id, [])

        # 윈도우 외 요청 제거
        requests = [r for r in requests if now - r < self.window]

        if len(requests) >= self.limit:
            return False

        requests.append(now)
        self.requests[client_id] = requests
        return True

# chat_router.py에서 사용
@router.post("/stream")
async def chat_stream(request: Request):
    client_id = request.headers.get("X-Session-ID") or request.client.host

    if not await streaming_limiter.check_limit(client_id):
        raise HTTPException(429, "Rate limit exceeded")

    return StreamingResponse(...)
```

---

### 4.2 모니터링 강화

**추가할 메트릭**:

```python
# app/core/monitoring/metrics.py

class ProductionMetrics:
    """프로덕션 필수 메트릭"""

    # 보안 메트릭
    auth_failures: int = 0           # 인증 실패 횟수
    rate_limit_hits: int = 0         # Rate Limit 도달 횟수

    # 안정성 메트릭
    circuit_breaker_opens: int = 0   # Circuit Breaker 개방 횟수
    fallback_activations: int = 0    # Fallback 활성화 횟수

    # 비용 메트릭
    llm_cost_hourly: float = 0.0     # 시간당 LLM 비용
    cache_savings: float = 0.0       # 캐시로 절약한 비용
```

---

### 4.3 API Key 로테이션

```python
# app/lib/auth.py 확장

class APIKeyManager:
    """API Key 로테이션 관리"""

    def __init__(self):
        self.primary_key = os.getenv("FASTAPI_AUTH_KEY")
        self.secondary_key = os.getenv("FASTAPI_AUTH_KEY_SECONDARY")
        self.deprecated_keys = self._load_deprecated_keys()

    def validate(self, key: str) -> tuple[bool, str]:
        """
        키 검증 및 상태 반환

        Returns:
            (is_valid, status): 유효성 및 상태
            - status: "active", "secondary", "deprecated", "invalid"
        """
        if secrets.compare_digest(key, self.primary_key):
            return True, "active"
        if self.secondary_key and secrets.compare_digest(key, self.secondary_key):
            return True, "secondary"
        if key in self.deprecated_keys:
            logger.warning(f"Deprecated API key used: {key[:8]}...")
            return True, "deprecated"
        return False, "invalid"
```

---

## Phase 5: 검색 품질 개선 (P4) - 1주

### 예상 소요 시간: 1주

### 5.1 스트리밍 에러 복구 메커니즘

**문제점**
- `stream_rag_pipeline()` 실행 중 에러 발생 시 이미 전송된 청크 손실
- 사용자는 부분적인 답변만 받고 갑자기 연결 종료됨

**현재 코드** (`app/api/services/chat_service.py`):
```python
async def stream_rag_pipeline(...) -> AsyncGenerator:
    try:
        async for text_chunk in generation_module.stream_answer(...):
            yield {"event": "chunk", "data": text_chunk, ...}
    except Exception as e:
        # 에러 발생 시 버퍼링된 청크는 클라이언트에 도달 못함
        yield {"event": "error", "message": "..."}
```

**해결 방안**: 체크포인트 기반 복구
```python
async def stream_rag_pipeline(...) -> AsyncGenerator:
    checkpoint_interval = 5  # 5개 청크마다 체크포인트
    accumulated_text = ""

    try:
        async for text_chunk in generation_module.stream_answer(...):
            accumulated_text += text_chunk
            chunk_index += 1

            yield {"event": "chunk", "data": text_chunk, "index": chunk_index}

            # 체크포인트 이벤트 전송
            if chunk_index % checkpoint_interval == 0:
                yield {
                    "event": "checkpoint",
                    "chunk_index": chunk_index,
                    "accumulated_length": len(accumulated_text)
                }
    except Exception as e:
        # 에러 발생 시에도 마지막 체크포인트 정보 전송
        yield {
            "event": "error",
            "message": str(e),
            "last_checkpoint": chunk_index - (chunk_index % checkpoint_interval),
            "partial_text_length": len(accumulated_text)
        }
```

**영향도**: 사용자 경험 ↑, 부분 답변 복구 가능

---

### 5.2 점수 정규화 및 가중 합산 - ❌ 불필요 (2026-01-28 검증)

**초기 가정 (잘못됨)**
- 벡터 점수(0~1)와 리랭크 점수(0~100) 범위가 다름

**실제 코드 분석 결과**
모든 리랭커가 이미 **0~1 범위**를 반환하고 있음:

| 리랭커 | 점수 범위 | 구현 방식 |
|--------|----------|----------|
| **Jina** | 0~1 | API `relevance_score` (스펙 보장) |
| **Cohere** | 0~1 | API `relevance_score` (스펙 보장) |
| **ColBERT** | 0~1 | Jina API `relevance_score` |
| **Gemini** | 0~1 | `max(0.0, min(1.0, score))` 클램핑 |
| **OpenAI** | 0~1 | `max(0.0, min(1.0, score))` 클램핑 |
| **OpenRouter** | 0~1 | `max(0.0, min(1.0, score))` 클램핑 (v1.2.1 수정) |
| **Local** | 0~1 | Sigmoid 정규화 `1/(1+exp(-x))` |

**추가 발견**
- 리랭킹은 점수를 **혼합하지 않고 대체**함 (RRF merge 후 rerank)
- `min_score` 필터링은 orchestrator에서 **미구현** 상태
- 따라서 점수 범위 불일치 문제 자체가 존재하지 않음

**결론**: 이 개선 항목은 **불필요**. 문서 초기 작성 시 잘못된 가정에 기반함.

---

## 검증 체크리스트

### ✅ Phase 1 완료 조건 (2026-01-23 검증 완료)

- [x] `DELETE /api/documents/all` 401 응답 (인증 없이)
- [x] `POST /ingest/web` 401 응답 (인증 없이)
- [x] 개발 환경 + AUTH_KEY 설정 시 `is_production() == False`
- [x] 모든 기존 테스트 통과 (1,672개 통과)

### ✅ Phase 2 완료 조건 (2026-01-23 검증 완료)

- [x] `GET /api/monitoring/costs` 401 응답 (인증 없이)
- [x] `POST /api/prompts` 401 응답 (인증 없이)
- [x] CORS preflight에 명시적 메서드만 포함 (GET, POST, PUT, DELETE, OPTIONS, PATCH)
- [x] Ruff 린트 검사 통과
- [x] Mypy 타입 검사 통과

### ✅ Phase 3 완료 조건 (검증 완료)

- [x] Self-RAG 활성화 후 정상 동작 (`self_rag.yaml`: enabled: true)
- [x] LLM Router 활성화 후 정상 동작 (`routing.yaml`: llm_router.enabled: true)
- [x] 환경별 설정 분리 확인 (development.yaml, production.yaml, test.yaml)

### ✅ Phase 4 완료 조건 (검증 완료)

- [x] Chat API에 Rate Limit 적용 (`@limiter.limit("100/15minutes")`)
- [x] 프로덕션 메트릭 대시보드 구성 (`/api/admin/realtime-metrics`)
- [ ] API Key 로테이션 테스트 완료 (선택 사항)

### Phase 5 상태 (선택 사항)

- [ ] 5.1 스트리밍 에러 복구 - ⏭️ 패스 (사용자 결정)
- [x] 5.2 점수 정규화 - ❌ 불필요 (2026-01-28 검증: 모든 리랭커가 이미 0~1 반환)

---

## 버전 계획

| 버전 | Phase | 주요 변경 | 상태 |
|------|-------|-----------|------|
| **v1.2.2** | Phase 1, 2 | 보안 패치 (Critical 4개 + High 6개) | ✅ 완료 |
| **v1.3.0** | Phase 3 | 기능 정상화 + 설정 분리 | ✅ 완료 |
| **v1.3.1** | Phase 4 | 운영 최적화 (Rate Limit, 실시간 메트릭) | ✅ 완료 |
| **v1.4.0** | Phase 5 | 검색 품질 개선 (5.1 패스, 5.2 불필요 확인) | ⏭️ 스킵 |

---

**문서 작성자**: Claude Code (Automated Planning)
**최종 업데이트**: 2026-01-28 (Phase 5.2 불필요 확인 - 모든 리랭커 0~1 반환)
**검토 필요**: Tech Lead, Security Team
