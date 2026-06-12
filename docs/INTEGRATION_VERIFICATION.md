# 통합 검증 가이드 (Integration Verification)

정적 CI 게이트(`lint` / `mypy` / `lint-imports` / 단위·통합 stub 테스트)는 빠르고
의존성이 없지만, **실제 외부 서비스 연결과 무거운 optional provider 동작은
검증하지 않는다.** 이 문서는 그 간극을 메우는 통합 검증 환경 구성과 실행 방법을
설명한다.

## 무엇을 추가로 검증하는가

| 항목 | 정적 게이트 | 통합 검증 |
|---|---|---|
| Weaviate 하이브리드 검색 (실 연결) | ❌ (skip) | ✅ |
| PostgreSQL 세션/평가/프롬프트 영속화 | stub | ✅ 실 DB |
| pgvector VectorStore (실 연결) | mock | ✅ 실 DB (pgvector/pgvector:pg16) |
| Qdrant VectorStore (실 연결) | mock | ✅ 실 서버 |
| spaCy 한국어 NER (PII detector) | ❌ (skip) | ✅ |
| sentence-transformers 로컬 임베더 | ❌ (skip) | ✅ |
| 실모델 CrossEncoder 리랭커 (HF 다운로드+추론) | ❌ (skip) | ✅ |
| 실 LLM 호출 (self-reflection 등) | mock | ✅ (API 키 필요, 비용 발생) |
| Neo4j GraphRAG | ❌ (skip) | 선택 (별도 기동 필요) |

## 라이브 프로바이더 검증 매트릭스

vector DB 프로바이더별로 **어느 계층에서 실연결 검증되는지** 정리한 표이다.
직전 사이클에서 mock 기반 테스트만으로 pinecone 회귀가 CI를 통과한 사례가 있어,
컨테이너 가능한 프로바이더는 모두 로컬 verify 스택에서 실연결로 검증한다.

| 프로바이더 | 검증 계층 | 방식 |
|---|---|---|
| Weaviate | 로컬 verify 스택 | `docker-compose.verify.yml` (하이브리드 검색 실연결) |
| PostgreSQL (세션 영속화) | 로컬 verify 스택 | `docker-compose.verify.yml` (pgvector 이미지가 postgres:16 호환이라 세션 테스트 겸용) |
| pgvector | 로컬 verify 스택 | `docker-compose.verify.yml` (`pgvector/pgvector:pg16` — 확장 내장 이미지) |
| Qdrant | 로컬 verify 스택 | `docker-compose.verify.yml` (`qdrant/qdrant:v1.18.2`) |
| Chroma | 로컬 verify | 로컬 파일 기반 — 컨테이너 불필요, integration 테스트에서 직접 검증 |
| Pinecone | 주간 클라우드 스모크 | 관리형 서비스 — 별도 작업으로 `.github/workflows/live-provider-smoke.yml` 추가 중 |
| MongoDB Atlas | 주간 클라우드 스모크 | 관리형 서비스 — 별도 작업으로 `.github/workflows/live-provider-smoke.yml` 추가 중 |

## 1. 선행 의존성 설치

```bash
# 무거운 optional 의존성 (sentence-transformers + torch ≈ 2GB)
# + vector DB 클라이언트 (qdrant-client, pgvector — pgvector extra에는
#   실 DB 연결용 psycopg[binary]가 보강될 예정)
uv sync --extra dev --extra local-embedding --extra qdrant --extra pgvector

# spaCy 한국어 모델 (PyPI 미배포 → GitHub release wheel 직접 설치)
# spaCy 3.7.x → 모델 3.7.0
uv pip install "https://github.com/explosion/spacy-models/releases/download/ko_core_news_sm-3.7.0/ko_core_news_sm-3.7.0-py3-none-any.whl"
```

> spaCy `python -m spacy download`는 uv 환경에 `pip`가 없어 실패한다. 위처럼
> `uv pip install`로 wheel을 직접 설치한다. spaCy 버전이 바뀌면 모델 버전도 맞춘다.

## 2. LLM 키 (실 LLM 테스트용, 선택)

`.env`에 `GOOGLE_API_KEY` / `OPENAI_API_KEY` / `OPENROUTER_API_KEY` 중 하나 이상을
설정한다. 없으면 실 LLM 테스트는 자동 skip된다. **실 LLM 호출은 토큰 비용이
발생한다.**

## 3. 실행

### 한 번에 (권장)

```bash
make verify-integration
```

이 타깃은 `scripts/verify-integration.sh`를 실행하며:

1. `docker-compose.verify.yml`로 **Weaviate + PostgreSQL(pgvector) + Qdrant**를
   기동하고 healthy까지 대기
2. optional provider 게이트(`ONERAG_RUN_OPTIONAL_PROVIDER_TESTS=1`)와 실모델
   게이트(`ONERAG_RUN_REAL_MODEL_TESTS=1`)를 켜고 PII detector·로컬 임베더·
   실모델 CrossEncoder 리랭커 단위 테스트 실행
