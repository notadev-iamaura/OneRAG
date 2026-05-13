# OneRAG 개선 우선순위 로드맵

**작성일**: 2026-01-11
**상태 검토**: 2026-05-13
**기준**: 시급도(Urgency) × 난이도(Difficulty) × 수정 임팩트(Impact)
**평가 방법론**: ROI 기반 우선순위 매트릭스

---

> 이 문서는 2026-01 기준 우선순위 산정 기록입니다. 현재 운영 상태와 완료된 release-readiness 항목은 `docs/STATUS.md`와 `docs/release-readiness/2026-05-03-release-readiness-priorities.md`를 우선합니다.

## 현재 반영 상태 (2026-05-13)

- P0 오픈소스 기본 문서와 PR 템플릿은 반영됨.
- 통합 Docker/quickstart 경로와 frontend/backend CI gate는 반영됨.
- `make test-operational-smoke`가 readiness, compose, quickstart 안전성을 검증함.
- E2E/nightly, strict dependency audit, 접근성 회귀 확대는 후속 품질 과제로 남아 있음.

## 📊 우선순위 평가 기준

각 문제에 대해 다음 3가지 차원을 1-5점으로 평가합니다:

- **시급도 (U)**: 얼마나 빨리 해결해야 하는가? (5=즉시, 1=나중에)
- **난이도 (D)**: 구현이 얼마나 어려운가? (5=매우 어려움, 1=쉬움)
- **임팩트 (I)**: 해결 시 얻는 가치 (5=매우 큼, 1=작음)

**우선순위 점수 = (U × 2 + I × 2 - D) ÷ 5**

점수가 높을수록 ROI가 높아 먼저 처리해야 합니다.

---

## 🎯 우선순위 그룹 분류

### P0: Critical Quick Wins (즉시 착수, 1-2주)
**특징**: 시급도 높음 + 난이도 낮음 + 임팩트 높음
**목표**: 오픈소스 프로젝트 최소 생존 조건 충족

| # | 문제 | U | D | I | 점수 | 예상 공수 | 담당 |
|---|------|---|---|---|------|-----------|------|
| **1** | CONTRIBUTING.md 부재 | 5 | 1 | 5 | 3.8 | 4시간 | 문서화 |
| **2** | Issue/PR 템플릿 부재 | 5 | 1 | 4 | 3.4 | 2시간 | DevOps |
| **3** | 실사용 튜토리얼 부족 | 5 | 2 | 5 | 3.2 | 16시간 | 문서화 |
| **4** | 통합 docker-compose.yml 부재 | 4 | 1 | 4 | 3.0 | 4시간 | DevOps |
| **5** | 버전 체계 혼란 (v1.x vs v3.x) | 4 | 1 | 3 | 2.6 | 2시간 | 프로젝트 관리 |
| **6** | "기술부채 Zero" 마케팅 문구 제거 | 5 | 1 | 3 | 2.6 | 1시간 | 마케팅 |

**총 예상 공수**: 29시간 (약 1주)

---

### P1: High Priority (1-2개월)
**특징**: 시급도 또는 임팩트가 매우 높음
**목표**: 프로젝트 정체성 확립 및 사용성 개선

| # | 문제 | U | D | I | 점수 | 예상 공수 | 담당 |
|---|------|---|---|---|------|-----------|------|
| **7** | 포지셔닝 모호 ("범용" → "한국어 엔터프라이즈") | 5 | 2 | 5 | 3.2 | 24시간 | 전략 |
| **8** | API 사용 예제 부족 (10개 추가) | 4 | 2 | 5 | 2.8 | 40시간 | 문서화 |
| **9** | 통합 테스트 비율 증가 (15% → 30%) | 4 | 4 | 5 | 2.2 | 80시간 | QA |
| **10** | 트러블슈팅 가이드 작성 | 4 | 2 | 4 | 2.4 | 16시간 | 문서화 |
| **11** | 성능 벤치마크 결과 공개 | 3 | 3 | 5 | 2.0 | 40시간 | 엔지니어링 |
| **12** | 핵심 사용 사례 3개 문서화 | 4 | 2 | 5 | 2.8 | 24시간 | PM |

