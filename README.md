<p align="center">
  <img src="assets/logo.svg" alt="OneRAG Logo" width="400"/>
</p>

<p align="center">
  <strong>5분 안에 시작하고, 설정 1줄로 컴포넌트를 교체하는 Production-ready RAG 백엔드</strong>
</p>

<p align="center">
  <a href="https://github.com/youngouk/OneRAG/actions/workflows/ci.yml"><img src="https://github.com/youngouk/OneRAG/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="https://opensource.org/licenses/MIT"><img src="https://img.shields.io/badge/License-MIT-blue.svg" alt="License: MIT"></a>
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/Python-3.11+-blue.svg" alt="Python 3.11+"></a>
  <a href="https://github.com/youngouk/OneRAG/stargazers"><img src="https://img.shields.io/github/stars/youngouk/OneRAG?style=social" alt="GitHub Stars"></a>
</p>

<p align="center">
  <strong>한국어</strong> | <a href="README_EN.md">English</a>
</p>

---

## TL;DR

```bash
git clone https://github.com/youngouk/OneRAG.git && cd OneRAG && uv sync
```

```bash
# 🐳 Docker 있으면 → Full API 서버 (Weaviate + FastAPI + Swagger UI)
cp quickstart/.env.quickstart .env   # GOOGLE_API_KEY만 설정
make start                            # → http://localhost:8000/docs

# 💻 Docker 없으면 → 로컬 CLI 챗봇 (설치만으로 바로 실행)
make easy-start                       # → 터미널에서 바로 대화
```

**Vector DB 바꾸고 싶다면?** `.env`에서 `VECTOR_DB_PROVIDER=pinecone` 한 줄 변경.
**LLM 바꾸고 싶다면?** `LLM_PROVIDER=openai` 한 줄 변경. 끝.

---

## 왜 OneRAG인가?

### 기존 RAG 개발의 문제점

| 상황 | 기존 방식 | OneRAG |
|------|----------|--------|
| Vector DB 변경 | 코드 전체 수정 + 테스트 반복 | `.env` 1줄 변경 |
| LLM 교체 | API 연동 코드 재작성 | `.env` 1줄 변경 |
| 기능 추가 (캐싱, 리랭킹 등) | 직접 구현 | `YAML` 설정으로 On/Off |
| PoC → Production | 처음부터 다시 구축 | 동일 코드베이스로 확장 |

### OneRAG가 제공하는 것

```
┌─────────────────────────────────────────────────────────────────┐
│                         OneRAG                                   │
├─────────────┬─────────────┬─────────────┬─────────────┬─────────┤
│  Vector DB  │     LLM     │  Reranker   │    Cache    │  Extra  │
├─────────────┼─────────────┼─────────────┼─────────────┼─────────┤
│ • Weaviate  │ • Gemini    │ • Jina      │ • Memory    │ • Graph │
│ • Chroma    │ • OpenAI    │ • Cohere    │ • Redis     │   RAG   │
│ • Pinecone  │ • Claude    │ • Google    │ • Semantic  │ • PII   │
│ • Qdrant    │ • OpenRouter│ • OpenAI    │             │   Mask  │
│ • pgvector  │             │ • Local     │             │ • Agent │
│ • MongoDB   │             │             │             │         │
└─────────────┴─────────────┴─────────────┴─────────────┴─────────┘
                    ↑ 모두 설정 파일로 교체 가능
```

---

## 시작하기

두 가지 방법 중 환경에 맞는 걸 선택하세요.

|  | Full API 서버 (`make start`) | CLI 챗봇 (`make easy-start`) |
|---|---|---|
| **Docker** | 필요 | 불필요 |
| **Vector DB** | Weaviate (하이브리드 검색) | ChromaDB (로컬 파일) |
| **인터페이스** | REST API + Swagger UI | 터미널 CLI |
| **LLM** | 4종 (Gemini, OpenAI, Claude, OpenRouter) | Gemini / OpenRouter |
| **용도** | 프로덕션, API 통합, 팀 개발 | 학습, 체험, 빠른 PoC |

### 방법 A: Full API 서버 (Docker)

```bash
git clone https://github.com/youngouk/OneRAG.git
cd OneRAG && uv sync

cp quickstart/.env.quickstart .env
# .env 파일에서 GOOGLE_API_KEY 설정
# (무료: https://aistudio.google.com/apikey)

make start
```

