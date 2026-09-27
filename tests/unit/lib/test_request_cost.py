"""Tests for request-scoped token accounting."""

from app.lib.request_cost import (
    RequestCostLedger,
    bind_request_cost_ledger,
    get_current_ledger,
)


def test_ledger_accumulates_positive_usage() -> None:
    ledger = RequestCostLedger()
    ledger.add(prompt_tokens=10, completion_tokens=20)
    ledger.add(prompt_tokens=1, completion_tokens=2, total_tokens=5)
    ledger.add(total_tokens=0)
    ledger.add(total_tokens=-3)

    assert ledger.total_tokens == 35
    assert ledger.call_count == 2


def test_bound_ledger_is_restored_after_scope() -> None:
    assert get_current_ledger() is None
    with bind_request_cost_ledger() as ledger:
        assert get_current_ledger() is ledger
        with bind_request_cost_ledger() as nested:
            assert get_current_ledger() is nested
        assert get_current_ledger() is ledger
    assert get_current_ledger() is None