**총 예상 공수**: 224시간 (약 6주, 1명 기준)

---

### P2: Medium Priority - Strategic (3-6개월)
**특징**: 장기 경쟁력 확보를 위한 구조적 개선
**목표**: 기술 부채 실질적 감소 및 유지보수성 향상

| # | 문제 | U | D | I | 점수 | 예상 공수 | 담당 |
|---|------|---|---|---|------|-----------|------|
| **13** | DI Container 리팩토링 (2,267 LOC 분해) | 3 | 5 | 4 | 1.4 | 120시간 | 아키텍트 |
| **14** | 40개 YAML 설정 통합/단순화 | 3 | 4 | 3 | 1.2 | 60시간 | 아키텍트 |
| **15** | 타입 안전성 100% (Mypy strict 전체 적용) | 3 | 4 | 4 | 1.4 | 80시간 | 엔지니어링 |
| **16** | 복잡도 감소 (36개 함수 복잡도 >10) | 2 | 4 | 3 | 0.8 | 100시간 | 리팩토링 |
| **17** | 벡터 DB 6개 → 2-3개로 축소 | 3 | 3 | 4 | 1.6 | 40시간 | 아키텍트 |
| **18** | E2E 테스트 활성화 | 3 | 4 | 4 | 1.4 | 60시간 | QA |
| **19** | 비용 최적화 가이드 (LLM API) | 3 | 2 | 4 | 2.0 | 24시간 | FinOps |

**총 예상 공수**: 484시간 (약 12주, 1명 기준)

---

### P3: Low Priority - Long Term (6-12개월)
**특징**: 비즈니스 모델 및 커뮤니티 확장
**목표**: 지속 가능한 오픈소스 생태계 구축

| # | 문제 | U | D | I | 점수 | 예상 공수 | 담당 |
|---|------|---|---|---|------|-----------|------|
| **20** | 커뮤니티 확보 (100+ GitHub Stars) | 2 | 4 | 5 | 1.6 | 200시간 | 커뮤니티 매니저 |
| **21** | 엔터프라이즈 유료 지원 도입 | 2 | 5 | 5 | 1.2 | 400시간 | 비즈니스 |
| **22** | Managed RAG 호스팅 서비스 | 1 | 5 | 5 | 1.0 | 800시간 | 플랫폼 팀 |
| **23** | 다국어 지원 (영어/일본어) | 1 | 4 | 3 | 0.6 | 160시간 | i18n |
| **24** | Prometheus/Grafana 대시보드 | 2 | 3 | 3 | 1.2 | 40시간 | SRE |

**총 예상 공수**: 1,600시간 (약 10개월, 1명 기준)

---

## 🚀 실행 계획

### Phase 1: 생존 (Week 1-2) - P0 실행
**목표**: 오픈소스 프로젝트로서 최소 자격 갖추기

#### Sprint 1-1: 커뮤니티 기반 구축 (Week 1)
```bash
□ [#1] CONTRIBUTING.md 작성
  - 개발 환경 설정 가이드
  - 브랜치 전략 (main, develop, feature/*)
  - 커밋 메시지 컨벤션
  - 코드 리뷰 프로세스
  - 테스트 요구사항

□ [#2] GitHub 템플릿 추가
  - .github/ISSUE_TEMPLATE/bug_report.md
  - .github/ISSUE_TEMPLATE/feature_request.md
  - .github/PULL_REQUEST_TEMPLATE.md
  - .github/CODE_OF_CONDUCT.md

□ [#6] README 마케팅 문구 수정
  - "기술부채 Zero" → "엔터프라이즈급 코드 품질"
  - "무결점 표준 모델" → "프로덕션 레디 RAG 시스템"
  - 과장된 표현 제거, 객관적 사실 기반 설명
```

