# 개발 및 품질 가이드 (Development)

프로젝트의 코드 품질을 유지하고 협업 효율을 높이기 위한 개발 가이드라인입니다.

---

## 1. 코딩 컨벤션

### 1.1 타입 힌트 (Type Hinting)
- 모든 함수와 메서드에는 명확한 타입 힌트를 작성해야 합니다.
- **MyPy 엄격 모드** 적용: `app/modules/core/privacy`, `app/modules/core/self_rag` 등 핵심 모듈은 타입 체크를 통과해야 합니다.

### 1.2 비동기 프로그래밍
- I/O 작업(DB, API 호출)은 반드시 `async`/`await`를 사용합니다.
- 동기 라이브러리를 사용할 경우 `asyncio.to_thread` 등으로 래핑하여 이벤트 루프 블로킹을 방지합니다.

---

## 2. 도구 활용 (Makefile)

패키지 관리와 품질 검사를 위해 `make` 명령어를 제공합니다.

- `make lint`: Ruff를 이용한 코드 스타일 검사
- `make format`: 코드 자동 포맷팅
- `make type-check`: MyPy 타입 체크
- `make test`: 전체 유닛 테스트 실행
- `make test-operational-smoke`: readiness, startup policy, Docker compose, quickstart 안전성 smoke 검증

---

## 3. 테스트 가이드

### 3.1 테스트 구조
- `tests/unit`: 개별 클래스 및 함수 단위 테스트
- `tests/integration`: 컴포넌트 간 결합 및 외부 API(Mock) 테스트

### 3.2 테스트 실행 및 격리
```bash
# 전체 테스트 실행
make test

# 운영 안정성 smoke 검증
make test-operational-smoke
```

**테스트 환경 격리 전략 (v1.0.0):**
- **Langfuse 격리**: 테스트 실행 시 `ENVIRONMENT=test` 설정을 통해 Langfuse SDK 로딩을 원천 차단합니다. 이를 통해 네트워크 연결 오류(`Connection refused`) 없이 깨끗한 테스트 로그를 유지할 수 있습니다.
- **Dependency Overrides**: FastAPI의 `dependency_overrides`를 활용하여 통합 테스트 시 인증이나 외부 서비스를 안전하게 모킹합니다.

**운영 안정성 검증:**
시스템은 다음 장애 시나리오에 대한 100% 회복력을 테스트로 증명했습니다:
- **LLM/DB 장애**: API 타임아웃 시 Fallback 체인 작동.
- **Circuit Breaker**: 연속 실패 시 장애 격리 및 자동 복구.
- **Race Condition**: 동시 세션 생성 시 데이터 일관성 유지 (asyncio.Lock).
- **Readiness 계약**: `/health`는 liveness, `/ready`는 startup/retrieval readiness를 검증합니다.
- **Quickstart 안전성**: 샘플 데이터 로더는 기본적으로 컬렉션을 삭제하지 않고 명시적 `--reset`에서만 초기화합니다.

---

## 4. 통합 테스트 환경 설정

### 4.1 Neo4j GraphRAG 테스트

Neo4j 통합 테스트는 실제 Neo4j 인스턴스가 필요합니다. 환경이 없으면 자동으로 Skip됩니다.

#### 로컬 환경 설정

```bash
# 1. Neo4j 컨테이너 실행
docker-compose -f docker-compose.neo4j.yml up -d

# 2. 환경 변수 설정 (선택 - 기본값 사용 가능)
export NEO4J_URI="bolt://localhost:7687"
export NEO4J_USER="neo4j"
export NEO4J_PASSWORD="testpassword123"

# 3. 통합 테스트 실행
ENVIRONMENT=test uv run pytest tests/integration/test_neo4j_integration.py -v
```

#### 환경 변수 참조

| 변수 | 기본값 | 설명 |
|------|--------|------|
| `NEO4J_URI` | `bolt://localhost:7687` | Bolt 프로토콜 연결 URI |
| `NEO4J_USER` | `neo4j` | 데이터베이스 사용자 |
| `NEO4J_PASSWORD` | `testpassword123` | 데이터베이스 비밀번호 |
| `NEO4J_DATABASE` | `neo4j` | 데이터베이스 이름 |

#### Docker Compose 구성

`docker-compose.neo4j.yml`은 다음 기능을 제공합니다:
- **Neo4j 5.27 Community Edition** 사용
- **APOC 플러그인** 포함 (그래프 알고리즘)
- **HTTP UI**: http://localhost:7474 (브라우저에서 그래프 시각화)
- **Bolt**: bolt://localhost:7687 (드라이버 연결)
- **자동 헬스체크** 및 영속 볼륨

#### CI 환경

GitHub Actions에서는 `services` 블록으로 Neo4j 컨테이너가 자동 시작됩니다.

```yaml
services:
  neo4j:
    image: neo4j:5.27-community
    env:
      NEO4J_AUTH: neo4j/testpassword123
    ports:
      - 7687:7687
```

#### 테스트 범위

