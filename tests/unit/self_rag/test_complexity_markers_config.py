"""ComplexityCalculator 마커 config 외부화 + 언어 중립 신호 테스트

깊이/다중의도 마커를 생성자 인자로 노출하고, 언어 중립 신호 보강을
토글로 추가한 변경을 검증한다.

핵심 요구사항:
1. (회귀 0) 마커 미설정 시 코드 내장 한국어 기본 마커를 사용한다.
2. (오버라이드) 마커 주입 시 비한국어 쿼리도 깊이/다중의도 점수를 받는다.
3. (회귀 0) 언어 중립 신호 보강은 기본 off — 켜기 전까지 한국어 점수 동치.
4. 언어 중립 신호 on 시 마커 미매칭 언어에서도 다중의도 점수가 보강된다.
"""

from __future__ import annotations

import pytest

from app.modules.core.routing.complexity_calculator import ComplexityCalculator


@pytest.mark.asyncio
async def test_depth_markers_default_korean() -> None:
    """마커 미설정 시 한국어 깊이 마커가 동작한다(회귀 0)."""
    calc = ComplexityCalculator()
    result = await calc.calculate("이 둘의 차이는 어떻게 비교하나요")
    assert result.depth_score > 0
    assert result.details["depth_indicators_found"] >= 2


@pytest.mark.asyncio
async def test_default_markers_score_zero_for_non_korean() -> None:
    """기본(한국어) 마커는 비한국어 쿼리에서 0점이다(현 동작 보존)."""
    calc = ComplexityCalculator()
    result = await calc.calculate("how to compare the difference and the price")
    assert result.depth_score == 0.0
    assert result.multi_intent_score == 0.0


@pytest.mark.asyncio
async def test_markers_override_for_english() -> None:
    """마커 주입 시 영어 쿼리도 깊이/다중의도 점수를 받는다."""
    calc = ComplexityCalculator(
        depth_indicators=["how", "why", "compare", "difference"],
        multi_intent_indicators=["and", "or", "also"],
    )
    result = await calc.calculate("how to compare the difference and the cost")
    assert result.depth_score > 0
    assert result.multi_intent_score > 0


@pytest.mark.asyncio
async def test_language_neutral_signals_off_by_default() -> None:
    """언어 중립 신호는 기본 off — 한국어 점수가 켰을 때보다 작거나 같다(회귀 0)."""
    base = ComplexityCalculator()
    on = ComplexityCalculator(use_language_neutral_signals=True)

    # 물음표가 있는 한국어 쿼리: off는 다중의도 마커가 없어 0
    base_res = await base.calculate("차이가 뭔가요?")
    on_res = await on.calculate("차이가 뭔가요?")
    assert base_res.multi_intent_score == 0.0
    assert on_res.multi_intent_score > 0.0


@pytest.mark.asyncio
async def test_language_neutral_signals_help_non_korean() -> None:
    """언어 중립 신호 on 시 마커 미매칭 영어 쿼리도 다중의도 점수를 받는다."""
    calc = ComplexityCalculator(use_language_neutral_signals=True)
    # 마커는 한국어 기본이라 미매칭이지만, 세미콜론/and/물음표 신호로 보강됨
    result = await calc.calculate("explain A and B; is that ok?")
    assert result.multi_intent_score > 0.0
