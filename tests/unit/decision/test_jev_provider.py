"""실제 네트워크 없이 System One 요청/응답 및 fail-open 계약 검증."""

import json

import httpx
import pytest

from app.modules.core.decision import JevDecisionProvider

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize("state", ["query/context/answer", {"query": "q", "context": "c", "answer": "a"}])
async def test_systemone_request_and_noul_response(state):
    calls = []

    def handler(request):
        calls.append(request)
        assert request.method == "POST"
        assert str(request.url) == "https://api.typesafe.ai/v1/systemone"
        assert request.headers["Authorization"] == "Bearer test-key"
        assert request.headers["Content-Type"] == "application/json"
        assert json.loads(request.content) == {
            "state": state,
            "model": "jev-latest",
            "questions": {"grounded": {"type": "noul", "instructions": "Supported?"}},
        }
        assert request.extensions["timeout"]["read"] == 0.5
        return httpx.Response(200, json={"answers": {"grounded": {"type": "noul", "noul": 0.82}}})

    provider = JevDecisionProvider(api_key="test-key", transport=httpx.MockTransport(handler))
    try:
        result = await provider.noul(instructions="Supported?", state=state, timeout_s=0.5)
    finally:
        await provider.aclose()
    assert result.status == "ok"
    assert result.probability == 0.82
    assert result.provider == "jev"
    assert result.latency_ms >= 0
    assert len(calls) == 1


async def test_configurable_endpoint_model_and_environment_key(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "env-test-key")

    def handler(request):
        assert str(request.url) == "https://typesafe.example/proxy/v1/systemone"
        assert request.headers["Authorization"] == "Bearer env-test-key"
        assert json.loads(request.content)["model"] == "jev-test"
        return httpx.Response(200, json={"answers": {"grounded": {"noul": 1}}})

    provider = JevDecisionProvider(
        api_base="https://typesafe.example/proxy/",
        systemone_path="v1/systemone",
        model="jev-test",
        transport=httpx.MockTransport(handler),
    )
    try:
        result = await provider.noul(instructions="i", state="s", timeout_s=0.5)
    finally:
        await provider.aclose()
    assert result.status == "ok"
    assert result.probability == 1.0


@pytest.mark.parametrize(
    "body",
    [
        "not json",
        '[]',
        '{}',
        '{"probability": 0.1}',
        '{"answers": {"grounded": {"probability": 0.1}}}',
        '{"answers": null}',
        *[json.dumps({"answers": {"grounded": {"noul": p}}}) for p in
          [None, True, "0.1", -0.1, 1.7, float("nan"), float("inf"), {}, []]],
    ],
)
async def test_invalid_response_fails_open(body):
    provider = JevDecisionProvider(
        api_key="test-key",
        transport=httpx.MockTransport(lambda request: httpx.Response(200, content=body)),
    )
    try:
        result = await provider.noul(instructions="i", state="s", timeout_s=0.5)
    finally:
        await provider.aclose()
    assert result.status == "parse_error"
    assert result.probability is None


@pytest.mark.parametrize("status_code", [302, 401, 429, 500])
async def test_http_error_is_a_result(status_code):
    provider = JevDecisionProvider(
        api_key="test-key",
        transport=httpx.MockTransport(lambda request: httpx.Response(status_code)),
    )
    try:
        result = await provider.noul(instructions="i", state="s", timeout_s=0.5)
    finally:
        await provider.aclose()
    assert result.status == "http_error"
    assert result.probability is None
    assert result.error == f"HTTP {status_code}"


@pytest.mark.parametrize(
    ("exception_type", "status"),
    [(httpx.ReadTimeout, "timeout"), (httpx.ConnectError, "error"), (RuntimeError, "error")],
)
async def test_transport_errors_do_not_raise_or_expose_secrets(exception_type, status, capsys):
    secret = "private-test-key"

    def handler(request):
        raise exception_type(f"request contains {secret} and private context")

    provider = JevDecisionProvider(api_key=secret, transport=httpx.MockTransport(handler))
    try:
        result = await provider.noul(instructions="i", state="private context", timeout_s=0.5)
    finally:
        await provider.aclose()
    assert result.status == status
    assert result.probability is None
    captured = capsys.readouterr()
    assert secret not in repr(result) + captured.out + captured.err
    assert "private context" not in repr(result) + captured.out + captured.err


@pytest.mark.parametrize("api_key", [None, "", "   "])
async def test_missing_key_creates_no_client_and_makes_zero_http_calls(monkeypatch, api_key):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(500)

    provider = JevDecisionProvider(api_key=api_key, transport=httpx.MockTransport(handler))
    result = await provider.noul(instructions="i", state="s", timeout_s=0.5)
    assert result.status == "missing_api_key"
    assert result.probability is None
    assert calls == []
    assert provider._client is None
    await provider.aclose()


async def test_aclose_is_idempotent_and_noul_recreates_client():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"answers": {"grounded": {"noul": 0.8}}})

    provider = JevDecisionProvider(api_key="test-key", transport=httpx.MockTransport(handler))
    await provider.aclose()
    assert provider._client is None
    first = await provider.noul(instructions="i", state="s", timeout_s=0.5)
    old_client = provider._client
    assert first.status == "ok"
    assert old_client is not None and not old_client.is_closed
    await provider.aclose()
    assert old_client.is_closed and provider._client is None
    await provider.aclose()
    second = await provider.noul(instructions="i", state="s", timeout_s=0.5)
    assert second.status == "ok"
    assert provider._client is not old_client
    assert len(calls) == 2
    await provider.aclose()
