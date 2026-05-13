# OneRAG 코드 품질 분석 보고서

> 분석일: 2026-01-20
> 상태 검토: 2026-05-13
> 상태: 🟢 운영 안정성 게이트 통과. 최신 CI/런타임 상태는 `docs/STATUS.md` 기준.

## 요약

OneRAG 프로젝트는 Phase 1, 2, 3 개선으로 주요 deprecated 함수가 정리되고 DI 패턴이 강화되었습니다. 이후 운영 안정성 보강으로 `/ready` readiness, retrieval startup policy, quickstart 데이터 안전화, runtime smoke CI가 추가되었습니다.

| 카테고리 | 현황 | 우선순위 |
|---------|------|---------|
| DI 컨테이너 | 80+ Provider, 잘 구조화됨 | 🟢 유지 |
| 팩토리 패턴 | 9개 명시적 팩토리 | 🟢 유지 |
| 레거시 코드 | ✅ 모든 deprecated 함수 제거 완료 | 🟢 완료 |
| 전역 상태 | ✅ DI Container로 완전 이전 | 🟢 완료 |
| 테스트 | 1,700+개 통과, 일부 skip | 🟢 양호 |
| Multi Retrieval Provider | ✅ Vector DB 6종 + Grok Retriever 모드 | 🟢 완료 |
| Reranker 설정 | ✅ v2.1 (4 approach, 6 provider) | 🟢 완료 |

---

## 1. DI 컨테이너 분석

### 1.1 현재 구조 (✅ 우수)

```
app/core/di_container.py
├── Singleton Providers (약 70개)
│   ├── 설정 관련: config_loader, settings
│   ├── 저장소: weaviate_client, mongodb_client
│   ├── 서비스: retrieval_module, generation_module
│   └── 유틸리티: logger, metrics
│
└── Factory Providers (약 10개)
    ├── session_factory
    ├── request_context_factory
    └── 기타 동적 생성 객체
```

### 1.2 명시적 팩토리 클래스 (9개)

| 팩토리 | 위치 | 역할 |
|--------|------|------|
| `AgentFactory` | `factories/agent_factory.py` | 에이전트 인스턴스 생성 |
| `EvaluatorFactory` | `factories/evaluator_factory.py` | 평가기 생성 |
| `GraphRAGFactory` | `factories/graphrag_factory.py` | GraphRAG 컴포넌트 생성 |
| `CacheFactory` | `factories/cache_factory.py` | 캐시 인스턴스 생성 |
| `MCPFactory` | `factories/mcp_factory.py` | MCP 클라이언트 생성 |
| `IngestionFactory` | `factories/ingestion_factory.py` | 문서 수집기 생성 |
| `VectorStoreFactory` | `infrastructure/storage/vector/factory.py` | 벡터 DB 인스턴스 생성 |
| `RetrieverFactory` | `modules/core/retrieval/retrievers/factory.py` | Retriever 인스턴스 생성 |
| `RerankerFactoryV2` | `modules/core/retrieval/rerankers/factory.py` | Reranker 인스턴스 생성 (v2) |

### 1.3 개선 완료 영역 (v1.0.6)

#### 전역 상태 패턴 → DI Container 이전 ✅

**1) APIKeyAuth DI Provider 추가**
```python
# app/core/di_container.py
api_key_auth = providers.Singleton(get_api_key_auth)
```
- **상태**: ✅ 완료
- **방식**: 기존 전역 싱글톤을 DI Provider로 래핑하여 하위 호환성 유지

**2) CircuitBreaker Factory DI 주입**
```python
# LLMQueryRouter에 circuit_breaker_factory 필수 주입
query_router = providers.Singleton(
    LLMQueryRouter,
    circuit_breaker_factory=circuit_breaker_factory,
)
```
- **상태**: ✅ 완료
- **효과**: `get_circuit_breaker()` 함수 완전 제거됨 (v1.0.6)

---

## 2. 레거시 코드 분석

### 2.1 Deprecated 함수 (v1.0.7 완전 제거)

| 함수 | 위치 | 대체 방안 | 상태 |
|------|------|----------|------|
| `get_cost_tracker()` | `metrics.py` | DI Container 직접 사용 | ✅ 제거됨 (v1.0.3) |
| `get_mongodb_client()` | `mongodb_client.py` | DI Container 직접 사용 | ✅ 제거됨 (v1.0.3) |
| `get_prompt_manager()` | `prompt_manager.py` | DI Container 직접 사용 | ✅ 제거됨 (v1.0.6) |
| `GPT5NanoReranker` | `openai_llm_reranker.py` | `OpenAILLMReranker` 사용 | ✅ 제거됨 (v1.0.6) |
| `get_circuit_breaker()` | `circuit_breaker.py` | `circuit_breaker_factory.get()` | ✅ 제거됨 (v1.0.6) |
| `get_performance_metrics()` | `metrics.py` | `_get_performance_metrics()` (private) | ✅ 리팩토링됨 (v1.0.7) |

