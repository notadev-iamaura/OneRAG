"""
metrics.py 내부 함수 테스트

Phase 3: get_performance_metrics() → _get_performance_metrics() 리팩토링 검증
"""

import warnings

import pytest


class TestGetPerformanceMetricsDeprecation:
    """get_performance_metrics 함수의 deprecated 상태 테스트"""

    def test_공개_함수가_존재하지_않음(self):
        """
        공개 API에서 get_performance_metrics가 제거되었는지 확인

        Phase 3 완료 후 이 테스트는 통과해야 함
        """
        from app.lib import metrics

        # 공개 함수가 존재하면 안 됨
        assert not hasattr(metrics, "get_performance_metrics"), (
            "get_performance_metrics()는 public API에서 제거되어야 합니다"
        )

    def test_private_함수가_존재함(self):
        """
        private 함수 _get_performance_metrics가 존재하는지 확인
        """
        from app.lib import metrics

        # private 함수는 존재해야 함
        assert hasattr(metrics, "_get_performance_metrics"), (
            "_get_performance_metrics() private 함수가 있어야 합니다"
        )

    def test_private_함수는_deprecation_경고_없음(self):
        """
        private 함수 호출 시 DeprecationWarning이 발생하지 않아야 함
        """
        from app.lib.metrics import PerformanceMetrics, _get_performance_metrics

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result = _get_performance_metrics()

            # DeprecationWarning이 없어야 함
            deprecation_warnings = [
                warning
                for warning in w
                if issubclass(warning.category, DeprecationWarning)
            ]
            assert len(deprecation_warnings) == 0, (
                "private 함수는 deprecation 경고가 없어야 합니다"
            )

        # 유효한 인스턴스 반환 확인
        assert isinstance(result, PerformanceMetrics)


class TestTrackFunctionPerformanceDecorator:
    """track_function_performance 데코레이터가 정상 작동하는지 확인"""

    @pytest.mark.asyncio
    async def test_데코레이터가_메트릭을_기록함(self):
        """
        데코레이터 적용 함수 호출 시 메트릭이 기록되어야 함
        """
        from app.lib.metrics import _get_performance_metrics, track_function_performance

        @track_function_performance("test_decorator_function")
        async def sample_function():
            return "success"

        # 함수 실행
        result = await sample_function()

        assert result == "success"

        # 메트릭 확인
        metrics = _get_performance_metrics()
        stats = metrics.get_stats("test_decorator_function")
        assert stats["count"] >= 1

    @pytest.mark.asyncio
    async def test_데코레이터가_에러를_기록함(self):
        """
        데코레이터 적용 함수에서 예외 발생 시 에러 카운트 증가
        """
        from app.lib.metrics import _get_performance_metrics, track_function_performance

        @track_function_performance("test_error_function")
        async def failing_function():
            raise ValueError("테스트 에러")

        # 초기 에러 카운트 확인
        metrics = _get_performance_metrics()
        initial_errors = metrics.error_counts.get("test_error_function", 0)

        # 함수 실행 (예외 발생)
        with pytest.raises(ValueError):
            await failing_function()

        # 에러 카운트 증가 확인
        final_errors = metrics.error_counts.get("test_error_function", 0)
        assert final_errors == initial_errors + 1


class TestGlobalMetricsObject:
    """전역 metrics 객체가 정상 초기화되는지 확인"""

    def test_전역_metrics_객체가_유효함(self):
        """
        모듈 레벨 metrics 객체가 PerformanceMetrics 인스턴스인지 확인
        """
        from app.lib.metrics import PerformanceMetrics, metrics

        assert isinstance(metrics, PerformanceMetrics)

    def test_전역_metrics와_private_함수가_동일_인스턴스(self):
        """
        전역 metrics 객체와 _get_performance_metrics() 반환값이 동일해야 함
        """
        from app.lib.metrics import _get_performance_metrics, metrics

        assert metrics is _get_performance_metrics()
