# CLAUDE.md (v1.0.7)

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 프로젝트 개요
도메인 범용화된 완벽한 오픈소스 RAG 시스템. 2026년 기준 가장 진보된 RAG 기술들을 하나의 표준 파이프라인으로 통합한 엔터프라이즈급 솔루션입니다.

- **버전**: 1.0.7
- **상태**: ✅ **2,200+ 테스트 통과**, ✅ **보안 완비**, ✅ **DI 패턴 완성**, ✅ **Streaming API**, ✅ **WebSocket**
- **주요 개선**: Reranker 확장 - Cohere, Local(sentence-transformers), OpenRouter 추가 (v1.2.1)

## 🚀 시작하기

두 가지 실행 방법을 제공합니다:

|  | Full API 서버 (`make start`) | CLI 챗봇 (`make easy-start`) |
|---|---|---|
| **Docker** | 필요 | 불필요 |
| **Vector DB** | Weaviate (하이브리드 검색) | ChromaDB (로컬 파일) |
| **인터페이스** | REST API + Swagger UI | 터미널 CLI |
| **LLM** | 5종 (Gemini, OpenAI, Claude, OpenRouter, Ollama) | Gemini / OpenRouter / Ollama |
| **용도** | 프로덕션, API 통합, 팀 개발 | 학습, 체험, 빠른 PoC |

### 방법 A: Full API 서버 (Docker)

```bash
git clone https://github.com/youngouk/OneRAG.git
cd OneRAG && uv sync
cp quickstart/.env.quickstart .env  # GOOGLE_API_KEY만 설정
make start                           # → http://localhost:8000/docs
```

### 방법 B: 로컬 CLI 챗봇 (Docker 불필요)

```bash
git clone https://github.com/youngouk/OneRAG.git
cd OneRAG && uv sync
make easy-start                      # → 터미널에서 바로 대화
```

