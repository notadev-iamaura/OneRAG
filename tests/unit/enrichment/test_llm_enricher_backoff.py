"""
LLMEnricher._call_llm_with_retry 특성 테스트 (characterization test)

목적:
- tenacity 이관 전후로 ``_call_llm_with_retry``의 **현재 동작을 고정**합니다.
- 단언 대상: (1) LLM 호출 횟수, (2) 재시도 대기 시퀀스, (3) 최종 반환값.

동작 보존 기준 (가장 미묘한 부분):
- ``APITimeoutError`` / ``APIError``: 지수 백오프 ``1.0 * 2^attempt`` → 1, 2, 4초 대기 후 재시도.
- 기타 ``Exception``: **break** (재시도 안 함) → 즉시 None 반환. 대기 없음.
- 빈 응답(falsy) 또는 파싱 실패(falsy result): **대기 없이** continue (재시도).
- 성공(truthy result): 즉시 결과 반환.
- 모든 재시도 실패 시: None 반환.

tenacity 이관 시 의도된 동작 차이 (외부 관찰 동작은 보존):
- jitter 추가: 정확한 대기 값 → ``[base, base + 0.5)`` 범위.
- 마지막(N번째) 시도 실패 후의 불필요한 대기 제거: 기존 코드는 마지막 시도 후에도
  한 번 더 sleep한 뒤 None을 반환했으나(무의미한 지연), tenacity는 마지막 시도 실패
  즉시 None을 반환합니다. 시도 횟수(max_retries)와 최종 반환값(None)은 동일하므로
  호출자 관점의 동작은 보존되며, 불필요한 대기만 제거됩니다.
  → max_retries=3 기준 예외 백오프 대기는 [1,2,4](3회) → [1,2](2회)로 감소.
- 핵심 보존 (변하지 않음): 기타 예외의 break(재시도 안 함)와 falsy result의 무대기 재시도.
- falsy result 재시도 시 tenacity는 ``asyncio.sleep(0.0)``을 호출합니다(즉시 반환,
  이벤트 루프 양보만). 기존 ``continue``는 sleep 자체를 호출하지 않았으나 의미상
  "대기 없음"은 동일하게 보존됩니다(대기 시간 = 0).
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from openai import APIError, APITimeoutError

from app.modules.core.enrichment.enrichers.llm_enricher import LLMEnricher
from app.modules.core.enrichment.schemas.enrichment_schema import EnrichmentConfig

# jitter 범위: 지수 백오프 base에 [0, JITTER) 추가.
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


def _make_timeout_error() -> APITimeoutError:
    """openai APITimeoutError 인스턴스 생성"""
    return APITimeoutError(request=None)  # type: ignore[arg-type]


def _make_api_error() -> APIError:
    """openai APIError 인스턴스 생성"""
    return APIError("api error", request=None, body=None)  # type: ignore[arg-type]


@pytest.fixture
def sleep_recorder(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """재시도 대기 시간을 기록하는 픽스처 (전역 asyncio.sleep 교체)"""
    import asyncio

    waits: list[float] = []

    async def _fake_sleep(seconds: float, *args: Any, **kwargs: Any) -> None:
        waits.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", _fake_sleep)
    return waits


@pytest.fixture
def enricher() -> LLMEnricher:
    """max_retries=3 enricher (실제 LLM 미초기화)"""
    config = EnrichmentConfig(max_retries=3)
    return LLMEnricher(config=config, openai_api_key="test-key")


@pytest.mark.asyncio
async def test_success_first_try_no_sleep(
    enricher: LLMEnricher, monkeypatch: pytest.MonkeyPatch, sleep_recorder: list[float]
) -> None:
    """첫 시도 성공: 결과 반환, 대기 없음"""
    monkeypatch.setattr(enricher, "_call_llm", AsyncMock(return_value="raw"))
    monkeypatch.setattr(
        enricher, "_parse_json_response", MagicMock(return_value={"k": "v"})
    )

    result = await enricher._call_llm_with_retry("sys", "user", timeout=10)

    assert result == {"k": "v"}
    assert sleep_recorder == []


@pytest.mark.asyncio
async def test_timeout_exponential_backoff_then_none(
    enricher: LLMEnricher, monkeypatch: pytest.MonkeyPatch, sleep_recorder: list[float]
) -> None:
    """APITimeoutError 반복: 1,2,4초 지수 백오프 후 None 반환 (3회)"""
    call_mock = AsyncMock(side_effect=_make_timeout_error())
    monkeypatch.setattr(enricher, "_call_llm", call_mock)
    monkeypatch.setattr(enricher, "_parse_json_response", MagicMock(return_value=None))

    result = await enricher._call_llm_with_retry("sys", "user", timeout=10)

    assert result is None
    # max_retries=3: 3회 모두 시도하되, 마지막 시도 후엔 대기 없이 None (불필요한 대기 제거)
    # 재시도 대기 base: 1,2 (각 [base, base+jitter) 범위)
    assert call_mock.call_count == 3
    _assert_wait_sequence(sleep_recorder, [1.0, 2.0])


@pytest.mark.asyncio
async def test_api_error_exponential_backoff_then_none(
    enricher: LLMEnricher, monkeypatch: pytest.MonkeyPatch, sleep_recorder: list[float]
) -> None:
    """APIError 반복: 1,2,4초 지수 백오프 후 None 반환"""
    call_mock = AsyncMock(side_effect=_make_api_error())
    monkeypatch.setattr(enricher, "_call_llm", call_mock)
    monkeypatch.setattr(enricher, "_parse_json_response", MagicMock(return_value=None))

    result = await enricher._call_llm_with_retry("sys", "user", timeout=10)

    assert result is None
    assert call_mock.call_count == 3
    _assert_wait_sequence(sleep_recorder, [1.0, 2.0])


@pytest.mark.asyncio
async def test_timeout_then_success(
    enricher: LLMEnricher, monkeypatch: pytest.MonkeyPatch, sleep_recorder: list[float]
) -> None:
    """APITimeoutError 한 번 후 성공: 1초 대기 후 결과 반환"""
    call_mock = AsyncMock(side_effect=[_make_timeout_error(), "raw"])
    monkeypatch.setattr(enricher, "_call_llm", call_mock)
    monkeypatch.setattr(
        enricher, "_parse_json_response", MagicMock(return_value={"ok": 1})
    )

    result = await enricher._call_llm_with_retry("sys", "user", timeout=10)

    assert result == {"ok": 1}
    _assert_wait_sequence(sleep_recorder, [1.0])
    assert call_mock.call_count == 2


@pytest.mark.asyncio
async def test_unexpected_exception_breaks_no_retry(
    enricher: LLMEnricher, monkeypatch: pytest.MonkeyPatch, sleep_recorder: list[float]
) -> None:
    """
    기타 Exception(ValueError): break → 즉시 None 반환, 대기/재시도 없음.

    이것이 가장 보존이 중요한 동작 — 특정 예외는 재시도하지 않습니다.
    """
    call_mock = AsyncMock(side_effect=ValueError("boom"))
    monkeypatch.setattr(enricher, "_call_llm", call_mock)
    monkeypatch.setattr(enricher, "_parse_json_response", MagicMock(return_value=None))

    result = await enricher._call_llm_with_retry("sys", "user", timeout=10)

    assert result is None
    assert call_mock.call_count == 1  # break 즉시
    assert sleep_recorder == []


@pytest.mark.asyncio
async def test_empty_response_continues_without_sleep(
    enricher: LLMEnricher, monkeypatch: pytest.MonkeyPatch, sleep_recorder: list[float]
) -> None:
    """
    빈 응답(None) 반복: 대기 없이 재시도, 모두 빈 응답이면 None 반환.

    현재 동작: 빈 응답은 ``continue`` (백오프 대기 없음).
    """
    call_mock = AsyncMock(return_value=None)
    monkeypatch.setattr(enricher, "_call_llm", call_mock)
    monkeypatch.setattr(enricher, "_parse_json_response", MagicMock(return_value=None))

    result = await enricher._call_llm_with_retry("sys", "user", timeout=10)

    assert result is None
    assert call_mock.call_count == 3  # max_retries=3 모두 시도
    # 무대기 재시도: tenacity는 wait=0.0으로 sleep(0.0)을 호출(즉시 반환, 이벤트 루프 양보).
    # 의미상 "대기 없음"이 보존됨 — 모든 대기가 0이어야 함.
    assert all(w == 0.0 for w in sleep_recorder)


@pytest.mark.asyncio
async def test_parse_failure_continues_without_sleep(
    enricher: LLMEnricher, monkeypatch: pytest.MonkeyPatch, sleep_recorder: list[float]
) -> None:
    """
    파싱 실패(falsy result) 반복: 대기 없이 재시도, 모두 실패면 None 반환.

    현재 동작: result가 falsy면 ``continue`` (백오프 대기 없음).
    """
    call_mock = AsyncMock(return_value="raw text")
    monkeypatch.setattr(enricher, "_call_llm", call_mock)
    # 파싱은 항상 None (falsy) 반환
    monkeypatch.setattr(enricher, "_parse_json_response", MagicMock(return_value=None))

    result = await enricher._call_llm_with_retry("sys", "user", timeout=10)

    assert result is None
    assert call_mock.call_count == 3
    # 무대기 재시도 (위 테스트와 동일): 모든 대기가 0.0
    assert all(w == 0.0 for w in sleep_recorder)