#### Sprint 1-2: 사용성 개선 (Week 2)
```bash
□ [#3] 실사용 튜토리얼 3개 작성
  - Tutorial 1: "5분 만에 첫 RAG 챗봇 만들기"
  - Tutorial 2: "PDF 문서 업로드 및 질의응답"
  - Tutorial 3: "한국어 PII 마스킹 활용하기"

□ [#4] 통합 docker-compose.yml
  - Weaviate + PostgreSQL + Langfuse + App 통합
  - make up / make down 명령어 추가
  - 초기 데이터 시딩 스크립트

□ [#5] 버전 체계 정리
  - Git 태그 정리 (v1.0.7로 통일)
  - CHANGELOG 버전 체계 설명 추가
  - 향후 시맨틱 버저닝 규칙 명시
```

**완료 기준 (DoD)**:
- ✅ 외부 기여자가 30분 내 PR 제출 가능
- ✅ 신규 사용자가 10분 내 챗봇 실행 가능
- ✅ 버전 혼란 이슈 0건

---

### Phase 2: 정체성 확립 (Month 1-2) - P1 실행
**목표**: "한국어 엔터프라이즈 RAG"로 포지셔닝

#### Sprint 2-1: 전략적 포지셔닝 (Week 3-4)
```bash
□ [#7] 포지셔닝 재정의
  ├─ README: "범용 RAG" → "금융/의료/공공 특화 한국어 RAG"
  ├─ 타겟 페르소나 정의
  │  - Primary: 대기업 백엔드 개발자 (개인정보 보호 필수)
  │  - Secondary: 스타트업 CTO (빠른 RAG 도입)
  ├─ 경쟁 우위 명확화
  │  - vs LangChain: 한국어 NLP + PIPA 준수
  │  - vs LlamaIndex: 엔터프라이즈 보안 + 감사 로그
  └─ 사용 사례 3개 상세화
     1. 금융사 고객 상담 챗봇 (전화번호/계좌번호 자동 마스킹)
     2. 병원 의료 기록 검색 (주민번호 차단)
     3. 공공기관 민원 응대 (개인정보 보호법 준수)

□ [#12] 핵심 사용 사례 문서화
  - docs/use-cases/financial-chatbot.md
  - docs/use-cases/medical-search.md
  - docs/use-cases/public-service.md
  - 각 사례마다 아키텍처 다이어그램, 코드 예제, 배포 가이드 포함
```

#### Sprint 2-2: API 사용성 개선 (Week 5-6)
```bash
□ [#8] API 사용 예제 10개
  ├─ 기본 (4개)
  │  1. POST /chat - 기본 질의응답
  │  2. POST /chat - 스트리밍 응답
  │  3. POST /chat - 세션 기반 대화
  │  4. POST /admin/upload - 문서 업로드
  ├─ 고급 (4개)
  │  5. GraphRAG - 지식 그래프 검색
  │  6. Agent Mode - 도구 사용 에이전트
  │  7. Multi-Query - 병렬 검색
  │  8. Privacy Masking - PII 마스킹 커스터마이징
  └─ 통합 (2개)
     9. Python SDK 래퍼 예제
     10. React 프론트엔드 통합

□ [#10] 트러블슈팅 가이드
  - docs/TROUBLESHOOTING.md 작성
  - 자주 발생하는 에러 20개 + 해결책
  - FAQ 섹션 추가
```

