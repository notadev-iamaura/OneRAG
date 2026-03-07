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

# 🔒 API 키 없이 → Ollama 로컬 LLM으로 완전 오프라인 동작
ollama pull llama3.2 && make easy-start
```

---

## 왜 OneRAG인가?

**하나의 코드베이스로 모든 RAG 컴포넌트를 조립합니다.**

- **설정 1줄로 교체** — Vector DB, LLM, Reranker, Cache 모두 `.env` 또는 YAML 한 줄로 변경
- **API 키 없이 시작** — Ollama 로컬 LLM으로 인터넷 없이도 완전 동작
- **OpenAI SDK 호환** — 기존 OpenAI 코드 그대로 OneRAG에 연결 (`/v1/chat/completions`)
- **2,100+ 테스트** — 프로덕션 검증된 안정성, CI/CD 완비
- **PoC에서 프로덕션까지** — 동일한 코드베이스로 확장, 재구축 불필요

### 아키텍처 한눈에 보기

<p align="center">
  <img src="assets/architecture.svg" alt="OneRAG Architecture" width="100%"/>
</p>

---

## 시작하기

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
# 셋 중 하나만 설정하면 됩니다
export GOOGLE_API_KEY="발급받은키"       # 무료: https://aistudio.google.com/apikey
export OPENROUTER_API_KEY="발급받은키"   # https://openrouter.ai/keys
ollama pull llama3.2                     # API 키 없이 로컬 LLM 사용
```

> **OneRAG가 처음이라면?** `make easy-start`로 시작해서 챗봇에게 직접 물어보세요.
> "하이브리드 검색이 뭐야?", "RAG 파이프라인이 어떻게 돼?" — 샘플 데이터에 답이 있습니다.

---

## OpenAI 호환 API

기존 OpenAI SDK 코드를 수정 없이 OneRAG에 연결할 수 있습니다.

```python
from openai import OpenAI

client = OpenAI(base_url="http://localhost:8000/v1", api_key="not-needed")

# RAG 검색 + AI 답변 생성
response = client.chat.completions.create(
    model="gemini",  # 또는 ollama/llama3.2, openrouter/google/gemini-2.0-flash
    messages=[{"role": "user", "content": "RAG란 무엇인가요?"}],
)
print(response.choices[0].message.content)
```

**지원 엔드포인트:**
- `POST /v1/chat/completions` — 채팅 완료 (스트리밍 지원)
- `GET /v1/models` — 사용 가능한 모델 목록

**모델 선택:**
| 형식 | 예시 | 설명 |
|------|------|------|
| `provider` | `gemini`, `ollama`, `claude` | 기본 모델 사용 |
| `provider/model` | `ollama/qwen2.5:3b` | 특정 모델 지정 |
| `openrouter/vendor/model` | `openrouter/google/gemini-2.0-flash` | OpenRouter 경유 |

LangChain, Cursor, Open WebUI 등 OpenAI SDK를 사용하는 모든 도구와 바로 연결됩니다.

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
LLM_PROVIDER=google  # 또는 openai, anthropic, openrouter, ollama
```

### 리랭커 추가하기 (YAML 2줄)

```yaml
# app/config/features/reranking.yaml
reranking:
  approach: "cross-encoder"  # 또는 late-interaction, llm, local
  provider: "jina"           # 또는 cohere, google, openai, openrouter, sentence-transformers
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
| **LLM** | Google Gemini, OpenAI, Anthropic Claude, OpenRouter, Ollama | 환경변수 1줄 |
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
| 답변 생성 | LLM 응답 생성 | 5종 LLM |
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

## 프론트엔드 UI

별도의 React 기반 웹 UI가 포함되어 있습니다. 백엔드 API 서버와 함께 실행하면 브라우저에서 전체 RAG 시스템을 체험할 수 있습니다.

**주요 기능:**
- WebSocket 실시간 스트리밍 채팅 (RAG 검색 결과 + AI 답변)
- 드래그앤드롭 문서 업로드 (PDF, Word, Excel, Markdown 등)
- 문서 관리 — 검색, 정렬, 일괄 삭제, 상세 정보 조회
- 다크 모드, 모바일 반응형 레이아웃
- Feature Flag 기반 모듈 활성화/비활성화

```bash
# 백엔드 실행 중인 상태에서
make frontend-dev    # → http://localhost:5173
```

> 프론트엔드 + 백엔드 + Weaviate 동시 실행: `make start-full`

---

## 다국어 지원

easy-start CLI 챗봇은 4개 언어를 지원합니다.

```bash
make easy-start LANG=en    # English
make easy-start LANG=ja    # 日本語
make easy-start LANG=zh    # 中文
make easy-start            # 한국어 (기본)
```

각 언어별로 UI 텍스트, 시스템 프롬프트, 샘플 데이터가 모두 현지화되어 있습니다.

---

## 개발

```bash
make dev-reload   # 개발 서버 (자동 리로드)
make test         # 테스트 실행 (2,100+)
make lint         # 린트 검사
make type-check   # 타입 체크
```

---

## 문서

- [상세 설정 가이드](docs/SETUP.md)
- [아키텍처 설명](docs/ARCHITECTURE.md)
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
