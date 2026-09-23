"""MockTransport tests for the Jev HTTP boundary."""

import json

import httpx
import pytest

from app.modules.core.retrieval.rerankers.jev_client import JevAPIError, TypeSafeJevClient


@pytest.mark.asyncio
async def test_request_shape_and_noul_float() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200, json={"answers": {"relevant": {"type": "noul", "noul": 0.83}}}
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = TypeSafeJevClient("test-key", client=http)
        answer = await client.ask(
            {"query": "q", "passage": "p"},
            {"relevant": {"type": "noul", "instructions": "judge"}},
        )
        assert answer["relevant"].probability == 0.83
        request = seen[0]
        assert str(request.url) == "https://api.typesafe.ai/v1/systemone"
        assert request.headers["Authorization"] == "Bearer test-key"
        assert json.loads(request.content) == {
            "model": "jev-1.13.0",
            "state": {"query": "q", "passage": "p"},
            "questions": {"relevant": {"type": "noul", "instructions": "judge"}},
        }
        await client.aclose()
        assert not http.is_closed


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"answers": {"relevant": {"type": "noul", "noul": True}}}, 1.0),
        ({"relevant": {"type": "noul", "noul": False}}, 0.0),
        ({"relevant": {"type": "noul", "noul": 1.4}}, 1.0),
        ({"answers": {"relevant": {"noul": 0.4}}}, 0.4),
    ],
)
async def test_tolerant_noul_parsing(payload: dict, expected: float) -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))
    ) as http:
        client = TypeSafeJevClient("key", client=http)
        answer = await client.ask({}, {"relevant": {"type": "noul", "instructions": "x"}})
        assert answer["relevant"].probability == expected


@pytest.mark.asyncio
async def test_score_normalization_and_confidence() -> None:
    payload = {"answers": {"relevant": {"type": "score", "score": 3, "confidence": 0.8}}}
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))
    ) as http:
        client = TypeSafeJevClient("key", client=http, score_scale_max=4)
        answer = await client.ask({}, {"relevant": {"type": "score", "instructions": "x"}})
        assert answer["relevant"].probability == 0.75
        assert answer["relevant"].confidence == 0.8


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("handler", "kind"),
    [
        (lambda _: httpx.Response(429), "http_429"),
        (lambda _: httpx.Response(200, text="not json"), "decode"),
        (lambda _: httpx.Response(200, json={"answers": {}}), "unparseable"),
    ],
)
async def test_bad_responses_map_to_error(handler, kind: str) -> None:
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = TypeSafeJevClient("key", client=http)
        with pytest.raises(JevAPIError) as error:
            await client.ask({}, {"relevant": {"type": "noul", "instructions": "x"}})
        assert error.value.kind == kind


@pytest.mark.asyncio
async def test_timeout_maps_to_error() -> None:
    def timeout(_: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timeout")

    async with httpx.AsyncClient(transport=httpx.MockTransport(timeout)) as http:
        client = TypeSafeJevClient("key", client=http)
        with pytest.raises(JevAPIError) as error:
            await client.ask({}, {"relevant": {"type": "noul", "instructions": "x"}})
        assert error.value.kind == "timeout"