#### Sprint 2-3: 품질 검증 (Week 7-8)
```bash
□ [#9] 통합 테스트 30%로 증가
  - tests/integration/ 확장
  - E2E 시나리오 10개 추가
    1. 문서 업로드 → 검색 → 답변 생성
    2. PII 탐지 → 마스킹 → 감사 로그
    3. GraphRAG 전체 플로우
    4. Multi-LLM fallback 동작
    5. 캐시 히트/미스 동작
    6. Rate limiting 동작
    7. Circuit breaker 동작
    8. 세션 상태 관리
    9. 병렬 요청 처리
    10. 장애 복구 (Weaviate 재시작)
  - CI에서 integration 테스트 활성화 (환경변수 mock)

□ [#11] 성능 벤치마크
  - 테스트 환경: AWS t3.medium (2 vCPU, 4GB RAM)
  - 메트릭: Latency(P50/P95/P99), Throughput(RPS), Cost($)
  - 시나리오:
    1. 단순 RAG (Vector Search only)
    2. Hybrid RAG (Vector + BM25)
    3. GraphRAG (Vector + Graph + Reranking)
  - 결과: docs/BENCHMARKS.md에 공개
```

**완료 기준 (DoD)**:
- ✅ "한국어 엔터프라이즈 RAG"로 검색 시 프로젝트 노출
- ✅ API 예제만으로 30분 내 프로덕션 통합 가능
- ✅ 통합 테스트 커버리지 30% 달성

---

### Phase 3: 기술 부채 해소 (Month 3-6) - P2 실행
**목표**: 실질적 복잡도 감소 및 유지보수성 향상

#### Sprint 3-1: 아키텍처 단순화 (Week 9-14)
```bash
□ [#13] DI Container 리팩토링
  현재 문제:
  - di_container.py: 2,267 LOC (단일 파일)
  - 80+ Provider (과도한 추상화)

  해결 방안:
  ├─ app/core/di/
  │  ├─ __init__.py (AppContainer만)
  │  ├─ infrastructure.py (DB, Cache, Vector Store)
  │  ├─ services.py (RAG, Chat, Ingestion)
  │  ├─ modules.py (Privacy, Graph, Agent)
  │  └─ external.py (LLM, Embedding, Reranking)
  └─ 각 파일 300-500 LOC로 제한

  마이그레이션:
  1. 새 구조로 Provider 이동 (하위 호환성 유지)
  2. 기존 di_container.py는 deprecated 마크
  3. v2.0.0에서 완전 제거 예고

□ [#14] YAML 설정 통합
  현재: 40개 파일 (base.yaml + 26 features + 환경별)
  목표: 15개 파일

  통합 전략:
  ├─ config/base.yaml (핵심 설정만)
  ├─ config/features/
  │  ├─ search.yaml (retrieval + reranking + cache 통합)
  │  ├─ generation.yaml (llm + prompt 통합)
  │  ├─ security.yaml (privacy + auth 통합)
  │  ├─ graph.yaml (graph_rag + neo4j)
  │  └─ observability.yaml (langfuse + metrics)
  └─ config/environments/ (그대로 유지)

  검증:
  - 하위 호환성 테스트 (기존 설정 파일로 실행 가능)
  - 마이그레이션 가이드 작성

□ [#17] 벡터 DB 6개 → 3개로 축소
  제거 대상:
  - MongoDB Atlas (사용률 낮음, 성능 미달)
  - pgvector (Weaviate 하위 호환)
  - Pinecone (클라우드 종속성)

  유지:
  - Weaviate (기본, 프로덕션 권장)
  - Chroma (로컬 개발, 경량)
  - Qdrant (고성능 자체 호스팅)

  영향 분석:
  - 의존성 -3개 (패키지 크기 감소)
  - 테스트 -150개 제거 가능
  - 문서 유지보수 부담 -50%
```

