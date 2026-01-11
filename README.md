# RAG_Standard (v1.0.7 - 기술부채 Zero 완성)

**한국어** | [English](README_EN.md)

[![CI](https://github.com/youngouk/RAG_Standard/actions/workflows/ci.yml/badge.svg)](https://github.com/youngouk/RAG_Standard/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)

범용 RAG(Retrieval-Augmented Generation) 챗봇 백엔드 시스템. FastAPI 기반의 고성능 비동기 웹 서비스로, 엔터프라이즈급 보안과 최신 GraphRAG 기술이 통합된 **2026년 기준 무결점(Clean Code) 표준 모델**입니다.

## 🏆 프로젝트 상태: "기술부채 Zero (v1.0.7)"

본 프로젝트는 단순한 구현을 넘어, 상용화 수준의 품질과 안정성을 확보한 **기술부채 Zero** 상태를 달성했습니다.

- **테스트 무결성**: 총 **1,295개**의 단위/통합/장애 시나리오 테스트 100% 통과 (Pass)
- **기술 부채 Zero**: 모든 deprecated 함수 제거, DI 패턴 완성, 80+ Provider 구조화
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

## 🏃 빠른 시작 (5분)

### 사전 요구사항

시작하기 전에 다음 도구들이 설치되어 있는지 확인하세요.

```bash
# Python 3.11 이상
python --version  # Python 3.11.x 이상 필요

# Docker & Docker Compose
docker --version          # Docker 20.10 이상
docker compose version    # Docker Compose v2 이상

# UV 패키지 매니저 (없으면 설치)
uv --version || pip install uv
```

### Step 1: 프로젝트 클론 및 의존성 설치 (2분)

```bash
git clone https://github.com/youngouk/RAG_Standard.git
cd RAG_Standard

# 모든 의존성 자동 설치 (spaCy 한국어 모델 포함)
uv sync
```

### Step 2: 환경 변수 설정 (1분)

```bash
# 환경 변수 템플릿 복사
cp .env.example .env
```

`.env` 파일을 열어 **최소 2개 항목**을 설정하세요.

```bash
# 필수 1: API 인증 키 (아무 문자열이나 32자 이상)
FASTAPI_AUTH_KEY=your_secure_random_key_here_at_least_32_chars

# 필수 2: LLM API 키 (아래 중 1개 선택)
GOOGLE_API_KEY=AIza...    # 권장 - 무료 티어 제공: https://makersuite.google.com/app/apikey
# 또는 OPENAI_API_KEY=sk-...
# 또는 ANTHROPIC_API_KEY=sk-ant-...
```

### Step 3: 인프라 실행 (1분)

```bash
# Weaviate 벡터 데이터베이스 실행
docker compose -f docker-compose.weaviate.yml up -d

# 실행 확인 (healthy 상태까지 약 30초 소요)
docker compose -f docker-compose.weaviate.yml ps
```

### Step 4: 서버 실행

```bash
# 개발 서버 (자동 리로드)
make dev-reload
```

### Step 5: 동작 검증

서버가 정상 실행되면 아래 URL로 접속하세요.

| 항목 | URL | 설명 |
|------|-----|------|
| **API 문서** | http://localhost:8000/docs | Swagger UI - 모든 API 테스트 가능 |
| **헬스 체크** | http://localhost:8000/health | 서버 상태 확인 |

### 테스트 실행 (선택)

```bash
# 1,295개 테스트 실행 (격리 환경에서 실행)
ENVIRONMENT=test make test
```

> 📖 **상세 설정 가이드**: [docs/SETUP.md](docs/SETUP.md) 참조

## 📂 프로젝트 구조
- `app/api/`: REST API 및 인증 레이어 (v3.3 보안 강화)
- `app/modules/core/`: RAG 핵심 브레인 (Graph, Retrieval, Privacy, Generation)
- `app/core/`: 인터페이스 규격 및 중앙 의존성 관리 (DI)
- `docs/`: 정예화된 프로젝트 가이드 문서 (Ingestion, Domain Guide 등)

## 📜 라이선스
MIT License
