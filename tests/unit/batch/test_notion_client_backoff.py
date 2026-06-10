"""
NotionAPIClient._request_with_backoff 특성 테스트 (characterization test)

목적:
- tenacity 이관 전후로 ``_request_with_backoff``의 **현재 동작을 고정**합니다.
- 단언 대상: 각 입력/응답코드/예외에 대해
  (1) 재시도 횟수, (2) 각 시도의 ``asyncio.sleep`` 대기 시퀀스,
  (3) 최종 반환값 또는 발생 예외 타입.

테스트 전략:
- 실제 HTTP를 호출하지 않도록 ``client.get/post/...``를 ``AsyncMock``으로 대체합니다.
- 시간 단축을 위해 ``asyncio.sleep``을 monkeypatch하여 호출 인자(대기 시간)를 기록만 합니다.

동작 보존 기준 (이관 후에도 유지되어야 함):
- 429: 지수 백오프 base ``BASE_DELAY * 2^(attempt)`` → 1, 2, 4, 8초 (재시도 대기)
- TimeoutException: 고정 ``BASE_DELAY``(1.0초) 대기 후 재시도
- 401: 즉시 NotionAuthError (재시도/대기 없음)
- 404: 즉시 NotionNotFoundError (재시도/대기 없음)
- 기타 status: 즉시 NotionAPIError (재시도/대기 없음)
- RequestError: 즉시 NotionAPIError (재시도/대기 없음)
- 최대 재시도(5) 소진 시: NotionRateLimitError

tenacity 이관 시 의도된 동작 차이 (외부 관찰 동작은 보존):
- jitter 추가: 정확한 대기 값 → ``[base, base + 0.5)`` 범위.
- 마지막(5번째) 시도 실패 후의 불필요한 대기 제거: 기존 코드는 마지막 시도
  후에도 한 번 더 sleep한 뒤 예외를 던졌으나(무의미한 지연), tenacity는
  마지막 시도 실패 즉시 예외를 던집니다. 시도 횟수(5)와 최종 예외는 동일하므로
  호출자 관점의 동작(반환값/예외 타입)은 보존되며, 불필요한 대기만 제거됩니다.
  → 재시도 대기 횟수는 5 → 4로 감소.
"""

from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest

from app.batch.notion_client import (
    NotionAPIClient,
    NotionAPIError,
    NotionAuthError,
    NotionNotFoundError,
    NotionRateLimitError,
)

# jitter 범위: BACKOFF_JITTER 도입 후 각 대기는 [base, base + JITTER) 범위.
# (단, 지수 백오프 base는 max=inf이므로 상한 캡 없음)
_JITTER = 0.5


def _assert_wait_sequence(waits: list[float], expected_bases: list[float]) -> None:
    """
    재시도 대기 시퀀스가 기대 base 시퀀스와 일치하는지 jitter 범위로 검증.

    동작 보존 단언: 각 대기는 ``[base, base + _JITTER)`` 범위에 있어야 함.
    """
    assert len(waits) == len(expected_bases), (
        f"재시도 횟수 불일치: 실제 {waits}, 기대 base {expected_bases}"
    )
    for actual, base in zip(waits, expected_bases, strict=True):
        assert base <= actual < base + _JITTER, (
            f"대기 {actual}가 [{base}, {base + _JITTER}) 범위를 벗어남"
        )


def _make_response(status_code: int, json_body: dict | None = None, text: str = "") -> Any:
    """httpx.Response 흉내 객체 생성"""
    resp = AsyncMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json = lambda: (json_body or {})  # type: ignore[assignment]
    resp.text = text
    return resp