3. `WEAVIATE_URL`·`WEAVIATE_GRPC_PORT`·`DATABASE_URL`·`QDRANT_URL`을 주입하고
   `pytest tests/integration -m integration` 실행 — `tests/integration/vector_stores/`
   하위 신규 테스트도 marker로 자동 포함된다
4. 종료 시 서비스·볼륨 정리 (`down -v` — 매 실행 깨끗한 상태 보장,
   `KEEP_SERVICES=1`로 유지 가능)

> 검증 스택은 dev 스택(`make start`)과 동시 실행이 가능하도록 호스트 포트를
> 리맵했다: Weaviate HTTP `8081`, gRPC `50052`, PostgreSQL `55432`,
> Qdrant HTTP `16333`, gRPC `16334`.
> `restart: "no"` 정책이라 Docker 데몬 재시작 시 부활하지 않는다.

### 수동 (디버깅)

```bash
# 서비스만 기동
docker compose -f docker-compose.verify.yml up -d --wait

# 환경변수 게이트 (verify 스택은 dev 스택과 다른 포트 사용)
export ONERAG_RUN_OPTIONAL_PROVIDER_TESTS=1
export ONERAG_RUN_REAL_MODEL_TESTS=1
export WEAVIATE_URL=http://localhost:8081
export WEAVIATE_GRPC_PORT=50052
export DATABASE_URL=postgresql://onerag:onerag-verify@localhost:55432/rag_db
export QDRANT_URL=http://localhost:16333
export ENVIRONMENT=test

# 부분 실행 예시
uv run pytest tests/integration/test_hybrid_search_integration.py -q   # Weaviate
uv run pytest tests/unit/privacy/test_pii_detector.py -q               # spaCy ko
uv run pytest tests/unit/retrieval/rerankers/test_local_reranker.py -q # 실모델 reranker

# 종료
docker compose -f docker-compose.verify.yml down -v
```

## 핵심 게이트 환경변수

| 변수 | 용도 |
|---|---|
| `ONERAG_RUN_OPTIONAL_PROVIDER_TESTS=1` | spaCy/sentence-transformers 등 무거운 optional 테스트 활성화 (기본 비활성). 제외 경로 목록의 단일 진실원은 `tests/conftest.py`의 `OPTIONAL_PROVIDER_TEST_PATHS` |
| `ONERAG_RUN_REAL_MODEL_TESTS=1` | 실모델 테스트 활성화 (기본 비활성). `test_local_reranker.py`가 실제 CrossEncoder 모델을 HuggingFace에서 다운로드해 추론까지 검증한다. CI 기본 게이트는 결정성(네트워크 무의존)을 위해 skip하며, 실모델 reranker 추론 검증은 이 게이트를 켜고 수행 |
| `WEAVIATE_URL` | Weaviate 연결 (verify 스택 기본 `http://localhost:8081`) |
| `WEAVIATE_GRPC_PORT` | Weaviate gRPC 포트 (verify 스택 기본 `50052`) |
| `DATABASE_URL` | PostgreSQL/pgvector 연결 (verify 스택 기본 `postgresql://onerag:onerag-verify@localhost:55432/rag_db`) |
| `QDRANT_URL` | Qdrant 연결 (verify 스택 기본 `http://localhost:16333`, gRPC는 `16334`) |
| `NEO4J_URI` | (선택) Neo4j GraphRAG 테스트. 미설정 시 skip |

## Neo4j (선택)

GraphRAG integration 테스트는 Neo4j가 필요하다. 검증하려면 별도 기동:

```bash
docker compose -f docker-compose.neo4j.yml up -d
export NEO4J_URI=bolt://localhost:7687
```

## 현재 검증 상태 (2026-06-10)

- ✅ Weaviate 하이브리드 검색 integration 통과
- ✅ PostgreSQL 세션 race condition / 영속화 통과
- ✅ spaCy 한국어 NER (PII detector) 통과
- ✅ sentence-transformers 로컬 임베더 통과
- ⏭️ Neo4j GraphRAG: 별도 기동 시에만 (기본 skip)
- 💰 실 LLM 테스트: 키 설정 시 통과 (토큰 비용 발생)
- 🆕 pgvector·Qdrant: verify 스택에 추가됨 — 대응 integration 테스트
  (`tests/integration/vector_stores/`)와 함께 첫 실연결 검증 예정

> 통합 검증 중 `test_session_race_condition.py`의 중복-ID 테스트가
> IDOR 방어(약한 session_id 거부) 변경과 불일치해 실패했고, 유효 UUID4를
> 쓰도록 테스트를 수정했다. 이처럼 통합 검증은 단위 테스트가 놓친 실제
> 시나리오 회귀를 잡아낸다.