Neo4j 통합 테스트는 다음을 검증합니다:
- **CRUD**: 엔티티/관계 추가, 조회, 검색
- **멀티홉 탐색**: 2-hop 이웃 탐색, 관계 타입 필터링
- **트랜잭션**: 커밋/롤백 동작
- **헬스체크**: 연결 상태 및 응답 시간

---

### 4.2 Multi Retrieval Provider 설정 (v1.0.5+)

본 프로젝트는 VectorStore 기반 6종 데이터베이스와 Grok 관리형 검색 모드를 지원합니다. `VECTOR_DB_PROVIDER` 환경변수로 사용할 검색 Provider를 선택합니다.

#### 지원 Provider 목록

| Provider | 하이브리드 검색 | 설치 의존성 | 용도 |
|----------|---------------|------------|------|
| **weaviate** (기본) | ✅ Dense + BM25 | `weaviate-client` | 셀프호스팅, 프로덕션 |
| **chroma** | ✅ Dense + BM25 | `chromadb` | 로컬 개발, 프로토타이핑 (BM25 엔진 필요) |
| **pinecone** | ✅ Dense + Sparse | `pinecone-client` | 서버리스 클라우드 |
| **qdrant** | ✅ Dense + Full-Text | `qdrant-client` | 고성능 셀프호스팅 |
| **pgvector** | ❌ Dense 전용 | `psycopg[binary]` | PostgreSQL 통합 |
| **mongodb** | ❌ Dense 전용 | `pymongo` | Atlas Vector Search |
| **grok** | ✅ 관리형 검색 | 기본 의존성 | xAI Grok Collections, VectorStore 불필요 |

#### 환경변수 설정

```bash
# Provider 선택 (필수)
export VECTOR_DB_PROVIDER="weaviate"  # weaviate | chroma | pinecone | qdrant | pgvector | mongodb | grok

# === Weaviate (기본) ===
export WEAVIATE_URL="http://localhost:8080"
export WEAVIATE_API_KEY=""  # 클라우드 사용 시

# === Chroma ===
export CHROMA_PERSIST_DIR="./chroma_data"

# === Pinecone ===
export PINECONE_API_KEY="your-api-key"
export PINECONE_ENVIRONMENT="us-east-1"
export PINECONE_INDEX_NAME="rag-index"

# === Qdrant ===
export QDRANT_URL="http://localhost:6333"
export QDRANT_API_KEY=""  # 클라우드 사용 시

# === pgvector ===
export PGVECTOR_CONNECTION_STRING="postgresql://user:pass@localhost:5432/vectors"
# 또는
export DATABASE_URL="postgresql://user:pass@localhost:5432/vectors"

# === MongoDB Atlas ===
export MONGODB_URI="mongodb+srv://user:pass@cluster.mongodb.net/"
export MONGODB_DATABASE="rag_db"
export MONGODB_COLLECTION="documents"

# === Grok Collections API ===
export VECTOR_DB_PROVIDER="grok"
export XAI_API_KEY="your-xai-api-key"
# app/config/features/grok.yaml에서 collection_ids를 설정합니다.
```

#### 선택적 의존성 설치

VectorStore 기반 Provider는 필요한 클라이언트만 설치할 수 있습니다. Grok 모드는 VectorStore를 만들지 않고 `RetrieverFactory` 경로로 직접 동작합니다:

```bash
# 개별 설치
uv add chromadb              # Chroma
uv add pinecone-client       # Pinecone
uv add qdrant-client         # Qdrant
uv add "psycopg[binary]"     # pgvector

# 그룹 설치 (pyproject.toml optional-dependencies)
uv sync --extra chroma
uv sync --extra pinecone
uv sync --extra qdrant
uv sync --extra pgvector
uv sync --extra all-vectordb  # 모든 벡터 DB
```

#### Docker Compose 예시 (로컬 개발)

```bash
# Weaviate
docker run -d -p 8080:8080 semitechnologies/weaviate:latest

# Qdrant
docker run -d -p 6333:6333 qdrant/qdrant:latest

# pgvector (PostgreSQL + 확장)
docker run -d -p 5432:5432 -e POSTGRES_PASSWORD=pass ankane/pgvector:latest
```

#### 코드에서 사용

```python
from app.core.di_container import Container

# DI 컨테이너가 VECTOR_DB_PROVIDER 환경변수를 읽어 자동 설정
container = Container()
retriever = container.retriever()  # 선택된 Retriever 인스턴스 반환

# 또는 Factory 직접 사용
from app.infrastructure.storage.vector.factory import VectorStoreFactory

store = VectorStoreFactory.create("pinecone", {
    "api_key": "...",
    "environment": "us-east-1",
    "index_name": "my-index"
})
```

`VECTOR_DB_PROVIDER=grok`는 `VectorStoreFactory`가 아니라 `RetrieverFactory`에 등록된 `GrokRetriever`를 사용합니다.

---

## 5. 코드 품질 관리

본 프로젝트는 **TODO/FIXME 주석 금지** 원칙을 지향합니다.
- 새로운 `TODO`를 작성할 때는 반드시 기한과 담당자를 명시하거나, 즉시 해결을 권장합니다.
- 정적 분석(`Ruff`, `Mypy`)은 CI/CD 파이프라인에서 필수로 통과해야 합니다.
