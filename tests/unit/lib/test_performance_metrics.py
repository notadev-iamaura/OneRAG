"""
PerformanceMetrics 결함 회귀 테스트

P0: get_all_stats() 자기 데드락
    - get_all_stats()가 비재진입 Lock을 잡은 채 get_stats()를 재호출하여
      같은 Lock을 중복 획득 → function_metrics가 비어있지 않으면 영구 데드락.

P1: error_rate 누적/윈도우 불일치
    - record_latency는 함수별 최근 100건 윈도우만 유지하는데
      error_counts는 무한 누적되어 error_rate가 100%를 초과 가능.
    - 에러만 기록된 함수는 get_all_stats 결과에서 통째로 누락.
"""

from __future__ import annotations

import inspect
import threading
from typing import Any

import pytest

from app.lib.metrics import PerformanceMetrics


class TestGetAllStatsDeadlock:
    """P0: get_all_stats()가 데드락 없이 즉시 반환되는지 검증"""

    def test_데이터가_있을_때_get_all_stats가_즉시_반환됨(self) -> None:
        """
        record_latency 1건 기록 후 get_all_stats() 호출 시
        비재진입 Lock 중복 획득으로 인한 영구 데드락이 없어야 한다.

        별도 데몬 스레드에서 호출하고 join(timeout=5)으로 검증하여
        데드락이 발생해도 테스트 자체는 행이 걸리지 않도록 한다.
        """
        pm = PerformanceMetrics()
        pm.record_latency("fn_a", 12.5)

        result: dict[str, Any] = {}

        def call_get_all_stats() -> None:
            # 데드락 시 이 스레드는 영원히 블록되고 join 타임아웃으로 감지된다
            result["stats"] = pm.get_all_stats()

        worker = threading.Thread(target=call_get_all_stats, daemon=True)
        worker.start()
        worker.join(timeout=5)

        assert not worker.is_alive(), "get_all_stats()가 5초 내 반환되지 않음 (자기 데드락)"
        assert "fn_a" in result["stats"]
        assert result["stats"]["fn_a"]["count"] == 1


class TestCallCountsCumulative:
    """P1-1: 함수별 누적 호출 카운터가 윈도우와 별개로 유지되는지 검증"""

    def test_total_calls는_윈도우와_별개로_무한_누적(self) -> None:
        """
        150건 기록 시 윈도우 count는 100(최근 100건)으로 잘리지만
        total_calls(누적)는 150이어야 한다.
        """
        pm = PerformanceMetrics()
        for i in range(150):
            pm.record_latency("fn_many", float(i))

        stats = pm.get_stats("fn_many")
        assert stats["count"] == 100, "윈도우 크기(최근 100건)는 호환성을 위해 유지되어야 함"
        assert stats["total_calls"] == 150, "누적 호출 수는 윈도우와 별개로 무한 누적되어야 함"

    def test_reset_시_누적_카운터도_초기화(self) -> None:
        """reset() 호출 시 call_counts도 함께 초기화되어야 한다."""
        pm = PerformanceMetrics()
        pm.record_latency("fn_reset", 1.0)
        pm.record_error("fn_reset")
        pm.reset()

        stats = pm.get_stats("fn_reset")
        assert stats["total_calls"] == 0
        assert stats["errors"] == 0
        assert pm.get_all_stats() == {}


class TestErrorOnlyFunctionIncluded:
    """P1-2: 에러만 기록된 함수도 get_all_stats 결과에 포함되는지 검증"""

    def test_에러만_있는_함수도_get_all_stats에_포함(self) -> None:
        """
        성공 호출(record_latency) 없이 에러만 기록된 함수는
        function_metrics에 키가 없어 기존 구현에서 통째로 누락되던 결함 회귀 방지.
        """
        pm = PerformanceMetrics()
        pm.record_error("fn_error_only")

        all_stats = pm.get_all_stats()
        assert "fn_error_only" in all_stats, "에러 전용 함수가 get_all_stats에서 누락됨"

        stats = all_stats["fn_error_only"]
        assert stats["errors"] == 1
        assert stats["count"] == 0
        assert stats["total_calls"] == 0
        # latencies가 없으므로 통계값은 모두 0이어야 한다
        assert stats["avg_latency_ms"] == 0
        assert stats["min_latency_ms"] == 0
        assert stats["max_latency_ms"] == 0
        assert stats["p95_latency_ms"] == 0


class TestErrorRateBounded:
    """P1-3: 장기 운영 시 error_rate가 100%를 초과하지 않는지 검증"""

    def test_윈도우_초과_후에도_error_rate가_100을_넘지_않음(self) -> None:
        """
        성공 150건(윈도우는 100건만 유지) + 에러 120건 시나리오.

        구 계산식(total_errors / 윈도우 count * 100)은 120/100*100 = 120%로 결함.
        신 계산식(total_errors / (누적 total_calls + total_errors) * 100)은
        120/(150+120)*100 ≈ 44.4%로 항상 100% 이하여야 한다.
        """
        pm = PerformanceMetrics()
        for _ in range(150):
            pm.record_latency("fn_busy", 10.0)
        for _ in range(120):
            pm.record_error("fn_busy")

        # admin.get_realtime_metrics의 집계식 재현
        all_stats = pm.get_all_stats()
        func_stats = [
            s for s in all_stats.values() if isinstance(s, dict) and "avg_latency_ms" in s
        ]
        total_calls = sum(s.get("total_calls", 0) for s in func_stats)
        total_errors = sum(s.get("errors", 0) for s in func_stats)

        assert total_calls == 150
        assert total_errors == 120

        # 에러 발생 호출은 record_latency 미호출 → 분모 = 성공(누적) + 에러
        error_rate = total_errors / (total_calls + total_errors) * 100
        assert error_rate <= 100.0
        assert error_rate == pytest.approx(120 / 270 * 100)

    def test_admin이_누적_분모_계산식을_사용(self) -> None:
        """
        admin.get_realtime_metrics가 구 결함 계산식(윈도우 count 분모)을 제거하고
        누적 total_calls + total_errors 분모를 사용하는지 소스 검증.
        (test_cost_tracking_chain.py와 동일한 소스 검사 패턴)
        """
        from app.api import admin

        source = inspect.getsource(admin.get_realtime_metrics)
        assert "total_errors / total_calls * 100" not in source, (
            "구 결함 계산식(윈도우 count 분모)이 남아 있음"
        )
        assert "total_calls + total_errors" in source, (
            "error_rate 분모에 성공(누적) + 에러 합산이 필요함"
        )
