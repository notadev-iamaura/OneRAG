"""
SitemapConnector._safe_fetch_and_parse 특성 테스트 (characterization test)

목적:
- tenacity 이관 전후로 ``_safe_fetch_and_parse``의 **현재 동작을 고정**합니다.
- 단언 대상: (1) 재시도 횟수, (2) 각 재시도 대기 시퀀스, (3) 최종 반환값.

동작 보존 기준:
- ``(httpx.ConnectError, httpx.TimeoutException)``: 선형 백오프 ``(attempt+1)*2`` →
  2, 4초 대기 (max_retries=3 기준, attempt 0,1에서 대기, attempt 2는 마지막이라 None 반환).
- 마지막 시도 실패 시: ``None`` 반환 (예외 전파 없음).
- 그 외 예외(비재시도 대상): 즉시 ``None`` 반환 (대기 없음).
- 성공 시: 결과 반환.
- 세마포어: 동시 요청 수 제한 (``max_parallel`` 만큼만 동시 진입).
"""

from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest

from app.modules.ingestion.connectors.sitemap import SitemapConnector
from app.modules.ingestion.interfaces import StandardDocument

# jitter 범위: 선형 백오프 base에 [0, JITTER) 추가.
_JITTER = 0.5


def _assert_wait_sequence(waits: list[float], expected_bases: list[float]) -> None:
    """재시도 대기 시퀀스를 jitter 범위 ``[base, base + _JITTER)``로 검증."""
    assert len(waits) == len(expected_bases), (
        f"재시도 횟수 불일치: 실제 {waits}, 기대 base {expected_bases}"
    )
    for actual, base in zip(waits, expected_bases, strict=True):
        assert base <= actual < base + _JITTER, (
            f"대기 {actual}가 [{base}, {base + _JITTER}) 범위를 벗어남"
        )


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


def _make_doc(url: str) -> StandardDocument:
    """더미 StandardDocument 생성"""
    return StandardDocument(content="ok", source_url=url, metadata={})


@pytest.mark.asyncio
async def test_success_first_try_no_sleep(sleep_recorder: list[float]) -> None:
    """첫 시도 성공: 결과 반환, 대기 없음"""
    connector = SitemapConnector(url="https://x", max_retries=3)
    fetch_mock = AsyncMock(return_value=_make_doc("https://x/p"))
    connector._fetch_and_parse_page = fetch_mock  # type: ignore[method-assign]

    result = await connector._safe_fetch_and_parse("https://x/p")

    assert result is not None
    assert result.source_url == "https://x/p"
    assert sleep_recorder == []
    assert fetch_mock.call_count == 1


@pytest.mark.asyncio
async def test_retryable_all_fail_returns_none(sleep_recorder: list[float]) -> None:
    """ConnectError 반복: 선형 백오프 2,4초 후 None 반환 (3회 시도)"""
    connector = SitemapConnector(url="https://x", max_retries=3)
    fetch_mock = AsyncMock(side_effect=httpx.ConnectError("conn refused"))
    connector._fetch_and_parse_page = fetch_mock  # type: ignore[method-assign]

    result = await connector._safe_fetch_and_parse("https://x/p")

    assert result is None
    # max_retries=3: attempt 0,1에서 대기 (2,4), attempt 2는 마지막이라 대기 없이 None
    assert fetch_mock.call_count == 3
    _assert_wait_sequence(sleep_recorder, [2.0, 4.0])


@pytest.mark.asyncio
async def test_linear_sequence_extends_2_4_6(sleep_recorder: list[float]) -> None:
    """
    max_retries=4: 선형 백오프 2,4,6초 시퀀스 보존 검증.

    RetryPolicy(LINEAR) 이관 후에도 ``(attempt+1)*2`` 시퀀스가 유지되어야 합니다
    (increment_s 미지정 → initial_delay_s(2.0)와 동일 증가 폭).
    """
    connector = SitemapConnector(url="https://x", max_retries=4)
    fetch_mock = AsyncMock(side_effect=httpx.ConnectError("conn refused"))
    connector._fetch_and_parse_page = fetch_mock  # type: ignore[method-assign]

    result = await connector._safe_fetch_and_parse("https://x/p")

    assert result is None
    # 4회 시도, 재시도 대기 3번: base 2, 4, 6 (각 [base, base+jitter) 범위)
    assert fetch_mock.call_count == 4
    _assert_wait_sequence(sleep_recorder, [2.0, 4.0, 6.0])


@pytest.mark.asyncio
async def test_timeout_then_success(sleep_recorder: list[float]) -> None:
    """TimeoutException 한 번 후 성공: 2초 대기 후 결과 반환"""
    connector = SitemapConnector(url="https://x", max_retries=3)
    fetch_mock = AsyncMock(
        side_effect=[
            httpx.TimeoutException("t"),
            _make_doc("https://x/p"),
        ]
    )
    connector._fetch_and_parse_page = fetch_mock  # type: ignore[method-assign]

    result = await connector._safe_fetch_and_parse("https://x/p")

    assert result is not None
    _assert_wait_sequence(sleep_recorder, [2.0])
    assert fetch_mock.call_count == 2


@pytest.mark.asyncio
async def test_non_retryable_returns_none_immediately(sleep_recorder: list[float]) -> None:
    """비재시도 예외(ValueError): 즉시 None 반환, 대기/재시도 없음"""
    connector = SitemapConnector(url="https://x", max_retries=3)
    fetch_mock = AsyncMock(side_effect=ValueError("parse error"))
    connector._fetch_and_parse_page = fetch_mock  # type: ignore[method-assign]

    result = await connector._safe_fetch_and_parse("https://x/p")

    assert result is None
    assert fetch_mock.call_count == 1
    assert sleep_recorder == []


@pytest.mark.asyncio
async def test_semaphore_limits_concurrency() -> None:
    """
    세마포어: max_parallel=2일 때 동시 진입 최대 2개로 제한

    (sleep_recorder를 사용하지 않음 — asyncio.sleep(0) 양보가 필요하므로 patch 금지)
    """
    import asyncio

    connector = SitemapConnector(url="https://x", max_parallel=2, max_retries=1)

    concurrent = 0
    peak = 0
    gate = asyncio.Event()

    async def _slow_fetch(client: Any, url: str) -> StandardDocument:
        nonlocal concurrent, peak
        concurrent += 1
        peak = max(peak, concurrent)
        await gate.wait()
        concurrent -= 1
        return _make_doc(url)

    connector._fetch_and_parse_page = _slow_fetch  # type: ignore[method-assign]

    # 4개 동시 호출 시작
    tasks = [
        asyncio.create_task(connector._safe_fetch_and_parse(f"https://x/{i}"))
        for i in range(4)
    ]
    # 진입이 안정될 시간 확보
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    # 세마포어로 동시 진입은 max_parallel=2를 넘지 않아야 함
    gate.set()
    await asyncio.gather(*tasks)

    assert peak <= 2
