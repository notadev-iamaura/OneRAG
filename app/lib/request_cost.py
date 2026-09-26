"""Request-scoped token accounting for LLM calls."""

from _thread import LockType
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from threading import Lock


@dataclass
class RequestCostLedger:
    """Accumulate token usage within one request."""

    total_tokens: int = 0
    call_count: int = 0
    _lock: LockType = field(default_factory=Lock, repr=False)

    def add(
        self,
        *,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        total_tokens: int = 0,
    ) -> None:
        tokens = total_tokens or (prompt_tokens + completion_tokens)
        if tokens <= 0:
            return
        with self._lock:
            self.total_tokens += tokens
            self.call_count += 1


_current_ledger: ContextVar[RequestCostLedger | None] = ContextVar(
    "_current_ledger", default=None
)


def get_current_ledger() -> RequestCostLedger | None:
    return _current_ledger.get()


@contextmanager
def bind_request_cost_ledger() -> Iterator[RequestCostLedger]:
    """Bind a fresh ledger to the current context for the duration of a request."""
    ledger = RequestCostLedger()
    token = _current_ledger.set(ledger)
    try:
        yield ledger
    finally:
        _current_ledger.reset(token)