#### Sprint 3-2: 코드 품질 개선 (Week 15-20)
```bash
□ [#15] Mypy strict 100%
  현재 예외: app/api/, tests/, app/middleware/

  단계별 적용:
  1. app/api/schemas/ (쉬움, Pydantic 모델)
  2. app/middleware/ (보통, 에러 핸들러)
  3. app/api/routers/ (어려움, FastAPI 데코레이터)
  4. tests/ (가장 어려움, fixture 타입)

  각 단계마다:
  - 타입 힌트 추가
  - reveal_type() 디버깅
  - CI에 mypy 검사 추가
  - 팀 리뷰 및 수정

□ [#16] 복잡도 감소 (함수 복잡도 >10)
  현재: 36개 함수
  목표: <20개 함수

  우선순위 함수 (복잡도 >15):
  1. RAGPipeline.execute() - 복잡도 20
  2. ChatService.process_message() - 복잡도 18
  3. PIIProcessor.process_document() - 복잡도 16

  리팩토링 기법:
  - Extract Method (메서드 추출)
  - Replace Conditional with Polymorphism
  - Strategy Pattern 적용

□ [#18] E2E 테스트 활성화
  2026-01 당시 상태: 마커만 있고 실행 안 됨

  활성화:
  - Playwright 통합 (브라우저 자동화)
  - TestContainers (Docker 환경)
  - E2E 시나리오 5개
    1. 회원가입 → 문서업로드 → 채팅
    2. API Key 인증 → 관리자 기능
    3. GraphRAG 전체 플로우
    4. 멀티모달 (이미지 + 텍스트)
    5. 장애 복구 시나리오
  - CI/CD에 nightly E2E 테스트 추가

□ [#19] 비용 최적화 가이드
  - docs/COST_OPTIMIZATION.md 작성
  - LLM API 비용 계산기 (토큰 × 단가)
  - 캐싱 전략 (비용 -70%)
  - 모델 선택 가이드 (GPT-4 vs Gemini)
  - 프롬프트 최적화 (토큰 감소)
```

**완료 기준 (DoD)**:
- ✅ DI Container 파일 수 5개, 각 500 LOC 이하
- ✅ YAML 설정 파일 15개 이하
- ✅ 복잡도 >10 함수 20개 이하
- ✅ Mypy strict 100% 통과

---

### Phase 4: 생태계 구축 (Month 7-12) - P3 실행
**목표**: 지속 가능한 커뮤니티 및 비즈니스 모델

#### Sprint 4-1: 커뮤니티 성장 (Month 7-9)
```bash
□ [#20] GitHub Stars 100+ 달성
  전략:
  1. Product Hunt 런칭
  2. Reddit r/MachineLearning, r/LangChain 홍보
  3. 기술 블로그 3편 발행
     - "한국어 RAG를 위한 PII 마스킹 전략"
     - "GraphRAG vs Vector RAG: 벤치마크 비교"
     - "FastAPI로 프로덕션 RAG 구축하기"
  4. YouTube 튜토리얼 영상 (한/영)
  5. Hacker News 제출

  커뮤니티 활동:
  - Issue 응답 SLA: 24시간
  - PR 리뷰 SLA: 48시간
  - Monthly Release Notes
  - Contributor Recognition (README에 명시)

□ [#24] Observability 대시보드
  - Prometheus + Grafana 통합
  - 주요 메트릭:
    1. Request Rate (RPS)
    2. Latency (P50/P95/P99)
    3. Error Rate (%)
    4. LLM Cost ($)
    5. Cache Hit Rate (%)
    6. Vector DB QPS
  - 알림 규칙:
    - Latency P95 > 5초
    - Error Rate > 1%
    - LLM Cost > $100/day
```

#### Sprint 4-2: 비즈니스 모델 (Month 10-12)
```bash
□ [#21] 엔터프라이즈 유료 지원
  Freemium 모델:
  ├─ Open Source (무료)
  │  - Community Support (GitHub Issues)
  │  - Self-Hosted Deployment
  │  - 기본 기능 (RAG, GraphRAG, Privacy)
  │
  └─ Enterprise (유료, $500-2000/month)
     - SLA 보장 (99.9% Uptime)
     - Priority Support (Slack, Email)
     - 전용 기능:
       1. Multi-Tenancy
       2. SSO/SAML 인증
       3. Advanced Analytics
       4. Custom Model Fine-Tuning
       5. On-Premise Deployment Support

  파일럿 고객 3개사 확보:
  - 금융사 1개 (카드사/은행)
  - 의료기관 1개 (병원/제약)
  - 공공기관 1개 (정부/지자체)

□ [#22] Managed RAG 서비스
  SaaS 플랫폼: rag-standard.io

  기능:
  - 클릭 3번으로 RAG 챗봇 배포
  - No-Code 문서 업로드
  - API Key 자동 발급
  - 사용량 기반 과금

  인프라:
  - AWS EKS (Kubernetes)
  - RDS (PostgreSQL)
  - Weaviate Cloud
  - CloudFront (CDN)

  가격:
  - Starter: $29/month (1K requests)
  - Pro: $99/month (10K requests)
  - Enterprise: Custom pricing

□ [#23] 다국어 지원
  - 영어: 완전 지원 (README, Docs)
  - 일본어: 부분 지원 (README만)
  - PII 탐지: spaCy 영어/일본어 모델 추가
```