**끝!** [http://localhost:8000/docs](http://localhost:8000/docs)에서 바로 테스트할 수 있습니다.

```bash
make start-down  # 종료
```

### 방법 B: 로컬 CLI 챗봇 (Docker 불필요)

Docker 설치 없이 터미널에서 바로 RAG 검색 + AI 답변을 체험할 수 있습니다.

```bash
git clone https://github.com/youngouk/OneRAG.git
cd OneRAG && uv sync

make easy-start
```

샘플 데이터 25개가 자동 적재되고, 하이브리드 검색(Dense + BM25)이 바로 작동합니다.
AI 답변 생성을 사용하려면 API 키를 하나 설정하세요:

```bash
# 둘 중 하나만 설정하면 됩니다
export GOOGLE_API_KEY="발급받은키"       # 무료: https://aistudio.google.com/apikey
export OPENROUTER_API_KEY="발급받은키"   # https://openrouter.ai/keys
```

> **OneRAG가 처음이라면?** `make easy-start`로 시작해서 챗봇에게 직접 물어보세요.
> "하이브리드 검색이 뭐야?", "RAG 파이프라인이 어떻게 돼?" — 샘플 데이터에 답이 있습니다.

---

## 컴포넌트 교체하기

### Vector DB 바꾸기 (설정 1줄)

```bash
# .env 파일에서 한 줄만 변경
VECTOR_DB_PROVIDER=weaviate  # 또는 chroma, pinecone, qdrant, pgvector, mongodb
```

### LLM 바꾸기 (설정 1줄)

```bash
# .env 파일에서 한 줄만 변경
LLM_PROVIDER=google  # 또는 openai, anthropic, openrouter
```

### 리랭커 추가하기 (YAML 2줄)

```yaml
# app/config/features/reranking.yaml
reranking:
  approach: "cross-encoder"  # 또는 late-interaction, llm, local
  provider: "jina"           # 또는 cohere, google, openai, sentence-transformers
```

### 기능 On/Off (YAML 설정)

```yaml
# 캐싱 활성화
cache:
  enabled: true
  type: "redis"  # 또는 memory, semantic

# GraphRAG 활성화
graph_rag:
  enabled: true

# PII 마스킹 활성화
pii:
  enabled: true
```

---

## 조립 가능한 블록들

| 카테고리 | 선택지 | 변경 방법 |
|---------|-------|----------|
| **Vector DB** | Weaviate, Chroma, Pinecone, Qdrant, pgvector, MongoDB | 환경변수 1줄 |
| **LLM** | Google Gemini, OpenAI, Anthropic Claude, OpenRouter | 환경변수 1줄 |
| **리랭커** | Jina, Cohere, Google, OpenAI, OpenRouter, Local | YAML 2줄 |
| **캐시** | Memory, Redis, Semantic | YAML 1줄 |
| **쿼리 라우팅** | LLM 기반, Rule 기반 | YAML 1줄 |
| **한국어 검색** | 동의어, 불용어, 사용자사전 | YAML 설정 |
| **보안** | PII 탐지, 마스킹, 감사 로깅 | YAML 설정 |
| **GraphRAG** | 지식 그래프 기반 관계 추론 | YAML 1줄 |
| **Agent** | 도구 실행, MCP 프로토콜 | YAML 설정 |

---

## RAG 파이프라인

```
Query → Router → Expansion → Retriever → Cache → Reranker → Generator → PII Masking → Response
```

| 단계 | 기능 | 교체 가능 |
|-----|------|----------|
| 쿼리 라우팅 | 쿼리 유형 분류 | LLM/Rule 선택 |
| 쿼리 확장 | 동의어, 불용어 처리 | 사전 커스텀 |
| 검색 | 벡터/하이브리드 검색 | 6종 DB |
| 캐싱 | 응답 캐시 | 3종 캐시 |
| 재정렬 | 검색 결과 정렬 | 6종 리랭커 |
| 답변 생성 | LLM 응답 생성 | 4종 LLM |
| 후처리 | 개인정보 마스킹 | 정책 커스텀 |

---

## 단계별 구성 가이드

| 단계 | 구성 | 용도 |
|-----|------|-----|
| **Basic** | 벡터 검색 + LLM | 간단한 문서 Q&A |
| **Standard** | + 하이브리드 검색 + Reranker | 검색 품질이 중요한 서비스 **(권장)** |
| **Advanced** | + GraphRAG + Agent | 복잡한 관계 추론, 도구 실행 |

> Basic으로 시작해서, 필요할 때 블록을 추가하면 됩니다.

---

## 개발

```bash
make dev-reload   # 개발 서버 (자동 리로드)
make test         # 테스트 실행
make lint         # 린트 검사
make type-check   # 타입 체크
```

---

## 문서

- [상세 설정 가이드](docs/SETUP.md)
- [아키텍처 설명](docs/TECHNICAL_DEBT_ANALYSIS.md)
- [Streaming API 가이드](docs/streaming-api-guide.md)
- [WebSocket API 가이드](docs/websocket-api-guide.md)

---

## 라이선스

MIT License

---

<p align="center">
  <sub>이 프로젝트는 RAG Chat Service PM이 여러 프로젝트를 진행하며 구현해보고 싶었던 기능들을 모아 만들었습니다.<br>
  RAG를 처음 접하는 분들이 쉽게 PoC를 진행하고, 프로덕션까지 확장할 수 있도록 설계했습니다.</sub>
</p>

<p align="center">
  <a href="https://github.com/youngouk/OneRAG/issues">Report Bug</a> ·
  <a href="https://github.com/youngouk/OneRAG/issues">Request Feature</a> ·
  <a href="https://github.com/youngouk/OneRAG/discussions">Discussions</a>
</p>
