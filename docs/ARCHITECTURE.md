# 시스템 아키텍처 (Architecture) - v1.0.0

Blank RAG 시스템은 고성능, 확장성, 프로덕션급 보안을 지향하는 **Advanced RAG 프레임워크**입니다.

---

## 1. 기술 스택 (Tech Stack)

- **Backend**: Python 3.11+, FastAPI (Async)
- **DI Container**: `dependency-injector` (중앙 집중식 의존성 및 생명주기 관리)
- **Vector DB**: **Weaviate** (Primary, `kagome_kr` 하이브리드 검색)
- **Graph DB**: NetworkX (In-memory, **지능형 벡터 검색 지원**) / Neo4j (준비 중)
- **Metadata Store**: PostgreSQL (프롬프트 관리 및 감사 로그 저장)
- **LLM**: Google Gemini 2.5 Pro (Primary), GPT-4o, Claude 3.5 지원
- **Reranking**: Jina ColBERT v2 (토큰 레벨 정밀 재정렬)
- **Observability**: LangSmith & Langfuse (테스트 환경 완전 격리 지원)

---

## 2. 핵심 아키텍처 레이어

### 2.1 지능형 검색 레이어 (Advanced Retrieval)
- **Hybrid Search**: Weaviate를 통한 Dense + Sparse 하이브리드 검색.
- **GraphRAG v3.3**: 단순 이름 매칭을 넘어 **엔티티 벡터 유사도 검색**을 통합. 오타나 의미적 유사어로도 지식 그래프 탐색 가능.
- **Semantic Caching**: 쿼리 임베딩 유사도를 분석하여 캐시된 고품질 답변을 즉시 반환.

### 2.2 통합 보안 레이어 (Unified Security)
- **PII Processor Facade**: 분산되어 있던 개인정보 마스킹 로직을 하나로 통합. AI 기반의 NER(개체명 인식)과 정책 엔진을 결합하여 중요 문서를 정밀 검토.
- **Admin Defense-in-Depth**: 미들웨어와 라우터 수준의 이중 API Key 인증을 통해 모든 관리자 API를 완벽히 보호.

### 2.3 자가 수정 레이어 (Self-Correction)
- **Self-RAG**: 생성된 답변의 관련성(Relevance)과 근거(Groundedness)를 스스로 평가하고, 품질 미달 시 자동으로 재검색 및 재생성 수행.

---

## 3. 데이터 흐름 (Data Flow)

### 3.1 쿼리 처리 파이프라인
1.  **Rule-Based Routing**: YAML 기반 동적 키워드 매칭을 통해 Direct Answer 또는 RAG 여부 결정.
2.  **Semantic Search**: 벡터 + 그래프 하이브리드 검색 수행.
3.  **Refinement**: RRF 병합 후 ColBERT로 최상위 결과 추출.
4.  **Verification**: Self-RAG 품질 필터를 통과한 답변만 최종 반환.

---

## 4. 상세 모듈 구조

- `app/api`: FastAPI 라우터 및 서비스 레이어
- `app/core`: 인터페이스 정의 및 DI 컨테이너 (`AppContainer`)
- `app/infrastructure`: 인프라 어댑터 (Vector/Graph/Metadata Storage)
- `app/modules/core`: RAG 핵심 브레인 (Retrieval, Generation, Self-RAG, PII)
- `app/modules/ingestion`: 데이터 적재 파이프라인
- `app/lib`: 공통 유틸리티 (Auth, Logger, LLM Client)
