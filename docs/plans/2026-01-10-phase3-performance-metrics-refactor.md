# Phase 3: get_performance_metrics() 리팩토링 - TDD 기반 구현 계획

> **작성일**: 2026-01-10
> **예상 작업량**: 약 30분
> **목표**: deprecated 함수를 private 함수로 변환하여 기술부채 Zero 완성

## 개요

### 현재 상태
`get_performance_metrics()` 함수는 deprecation 경고를 포함하고 있지만, **모듈 내부에서만 사용**됩니다:
- `track_function_performance` 데코레이터 내부 (line 272)
- 전역 `metrics` 객체 초기화 (line 293)

### 목표 상태
- deprecated 함수를 **private 함수**(`_get_performance_metrics()`)로 변환
- deprecation 경고 제거 (내부용이므로 불필요)
- DI Container는 여전히 공식 공개 API로 유지
- 외부 사용자에게는 영향 없음 (이미 deprecated 경고로 DI Container 사용 안내됨)

## TDD 접근법

### 원칙
1. **RED**: 실패하는 테스트 먼저 작성
2. **GREEN**: 최소한의 코드로 테스트 통과
3. **REFACTOR**: 코드 품질 개선

---

## Task 1: 테스트 파일 생성 (RED Phase)

### 파일 경로
```
tests/unit/lib/test_metrics_internal.py
```

### 테스트 코드
```python
"""
metrics.py 내부 함수 테스트

Phase 3: get_performance_metrics() → _get_performance_metrics() 리팩토링 검증
"""

import warnings
from unittest.mock import patch

import pytest


class Test_GetPerformanceMetricsDeprecation:
    """get_performance_metrics 함수의 deprecated 상태 테스트"""

    def test_공개_함수가_존재하지_않음(self):
        """
        공개 API에서 get_performance_metrics가 제거되었는지 확인

        Phase 3 완료 후 이 테스트는 통과해야 함
        """
        from app.lib import metrics

        # 공개 함수가 존재하면 안 됨
        assert not hasattr(metrics, 'get_performance_metrics'), \
            "get_performance_metrics()는 public API에서 제거되어야 합니다"

    def test_private_함수가_존재함(self):
        """
        private 함수 _get_performance_metrics가 존재하는지 확인
        """
        from app.lib import metrics

        # private 함수는 존재해야 함
        assert hasattr(metrics, '_get_performance_metrics'), \
            "_get_performance_metrics() private 함수가 있어야 합니다"

    def test_private_함수는_deprecation_경고_없음(self):
        """
        private 함수 호출 시 DeprecationWarning이 발생하지 않아야 함
        """
        from app.lib.metrics import _get_performance_metrics

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result = _get_performance_metrics()

            # DeprecationWarning이 없어야 함
            deprecation_warnings = [
                warning for warning in w
                if issubclass(warning.category, DeprecationWarning)
            ]
            assert len(deprecation_warnings) == 0, \
                "private 함수는 deprecation 경고가 없어야 합니다"

        # 유효한 인스턴스 반환 확인
        from app.lib.metrics import PerformanceMetrics
        assert isinstance(result, PerformanceMetrics)


class TestTrackFunctionPerformanceDecorator:
    """track_function_performance 데코레이터가 정상 작동하는지 확인"""

    @pytest.mark.asyncio
    async def test_데코레이터가_메트릭을_기록함(self):
        """
        데코레이터 적용 함수 호출 시 메트릭이 기록되어야 함
        """
        from app.lib.metrics import track_function_performance, _get_performance_metrics

        @track_function_performance("test_function")
        async def sample_function():
            return "success"

        # 함수 실행
        result = await sample_function()

        assert result == "success"

        # 메트릭 확인
        metrics = _get_performance_metrics()
        stats = metrics.get_stats("test_function")
        assert stats["count"] >= 1

    @pytest.mark.asyncio
    async def test_데코레이터가_에러를_기록함(self):
        """
        데코레이터 적용 함수에서 예외 발생 시 에러 카운트 증가
        """
        from app.lib.metrics import track_function_performance, _get_performance_metrics

        @track_function_performance("error_function")
        async def failing_function():
            raise ValueError("테스트 에러")

        # 초기 에러 카운트 확인
        metrics = _get_performance_metrics()
        initial_errors = metrics.error_counts.get("error_function", 0)

        # 함수 실행 (예외 발생)
        with pytest.raises(ValueError):
            await failing_function()

        # 에러 카운트 증가 확인
        final_errors = metrics.error_counts.get("error_function", 0)
        assert final_errors == initial_errors + 1


class TestGlobalMetricsObject:
    """전역 metrics 객체가 정상 초기화되는지 확인"""

    def test_전역_metrics_객체가_유효함(self):
        """
        모듈 레벨 metrics 객체가 PerformanceMetrics 인스턴스인지 확인
        """
        from app.lib.metrics import metrics, PerformanceMetrics

        assert isinstance(metrics, PerformanceMetrics)

    def test_전역_metrics와_private_함수가_동일_인스턴스(self):
        """
        전역 metrics 객체와 _get_performance_metrics() 반환값이 동일해야 함
        """
        from app.lib.metrics import metrics, _get_performance_metrics

        assert metrics is _get_performance_metrics()
```

