# 변경 이력 (Changelog)

이 프로젝트의 모든 주요 변경 사항을 기록합니다.
형식은 [Keep a Changelog](https://keepachangelog.com/ko/1.1.0/)를 따르며,
이 프로젝트는 [Semantic Versioning](https://semver.org/lang/ko/)을 준수합니다.

## [Unreleased]

### 추가됨
- BM25 하이브리드 검색 엔진 구현 (Phase 1 - ChromaDB + BM25 기반)
- Docker-Free 로컬 퀵스타트 Phase 2 구현
- 로컬 챗봇에 LLM 답변 생성 및 Rich UI 개선
- SSE `StreamMetadataEvent` Pydantic 스키마 추가
- 0% 커버리지 모듈 5개에 단위 테스트 56개 추가 (Phase 1)

### 변경됨
- `GenerationConfig` max_tokens 범위 통일 (100-32000 -> 1-128000)
- pyproject.toml 마이그레이션 및 .gitignore 개선
- 약한 테스트 제거 및 유의미한 단위 테스트 79개 재작성

### 수정됨
- BM25 인덱스 직렬화 오류 해결 (Kiwi pickle 불가)
- ChromaDB 코사인 메트릭 적용 및 검색 점수 정규화
- 6-도메인 검증 결과 기반 1/2순위 개선 (13건)

### 문서
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

[Unreleased]: https://github.com/youngouk/RAG_Standard/compare/v1.2.1...HEAD
[1.2.1]: https://github.com/youngouk/RAG_Standard/compare/v1.2.0...v1.2.1
[1.2.0]: https://github.com/youngouk/RAG_Standard/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/youngouk/RAG_Standard/compare/v1.0.9...v1.1.0
[1.0.9]: https://github.com/youngouk/RAG_Standard/compare/v1.0.8...v1.0.9
[1.0.8]: https://github.com/youngouk/RAG_Standard/compare/v1.0.7...v1.0.8
[1.0.7]: https://github.com/youngouk/RAG_Standard/compare/v1.0.5...v1.0.7
[1.0.5]: https://github.com/youngouk/RAG_Standard/compare/v1.0.0...v1.0.5
[1.0.0]: https://github.com/youngouk/RAG_Standard/releases/tag/v1.0.0
