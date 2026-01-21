# RAG_Standard

> 개발베이스가 아닌 RAG Chat Service PM이 여러 프로젝트를 진행하며 구현해보고자 했던 기능을 주로 바이브코딩의 도움을 받아 구현한 프로젝트입니다.
> RAG는 꽤나 재미있고 매력적인 프로젝트라고 생각하기에, 더 많은 사람들이 쉽게 접근하여 PoC를 진행하고 도입을 결정하기 쉽도록 만들었습니다.

**한국어** | [English](README_EN.md)

[![CI](https://github.com/youngouk/RAG_Standard/actions/workflows/ci.yml/badge.svg)](https://github.com/youngouk/RAG_Standard/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)

## 이 프로젝트는

RAG(Retrieval-Augmented Generation) 시스템을 **필요한 만큼만** 구축할 수 있는 모듈형 백엔드입니다.

DI(Dependency Injection) 구조로 설계되어, 단순한 벡터 검색부터 GraphRAG까지 프로젝트 규모에 맞게 기능을 조합할 수 있습니다.

## 누구를 위한 프로젝트인가

- RAG 시스템을 **직접 구축**하고 싶은 개발자
- 특정 벡터 DB나 LLM에 **종속되지 않는** 유연한 구조가 필요한 팀
- 프로토타입부터 프로덕션까지 **점진적으로 확장**하고 싶은 프로젝트

## 기능 선택 가이드

| 단계 | 구성 | 용도 |
|------|------|------|
| **Basic** | 벡터 검색 + LLM | 간단한 문서 Q&A |
| **Standard** | 하이브리드 검색 (Dense + BM25) + Reranker | 검색 품질이 중요한 서비스 (권장) |
| **Advanced** | + GraphRAG + Multi-Query | 복잡한 관계 추론이 필요한 경우 |

모든 컴포넌트는 인터페이스(Protocol) 기반이라, 필요한 것만 활성화하거나 직접 구현체를 교체할 수 있습니다.

## 지원 현황

**벡터 DB** (6종): Weaviate, Chroma, Pinecone, Qdrant, pgvector, MongoDB

**LLM** (4종): Google Gemini, OpenAI, Anthropic Claude, OpenRouter

**Reranker** (6종): Jina, Cohere, Google, OpenAI, OpenRouter, Local(sentence-transformers)

## Quickstart

```bash
# 1. 클론 및 설치
git clone https://github.com/youngouk/RAG_Standard.git
cd RAG_Standard && uv sync

# 2. 환경 설정
cp quickstart/.env.quickstart .env
# .env에서 GOOGLE_API_KEY 설정 (무료: https://aistudio.google.com/apikey)

# 3. 실행
make quickstart
```

http://localhost:8000/docs 에서 API 테스트 가능

```bash
# 종료
make quickstart-down
```

## 개발

```bash
make dev-reload    # 개발 서버 (자동 리로드)
make test          # 테스트 실행
make lint          # 린트 검사
make type-check    # 타입 체크
```

## 문서

- [상세 설정 가이드](docs/SETUP.md)
- [아키텍처 설명](docs/TECHNICAL_DEBT_ANALYSIS.md)
- [Streaming API 가이드](docs/streaming-api-guide.md)
- [WebSocket API 가이드](docs/websocket-api-guide.md)

## 라이선스

MIT License
