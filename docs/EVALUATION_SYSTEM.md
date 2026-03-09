# 평가 시스템 아키텍처 (Evaluation System)

본 문서는 Blank RAG 시스템의 답변 품질을 객관적으로 측정하고 개선하기 위한 **통합 평가 시스템** 구축 계획을 정의합니다. 

---

## 1. 개요 및 목적

RAG 시스템의 완성도는 "답변이 얼마나 정확하고 믿을 수 있는가"에 달려 있습니다. 우리는 리소스 효율성을 위해 자체 제작한 **Internal Evaluator**와 업계 표준인 **Ragas** 라이브러리를 결합하여 공신력 있는 평가 지표를 제공합니다.

### 🎯 핵심 목표
- **실시간 검증**: 답변 생성 즉시 환각(Hallucination) 여부를 체크하여 사용자에게 안전한 답변 제공.
- **표준 지표 확보**: Ragas를 통해 Faithfulness, Answer Relevancy 등 공신력 있는 점수 산출.
- **지속적 개선**: 사용자 피드백을 기반으로 '골든 데이터셋(정답셋)'을 자동 구축.

---

## 2. 시스템 구조 (Hybrid Architecture)

Hexagonal Architecture를 따라 평가 엔진을 **Provider** 형태로 추상화합니다.

```
[ Evaluation Module ]
      │
      ├─ [ IEvaluator Interface ] ──┐
      │                             │
      ├─ [ InternalProvider ]       ├─ [ RagasProvider ]
      │  (Fast, Low-cost)           │  (Authoritative, Batch)
      │  - 실시간 응답 검증          │  - 정기 품질 리포트
      │  - Self-RAG 연동            │  - 버전 간 성능 비교
```

---

## 3. 핵심 평가 지표

### 3.1 Internal Metrics (자체 지표)
- **Faithfulness (충실도)**: 생성된 답변의 모든 문장이 검색된 컨텍스트에 근거하는가?
- **Relevance (관련성)**: 답변이 사용자의 질문 의도에 직접적으로 부합하는가?

### 3.2 External Metrics (Ragas 표준 지표)
- **Context Precision**: 검색 결과 중 정답과 관련된 문서가 상단에 배치되었는가?
- **Answer Semantic Similarity**: 생성된 답변이 정답셋(Reference)과 의미적으로 얼마나 유사한가?

---

## 4. 데이터 선순환 (Feedback Loop)

평가 시스템의 품질은 정답셋의 양과 질에 비례합니다.

1.  **피드백 수집**: 유저가 응답에 👍/👎 피드백을 남깁니다. (`POST /api/chat/feedback`)
2.  **데이터 큐레이션**: 피드백이 좋은 응답은 **Golden Dataset** 후보로 등록됩니다.
3.  **정답셋 구축**: 관리자가 후보 데이터를 검토하여 확정된 정답셋(`eval_set.json`)을 업데이트합니다.
4.  **회귀 테스트**: 시스템 업데이트 시 정답셋을 대상으로 Ragas 평가를 실행하여 성능 저하 여부를 체크합니다.

---

## 5. 단계별 구현 계획 (Implementation Phases)

### Phase 1: 기반 구축 및 피드백 API (리소스 20%)
- `IEvaluator` 인터페이스 정의 및 `AppContainer` 등록.
- `PostgreSQL` 내 피드백 저장 테이블 생성.
- `/api/chat/feedback` 엔드포인트 구현.

### Phase 2: Ragas Provider 통합 (리소스 50%)
- `ragas` 라이브러리 연동 (Optional Dependency로 처리).
- 내부 검색/생성 결과를 Ragas Dataset 형식으로 변환하는 `RagasConverter` 구현.
- 관리자용 배치 평가 API (`POST /api/admin/evaluate`) 구현.

### Phase 3: 평가 대시보드 및 자동화 (리소스 30%)
- 누적된 피드백 및 Ragas 점수를 시각화하는 관리자 대시보드 연동.
- CI/CD 파이프라인에서 정답셋 대상 자동 평가 실행 스크립트 제공.

---

## 6. 리소스 균형 전략