API 키 없이도 검색은 작동합니다. AI 답변 생성을 사용하려면:
- `GOOGLE_API_KEY` (무료: https://aistudio.google.com/apikey)
- 또는 `OPENROUTER_API_KEY` (https://openrouter.ai/keys)

**Quickstart 구조**:
```
quickstart/                  # Docker 기반
├── .env.quickstart          # 최소 설정 템플릿
├── sample_data.json         # 25개 FAQ 샘플 데이터
└── load_sample_data.py      # Weaviate 데이터 로드

easy_start/                  # Docker-Free
├── .env.local               # 로컬 설정 템플릿
├── chat.py                  # CLI 챗봇 (Rich UI)
├── load_data.py             # ChromaDB 데이터 로드
└── run.py                   # 원클릭 실행 오케스트레이터
```

**실행 명령어**:
- `make start` - Docker 원클릭 실행 (Weaviate + API + 샘플데이터)
- `make start-down` - 서비스 종료
- `make start-logs` - 로그 확인
- `make easy-start` - Docker-Free 로컬 CLI 챗봇 실행

## 개발 명령어

```bash
# 초기 환경 설정 (spaCy 한국어 모델 포함 자동 설치)
uv sync

# 개발 서버 및 테스트
make dev-reload         # 자동 리로드 (uvicorn --reload)
make test               # 2,200+ 테스트 실행 (외부 로그 차단 격리 환경)
make test-cov           # 테스트 커버리지 리포트

# 코드 품질 관리 (CI/CD 통과 필수)
make lint               # ruff 린트 검사
make type-check         # mypy 엄격 모드 타입 체크
make lint-imports       # 아키텍처 계층 검증 (Import Linter)
```

## 아키텍처 핵심 (v1.0 고도화)

### 1. 지능형 검색 (Hybrid Retrieval)
- **Weaviate**: Dense(의미) + Sparse(BM25) 하이브리드.
- **GraphRAG**: `NetworkXGraphStore`에 벡터 검색 엔진 통합. "SAMSUNG"으로 "삼성전자" 노드 탐색 가능.
- **Reranker v2.1**: 3단계 계층 구조 (approach → provider → model)로 명확한 설정
  - **approach**: `llm`, `cross-encoder`, `late-interaction`, `local` (4종)
  - **provider**: google, openai, jina, cohere, openrouter, sentence-transformers (6종)
  - **v1.2.1 신규**: Cohere (100+ 언어), Local (API 키 불필요), OpenRouter (다양한 LLM 모델 지원)

### 2. 완벽한 보안 (Unified Security)
- **PII Facade**: `PIIProcessor`가 단순 마스킹과 고도화된 AI 리뷰(`PIIReviewProcessor`)를 통합 관리.
- **Admin Auth**: `/api/admin` 하위의 모든 엔드포인트에 `X-API-Key` 인증 전역 적용.

### 3. 운영 유연성 (Dynamic Config)
- **YAML Routing**: `routing_rules_v2.yaml`에서 서비스 핵심 키워드를 관리. 코드 수정 없이 복합 쿼리 판단 로직 변경 가능.
- **환경별 설정**: `app/config/environments/`에 development, test, production 설정 분리. 환경 자동 감지 및 병합.
- **강화된 검증**: Pydantic 기반 설정 검증으로 타입 안전성 및 범위 검증 (temperature, timeout 등).

### 4. 에러 시스템 v2.0 (Bilingual)
- **ErrorCode 기반**: 모든 에러가 구조화된 에러 코드 사용 (예: `GEN-001`, `SEARCH-003`)
- **양언어 자동 전환**: `Accept-Language` 헤더 기반 한국어/영어 메시지 자동 선택
- **사용자 친화적 메시지**: 기술 에러를 해결 방법과 함께 제공
```python
# 새 에러 형식
raise GenerationError(ErrorCode.GENERATION_TIMEOUT, model="claude-sonnet-4-5")
# → 한국어: "AI 모델 응답이 지연되고 있습니다. 해결 방법: 1) 잠시 후 다시 시도..."
# → 영어: "AI model response is delayed. Solutions: 1) Please try again later..."
```

### 5. DI 컨테이너 (Dependency Injection)
- **80+ Provider**: Singleton(70개) + Factory(10개) 패턴 완비
- **9개 명시적 팩토리**: Agent, Evaluator, GraphRAG, Cache, MCP, Ingestion, VectorStore, Retriever, RerankerV2
- **Deprecated 함수 정리 완료**: 모든 전역 헬퍼 함수 제거/리팩토링 완료 (v1.0.7)
  - `get_cost_tracker()`, `get_mongodb_client()`, `get_prompt_manager()` 제거
  - `get_circuit_breaker()` 제거, `get_performance_metrics()` → private 전환
- **테스트 용이성**: 모든 의존성 주입 가능, Mock 교체 용이

### 6. Multi-LLM Factory (v1.0.3)
- **5개 Provider 지원**: Google Gemini, OpenAI GPT, Anthropic Claude, OpenRouter, Ollama
- **자동 Fallback**: 주 LLM 실패 시 설정된 순서대로 자동 전환
- **GPT5QueryExpansionEngine**: `llm_factory` 필수화로 OpenAI 직접 의존성 제거

### 7. Multi Vector DB (v1.0.5)
- **Factory 패턴**: `VectorStoreFactory`, `RetrieverFactory`로 벡터 DB 동적 선택
- **6종 벡터 DB 지원**: 환경변수 `VECTOR_DB_PROVIDER`로 선택
  | Provider | 하이브리드 검색 | 특징 |
  |----------|---------------|------|
  | **weaviate** (기본) | ✅ Dense + BM25 | 셀프호스팅, 하이브리드 내장 |
  | **chroma** | ❌ Dense 전용 | 경량, 로컬 개발용 |
  | **pinecone** | ✅ Dense + Sparse | 서버리스 클라우드 |
  | **qdrant** | ✅ Dense + Full-Text | 고성능 셀프호스팅 |
  | **pgvector** | ❌ Dense 전용 | PostgreSQL 확장 |
  | **mongodb** | ❌ Dense 전용 | Atlas Vector Search |
- **선택적 의존성**: 필요한 DB만 설치 (`uv sync --extra pinecone` 등)

### 8. Observability (v1.0.4)
- **실시간 메트릭**: `/api/admin/realtime-metrics` 엔드포인트
- **캐시 모니터링**: `cache_hit_rate`, `cache_hits`, `cache_misses`, `cache_saved_time_ms`
- **비용 추적**: `total_cost_usd`, `cost_per_hour`, `total_llm_tokens`

### 9. Streaming API (v1.0.8)
- **POST /chat/stream**: SSE(Server-Sent Events) 기반 스트리밍 채팅 응답
- **Content-Type**: `text/event-stream`
- **이벤트 타입**: `metadata`, `chunk`, `done`, `error`
- **Rate Limit**: 100회/15분
- **Multi-LLM 지원**: Google Gemini, OpenAI GPT, Anthropic Claude 모두 스트리밍 지원
```
# SSE 응답 예시
event: metadata
data: {"session_id": "abc-123", "search_results": 5}

event: chunk
data: {"data": "안녕", "chunk_index": 0}

event: done
data: {"session_id": "abc-123", "total_chunks": 10}
```

상세 가이드: `docs/streaming-api-guide.md`

### 10. WebSocket API (v1.0.9)
- **WS /chat-ws**: 양방향 실시간 채팅 (SSE와 달리 클라이언트→서버 통신도 지원)
- **연결**: `wss://{host}/chat-ws?session_id={session_id}`
- **메시지 타입**: `message` (클라이언트), `stream_start`, `stream_token`, `stream_sources`, `stream_end`, `stream_error` (서버)
- **RAG 파이프라인 통합**: 기존 `ChatService.stream_rag_pipeline()` 재사용
```javascript
// 클라이언트 → 서버
{"type": "message", "message_id": "uuid", "content": "질문", "session_id": "abc"}

// 서버 → 클라이언트
{"type": "stream_token", "message_id": "uuid", "token": "안녕", "index": 0}
```

상세 가이드: `docs/websocket-api-guide.md`

### 11. OpenAI 호환 API (v1.1.0)
- **POST /v1/chat/completions**: OpenAI SDK 형식의 채팅 완료 (RAG 파이프라인 포함)
- **GET /v1/models**: 사용 가능한 모델 목록
- **인증**: 없음 (Ollama 방식 — 로컬 서비스 전제)
- **모델 선택**: `model` 필드에 슬래시 구분 (`provider/sub-model`)
  - `gemini` — Google Gemini 기본 모델
  - `ollama/qwen2.5:3b` — Ollama 특정 모델
  - `openrouter/google/gemini-2.0-flash` — OpenRouter 경유
  - `claude`, `openai` — 각 provider 기본 모델
- **RAG Mode 기본**: 문서 검색 → 컨텍스트 조합 → LLM 답변 생성
- **스트리밍 지원**: `"stream": true`로 SSE 스트리밍 응답
```python
# OpenAI SDK로 OneRAG에 연결
from openai import OpenAI
client = OpenAI(base_url="http://localhost:8000/v1", api_key="not-needed")
resp = client.chat.completions.create(
    model="gemini",
    messages=[{"role": "user", "content": "RAG란?"}],
)
print(resp.choices[0].message.content)
```

상세 분석: `docs/TECHNICAL_DEBT_ANALYSIS.md`

## 코드 컨벤션 및 규칙

- **TODO 금지**: 코드 내에 `TODO`, `FIXME` 주석을 남기지 않습니다. 발견 즉시 해결합니다.
- **Test Isolation**: 테스트 시 `ENVIRONMENT=test`를 통해 Langfuse 등 외부 통신을 원천 차단합니다.
- **Type Safety**: 모든 신규 함수는 명확한 타입 힌트가 필수이며 `mypy`를 통과해야 합니다.

## 설정 관리 (v1.0.1 신규)

### 환경별 설정 파일
```
app/config/environments/
├── development.yaml  # 개발: debug=true, reload=true, 상세 로깅
├── test.yaml         # 테스트: 짧은 타임아웃, 일관성 우선
└── production.yaml   # 프로덕션: 워커 4개, 캐시 활성화, 폴백 전략
```

### 환경 감지 로직
- **다층 감지**: ENVIRONMENT, NODE_ENV, WEAVIATE_URL, FASTAPI_AUTH_KEY 종합 판단
- **보안 강화**: 단일 환경 변수 조작으로 프로덕션 우회 불가
- **자동 병합**: base.yaml + environments/{env}.yaml 자동 병합

### 설정 검증 (Pydantic)
- **타입 안전성**: temperature (0.0-2.0), max_tokens (1-128000), port (1-65535)
- **환경별 규칙**: 프로덕션에서 debug=true 차단
- **Graceful Degradation**: 검증 실패해도 시스템 동작 (경고 출력)

상세 문서: `docs/config_management_improvements.md`

## 시스템 완성도 (Current Score: 100/100)

| 항목 | 현황 | 비고 |
|------|------|------|
| **전체 테스트** | 2,200+ Pass | 단위/통합/안정성 테스트 완비 |
| **Deprecated 함수** | 0건 | Phase 1,2,3 완료, 모든 deprecated 함수 제거/리팩토링 |
| **보안 인증** | 완료 | 관리자 API 및 PII 보호 통합 |
| **GraphRAG 지능** | 완료 | 벡터 검색 기반 엔티티 탐색 |
| **설정 관리** | 완료 | 환경별 분리 및 검증 강화 |
| **에러 시스템** | 완료 | 양언어(한/영) 자동 전환 v2.0 |
| **DI 컨테이너** | 완료 | 80+ Provider, 9개 팩토리 (RerankerV2 추가) |
| **Multi-LLM** | 완료 | 5개 Provider 지원, 자동 Fallback |
| **Multi Vector DB** | 완료 | 6종 지원 (Weaviate, Chroma, Pinecone, Qdrant, pgvector, MongoDB) |
| **Observability** | 완료 | 실시간 캐시 히트율/LLM 비용 모니터링 |
| **Streaming API** | 완료 | SSE 기반 실시간 응답, Multi-LLM 스트리밍 지원 |
| **WebSocket API** | 완료 | 양방향 실시간 채팅, RAG 파이프라인 통합 |
| **Reranker 설정 v2.1** | 완료 | 4 approach, 6 provider (Cohere, Local 추가) |
| **OpenAI 호환 API** | 완료 | /v1/chat/completions, /v1/models, 스트리밍 지원 |
| **문서화** | 완료 | API Reference, 개발 가이드 등 12개 문서 |

상세 기술부채 분석: `docs/TECHNICAL_DEBT_ANALYSIS.md`

## 향후 보강 계획 (Feature Roadmap)

15개 신규/개선 피처를 5단계로 나누어 추진합니다. 경쟁 프레임워크 분석(Dify, RAGFlow, Kotaemon 등) 및 2026 RAG 트렌드 기반.

| Phase | 기간 | 핵심 피처 | 목표 |
|-------|------|----------|------|
| **Phase 1** | 1-2주 | Ollama 통합, Grok API, 다국어 easy-start | 글로벌 사용자 유입 |
| **Phase 2** | 2-3주 | RAGAS 평가, 적응형 청킹, OpenAI 호환 API | 검색 품질 + 통합성 |
| **Phase 3** | 3-4주 | 문서 관리 GUI, PDF 인용 하이라이트, 시맨틱 캐시 | 프론트엔드 UX |
| **Phase 4** | 4-6주 | Agentic RAG, 데이터 커넥터, Auto-Metadata | 지능형 RAG |
| **Phase 5** | 6-8주+ | 멀티모달 RAG, NoCode 빌더, 경량 그래프 RAG | 차세대 경쟁 우위 |

상세 계획: `docs/plans/2026-02-25-feature-roadmap.md`

---
**Claude Note**: 본 프로젝트는 이미 "완벽"한 상태이므로, 코드 수정 시 기존의 추상화 인터페이스(Protocol)와 DI 패턴을 엄격히 준수하십시오.
- **에러**: 반드시 `ErrorCode` 기반 새 형식 사용
- **LLM**: 반드시 `llm_factory`를 통해 호출
- **Vector DB**: 새 벡터 DB 추가 시 `VectorStoreFactory`에 등록
- **모니터링**: 새 메트릭 추가 시 `RealtimeMetrics` 모델 확장
- **Reranker**: `RerankerFactoryV2` 사용, approach/provider/model 3단계 구조 준수
  - **지원 approach**: llm, cross-encoder, late-interaction, local
  - **지원 provider**: google, openai, jina, cohere, openrouter, sentence-transformers