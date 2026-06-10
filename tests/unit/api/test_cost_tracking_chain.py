"""
비용 추적 사슬 정합성 테스트 (Phase 2.5)

목적:
    비용 추적이 3중으로 끊겨 항상 0이던 결함을 회귀 방지한다.
    (1) generator가 실제 provider를 기록, (2) cost_tracker가 단일 인스턴스로
    공유, (3) admin이 실제 비용을 읽고 가짜 random을 쓰지 않음.
"""

from __future__ import annotations

import inspect

from app.lib.metrics import CostTracker


def test_cost_tracker_computes_nonzero_cost() -> None:
    """metrics.CostTracker는 google provider의 비용을 실제로 계산해야 한다."""
    ct = CostTracker()
    ct.track_usage("google", 1_000_000, is_input=False)
    summary = ct.get_summary()
    assert summary["total_cost_usd"] > 0, "비용이 계산되지 않음 (총 비용 0)"
    assert summary["total_tokens"] == 1_000_000


def test_modules_dict_includes_cost_tracker() -> None:
    """get_modules_dict가 cost_tracker/performance_metrics를 노출해야 한다."""
    import main

    source = inspect.getsource(main.RAGChatbotApp.get_modules_dict)
    assert '"cost_tracker"' in source, "modules_dict에 cost_tracker 키 누락"
    assert '"performance_metrics"' in source


def test_generator_records_real_provider() -> None:
    """generator가 하드코딩된 'openrouter' 대신 self.provider를 기록해야 한다."""
    from app.modules.core.generation import generator

    source = inspect.getsource(generator.GenerationModule._generate_with_model)
    assert "provider=self.provider" in source
    assert 'provider="openrouter"' not in source


def test_admin_reads_real_cost_and_no_random() -> None:
    """admin이 cost get_summary를 읽고 가짜 random 메트릭을 쓰지 않아야 한다."""
    from app.api import admin

    source = inspect.getsource(admin.get_realtime_metrics)
    assert "get_summary" in source
    assert "random.randint" not in source, "가짜 random 메트릭이 남아 있음"
    assert "random.uniform" not in source, "가짜 random 메트릭이 남아 있음"
