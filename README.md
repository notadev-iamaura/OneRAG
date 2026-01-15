# RAG_Standard (v1.0.7)

**한국어** | [English](README_EN.md)

[![CI](https://github.com/youngouk/RAG_Standard/actions/workflows/ci.yml/badge.svg)](https://github.com/youngouk/RAG_Standard/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)

범용 RAG(Retrieval-Augmented Generation) 챗봇 백엔드 시스템. FastAPI 기반의 고성능 비동기 웹 서비스로, 엔터프라이즈급 보안과 최신 GraphRAG 기술이 통합된 **2026년 기준 무결점(Clean Code) 표준 모델**입니다.

## 🏆 프로젝트 상태 (v1.0.7)

본 프로젝트는 단순한 구현을 넘어, 상용화 수준의 품질과 안정성을 확보했습니다.

- **테스트 무결성**: 총 **1,295개**의 단위/통합/장애 시나리오 테스트 100% 통과 (Pass)
- **코드 정리 완료**: 모든 deprecated 함수 제거, DI 패턴 완성, 80+ Provider 구조화
- **정적 분석 100%**: `Ruff` (Lint) 및 `Mypy` (Strict Type Check) 표준 완벽 준수
- **보안 완비**: 통합 PII 마스킹 시스템 및 모든 관리자 API 전역 인증(API Key) 강제화
- **Multi Vector DB**: 6종 벡터 DB 지원 (Weaviate, Chroma, Pinecone, Qdrant, pgvector, MongoDB)

## 🚀 기술적 강점

### 🧠 지능형 검색 및 관계 추론 (Hybrid GraphRAG)
- **Vector + Graph**: Weaviate의 벡터 검색과 지식 그래프의 관계 추론을 결합. 
- **지능형 노드 탐색**: v3.3부터 **지식 그래프 엔티티 벡터 검색**을 지원하여 오타, 줄임말, 의미적 유사어에도 강력하게 대응합니다.
- **ColBERT Reranking**: Jina ColBERT v2를 통한 토큰 레벨 정밀 재정렬로 최적의 컨텍스트를 선별합니다.

### 🛡️ 엔터프라이즈급 보안 및 안정성
- **Unified PII Processor**: 분산된 보안 로직을 하나로 통합한 Facade 구축. AI 기반 리뷰 시스템으로 민감 정보를 철저히 보호합니다.
- **Defense-in-Depth**: 미들웨어와 라우터 수준의 이중 인증 체계로 시스템 심장부인 관리자 기능을 격리했습니다.
- **Circuit Breaker**: 외부 LLM/DB 장애가 시스템 전체로 전파되는 것을 차단하는 방어적 설계를 갖췄습니다.

### ⚙️ 유연한 운영 및 확장성
- **YAML Dynamic Config**: 서비스 키워드, 라우팅 규칙 등을 실시간 수정 가능.
- **Clean Architecture**: `dependency-injector` 기반의 DI 패턴으로 특정 DB나 모델에 종속되지 않는 유연한 구조를 제공합니다.

## 🚀 Quickstart (3단계)

**처음 사용하시나요?** 3단계만 따라하면 RAG 시스템을 바로 체험할 수 있습니다.

### 사전 요구사항

```bash
# 필수 도구 확인
docker --version          # Docker 20.10+
docker compose version    # Docker Compose v2+
uv --version || curl -LsSf https://astral.sh/uv/install.sh | sh  # UV 패키지 매니저
```

### Step 1: 클론 및 설치

```bash
git clone https://github.com/youngouk/RAG_Standard.git
cd RAG_Standard
uv sync
```

### Step 2: 환경 설정

```bash
# Quickstart 환경 파일 복사
cp quickstart/.env.quickstart .env

# .env 파일 열어서 API 키 하나만 설정
# GOOGLE_API_KEY=your-key  (무료: https://aistudio.google.com/apikey)
```

### Step 3: 실행

```bash
make quickstart
```

완료! 🎉 http://localhost:8000/docs 에서 API를 테스트하세요.

```bash
# 종료
make quickstart-down
```

---

## 📖 상세 설정 가이드

Quickstart보다 세밀한 설정이 필요하다면 [docs/SETUP.md](docs/SETUP.md)를 참조하세요.

### 개발 환경 (로컬 실행)

```bash
# 1. Weaviate만 Docker로 실행
docker compose -f docker-compose.weaviate.yml up -d

# 2. 상세 환경 변수 설정
cp .env.example .env
# .env 파일 편집 (API 키, 인증 키 등)

# 3. 개발 서버 실행 (자동 리로드)
make dev-reload
```

### 테스트 실행

```bash
# 1,295개 테스트 실행
make test
```

## 📂 프로젝트 구조
- `app/api/`: REST API 및 인증 레이어 (v3.3 보안 강화)
- `app/modules/core/`: RAG 핵심 브레인 (Graph, Retrieval, Privacy, Generation)
- `app/core/`: 인터페이스 규격 및 중앙 의존성 관리 (DI)
- `docs/`: 정예화된 프로젝트 가이드 문서 (Ingestion, Domain Guide 등)

## 📜 라이선스
MIT License