**v1.0.7 완료 (Phase 1, 2, 3)**:
- **Phase 1**: `get_prompt_manager()`, `GPT5NanoReranker` 제거 (-48줄)
- **Phase 2**: `get_circuit_breaker()` 및 관련 전역 레지스트리 제거 (-57줄)
- **Phase 3**: `get_performance_metrics()` → `_get_performance_metrics()` 리팩토링 (TDD 기반)
- **검증**: 12가지 사용처 검증 (scripts, YAML, 동적 import, docs 등) 모두 통과
- **테스트**: 1,637개 전체 통과 (v1.1.0 기준)

### 2.2 설정 파일 통합 ✅

**완료된 마이그레이션 (v1.0.2)**
- ✅ `config/config.yaml` 제거 완료 → `config/base.yaml` 사용
- `routing_rules_v2.yaml`: 향상된 라우팅 로직 지원
- `base.yaml`: 환경별 설정 분리, Pydantic 검증 통합

### 2.3 OpenAI 직접 호출 (✅ v1.0.3 완료)

```python
# app/modules/core/retrieval/query_expansion/gpt5_engine.py
class GPT5QueryExpansionEngine:
    # ✅ OpenAI 직접 호출 제거 완료
    # llm_factory 필수화로 DI 패턴 완성
    def __init__(self, ..., llm_factory: Any = None, ...):
        if llm_factory is None:
            raise ValueError("llm_factory는 필수입니다.")
```

### 2.4 CircuitBreaker DI 필수화 (✅ v1.0.6 완료)

```python
# app/modules/core/routing/llm_query_router.py
class LLMQueryRouter:
    # ✅ circuit_breaker_factory 필수화로 DI 패턴 완성
    def _route_with_llm(self, ...):
        if not self.circuit_breaker_factory:
            raise ValueError("circuit_breaker_factory는 DI Container에서 주입되어야 합니다.")
        breaker = self.circuit_breaker_factory.get("llm_query_router", cb_config)
```

---

## 3. 테스트 현황

### 3.1 전체 통계
- **총 테스트**: 1,288개
- **통과**: 1,288개 ✅
- **Skip된 테스트**: 약 14개

### 3.2 Skip된 테스트 분석

| 테스트 | 사유 | 상태 |
|--------|------|------|
| `test_e2e_debug_flow` (3개) | 실제 서비스 연결 필요 (Weaviate, LLM) | 환경 의존 |
| `test_neo4j_integration` (9개) | Neo4j 환경 설정 필요 | 환경 의존 |
| `test_pgvector_store` | psycopg[binary] 미설치 | 선택적 의존성 |
| `test_qdrant_store` | qdrant-client 미설치 | 선택적 의존성 |

---

## 4. 에러 시스템 (✅ 완료)

### 4.1 양언어 지원 에러 시스템 v2.0

```python
# 현재 구조
class ErrorCode(Enum):
    # 각 에러 코드별 한국어/영어 메시지 매핑
    GENERATION_TIMEOUT = "GEN-001"
    RETRIEVAL_SEARCH_FAILED = "SEARCH-003"
    ...

# 사용 예시
raise GenerationError(ErrorCode.GENERATION_TIMEOUT, model="claude-sonnet-4-5")
```

### 4.2 완료된 마이그레이션
- ✅ `errors_legacy.py` 완전 제거
- ✅ 모든 예외 클래스 새 형식으로 통일
- ✅ Accept-Language 헤더 기반 언어 자동 선택

---

## 5. Multi Vector DB 지원 (✅ v1.0.5 완료)

### 5.1 지원 검색 Provider

| Provider | 하이브리드 검색 | 특징 |
|----------|---------------|------|
| **weaviate** (기본) | ✅ Dense + BM25 | 셀프호스팅, 하이브리드 내장 |
| **chroma** | ✅ Dense + BM25 | 경량, 로컬 개발용 (BM25 엔진 필요) |
| **pinecone** | ✅ Dense + Sparse | 서버리스 클라우드 |
| **qdrant** | ✅ Dense + Full-Text | 고성능 셀프호스팅 |
| **pgvector** | ❌ Dense 전용 | PostgreSQL 확장 |
| **mongodb** | ❌ Dense 전용 | Atlas Vector Search |
| **grok** | ✅ 관리형 검색 | xAI Grok Collections API, VectorStore 불필요 |

### 5.2 Factory 패턴

```python
# 환경변수로 검색 Provider 선택
export VECTOR_DB_PROVIDER="pinecone"

# DI Container가 자동으로 적절한 인스턴스 생성
container = Container()
retriever = container.retriever()  # 선택된 Retriever 반환
```

---

## 6. 권장 개선 로드맵