| 구분 | 실시간 (Online) | 배치 (Offline) |
| :--- | :--- | :--- |
| **도구** | Internal Evaluator (Gemini Flash) | Ragas + GPT-4o / Claude 3.5 |
| **비용** | 극소 (응답당 약 $0.0001) | 필요 시에만 지출 (리포트당 약 $1~5) |
| **속도** | < 0.5초 | 1~5분 (비동기 처리) |
| **목적** | 필터링 및 안전장치 | 품질 증명 및 벤치마크 |

---

**작성일**: 2026-01-05
**상태**: Phase 1, 2, 3-A 완료 (Phase 3-B 진행 예정)

---

## 7. 구현 현황 (Implementation Status)

### ✅ Phase 1: 완료 (2026-01-05)
- `IEvaluator` Protocol 정의 (`app/modules/core/evaluation/interfaces.py`)
- `InternalEvaluator` 실시간 평가기 (`app/modules/core/evaluation/internal_evaluator.py`)
- `EvaluationResult`, `FeedbackData` 모델 (`app/modules/core/evaluation/models.py`)
- `EvaluatorFactory` 팩토리 패턴 (`app/modules/core/evaluation/factory.py`)
- DI Container 등록 (`app/core/di_container.py`)
- Feedback API 엔드포인트 (`POST /api/chat/feedback`)
- 테스트: 131개 통과, 93.66% 커버리지

### ✅ Phase 2: 완료 (2026-01-05)
- `RagasEvaluator` 배치 평가기 (`app/modules/core/evaluation/ragas_evaluator.py`)
- Ragas 라이브러리 연동 (Optional Dependency: `pip install rag-chatbot[ragas]`)
- 지원 메트릭: `faithfulness`, `answer_relevancy`, `context_precision`
- Graceful Degradation: Ragas 미설치 시 기본값 반환

### ✅ Phase 3-A: 완료 (2026-01-05)
- 관리자용 배치 평가 API (`POST /api/admin/evaluate`)
- CI/CD 자동 평가 스크립트 (`scripts/run_eval.py`, `make eval`)
- pytest 마커 지원 (`@pytest.mark.eval`)

### ⏳ Phase 3-B: 진행 예정
- 평가 대시보드 연동 (Grafana/Prometheus)
- Golden Dataset 관리 시스템

---

## 8. 사용 방법 (Quick Start)

### 설정 파일 (`app/config/features/evaluation.yaml`)
```yaml
evaluation:
  enabled: true  # 평가 기능 활성화
  provider: "internal"  # "internal" | "ragas"
  internal:
    model: "google/gemini-2.5-flash-lite"
    timeout: 10.0
  ragas:
    metrics: ["faithfulness", "answer_relevancy"]
    batch_size: 10
```

### 코드 사용 예시
```python
from app.modules.core.evaluation import EvaluatorFactory

# 설정 기반 평가기 생성
evaluator = EvaluatorFactory.create(config)

# 단일 평가
result = await evaluator.evaluate(
    query="질문",
    answer="답변",
    context="컨텍스트"
)

# 배치 평가 (Ragas)
results = await evaluator.batch_evaluate([
    {"query": "q1", "answer": "a1", "context": "c1"},
    {"query": "q2", "answer": "a2", "context": "c2"},
])
```

### 배치 평가 API (관리자용)
```bash
# POST /api/admin/evaluate
curl -X POST http://localhost:8000/api/admin/evaluate \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your-api-key" \
  -d '{
    "samples": [
      {
        "query": "서울 맛집 추천해줘",
        "answer": "서울에 위치한 맛집 3곳을 추천드립니다...",
        "context": "A 레스토랑: 강남역 3번 출구..."
      }
    ],
    "provider": "internal"
  }'
```

### CI/CD 평가 스크립트
```bash
# 기본 실행 (internal 평가기)
make eval

# Ragas 평가기 사용
make eval-ragas

# 직접 스크립트 실행
python scripts/run_eval.py --provider internal --threshold 0.7

# 특정 데이터셋 지정
python scripts/run_eval.py --dataset data/golden_dataset.json

# pytest 마커로 평가 테스트 실행
pytest -m eval -v
```
