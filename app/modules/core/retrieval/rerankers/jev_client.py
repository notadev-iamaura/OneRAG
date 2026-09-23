"""Small HTTP client for TypeSafe Jev relevance decisions."""

from collections.abc import Iterable
from dataclasses import dataclass
from math import isfinite
from typing import Any

import httpx


class JevAPIError(Exception):
    """A Jev request or response could not be used."""

    def __init__(self, kind: str) -> None:
        self.kind = kind
        super().__init__(kind)


@dataclass(frozen=True)
class JevAnswer:
    probability: float
    confidence: float | None = None
    raw_type: str = "noul"


class TypeSafeJevClient:
    """Reuse one async client; an injected client remains owned by its caller."""

    def __init__(
        self,
        api_key: str,
        model: str = "jev-1.13.0",
        endpoint: str = "https://api.typesafe.ai/v1/systemone",
        timeout: float = 3.0,
        client: httpx.AsyncClient | None = None,
        score_scale_max: float = 1.0,
    ) -> None:
        self.model = model
        self.endpoint = endpoint
        self._api_key = api_key
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(timeout=timeout)
        self.score_scale_max = score_scale_max

    async def ask(
        self, state: dict[str, Any] | str, questions: dict[str, dict[str, Any]]
    ) -> dict[str, JevAnswer]:
        body = {"model": self.model, "state": state, "questions": questions}
        try:
            response = await self._client.post(
                self.endpoint,
                json=body,
                headers={"Authorization": f"Bearer {self._api_key}"},
            )
            response.raise_for_status()
            payload = response.json()
        except httpx.TimeoutException as exc:
            raise JevAPIError("timeout") from exc
        except httpx.HTTPStatusError as exc:
            raise JevAPIError(f"http_{exc.response.status_code}") from exc
        except httpx.HTTPError as exc:
            raise JevAPIError("transport") from exc
        except ValueError as exc:
            raise JevAPIError("decode") from exc
        return self._parse_answers(payload, questions.keys())

    def _parse_answers(
        self, payload: Any, names: Iterable[str]
    ) -> dict[str, JevAnswer]:
        if not isinstance(payload, dict):
            raise JevAPIError("unparseable")
        envelope = payload.get("answers", payload)
        if not isinstance(envelope, dict):
            raise JevAPIError("unparseable")

        parsed: dict[str, JevAnswer] = {}
        for name in names:
            raw = envelope.get(name, payload.get(name))
            if not isinstance(raw, dict):
                raise JevAPIError("unparseable")
            raw_type = raw.get("type")
            if raw_type is None:
                raw_type = "noul" if "noul" in raw else "score" if "score" in raw else None
            if raw_type not in ("noul", "score"):
                raise JevAPIError("unparseable")
            value = raw.get(raw_type)
            if not isinstance(value, (bool, int, float)):
                raise JevAPIError("unparseable")
            try:
                probability = float(value)
            except (OverflowError, ValueError) as exc:
                raise JevAPIError("unparseable") from exc
            if not isfinite(probability):
                raise JevAPIError("unparseable")
            if raw_type == "score":
                if self.score_scale_max <= 0:
                    raise JevAPIError("unparseable")
                probability /= self.score_scale_max
            probability = max(0.0, min(1.0, probability))
            confidence_raw = raw.get("confidence")
            confidence = None
            if isinstance(confidence_raw, (int, float)) and not isinstance(
                confidence_raw, bool
            ):
                try:
                    candidate = float(confidence_raw)
                    if isfinite(candidate):
                        confidence = candidate
                except (OverflowError, ValueError):
                    pass
            parsed[name] = JevAnswer(probability, confidence, raw_type)
        return parsed

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()
