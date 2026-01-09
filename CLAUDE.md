# CLAUDE.md (v1.0.5 - Multi Vector DB 6종 지원)

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 프로젝트 개요
도메인 범용화된 완벽한 오픈소스 RAG 시스템. 2026년 기준 가장 진보된 RAG 기술들을 하나의 표준 파이프라인으로 통합한 엔터프라이즈급 솔루션입니다.

- **버전**: 1.0.5 (Multi Vector DB 6종 지원)
- **상태**: ✅ **기술 부채 Zero**, ✅ **1288개 테스트 통과**, ✅ **보안 완비**, ✅ **DI 패턴 완성**
- **주요 개선**: 6종 벡터 DB Factory 패턴 (Weaviate, Chroma, Pinecone, Qdrant, pgvector, MongoDB Atlas)

## 개발 명령어

```bash
# 초기 환경 설정 (spaCy 한국어 모델 포함 자동 설치)
uv sync

# 개발 서버 및 테스트
make dev-reload         # 자동 리로드 (uvicorn --reload)
make test               # 1288개 테스트 실행 (외부 로그 차단 격리 환경)
make test-cov           # 테스트 커버리지 리포트

# 코드 품질 관리 (CI/CD 통과 필수)
make lint               # ruff 린트 검사
make type-check         # mypy 엄격 모드 타입 체크
make lint-imports       # 아키텍처 계층 검증 (Import Linter)
```

## 아키텍처 핵심 (v1.0 고도화)

### 1. 지능형 검색 (Hybrid Retrieval)
- **Weaviate**: Dense(의미) + Sparse(BM25) 하이브리드.
- **GraphRAG**: `NetworkXGraphStore`에 벡터 검색 엔진 통합. "SAMSUNG"으로 "삼성전자" 노드 탐색 가능.
- **Reranker Chain**: ColBERT v2를 최우선 적용하여 토큰 레벨의 정밀한 컨텍스트 추출.

### 2. 완벽한 보안 (Unified Security)
- **PII Facade**: `PIIProcessor`가 단순 마스킹과 고도화된 AI 리뷰(`PIIReviewProcessor`)를 통합 관리.
- **Admin Auth**: `/api/admin` 하위의 모든 엔드포인트에 `X-API-Key` 인증 전역 적용.

### 3. 운영 유연성 (Dynamic Config)
- **YAML Routing**: `routing_rules_v2.yaml`에서 서비스 핵심 키워드를 관리. 코드 수정 없이 복합 쿼리 판단 로직 변경 가능.
- **환경별 설정**: `app/config/environments/`에 development, test, production 설정 분리. 환경 자동 감지 및 병합.
- **강화된 검증**: Pydantic 기반 설정 검증으로 타입 안전성 및 범위 검증 (temperature, timeout 등).

### 4. 에러 시스템 v2.0 (Bilingual)
- **ErrorCode 기반**: 모든 에러가 구조화된 에러 코드 사용 (예: `GEN-001`, `SEARCH-003`)
- **양언어 자동 전환**: `Accept-Language` 헤더 기반 한국어/영어 메시지 자동 선택
- **사용자 친화적 메시지**: 기술 에러를 해결 방법과 함께 제공
```python
# 새 에러 형식
raise GenerationError(ErrorCode.GENERATION_TIMEOUT, model="claude-sonnet-4-5")
# → 한국어: "AI 모델 응답이 지연되고 있습니다. 해결 방법: 1) 잠시 후 다시 시도..."
# → 영어: "AI model response is delayed. Solutions: 1) Please try again later..."
```

### 5. DI 컨테이너 (Dependency Injection)
- **80+ Provider**: Singleton(70개) + Factory(10개) 패턴 완비
- **7개 명시적 팩토리**: Agent, Evaluator, GraphRAG, Cache, MCP, Ingestion, VectorStore
- **Deprecated 함수 Zero**: `get_cost_tracker()`, `get_mongodb_client()` 완전 제거
- **테스트 용이성**: 모든 의존성 주입 가능, Mock 교체 용이

### 6. Multi-LLM Factory (v1.0.3)
- **4개 Provider 지원**: Google Gemini, OpenAI GPT, Anthropic Claude, OpenRouter
- **자동 Fallback**: 주 LLM 실패 시 설정된 순서대로 자동 전환
- **GPT5QueryExpansionEngine**: `llm_factory` 필수화로 OpenAI 직접 의존성 제거

