"""TypeSafe System One HTTP API를 사용하는 Jev Noul 클라이언트."""

import math
import os
import time
from typing import Any

import httpx

from .interfaces import DecisionStatus, NoulResult


class JevDecisionProvider:
    """일반 오류는 결과로 반환한다. 호출자 태스크의 취소는 그대로 전파한다.

    POST /v1/systemone의 questions.grounded(type=noul)를 요청하고
    answers.grounded.noul만 읽는다. 키/상태/응답 본문은 로그에 남기지 않는다.
    """

    name = "jev"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        api_base: str = "https://api.typesafe.ai",
        systemone_path: str = "/v1/systemone",
        model: str = "jev-latest",
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._api_key = os.getenv("TYPESAFE_API_KEY", "") if api_key is None else api_key
        self.api_base = api_base
        self.systemone_path = systemone_path
        self.model = model
        self._transport = transport
        self._client: httpx.AsyncClient | None = None

    async def noul(
        self, *, instructions: str, state: str | dict[str, Any], timeout_s: float
    ) -> NoulResult:
        """근거성 확률을 요청하며 HTTP/파싱/설정 오류는 fail-open 상태로 반환한다."""
        started = time.perf_counter()

        def result(
            status: DecisionStatus, probability: float | None = None, error: str | None = None
        ) -> NoulResult:
            return NoulResult(
                probability=probability,
                status=status,
                latency_ms=(time.perf_counter() - started) * 1000,
                provider=self.name,
                error=error,
            )

        if not self._api_key or not self._api_key.strip():
            return result("missing_api_key")

        try:
            if self._client is None or self._client.is_closed:
                self._client = httpx.AsyncClient(transport=self._transport)
            response = await self._client.post(
                f"{self.api_base.rstrip('/')}/{self.systemone_path.lstrip('/')}",
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "state": state,
                    "model": self.model,
                    "questions": {"grounded": {"type": "noul", "instructions": instructions}},
                },
                timeout=timeout_s,
            )
            response.raise_for_status()
            try:
                value = response.json()["answers"]["grounded"]["noul"]
                # bool/문자열/NaN/범위 밖 값은 근거성 판단으로 사용하지 않는다.
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    return result("parse_error")
                probability = float(value)
                if not math.isfinite(probability) or not 0 <= probability <= 1:
                    return result("parse_error")
            except (ValueError, TypeError, KeyError, OverflowError):
                return result("parse_error")
            return result("ok", probability=probability)
        except httpx.TimeoutException:
            return result("timeout")
        except httpx.HTTPStatusError as exc:
            return result("http_error", error=f"HTTP {exc.response.status_code}")
        except Exception as exc:
            # 예외 메시지에는 URL/헤더/본문이 포함될 수 있으므로 타입만 보존한다.
            return result("error", error=type(exc).__name__)

    async def aclose(self) -> None:
        """생성된 HTTP 클라이언트를 정리한다."""
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
        self._client = None
