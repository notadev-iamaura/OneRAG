# LLM 문서 보강 (Enrichment) 모듈

문서 로드 시 LLM을 사용하여 메타데이터를 자동으로 생성하는 기능입니다.

## 개요

텍스트 데이터를 LLM으로 분석하여 다음 메타데이터를 자동 생성합니다:

- **category**: 주요 카테고리 (예: "기술", "비즈니스", "교육")
- **subcategory**: 세부 카테고리 (예: "프로그래밍", "마케팅", "튜토리얼")
- **intent**: 텍스트의 주요 의도 (예: "정보 제공", "문제 해결")
- **content_type**: 콘텐츠 유형 (예: "FAQ", "가이드", "보고서")
- **keywords**: 핵심 키워드 리스트
- **summary**: 한 줄 요약
- **is_tool_related**: 도구 관련 여부
- **requires_db_check**: DB 확인 필요 여부

---

## 주요 기능

### 핵심 기능

1. **LLM 기반 보강**: gpt-4o-mini 사용
2. **배치 처리**: 10개씩 묶어서 처리 (성능 최적화)
3. **Graceful Degradation**: 실패 시 원본 문서 사용
4. **재시도 로직**: Exponential Backoff 적용
5. **타임아웃 관리**: 단건 30초, 배치 90초

### 안전장치

- **기본값 false**: `enrichment.enabled: false`로 시작
- **Null Object 패턴**: 비활성화 시 NullEnricher 사용
- **에러 격리**: 보강 실패해도 파이프라인 정상 동작
- **토큰 추적**: 사용량 및 비용 모니터링

---

## 아키텍처

### 구조도

```
EnrichmentService (오케스트레이션)
    ├── EnricherInterface (추상 인터페이스)
    │   ├── NullEnricher (비활성화 시)
    │   └── LLMEnricher (활성화 시)
    ├── EnrichmentSchema (Pydantic 모델)
    └── Prompts (프롬프트 템플릿)
```

### 디렉토리 구조

```
app/modules/core/enrichment/
├── __init__.py
├── README.md                        # 이 파일
├── interfaces/
│   └── enricher_interface.py       # 추상 인터페이스
├── enrichers/
│   ├── null_enricher.py            # 비활성화 구현체
│   └── llm_enricher.py             # LLM 보강 구현체
├── schemas/
│   └── enrichment_schema.py        # Pydantic 모델
├── prompts/
│   └── enrichment_prompts.py       # 프롬프트 템플릿
└── services/
    └── enrichment_service.py       # 오케스트레이션
```

---

## 설정 방법

### 1. 환경 변수 설정 (.env)

```bash
# 보강 기능 활성화 (기본값: false)
ENRICHMENT_ENABLED=false

# LLM 모델 (기본값: gpt-4o-mini)
ENRICHMENT_LLM_MODEL=gpt-4o-mini

# 온도 (기본값: 0.1)
ENRICHMENT_LLM_TEMPERATURE=0.1

# 배치 크기 (기본값: 10)
ENRICHMENT_BATCH_SIZE=10

# OpenAI API 키 (기존 설정 재사용)
OPENAI_API_KEY=sk-...
```

### 2. 설정 파일 확인 (app/config/features/enrichment.yaml)

기본 설정이 이미 작성되어 있습니다. 필요 시 수정하세요.

```yaml
enrichment:
  enabled: false  # 기본값: 비활성화
  llm:
    model: gpt-4o-mini
    temperature: 0.1
    max_tokens: 1000
  batch:
    size: 10
    concurrency: 3
  timeout:
    single: 30
    batch: 90
```

---

## 사용 방법

### 1. 기본 사용 (단일 문서)

```python
from app.modules.core.enrichment import EnrichmentService
from app.lib.config_loader import load_config

# 설정 로드
config = load_config()

# 서비스 초기화
enrichment_service = EnrichmentService(config)
await enrichment_service.initialize()

# 단일 문서 보강
document = {
    "content": "Python에서 리스트 컴프리헨션을 사용하면 반복문을 간결하게 작성할 수 있습니다."
}

result = await enrichment_service.enrich(document)

if result:
    print(f"카테고리: {result.category}")
    print(f"키워드: {result.keywords}")
    print(f"요약: {result.summary}")

# 정리
await enrichment_service.cleanup()
```

### 2. 배치 처리

```python
# 여러 문서 동시 보강
documents = [
    {"content": "Python 리스트 컴프리헨션 설명..."},
    {"content": "2024년 매출 보고서..."},
    {"content": "서비스 이용약관 안내..."}
]

results = await enrichment_service.enrich_batch(documents)

for i, result in enumerate(results):
    if result:
        print(f"문서 {i+1}: {result.category} - {result.summary}")
    else:
        print(f"문서 {i+1}: 보강 실패 (원본 사용)")
```

### 3. 문서 로더 통합 (자동 보강)

```python
# 문서 로딩 시 자동 보강 (향후 구현 예정)
from app.modules.core.documents.loaders import DocumentLoaderFactory

loader = DocumentLoaderFactory.create_loader("example.json")
documents = await loader.load("example.json")

# 각 문서에 llm_enrichment 필드가 자동 추가됨
for doc in documents:
    enrichment = doc.metadata.get('llm_enrichment')
    if enrichment:
        print(f"카테고리: {enrichment['category']}")
```

### 4. 통계 확인

```python
# 보강 통계 조회
stats = enrichment_service.get_stats()

print(f"총 보강 시도: {stats['total_enrichments']}")
print(f"성공: {stats['successful_enrichments']}")
print(f"실패: {stats['failed_enrichments']}")
print(f"성공률: {stats['success_rate']:.2f}%")
print(f"토큰 사용량: {stats['total_tokens_used']}")
```

---

## 테스트

### 단위 테스트

```bash
# 전체 테스트 실행
pytest tests/unit/enrichment/ -v

# 특정 테스트 실행
pytest tests/unit/enrichment/test_enrichment_service.py -v
```

---

## 문제 해결

### Q1: 보강이 동작하지 않아요

**확인 사항:**
1. `.env`에서 `ENRICHMENT_ENABLED=true`로 설정했는지 확인
2. `OPENAI_API_KEY`가 올바르게 설정되었는지 확인
3. 로그에서 "Enrichment enabled" 메시지 확인

### Q2: LLM 호출이 너무 느려요

**해결 방법:**
1. 배치 크기 조정: `.env`에서 `ENRICHMENT_BATCH_SIZE=5`로 감소
2. 타임아웃 증가: `ENRICHMENT_TIMEOUT_SINGLE=60`
3. 동시 처리 수 증가: `ENRICHMENT_CONCURRENCY=5`

### Q3: JSON 파싱 에러가 발생해요

**원인:**
LLM이 JSON 외에 추가 텍스트를 출력하는 경우

**해결 방법:**
- 프롬프트에 "JSON만 출력" 강조 (이미 적용됨)
- 마크다운 코드 블록 제거 로직 (이미 적용됨)
- 재시도 로직 활용 (이미 적용됨)

---

## 성능 지표

### 예상 성능

| 항목 | 값 |
|------|-----|
| 단건 처리 시간 | 2-5초 |
| 배치 처리 시간 (10개) | 5-10초 |
| 토큰 사용량 (단건) | 300-500 tokens |
| 토큰 사용량 (배치 10개) | 1500-2500 tokens |
| 성공률 | 95%+ |

---

**마지막 업데이트**: 2026-03-09
**버전**: 2.0.0
