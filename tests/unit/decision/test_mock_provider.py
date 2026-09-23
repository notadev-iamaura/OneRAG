"""Mock provider의 고정값/상태/지연/예외/순차 결과 검증."""

import asyncio

import pytest

from app.modules.core.decision import (
    DecisionProvider,
    JevDecisionProvider,
    MockDecisionProvider,
    NoulResult,
    create_decision_provider,
)

pytestmark = pytest.mark.asyncio


async def test_fixed_probability_and_call_recording():
    provider = MockDecisionProvider(0.2)
    args = {"instructions": "Supported?", "state": {"answer": "a"}, "timeout_s": 0.5}
    result = await provider.noul(**args)
    assert result.probability == 0.2
    assert result.status == "ok"
    assert result.provider == "mock"
    assert provider.calls == [args]
    assert isinstance(provider, DecisionProvider)
    await provider.aclose()


@pytest.mark.parametrize("status", ["timeout", "http_error", "parse_error", "missing_api_key", "error"])
async def test_forced_status_has_no_probability(status):
    result = await MockDecisionProvider(status=status).noul(
        instructions="i", state="s", timeout_s=0.5
    )
    assert result.status == status
    assert result.probability is None


async def test_delay_can_be_cancelled_by_deadline():
    provider = MockDecisionProvider(delay_s=1)
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(provider.noul(instructions="i", state="s", timeout_s=0.01), 0.01)
    assert len(provider.calls) == 1


async def test_forced_exception():
    with pytest.raises(RuntimeError, match="forced"):
        await MockDecisionProvider(error=RuntimeError("forced")).noul(
            instructions="i", state="s", timeout_s=0.5
        )


async def test_sequence_includes_results_exceptions_and_repeats_last_value():
    failure = NoulResult(None, "timeout", 10, "mock")
    provider = MockDecisionProvider(sequence=[0.1, failure, ValueError("forced"), 0.8])
    args = {"instructions": "i", "state": "s", "timeout_s": 0.5}
    assert (await provider.noul(**args)).probability == 0.1
    assert await provider.noul(**args) is failure
    with pytest.raises(ValueError, match="forced"):
        await provider.noul(**args)
    assert (await provider.noul(**args)).probability == 0.8
    assert (await provider.noul(**args)).probability == 0.8


async def test_factory_creates_selected_provider_without_http():
    assert isinstance(create_decision_provider({"provider": "mock"}), MockDecisionProvider)
    jev = create_decision_provider({"provider": "jev", "api_key": ""})
    assert isinstance(jev, JevDecisionProvider)
    assert isinstance(jev, DecisionProvider)
    assert (await jev.noul(instructions="i", state="s", timeout_s=0.5)).status == "missing_api_key"
    await jev.aclose()
    with pytest.raises(ValueError, match="Unknown decision provider"):
        create_decision_provider({"provider": "bogus"})