### 검증 명령어
```bash
# 테스트 실행 (현재는 실패해야 함 - RED phase)
pytest tests/unit/lib/test_metrics_internal.py -v
```

**예상 결과**: 테스트 실패 (get_performance_metrics가 아직 존재하므로)

---

## Task 2: 코드 수정 (GREEN Phase)

### 파일 경로
```
app/lib/metrics.py
```

### 수정 사항

#### 2.1 함수명 변경 및 deprecation 제거

**Before (line 224-258)**:
```python
def get_performance_metrics() -> PerformanceMetrics:
    """
    전역 성능 메트릭 가져오기

    .. deprecated:: 3.1.0
        DI Container의 AppContainer.performance_metrics를 사용하세요.
        이 함수는 하위 호환성을 위해 유지되며 v4.0.0에서 제거될 예정입니다.

    ...docstring 생략...
    """
    import warnings

    warnings.warn(
        "get_performance_metrics()는 deprecated되었습니다. "
        "DI Container의 AppContainer.performance_metrics를 사용하세요.",
        DeprecationWarning,
        stacklevel=2,
    )
    global _global_performance_metrics
    if _global_performance_metrics is None:
        _global_performance_metrics = PerformanceMetrics()
        logger.info("✅ 전역 성능 메트릭 초기화")
    return _global_performance_metrics
```

**After**:
```python
def _get_performance_metrics() -> PerformanceMetrics:
    """
    전역 성능 메트릭 가져오기 (내부용)

    이 함수는 모듈 내부에서만 사용됩니다.
    외부에서는 DI Container의 AppContainer.performance_metrics를 사용하세요.

    Returns:
        PerformanceMetrics: 전역 성능 메트릭 인스턴스
    """
    global _global_performance_metrics
    if _global_performance_metrics is None:
        _global_performance_metrics = PerformanceMetrics()
        logger.info("✅ 전역 성능 메트릭 초기화")
    return _global_performance_metrics
```

#### 2.2 데코레이터 내부 호출 변경 (line 272)

**Before**:
```python
metrics = get_performance_metrics()
```

**After**:
```python
metrics = _get_performance_metrics()
```

#### 2.3 전역 객체 초기화 변경 (line 293)

**Before**:
```python
metrics = get_performance_metrics()
```

**After**:
```python
metrics = _get_performance_metrics()
```

### 검증 명령어
```bash
# 테스트 실행 (이제 통과해야 함 - GREEN phase)
pytest tests/unit/lib/test_metrics_internal.py -v

# 전체 테스트 실행
make test
```

**예상 결과**: 모든 테스트 통과 (1,288개 + 새 테스트)

---

## Task 3: 검증 및 정리 (REFACTOR Phase)

### 3.1 외부 사용처 최종 확인

```bash
# 외부에서 get_performance_metrics 직접 호출하는 곳이 없어야 함
grep -r "get_performance_metrics" app/ --include="*.py" | grep -v "def _get_performance_metrics" | grep -v "metrics = _get_performance_metrics()"

# __all__ 등에서 export되지 않아야 함
grep -r "get_performance_metrics" app/ --include="__init__.py"
```

