"""ComplexityCalculator config 배선(데드 키 아님) 테스트

routing.yaml의 complexity.{depth_indicators, multi_intent_indicators,
use_language_neutral_signals} 가 di_container를 통해 ComplexityCalculator에
실제로 전달되는지(데드 키 아님) 검증한다.

또한 기본 config(키 = null/false)에서 마커가 한국어 기본값으로 폴백되어
기존 동작과 동치임(회귀 0)을 확인한다.
"""

from __future__ import annotations

from app.core.di_container import AppContainer
from app.lib.config_loader import load_config


def _build_calculator():
    container = AppContainer()
    container.config.from_dict(load_config())
    return container.complexity_calculator()


def test_complexity_calculator_built_from_di() -> None:
    """DI 경로에서 ComplexityCalculator가 생성된다(provider 배선 확인)."""
    calc = _build_calculator()
    assert calc is not None
    # 기본 config(null)에서 한국어 기본 마커로 폴백(회귀 0)
    assert "어떻게" in calc.depth_indicators
    assert "그리고" in calc.multi_intent_indicators
    # 언어 중립 신호는 기본 off(회귀 0)
    assert calc.use_language_neutral_signals is False


def test_complexity_markers_override_wired_from_config() -> None:
    """config로 마커를 주입하면 DI 경로에서 그 값이 전달된다(데드 키 아님)."""
    cfg = load_config()
    cfg.setdefault("routing", {}).setdefault("complexity", {})
    cfg["routing"]["complexity"]["depth_indicators"] = ["how", "why"]
    cfg["routing"]["complexity"]["multi_intent_indicators"] = ["and", "or"]
    cfg["routing"]["complexity"]["use_language_neutral_signals"] = True

    container = AppContainer()
    container.config.from_dict(cfg)
    calc = container.complexity_calculator()

    assert calc.depth_indicators == ["how", "why"]
    assert calc.multi_intent_indicators == ["and", "or"]
    assert calc.use_language_neutral_signals is True
