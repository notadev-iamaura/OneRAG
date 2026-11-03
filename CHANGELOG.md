# 변경 이력 (Changelog)

이 프로젝트의 모든 주요 변경 사항을 기록합니다.
형식은 [Keep a Changelog](https://keepachangelog.com/ko/1.1.0/)를 따르며,
이 프로젝트는 [Semantic Versioning](https://semver.org/lang/ko/)을 준수합니다.

## [Unreleased]

### Breaking changes
- `RERANK_MODE=legacy|jev`로 리랭킹 모드를 선택합니다(미지정 시 legacy).
  새 모드 없이 옛 `approach=decision` + shadow/off/미지정 설정을 사용하면
  **migration error로 시작이 중단됩니다**. Gemini로 조용히 전환하지 않습니다.
  옛 `TYPESAFE_JEV_MODE=enforce`는 경고와 함께 호환되지만 키 누락 시 시작 실패합니다.
- legacy 예외 폴백도 검색 순서 `top_n` 이내로 제한됩니다. 정상 경로는 동일합니다.
- Jev 판정 성공 시 검색 `min_score` 대신 `min_relevance`를 사용합니다.
  Self-RAG precheck와 답변 생성 LLM은 이 스위치와 별개입니다.
  켜는 법, 배포 전 검사와 롤링/rollback 절차: [Rerank mode guide](docs/RERANK_MODE.md).

### 보안
- **업로드 토큰 권한 범위 제한**: 세션 생성(`POST /api/chat/session`)만으로 발급되는 단기 업로드
  토큰으로는 더 이상 문서 삭제(`DELETE /api/upload/documents/{id}`, `bulk-delete`)를 할 수 없습니다
  (403, 서버 API 키 필요). 취소/재시도는 토큰이 바인딩된 세션이 만든 작업에만 허용되며,
  업로드 작업 레코드에 `owner_session_id`가 기록됩니다. 조회/다운로드/업로드는 기존대로 동작합니다.
- **인증 fail-closed**: `FASTAPI_AUTH_KEY`가 비어 있으면 환경(development 포함)과 무관하게
  관리자 API, 업로드 API, `/v1`, 관리자 WebSocket이 401로 거부됩니다. 예전에는 개발 환경으로
  감지되면 인증을 통째로 건너뛰어 `docker-compose.yml`의 `ENVIRONMENT=development` 고정값만으로도
  관리자 API가 열렸습니다. 브라우저 채팅(`/api/chat`, `/chat-ws`)은 영향 없습니다.
- **약한 키 거부**: 템플릿 자리표시자(`your_api_auth_key_here`, `local-dev-only-change-me` 등)나
  16자 미만의 `FASTAPI_AUTH_KEY`는 프로덕션에서 서버 시작이 거부되고, 개발 환경에서는 경고만 출력됩니다.
- **레이트리밋 스푸핑 차단**: `X-Forwarded-For`/`X-Real-IP`는 직접 연결 상대가 `TRUSTED_PROXY_IPS`
  (기본 private: loopback + 사설망) 범위일 때만 신뢰합니다. 헤더만 바꿔 IP 한도를 우회하던 경로를 막습니다.
  WebSocket 채팅(`/chat-ws`) 메시지에도 HTTP 채팅과 같은 IP/세션 한도가 적용되며 초과 시
  `WS-004-RATE_LIMITED` 에러 이벤트를 받습니다.
- **프론트엔드 관리자 키 노출 제거**: `frontend/entrypoint.sh`가 `ADMIN_API_KEY`를 공개 정적 파일
  `config.js`에 기록하던 동작을 제거했습니다. `RUNTIME_CONFIG.ADMIN_API_KEY` 폴백도 삭제되어 관리자
  키는 운영자 설정 화면(localStorage)에서만 읽습니다. 배포 환경변수에 값이 있으면 무시하고 경고를 남깁니다.
- **의존성 취약점 정리**: FastAPI 0.104.1/Starlette 0.27.0(알려진 multipart DoS 등)을 현재
  Starlette 1.x 라인으로 올리고, pypdf·pillow·aiohttp·anyio·cryptography·urllib3·requests·lxml·nltk·
  pymongo 등 28개 전이 의존성을 갱신했습니다(pip-audit 409건 → 32건). 남은 항목과 사유는
  `docs/security/dependency-triage.md`의 Current Baseline 표를 참고하세요.
- **pip-audit 게이트 추가**: `make audit` 타깃과 GitHub Actions `Security Audit` 잡(기준선이 비기
  전까지 비차단)을 추가했습니다.

### 구조 개선 (P2)
- **RAG 파이프라인 분리**: 4,900줄짜리 `rag_pipeline.py`의 `RAGPipeline`을 단계별 믹스인 패키지
  `app/api/services/pipeline/`(routing, retrieval, rerank, generation, verification, output + models,
  document_utils, base)로 나눴습니다. 공개/비공개 메서드 이름과 동작, 예전 import 경로
  (`app.api.services.rag_pipeline.X`)는 그대로 유지됩니다. 오케스트레이션(`execute`,
  `run_retrieval_phase`, 타임아웃 예산)만 `rag_pipeline.py`에 남습니다.
- **스트리밍 경로 통합**: `ChatService.stream_rag_pipeline`이 `retrieval_module.search`를 직접 부르는 대신
  비스트리밍과 같은 `RAGPipeline.run_retrieval_phase`를 호출합니다. 이제 스트리밍에서도 세션 컨텍스트,
  멀티턴 재작성, 쿼리 확장, 정확 식별자·문서명 구출, 리랭크 융합·안정화, 앵커 부스트, SQL 컨텍스트가
  동일하게 적용됩니다. 기간 불일치 환각 게이트는 스트리밍 텍스트를 바꾸지 않고 `done` 이벤트의
  `hallucination_gate` 필드로 신호를 보냅니다(Self-RAG 재생성은 스트리밍 성격상 미적용).
- **DI 컨테이너 정리**: provider별 Retriever 설정 매핑(227줄)을
  `app/modules/core/retrieval/retrievers/wiring.py`로 옮기고 컨테이너는 위임만 합니다. 표준/graceful
  두 기동 함수가 따로 들고 있던 모듈 그래프를 `_build_startup_modules` 하나로 합쳤습니다
  (프로파일은 타임아웃/재시도만 다름). `scripts/index_all_data.py`에 있던 인덱싱 로직은
  `app/modules/ingestion/bulk_index.py`로 옮겨 운영 코드가 `scripts/`를 import 하지 않습니다.
- **계층 계약 확장**: import-linter 계약을 3개에서 6개로 늘렸습니다(DI 컨테이너를 하위 계층이 import
  금지, config → api/core 금지, modules → batch 금지(기존 2건은 명시 예외)). 네임스페이스 패키지라
  검사에서 빠져 있던 11개 디렉터리에 `__init__.py`를 추가해 **기존 3개 계약도 실제로 전체 모듈을
  검사**하게 됐고, 그 과정에서 드러난 `app.config.schemas.reranking → app.modules…rerankers.mode`
  역의존은 `mode.py`를 `app/lib/rerank_mode.py`로 옮겨 해소했습니다(예전 경로는 재노출 모듈).
- **mypy 범위 확대**: `app.core.*`와 `app.api.services.*`(파이프라인, 채팅 서비스, DI 컨테이너)가
  `ignore_errors` 목록에서 빠져 타입 검사를 받습니다. 그 과정에서 실제 버그 3건을 잡았습니다:
  (1) 평가기용 LLM 래퍼와 GraphRAG 추출기용 LLM 래퍼가 존재하지 않는 `client.generate`를 호출
  (`generate_text`로 수정), (2) 존재하지 않는 `ErrorCode.GENERATION_INVALID_RESPONSE` 참조
  (`GENERATION_REQUEST_FAILED`로 수정), (3) Circuit Breaker 팩토리 미주입 시 검색이 AttributeError로
  실패하던 경로(선택 의존성으로 처리).
- **중복 제거 / 죽은 코드**: Qdrant·Pinecone 리트리버 공통 베이스 추출, 수제 재시도 루프와 환경변수
  파서를 공용 헬퍼로 통일, 로깅 스타일을 `app.lib.logger.get_logger` 하나로 통일, 가려져 있던
  `app/config/schemas.py`·레거시 `RerankerFactory`·V1 리랭킹 스키마·미사용 `Base*` ABC 제거.

### 품질 게이트 / 정확성 (P1)
- **GraphRAG 엔티티 임베딩 복구**: `NetworkXGraphStore`가 동기 `embed_query`를 `await` 해
  매번 TypeError가 나고 광범위 except가 이를 삼켜, 운영에서는 엔티티 임베딩이 한 번도 생성되지
  않던 결함을 수정했습니다. 임베더가 동기/비동기 어느 쪽이든 처리하며(동기는 `to_thread`),
  실제 동기 임베더로 회귀 테스트를 추가했습니다. pgvector/qdrant/pinecone/mongodb 리트리버와
  로컬 임베더의 동기 임베딩 호출도 `asyncio.to_thread`로 통일해 이벤트 루프 블로킹을 없앴습니다.
- **통합 테스트 게이트 편입**: 외부 서비스 없이 통과하는 `tests/integration` 전체가 CI PR 게이트와
  `make test`에 포함됩니다(`-m "not live"`). 실제 네트워크·유료 LLM·외부 DB 테스트는 새 `live`
  마커 + `ONERAG_RUN_LIVE_PROVIDER_TESTS=1` 가드로 분리했습니다(`make test-live`). 선택 의존성이
  없는 환경에서 ERROR가 나던 로컬 임베더 통합 테스트는 `importorskip`으로 SKIP 처리합니다.
  깨져 있던 `make test-basic`, `make test-cov` 타깃을 수리했습니다.
- **커버리지 하한**: `fail_under = 61`을 설정해 커버리지가 내려가면 CI가 실패합니다. 앵커 없는
  `"pass"` 제외 규칙이 `password`/`passport`가 들어간 줄(PII 마스킹 코드 등)까지 커버리지에서
  빼던 문제를 `^\s*pass\s*$`로 교정했습니다.
- **버전 단일화**: `pyproject.toml`이 유일한 버전 소스가 되었고 `app.__version__`, FastAPI `version`,
  `/health`, `/api` 응답이 모두 여기서 읽습니다(이전에는 1.0.7 / 2.0.0 / 2.0.0 / 1.2.1 네 갈래).
  CHANGELOG 최신 릴리스와 일치하는지 검사하는 테스트를 추가했습니다.
- **SQL 검색 기본 비활성화 + 읽기 전용 강제**: `SQL_SEARCH_ENABLED` 기본값이 `false`가 되었습니다.
  켜더라도 실행 전 `SET TRANSACTION READ ONLY`와 `statement_timeout`을 적용하고, 검증기는
  `pg_sleep`, `pg_read_file`, `dblink`, `lo_import`, `SELECT ... INTO`, `SET` 등을 추가로 차단합니다.
  문자열 리터럴 안의 단어는 검사에서 제외해 오탐을 줄였습니다.
- **프론트엔드 타입체크 게이트**: `npm run typecheck`(tsc --noEmit)를 빌드와 CI에 추가하고
  기존 타입 오류를 해소했습니다. 이로써 strict tsconfig와 i18n 키 동등성이 실제로 강제됩니다.

### 추가됨
- 운영 안정성 smoke 게이트 추가: `make test-operational-smoke` 및 GitHub Actions `Runtime Smoke` job
- `/ready` readiness 엔드포인트 추가 및 Docker API healthcheck를 `/ready`로 전환
- `RETRIEVAL_STARTUP_POLICY=required|degraded` 기반 retrieval startup 정책 추가
- 현재 운영 상태 문서 `docs/STATUS.md` 추가
- BM25 하이브리드 검색 엔진 구현 (Phase 1 - ChromaDB + BM25 기반)
- Docker-Free 로컬 퀵스타트 Phase 2 구현
- 로컬 챗봇에 LLM 답변 생성 및 Rich UI 개선
- SSE `StreamMetadataEvent` Pydantic 스키마 추가
- 0% 커버리지 모듈 5개에 단위 테스트 56개 추가 (Phase 1)

### 변경됨
- Quickstart/easy-start 샘플 데이터 로더가 기본적으로 기존 컬렉션을 삭제하지 않도록 변경
- CI가 backend coverage artifact, frontend warning-gated build/test, runtime smoke를 모두 검증하도록 최신화
- `GenerationConfig` max_tokens 범위 통일 (100-32000 -> 1-128000)
- pyproject.toml 마이그레이션 및 .gitignore 개선
- 약한 테스트 제거 및 유의미한 단위 테스트 79개 재작성

### 수정됨
- Quickstart 샘플 데이터 적재를 deterministic ID 기반 갱신 방식으로 정리
- CI 전체 mypy에서 발생하던 redundant cast 오류 수정
- BM25 인덱스 직렬화 오류 해결 (Kiwi pickle 불가)
- ChromaDB 코사인 메트릭 적용 및 검색 점수 정규화
- 6-도메인 검증 결과 기반 1/2순위 개선 (13건)

### 문서
- 상태성 문서를 2026-05-13 기준으로 갱신하고 역사적 문서와 현재 상태 문서를 분리
- Rate Limiting 이중 계층 정책 가이드 추가
- 프로젝트 검증 시스템 설계 문서 (verify-system)

## [1.2.1] - 2026-01-20

### 추가됨
- Cohere Reranker 구현 (cross-encoder approach, 100+ 언어 지원)
- 로컬 CrossEncoder 리랭커 구현 (sentence-transformers 기반, API 키 불필요)
- OpenRouter Reranker 추가 - 다중 LLM 리랭킹 지원
- Factory에 Cohere, Local 리랭커 등록
- Self-RAG 및 LLM Router 활성화
- 환경별 설정 분리 완료 (development, test, production YAML)

### 수정됨
- Google provider Fallback 비활성화
- lint/type 주석 순서 수정

### 문서
- Reranker v1.2.1 문서 업데이트 (Cohere, Local, OpenRouter)
- README 개선 - RAG 파이프라인, DI 컨테이너 구성 요소 추가
- OneRAG 브랜딩 적용 및 영문 README 동기화

## [1.2.0] - 2026-01-20

### 변경됨
- 버전 v1.1.0 -> v1.2.0 업데이트
- CLAUDE.md 팩토리 수 일관성 수정 (8 -> 9)

## [1.1.0] - 2026-01-19

### 추가됨
- `RerankingConfig` v2 스키마 추가 (approach/provider/model 3단계 구조)
- `RerankerFactoryV2` 추가 (approach/provider/model 3단계)
- DI 컨테이너에 `create_reranker_instance_v2` 추가

### 변경됨
- Reranker 설정 v2를 메인 구현으로 승격
- `reranking.yaml` 3단계 구조로 마이그레이션

### 문서
- Reranker v2 리팩토링 완료 문서화

## [1.0.9] - 2026-01-16

### 추가됨
- WebSocket 실시간 채팅 API 구현 (`WS /chat-ws`)
- 6종 메시지 타입: `message`, `stream_start`, `stream_token`, `stream_sources`, `stream_end`, `stream_error`
- WebSocket DI 패턴을 위한 타입 정의, Context, Provider 추가
- `ChatWebSocketService` DI 팩토리 함수 구현
- WebSocket DI 패턴 프론트엔드 구현 완료
- Local Embedder 구현 (Qwen3-Embedding-0.6B)
- Frontend 모노레포 통합 (moduleRagChat_Front)
- WebSocket E2E 테스트 추가

### 변경됨
- 기존 싱글톤 서비스를 DI 기반으로 마이그레이션
- Chat Hook 중복 코드 제거 (Core Hook + Wrapper 패턴)
- RAG 파이프라인 통합 (`ChatService.stream_rag_pipeline()` 재사용)

### 수정됨
- Quickstart Google Gemini 직접 연결 지원

### 문서
- WebSocket API 사용 가이드 작성 (`docs/websocket-api-guide.md`)

## [1.0.8] - 2026-01-15

### 추가됨
- Streaming API 전체 구현 (`POST /chat/stream`, SSE 기반)
- 4종 이벤트 타입: `metadata`, `chunk`, `done`, `error`
- Multi-LLM 스트리밍 지원 (Google Gemini, OpenAI GPT, Anthropic Claude)
- Rate Limit: 100회/15분
- `/chat/stream` 엔드포인트 라우터에 추가
- LLM Client 스트리밍 인터페이스 추가 (OpenAI, Anthropic)
- `AgentReflector` 기본 구조 및 `reflect()` 메서드 구현
- `ReflectionResult` 데이터 클래스 추가
- `AgentConfig`에 Self-Reflection 설정 추가
- `GenerationModule` 스트리밍 답변 생성 메서드 추가
- 스트리밍 API Pydantic 스키마 정의
- Quickstart 원클릭 실행 환경 구현
- Self-Reflection E2E 통합 테스트 추가
- 스트리밍 API 통합 테스트 추가

### 변경됨
- MCP 모듈을 Tools 모듈로 재구성
- 스트리밍 RAG 파이프라인에 리랭킹 단계 추가

### 수정됨
- 스트리밍 에러 처리 보안 개선
- Generator 스트리밍 보안 및 통계 개선
- `load_sample_data` 함수 반환 타입 힌트 추가

### 문서
- Streaming API 사용 가이드 작성 (`docs/streaming-api-guide.md`)

## [1.0.7] - 2026-01-10

### 변경됨
- **Phase 3**: `get_performance_metrics()` -> `_get_performance_metrics()` private 전환
  - deprecated 공개 함수를 private 내부 헬퍼로 전환
  - `track_function_performance` 데코레이터 내부 호출 업데이트
  - 전역 metrics 객체 초기화 업데이트
  - 7개 테스트 추가 (`tests/unit/lib/test_metrics_internal.py`)
- **Phase 1**: deprecated 함수 제거 (-48줄)
  - `get_prompt_manager()` 완전 제거
  - `GPT5NanoReranker` 클래스 제거 -> `OpenAILLMReranker` 사용
- **Phase 2**: 전역 레지스트리 제거 (-57줄)
  - `get_circuit_breaker()` 함수 제거
  - `_circuit_breakers` 전역 레지스트리 제거
  - `LLMQueryRouter`에 `circuit_breaker_factory` 필수화
- 모든 deprecated 함수 제거/리팩토링 완료

### 문서
- CLAUDE.md v1.0.7 버전 동기화
- 기술부채 분석 보고서 업데이트
- 오픈소스 배포 준비 문서
- MIT 라이선스 추가
- CI: GitHub Actions 워크플로우 추가

## [1.0.5] - 2026-01-09

### 추가됨
- **Multi Vector DB 6종 지원**
  - `VectorStoreFactory`: 벡터 DB 동적 선택 팩토리
  - `RetrieverFactory`: Retriever 동적 선택 팩토리
  - 지원 DB: Weaviate (기본), Chroma, Pinecone, Qdrant, pgvector, MongoDB Atlas
  - 환경변수 `VECTOR_DB_PROVIDER`로 DB 선택
- E2E 디버깅 플로우 추가

### 변경됨
- pyproject.toml에 선택적 의존성 추가 (`chroma`, `pinecone`, `qdrant`, `pgvector`, `all-vectordb`)
- DI Container에 VectorStore, Retriever Factory Provider 추가

## [1.0.0] - 2026-01-09

### 추가됨
- 도메인 범용 RAG 시스템 초기 오픈소스 공개
- **지능형 검색 (Hybrid Retrieval)**
  - Weaviate 기반 Dense(의미) + Sparse(BM25) 하이브리드 검색
  - GraphRAG: `NetworkXGraphStore`에 벡터 검색 엔진 통합
  - Reranker: LLM, Cross-Encoder, Late-Interaction 3종 approach 지원
- **보안 시스템 (Unified Security)**
  - PII Facade: `PIIProcessor` 통합 (단순 마스킹 + AI 리뷰)
  - Admin Auth: `/api/admin` 전역 `X-API-Key` 인증
  - spaCy + Regex 하이브리드 PII 탐지
- **운영 유연성 (Dynamic Config)**
  - YAML Routing: `routing_rules_v2.yaml` 기반 동적 쿼리 라우팅
  - 환경별 설정 분리 (development, test, production)
  - Pydantic 기반 설정 검증 (타입 안전성 및 범위 검증)
- **에러 시스템 v2.0 (양언어)**
  - ErrorCode 기반 구조화된 에러 코드 (예: `GEN-001`, `SEARCH-003`)
  - `Accept-Language` 헤더 기반 한국어/영어 자동 전환
  - 사용자 친화적 메시지 및 해결 방법 제공
- **DI 컨테이너 (Dependency Injection)**
  - 80+ Provider: Singleton(70개) + Factory(10개)
  - 9개 명시적 팩토리: Agent, Evaluator, GraphRAG, Cache, MCP, Ingestion, VectorStore, Retriever, RerankerV2
- **Multi-LLM Factory**
  - 4개 Provider 지원: Google Gemini, OpenAI GPT, Anthropic Claude, OpenRouter
  - 자동 Fallback 전환
  - `GPT5QueryExpansionEngine`: `llm_factory` 필수화로 OpenAI 직접 의존성 제거
- **Observability**
  - 실시간 메트릭: `/api/admin/realtime-metrics` 엔드포인트
  - 캐시 모니터링: `cache_hit_rate`, `cache_hits`, `cache_misses`
  - 비용 추적: `total_cost_usd`, `cost_per_hour`, `total_llm_tokens`
- **GraphRAG 모듈**
  - `GraphRAGFactory`: 설정 기반 컴포넌트 생성
  - `KnowledgeGraphBuilder`: LLM 기반 엔티티/관계 추출
  - `NetworkXGraphRepository`: NetworkX 기반 그래프 저장소
  - 벡터+그래프 하이브리드 검색 (RRF 기반)
- **Agentic RAG 시스템**
  - `AgentOrchestrator`: ReAct 패턴 에이전트 루프
  - `AgentPlanner`: LLM 기반 도구 선택 (Function Calling)
  - `AgentExecutor`: 도구 병렬/순차 실행
- **시맨틱 캐시**: 쿼리 임베딩 유사도 기반 캐시 히트
- **ColBERT 리랭커**: 토큰 수준 Late Interaction 리랭킹
- **MCP 도구 시스템**: `search_vector_db`, `get_document_by_id`, `query_sql`
- **Factory 패턴**: `EmbedderFactory`, `RerankerFactory`, `CacheFactory`, `MCPToolFactory`
- RRF 점수 100점 정규화 (`app/lib/score_normalizer.py`)
- 1,700+ 테스트 통과 (단위/통합/안정성)

### 보안
- 프로덕션 환경 인증 우회 취약점 수정 (다층 환경 감지 로직)
- 환경 변수 검증 (`get_env_int()`, `get_env_bool()`, `get_env_url()`)
- Privacy 감사 로그 PII 노출 수정 (SHA-256 해시 저장, GDPR 준수)
- Agent 모듈 타임아웃 구현 (무한 대기 방지, 기본 300초)

[Unreleased]: https://github.com/notadev-iamaura/OneRAG/compare/v1.2.1...HEAD
[1.2.1]: https://github.com/notadev-iamaura/OneRAG/compare/v1.2.0...v1.2.1
[1.2.0]: https://github.com/notadev-iamaura/OneRAG/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/notadev-iamaura/OneRAG/compare/v1.0.9...v1.1.0
[1.0.9]: https://github.com/notadev-iamaura/OneRAG/compare/v1.0.8...v1.0.9
[1.0.8]: https://github.com/notadev-iamaura/OneRAG/compare/v1.0.7...v1.0.8
[1.0.7]: https://github.com/notadev-iamaura/OneRAG/compare/v1.0.5...v1.0.7
[1.0.5]: https://github.com/notadev-iamaura/OneRAG/compare/v1.0.0...v1.0.5
[1.0.0]: https://github.com/notadev-iamaura/OneRAG/releases/tag/v1.0.0
