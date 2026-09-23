"""검색/평가에서 재사용할 Noul 판단 provider 계약."""

from dataclasses import dataclass
from typing import Any, Literal, Protocol, runtime_checkable

DecisionStatus = Literal["ok", "timeout", "http_error", "parse_error", "missing_api_key", "error"]


@dataclass(frozen=True)
class NoulResult:
    """근거성 확률과 실패 상태를 예외 없이 전달하는 결과."""

    probability: float | None
    status: DecisionStatus
    latency_ms: float
    provider: str
    error: str | None = None


@runtime_checkable
class DecisionProvider(Protocol):
    """Noul 확률 판단 및 클라이언트 정리 인터페이스."""

    name: str

    async def noul(
        self, *, instructions: str, state: str | dict[str, Any], timeout_s: float
    ) -> NoulResult: ...

    async def aclose(self) -> None: ...
