# OneRAG 튜토리얼: 처음부터 프로덕션까지

이 튜토리얼은 OneRAG를 처음 사용하는 분들을 위한 단계별 가이드입니다.

---

## 목차

1. [환경 설정](#1-환경-설정)
2. [첫 번째 RAG 실행하기](#2-첫-번째-rag-실행하기)
3. [검색 Provider 바꿔보기](#3-검색-provider-바꿔보기)
4. [LLM 바꿔보기](#4-llm-바꿔보기)
5. [리랭커 추가하기](#5-리랭커-추가하기)
6. [캐싱 활성화하기](#6-캐싱-활성화하기)
7. [한국어 검색 최적화](#7-한국어-검색-최적화)
8. [프로덕션 배포](#8-프로덕션-배포)

---

## 1. 환경 설정

### 필수 조건

- Python 3.11 이상
- Docker & Docker Compose
- Git

### 설치

```bash
# 1. 레포지토리 클론
git clone https://github.com/youngouk/OneRAG.git
cd OneRAG

# 2. 의존성 설치 (uv 사용)
uv sync

# 3. 환경 변수 설정
cp quickstart/.env.quickstart .env
```

### API 키 설정

`.env` 파일을 열고 필요한 API 키를 설정합니다.

**최소 설정 (무료로 시작):**
```bash
# Google AI Studio에서 무료로 발급: https://aistudio.google.com/apikey
GOOGLE_API_KEY=your_google_api_key_here
```

**더 많은 옵션:**
```bash
# OpenAI
OPENAI_API_KEY=your_openai_key

# Anthropic
ANTHROPIC_API_KEY=your_anthropic_key

# Pinecone (옵션)
PINECONE_API_KEY=your_pinecone_key
PINECONE_ENVIRONMENT=your_environment
```

---

## 2. 첫 번째 RAG 실행하기

### 바로 시작하기

```bash
make start
```

이 명령어 하나로:
- Weaviate (Vector DB) 컨테이너 시작
- OneRAG 서버 시작
- 샘플 문서 인덱싱

### API 테스트

브라우저에서 http://localhost:8000/docs 접속

또는 curl로 테스트:

```bash
# 문서 업로드
curl -X POST "http://localhost:8000/api/v1/documents/upload" \
  -H "Content-Type: multipart/form-data" \
  -F "file=@your_document.pdf"

# 질문하기
curl -X POST "http://localhost:8000/api/v1/chat" \
  -H "Content-Type: application/json" \
  -d '{"query": "문서 내용에 대해 알려줘"}'
```

### 종료

```bash
make start-down
```

---

## 3. 검색 Provider 바꿔보기

### 현재 지원하는 Provider

| Provider | 환경 변수 값 | 특징 |
|----------|-------------|------|
| Weaviate | `weaviate` | 기본값, 하이브리드 검색 지원 |
| Chroma | `chroma` | 로컬 개발에 적합, 설치 간편 |
| Pinecone | `pinecone` | 관리형 서비스, 스케일링 용이 |
| Qdrant | `qdrant` | 빠른 성능, 필터링 강력 |
| pgvector | `pgvector` | PostgreSQL 기반, SQL 친화적 |
| MongoDB | `mongodb` | 문서 DB와 벡터 검색 통합 |
| Grok Collections | `grok` | xAI 관리형 검색, VectorStore 불필요 |

### 변경 방법

`.env` 파일에서 한 줄만 수정:

```bash
# Before
VECTOR_DB_PROVIDER=weaviate

# After (Pinecone으로 변경)
VECTOR_DB_PROVIDER=pinecone
PINECONE_API_KEY=your_key
PINECONE_ENVIRONMENT=your_env
```

Grok을 사용할 때는 `VECTOR_DB_PROVIDER=grok`, `XAI_API_KEY`, `app/config/features/grok.yaml`의 `collection_ids`가 필요합니다.

서버 재시작하면 끝!

```bash
make dev-reload
```

---

## 4. LLM 바꿔보기

### 현재 지원하는 LLM

| Provider | 환경 변수 값 | 모델 예시 |
|----------|-------------|----------|
| Google | `google` | gemini-pro, gemini-1.5-pro |
| OpenAI | `openai` | gpt-4, gpt-3.5-turbo |
| Anthropic | `anthropic` | claude-3-opus, claude-3-sonnet |
| OpenRouter | `openrouter` | 다양한 모델 접근 가능 |

### 변경 방법

```bash
# Before
LLM_PROVIDER=google

# After (OpenAI로 변경)
LLM_PROVIDER=openai
OPENAI_API_KEY=your_key
```

### 모델 지정

```bash
# 특정 모델 사용
LLM_MODEL=gpt-4-turbo
```

---

## 5. 리랭커 추가하기

리랭커는 검색 결과의 품질을 높여줍니다.

### 설정 파일 수정

`app/config/features/reranking.yaml`:

```yaml
reranking:
  enabled: true
  approach: "cross-encoder"  # 또는 late-interaction, llm, local
  provider: "jina"           # 또는 cohere, google, openai
  top_k: 5                   # 리랭킹 후 반환할 결과 수
```

### Provider별 설정

**Jina (권장 - 무료 티어 있음):**
```yaml
provider: "jina"
model: "jina-reranker-v2-base-multilingual"
```

**Cohere:**
```yaml
provider: "cohere"
model: "rerank-multilingual-v3.0"
```

**로컬 모델:**
```yaml
approach: "local"
model: "BAAI/bge-reranker-base"
```

---

## 6. 캐싱 활성화하기

반복되는 질문에 대한 응답 속도를 높입니다.

### 설정 파일 수정

`app/config/features/cache.yaml`:

```yaml
cache:
  enabled: true
  type: "memory"  # 또는 redis, semantic
  ttl: 3600       # 캐시 유효 시간 (초)
```

### 캐시 타입별 특징

| 타입 | 특징 | 사용 시점 |
|------|-----|----------|
| `memory` | 서버 재시작 시 초기화 | 개발/테스트 |
| `redis` | 영구 저장, 분산 환경 지원 | 프로덕션 |
| `semantic` | 유사한 질문도 캐시 히트 | 고급 사용 |

### Redis 사용 시

```yaml
cache:
  enabled: true
  type: "redis"
  redis_url: "redis://localhost:6379"
```

```bash
# Redis 컨테이너 시작
docker run -d -p 6379:6379 redis:alpine
```

---

## 7. 한국어 검색 최적화

OneRAG는 한국어 NLP를 내장하고 있습니다.

### 동의어 사전 설정

`app/config/korean/synonyms.yaml`:

```yaml
synonyms:
  - ["인공지능", "AI", "에이아이"]
  - ["머신러닝", "기계학습", "ML"]
  - ["딥러닝", "심층학습", "DL"]
```

### 불용어 설정

`app/config/korean/stopwords.yaml`:

```yaml
stopwords:
  - "그리고"
  - "하지만"
  - "그래서"
  - "즉"
```

### 사용자 사전 설정

특수 용어나 고유명사 등록:

`app/config/korean/user_dict.yaml`:

```yaml
user_dict:
  - word: "OneRAG"
    pos: "NNP"  # 고유명사
  - word: "벡터DB"
    pos: "NNG"  # 일반명사
```

---

## 8. 프로덕션 배포

### Docker Compose로 배포

```bash
# 프로덕션 설정으로 시작
docker-compose up -d
```

### 환경 변수 (프로덕션)

```bash
# .env.production
NODE_ENV=production
LOG_LEVEL=info

# 보안
API_KEY_REQUIRED=true
ALLOWED_ORIGINS=https://yourdomain.com

# 모니터링
LANGFUSE_PUBLIC_KEY=your_key
LANGFUSE_SECRET_KEY=your_secret
```

### 헬스 체크

```bash
curl http://localhost:8000/health
# {"status": "healthy"}
```

### 모니터링 (Langfuse)

Langfuse를 통해 RAG 파이프라인을 모니터링할 수 있습니다.

```bash
# Langfuse 컨테이너 시작
docker-compose -f docker-compose.langfuse.yml up -d
```

---

## 다음 단계

- [상세 설정 가이드](SETUP.md)
- [API 레퍼런스](http://localhost:8000/docs)
- [아키텍처 문서](TECHNICAL_DEBT_ANALYSIS.md)
- [GitHub Issues](https://github.com/youngouk/OneRAG/issues)

---

## 문제 해결

### "Vector DB 연결 실패"

```bash
# Docker 컨테이너 상태 확인
docker ps

# 로그 확인
docker logs onerag-weaviate-1
```

### "API 키 오류"

```bash
# .env 파일 확인
awk -F= '/API_KEY/ { print $1"=<redacted>" }' .env
```

### "메모리 부족"

Docker 설정에서 메모리 할당량을 늘려주세요. (최소 4GB 권장)

---

질문이나 문제가 있으면 [GitHub Issues](https://github.com/youngouk/OneRAG/issues)에 남겨주세요!