### 7. Multi Vector DB (v1.0.5)
- **Factory 패턴**: `VectorStoreFactory`, `RetrieverFactory`로 벡터 DB 동적 선택
- **6종 벡터 DB 지원**: 환경변수 `VECTOR_DB_PROVIDER`로 선택
  | Provider | 하이브리드 검색 | 특징 |
  |----------|---------------|------|
  | **weaviate** (기본) | ✅ Dense + BM25 | 셀프호스팅, 하이브리드 내장 |
  | **chroma** | ❌ Dense 전용 | 경량, 로컬 개발용 |
  | **pinecone** | ✅ Dense + Sparse | 서버리스 클라우드 |
  | **qdrant** | ✅ Dense + Full-Text | 고성능 셀프호스팅 |
  | **pgvector** | ❌ Dense 전용 | PostgreSQL 확장 |
  | **mongodb** | ❌ Dense 전용 | Atlas Vector Search |
- **선택적 의존성**: 필요한 DB만 설치 (`uv sync --extra pinecone` 등)

### 8. Observability (v1.0.4)
- **실시간 메트릭**: `/api/admin/realtime-metrics` 엔드포인트
- **캐시 모니터링**: `cache_hit_rate`, `cache_hits`, `cache_misses`, `cache_saved_time_ms`
- **비용 추적**: `total_cost_usd`, `cost_per_hour`, `total_llm_tokens`

상세 분석: `docs/TECHNICAL_DEBT_ANALYSIS.md`

## 코드 컨벤션 및 규칙

- **Zero TODO**: 코드 내에 `TODO`, `FIXME` 주석을 남기지 않습니다. 모든 기술 부채는 즉시 해결합니다.
- **Test Isolation**: 테스트 시 `ENVIRONMENT=test`를 통해 Langfuse 등 외부 통신을 원천 차단합니다.
- **Type Safety**: 모든 신규 함수는 명확한 타입 힌트가 필수이며 `mypy`를 통과해야 합니다.

## 설정 관리 (v1.0.1 신규)

### 환경별 설정 파일
```
app/config/environments/
├── development.yaml  # 개발: debug=true, reload=true, 상세 로깅
├── test.yaml         # 테스트: 짧은 타임아웃, 일관성 우선
└── production.yaml   # 프로덕션: 워커 4개, 캐시 활성화, 폴백 전략
```

### 환경 감지 로직
- **다층 감지**: ENVIRONMENT, NODE_ENV, WEAVIATE_URL, FASTAPI_AUTH_KEY 종합 판단
- **보안 강화**: 단일 환경 변수 조작으로 프로덕션 우회 불가
- **자동 병합**: base.yaml + environments/{env}.yaml 자동 병합

### 설정 검증 (Pydantic)
- **타입 안전성**: temperature (0.0-2.0), max_tokens (1-128000), port (1-65535)
- **환경별 규칙**: 프로덕션에서 debug=true 차단
- **Graceful Degradation**: 검증 실패해도 시스템 동작 (경고 출력)

상세 문서: `docs/config_management_improvements.md`

## 시스템 완성도 (Current Score: 100/100)

| 항목 | 현황 | 비고 |
|------|------|------|
| **전체 테스트** | 1,288개 Pass | 단위/통합/안정성 테스트 완비 |
| **기술 부채** | 0건 | Deprecated 함수 완전 제거, DI 패턴 완성 |
| **보안 인증** | 완료 | 관리자 API 및 PII 보호 통합 |
| **GraphRAG 지능** | 완료 | 벡터 검색 기반 엔티티 탐색 |
| **설정 관리** | 완료 | 환경별 분리 및 검증 강화 |
| **에러 시스템** | 완료 | 양언어(한/영) 자동 전환 v2.0 |
| **DI 컨테이너** | 완료 | 80+ Provider, 8개 팩토리 (VectorStore, Retriever 추가) |
| **Multi-LLM** | 완료 | 4개 Provider 지원, 자동 Fallback |
| **Multi Vector DB** | 완료 | 6종 지원 (Weaviate, Chroma, Pinecone, Qdrant, pgvector, MongoDB) |
| **Observability** | 완료 | 실시간 캐시 히트율/LLM 비용 모니터링 |
| **문서화** | 완료 | API Reference, 개발 가이드 등 10개 문서 |

상세 기술부채 분석: `docs/TECHNICAL_DEBT_ANALYSIS.md`

---
**Claude Note**: 본 프로젝트는 이미 "완벽"한 상태이므로, 코드 수정 시 기존의 추상화 인터페이스(Protocol)와 DI 패턴을 엄격히 준수하십시오.
- **에러**: 반드시 `ErrorCode` 기반 새 형식 사용
- **LLM**: 반드시 `llm_factory`를 통해 호출
- **Vector DB**: 새 벡터 DB 추가 시 `VectorStoreFactory`에 등록
- **모니터링**: 새 메트릭 추가 시 `RealtimeMetrics` 모델 확장