**완료 기준 (DoD)**:
- ✅ GitHub Stars 100+
- ✅ 파일럿 고객 3개사
- ✅ MRR $1,500+ (Monthly Recurring Revenue)

---

## 📈 성공 지표 (KPI)

### Phase 1 (Week 2)
- [ ] CONTRIBUTING.md 존재
- [ ] Issue/PR 템플릿 존재
- [ ] 외부 기여자 1명 이상
- [ ] 신규 사용자 온보딩 시간 <15분

### Phase 2 (Month 2)
- [ ] GitHub Stars 20+
- [ ] 포크 5+
- [ ] 실제 프로덕션 사용 1건
- [ ] 통합 테스트 30%
- [ ] API 예제 10개

### Phase 3 (Month 6)
- [ ] DI Container 500 LOC 이하 (파일당)
- [ ] 복잡도 >10 함수 <20개
- [ ] Mypy strict 100%
- [ ] GitHub Stars 50+

### Phase 4 (Month 12)
- [ ] GitHub Stars 100+
- [ ] 파일럿 고객 3개사
- [ ] MRR $1,500+
- [ ] Contributors 10+

---

## 🚧 리스크 및 대응 방안

### 리스크 1: 단독 개발자 (Bus Factor = 1)
**대응**:
- 코드 리뷰어 2명 확보 (외부 기여자)
- 모든 주요 모듈 README 작성
- Onboarding 가이드 충실화

### 리스크 2: LangChain/LlamaIndex 경쟁
**대응**:
- 한국어 특화 기능 강화 (차별점)
- 엔터프라이즈 보안 집중
- 커뮤니티보다 B2B 고객 우선

### 리스크 3: 기술 스택 변화 (Python 3.13, FastAPI 1.0)
**대응**:
- 의존성 버전 고정 (uv.lock)
- CI에서 최신 버전 테스트
- 마이그레이션 가이드 사전 작성

---

## 📝 결론 및 권장 사항

### 핵심 권장 사항
1. **즉시 시작**: P0 작업 (29시간, 1주일)을 오늘부터 착수
2. **포지셔닝 전환**: "범용" → "한국어 엔터프라이즈" 명확화
3. **복잡도 감소**: 80% 사용 사례에 집중, 나머지 제거
4. **커뮤니티 우선**: 코드보다 문서/예제 투자

### 현실적 목표 (12개월)
- GitHub Stars: 100+ (달성 가능)
- 파일럿 고객: 3-5개 (한국 시장 집중)
- MRR: $1,500-3,000 (소규모 SaaS)

### 비현실적 목표 (회피)
- ❌ LangChain 규모 (40K+ stars) 추격
- ❌ 글로벌 커뮤니티 (언어 장벽)
- ❌ VC 투자 유치 (팀 없음)

**이 로드맵대로 실행하면 6개월 내 생존 가능한 오픈소스 프로젝트, 12개월 내 수익화 가능한 제품으로 성장할 수 있습니다.**

---

**작성자**: 오픈소스 가치 분석 전문가
**검토 주기**: 월 1회 (매월 첫째 주 월요일)
**업데이트**: 진행 상황에 따라 동적 조정