### ✅ 완료됨 (v1.0.6)
1. ~~전역 상태 패턴 DI Container 이전~~ → 완료
2. ~~`config.yaml` → `base.yaml` 완전 전환~~ → 완료
3. ~~`GPT5QueryExpansionEngine` OpenAI 직접 호출 제거~~ → 완료
4. ~~Deprecated 헬퍼 함수 제거~~ → 완료 (Phase 1, 2)
5. ~~`routing_rules.yaml` → `routing_rules_v2.yaml` 완전 이관~~ → 완료
6. ~~Multi Vector DB 지원 (6종)~~ → 완료, Grok Retriever 모드 추가 반영

### ✅ 완료됨 (v1.1.0)

#### 1. 리랭커 설정 구조 리팩토링 ✅

**완료됨 (v1.1.0)**: `reranking.yaml` 설정이 3단계 계층 구조로 리팩토링됨

```yaml
# 새로운 구조 (approach → provider → model)
reranking:
  enabled: true
  approach: "late-interaction"  # llm | cross-encoder | late-interaction
  provider: "jina"              # approach에 따라 유효한 provider 선택

  # Provider별 개별 설정
  google:
    model: "gemini-flash-lite-latest"
    max_documents: 20
    timeout: 15

  jina:
    model: "jina-colbert-v2"
    top_n: 10
    timeout: 30
```

**approach-provider 유효 조합**:
| approach | 유효한 provider | 특징 |
|----------|----------------|------|
| `llm` | google, openai, openrouter | LLM의 언어 이해력 활용 |
| `cross-encoder` | jina, cohere | 쿼리+문서 쌍 인코딩 |
| `late-interaction` | jina | ColBERT 토큰 레벨 상호작용 |
| `local` | sentence-transformers | API 키 불필요, 오프라인 사용 |

**주요 변경 사항**:
- `RerankerFactoryV2` 추가 (새 코드에서 사용 권장)
- `RerankerFactory` 레거시 호환 유지 (기존 설정 자동 변환)
- Pydantic 기반 approach-provider 조합 검증
- 62개 신규 테스트 추가 (v1.2.1)

**v1.2.1 신규 Provider**:
- **Cohere**: `rerank-multilingual-v3.0` 모델, 100+ 언어 지원
- **Local (sentence-transformers)**: API 키 불필요, 오프라인 사용 가능
  - 설치: `uv sync --extra local-reranker`
  - 기본 모델: `cross-encoder/ms-marco-MiniLM-L-12-v2` (130MB)

**파일 구조**:
```
app/config/schemas/reranking.py                         # RerankingConfigV2 + RerankingConfig 별칭
app/modules/core/retrieval/rerankers/factory.py         # RerankerFactoryV2 + RerankerFactory (레거시)
app/modules/core/retrieval/rerankers/cohere_reranker.py # Cohere Reranker 구현
app/modules/core/retrieval/rerankers/local_reranker.py  # Local Reranker 구현
app/config/schemas/_legacy/                             # 레거시 스키마 보관
app/modules/core/retrieval/rerankers/_legacy/           # 레거시 팩토리 보관
```

### 장기 (선택적)
1. Admin 인증 시스템 구현
2. E2E 디버그 플로우 테스트 활성화 (실제 서비스 연결 시)

---

## 7. 결론

OneRAG는 **코드 정리와 운영 안정성 게이트가 강화된 프로젝트**입니다:

- **DI 패턴**: 80+ Provider로 잘 구조화됨, 모든 deprecated 함수 제거
- **팩토리 패턴**: 9개 명시적 팩토리로 확장성 확보 (VectorStore, Retriever, RerankerV2 추가)
- **에러 시스템**: 양언어 지원 v2.0 완료
- **테스트**: 1,637개 테스트로 높은 커버리지
- **Multi Retrieval Provider**: Vector DB 6종 + Grok Retriever 모드
- **Reranker 설정 v2**: 3단계 계층 구조 (approach/provider/model)

모든 필수 코드 정리가 완료되었습니다. 남은 항목은 **선택적 기능 확장**입니다.

---

## 변경 이력

| 버전 | 날짜 | 변경 내용 |
|------|------|----------|
| v1.2.1 | 2026-01-20 | Reranker 확장: Cohere, Local(sentence-transformers) 추가, 4 approach/6 provider 지원 |
| v1.2.0 | 2026-01-19 | Reranker 설정 v2 리팩토링: 3단계 계층 구조 (approach/provider/model) |
| v1.0.7 | 2026-01-10 | Phase 3: get_performance_metrics() → _get_performance_metrics() 리팩토링 (TDD) |
| v1.0.6 | 2026-01-10 | Phase 1, 2 deprecated 함수 완전 제거 (-105줄) |
| v1.0.5 | 2026-01-09 | Multi Vector DB 6종 지원 추가 |
| v1.0.3 | 2026-01-09 | Tier 2 개선, deprecated 함수 정리 |
| v1.0.2 | 2026-01-08 | 설정 파일 통합, DI Provider 추가 |
