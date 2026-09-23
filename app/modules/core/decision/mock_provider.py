"""네트워크 없이 Noul 성공/실패/지연을 재현하는 provider."""

import asyncio
import time
from collections.abc import Sequence
from typing import Any

from .interfaces import DecisionStatus, NoulResult


class MockDecisionProvider:
    """고정값 또는 순차 결과를 반환하며 마지막 순차 결과를 반복한다."""

    name = "mock"

    def __init__(
        self,
        probability: float = 0.9,
        *,
        status: DecisionStatus = "ok",
        delay_s: float = 0.0,
        error: Exception | None = None,
        sequence: Sequence[float | NoulResult | Exception] | None = None,
    ) -> None:
        self.probability = probability
        self.status = status
        self.delay_s = delay_s
        self.error = error
        self.sequence = list(sequence or [])
        self.calls: list[dict[str, Any]] = []

    async def noul(
        self, *, instructions: str, state: str | dict[str, Any], timeout_s: float
    ) -> NoulResult:
        """호출을 기록한 후 설정한 결과나 테스트용 예외를 전달한다."""
        started = time.perf_counter()
        index = len(self.calls)
        self.calls.append({"instructions": instructions, "state": state, "timeout_s": timeout_s})
        if self.delay_s:
            await asyncio.sleep(self.delay_s)
        if self.error is not None:
            raise self.error
        value = self.sequence[min(index, len(self.sequence) - 1)] if self.sequence else self.probability
        if isinstance(value, Exception):
            raise value
        if isinstance(value, NoulResult):
            return value
        return NoulResult(
            probability=value if self.status == "ok" else None,
            status=self.status,
            latency_ms=(time.perf_counter() - started) * 1000,
            provider=self.name,
        )

    async def aclose(self) -> None:
        """Mock은 정리할 외부 자원이 없다."""