@pytest.fixture
def sleep_recorder(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """
    재시도 대기 시간(asyncio.sleep 호출 인자)을 기록하는 픽스처

    tenacity의 ``AsyncRetrying``은 내부적으로 ``asyncio.sleep``을 동적 참조하므로
    전역 ``asyncio.sleep``을 교체해 대기 시퀀스를 기록합니다.
    """
    import asyncio

    waits: list[float] = []

    async def _fake_sleep(seconds: float, *args: Any, **kwargs: Any) -> None:
        waits.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", _fake_sleep)
    return waits


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> NotionAPIClient:
    """API 키 검증을 우회한 클라이언트"""
    monkeypatch.setenv("NOTION_API_KEY", "test-key")
    return NotionAPIClient(api_key="test-key")


def _patch_client_http(
    client: NotionAPIClient, monkeypatch: pytest.MonkeyPatch, get_mock: AsyncMock
) -> None:
    """_get_client가 반환하는 httpx 클라이언트의 get을 mock으로 교체"""
    fake_http = AsyncMock()
    fake_http.get = get_mock
    fake_http.post = get_mock
    fake_http.patch = get_mock
    fake_http.delete = get_mock

    async def _get_client() -> Any:
        return fake_http

    monkeypatch.setattr(client, "_get_client", _get_client)


@pytest.mark.asyncio
async def test_success_returns_json_no_sleep(
    client: NotionAPIClient, monkeypatch: pytest.MonkeyPatch, sleep_recorder: list[float]
) -> None:
    """200 응답: 즉시 JSON 반환, 대기 없음"""
    get_mock = AsyncMock(return_value=_make_response(200, {"ok": True}))
    _patch_client_http(client, monkeypatch, get_mock)

    result = await client._request_with_backoff("GET", "https://x")

    assert result == {"ok": True}
    assert sleep_recorder == []
    assert get_mock.call_count == 1


@pytest.mark.asyncio
async def test_429_exponential_backoff_then_rate_limit_error(
    client: NotionAPIClient, monkeypatch: pytest.MonkeyPatch, sleep_recorder: list[float]
) -> None:
    """429 반복: 1,2,4,8,16초 지수 백오프 후 NotionRateLimitError"""
    get_mock = AsyncMock(return_value=_make_response(429))
    _patch_client_http(client, monkeypatch, get_mock)

    with pytest.raises(NotionRateLimitError):
        await client._request_with_backoff("GET", "https://x")

    # MAX_RETRIES=5번 시도, 4번 재시도 대기 (마지막 시도 후엔 대기 없이 stop)
    # base 시퀀스: 1,2,4,8 (각 [base, base+jitter) 범위)
    assert get_mock.call_count == 5
    _assert_wait_sequence(sleep_recorder, [1.0, 2.0, 4.0, 8.0])


@pytest.mark.asyncio
async def test_429_then_200_recovers(
    client: NotionAPIClient, monkeypatch: pytest.MonkeyPatch, sleep_recorder: list[float]
) -> None:
    """429 두 번 후 200: 1,2초 대기 후 성공 반환"""
    responses = [
        _make_response(429),
        _make_response(429),
        _make_response(200, {"recovered": True}),
    ]
    get_mock = AsyncMock(side_effect=responses)
    _patch_client_http(client, monkeypatch, get_mock)

    result = await client._request_with_backoff("GET", "https://x")

    assert result == {"recovered": True}
    _assert_wait_sequence(sleep_recorder, [1.0, 2.0])
    assert get_mock.call_count == 3


@pytest.mark.asyncio
async def test_timeout_fixed_backoff(
    client: NotionAPIClient, monkeypatch: pytest.MonkeyPatch, sleep_recorder: list[float]
) -> None:
    """TimeoutException 반복: 고정 1.0초 대기 후 NotionRateLimitError"""
    get_mock = AsyncMock(side_effect=httpx.TimeoutException("timed out"))
    _patch_client_http(client, monkeypatch, get_mock)

    with pytest.raises(NotionRateLimitError):
        await client._request_with_backoff("GET", "https://x")

    # 5번 시도, 재시도 대기 4번 (마지막 시도 후엔 stop, 대기 없음)
    # 고정 BASE_DELAY=1.0초 (각 [1.0, 1.0+jitter) 범위)
    assert get_mock.call_count == 5
    _assert_wait_sequence(sleep_recorder, [1.0, 1.0, 1.0, 1.0])


@pytest.mark.asyncio
async def test_timeout_then_200_recovers(
    client: NotionAPIClient, monkeypatch: pytest.MonkeyPatch, sleep_recorder: list[float]
) -> None:
    """Timeout 한 번 후 200: 1.0초 대기 후 성공"""
    get_mock = AsyncMock(
        side_effect=[
            httpx.TimeoutException("t"),
            _make_response(200, {"ok": 1}),
        ]
    )
    _patch_client_http(client, monkeypatch, get_mock)

    result = await client._request_with_backoff("GET", "https://x")

    assert result == {"ok": 1}
    _assert_wait_sequence(sleep_recorder, [1.0])


@pytest.mark.asyncio
async def test_401_immediate_auth_error(
    client: NotionAPIClient, monkeypatch: pytest.MonkeyPatch, sleep_recorder: list[float]
) -> None:
    """401: 즉시 NotionAuthError, 재시도/대기 없음"""
    get_mock = AsyncMock(return_value=_make_response(401))
    _patch_client_http(client, monkeypatch, get_mock)

    with pytest.raises(NotionAuthError):
        await client._request_with_backoff("GET", "https://x")

    assert get_mock.call_count == 1
    assert sleep_recorder == []


@pytest.mark.asyncio
async def test_404_immediate_not_found(
    client: NotionAPIClient, monkeypatch: pytest.MonkeyPatch, sleep_recorder: list[float]
) -> None:
    """404: 즉시 NotionNotFoundError, 재시도/대기 없음"""
    get_mock = AsyncMock(return_value=_make_response(404))
    _patch_client_http(client, monkeypatch, get_mock)

    with pytest.raises(NotionNotFoundError):
        await client._request_with_backoff("GET", "https://x")

    assert get_mock.call_count == 1
    assert sleep_recorder == []


@pytest.mark.asyncio
async def test_500_immediate_api_error(
    client: NotionAPIClient, monkeypatch: pytest.MonkeyPatch, sleep_recorder: list[float]
) -> None:
    """기타 status(500): 즉시 NotionAPIError, 재시도/대기 없음"""
    get_mock = AsyncMock(return_value=_make_response(500, text="server error"))
    _patch_client_http(client, monkeypatch, get_mock)

    with pytest.raises(NotionAPIError) as exc_info:
        await client._request_with_backoff("GET", "https://x")

    # 메시지에 status와 본문 포함 (의미 보존)
    assert "500" in str(exc_info.value)
    assert get_mock.call_count == 1
    assert sleep_recorder == []


@pytest.mark.asyncio
async def test_request_error_immediate_api_error(
    client: NotionAPIClient, monkeypatch: pytest.MonkeyPatch, sleep_recorder: list[float]
) -> None:
    """RequestError(타임아웃 외 연결 오류): 즉시 NotionAPIError, 재시도/대기 없음"""
    get_mock = AsyncMock(side_effect=httpx.ConnectError("conn refused"))
    _patch_client_http(client, monkeypatch, get_mock)

    with pytest.raises(NotionAPIError):
        await client._request_with_backoff("GET", "https://x")

    assert get_mock.call_count == 1
    assert sleep_recorder == []


@pytest.mark.asyncio
async def test_unsupported_method_raises_value_error(
    client: NotionAPIClient, monkeypatch: pytest.MonkeyPatch, sleep_recorder: list[float]
) -> None:
    """
    지원하지 않는 HTTP 메서드: ValueError 발생.

    현재 동작: ValueError는 try 블록 내부에서 발생하지만 httpx 예외가 아니므로
    except 절에 걸리지 않고 그대로 전파됩니다.
    """
    get_mock = AsyncMock(return_value=_make_response(200))
    _patch_client_http(client, monkeypatch, get_mock)

    with pytest.raises(ValueError):
        await client._request_with_backoff("OPTIONS", "https://x")

    assert sleep_recorder == []