**예상 결과**: 결과 없음

### 3.2 문서 업데이트

`docs/TECHNICAL_DEBT_ANALYSIS.md` 업데이트:

```markdown
### 2.1 Deprecated 함수 (v1.0.7 완전 제거)

| 함수 | 위치 | 대체 방안 | 상태 |
|------|------|----------|------|
| `get_cost_tracker()` | `metrics.py` | DI Container 직접 사용 | ✅ 제거됨 (v1.0.3) |
| `get_mongodb_client()` | `mongodb_client.py` | DI Container 직접 사용 | ✅ 제거됨 (v1.0.3) |
| `get_prompt_manager()` | `prompt_manager.py` | DI Container 직접 사용 | ✅ 제거됨 (v1.0.6) |
| `GPT5NanoReranker` | `openai_llm_reranker.py` | `OpenAILLMReranker` 사용 | ✅ 제거됨 (v1.0.6) |
| `get_circuit_breaker()` | `circuit_breaker.py` | `circuit_breaker_factory.get()` | ✅ 제거됨 (v1.0.6) |
| `get_performance_metrics()` | `metrics.py` | `_get_performance_metrics()` (private) | ✅ 리팩토링됨 (v1.0.7) |

**v1.0.7 완료 (Phase 3)**:
- **Phase 3**: `get_performance_metrics()` → `_get_performance_metrics()` (내부용 private 함수로 전환)
- **효과**: 외부 API에서 deprecated 함수 완전 제거, 모듈 내부 기능 유지
- **테스트**: 1,288개 + 신규 테스트 전체 통과
```

### 3.3 커밋

```bash
git add -A
git commit -m "$(cat <<'EOF'
리팩터: get_performance_metrics() → _get_performance_metrics() 변환

Phase 3: deprecated 함수를 private 내부 헬퍼로 전환

변경사항:
- get_performance_metrics() → _get_performance_metrics() 리네임
- DeprecationWarning 제거 (내부용이므로 불필요)
- track_function_performance 데코레이터 내부 호출 업데이트
- 전역 metrics 객체 초기화 업데이트
- TDD 기반 테스트 추가 (test_metrics_internal.py)

효과:
- 외부 공개 API에서 deprecated 함수 완전 제거
- 모듈 내부 기능 정상 유지
- DI Container가 유일한 공개 API로 확립

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
EOF
)"
```

---

## 체크리스트

### RED Phase (테스트 먼저)
- [ ] `tests/unit/lib/test_metrics_internal.py` 생성
- [ ] 테스트 실행하여 실패 확인

### GREEN Phase (최소 구현)
- [ ] `get_performance_metrics` → `_get_performance_metrics` 리네임
- [ ] deprecation 경고 코드 제거
- [ ] 데코레이터 내부 호출 수정 (line 272)
- [ ] 전역 객체 초기화 수정 (line 293)
- [ ] 테스트 통과 확인

### REFACTOR Phase (정리)
- [ ] 전체 테스트 통과 확인 (`make test`)
- [ ] 외부 사용처 없음 확인
- [ ] 문서 업데이트
- [ ] 커밋 및 푸시

---

## 위험 요소 및 완화

| 위험 | 영향도 | 완화 방안 |
|------|--------|----------|
| 외부에서 직접 import | 낮음 | 이미 deprecated 경고로 DI 사용 안내됨 |
| 테스트 실패 | 낮음 | TDD로 사전 검증 |
| 문서 불일치 | 낮음 | 동시 업데이트 |

---

## 예상 결과

```
✅ app/lib/metrics.py - private 함수로 변환 (-35줄, docstring 간소화)
✅ tests/unit/lib/test_metrics_internal.py - 신규 테스트 추가
✅ docs/TECHNICAL_DEBT_ANALYSIS.md - v1.0.7 업데이트
✅ 전체 테스트 통과 (1,288개 + 신규)
✅ 기술부채 Zero 상태 유지
```
