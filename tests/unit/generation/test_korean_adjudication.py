from unittest.mock import AsyncMock

import pytest

from app.modules.core.generation.korean_adjudication import (
    SUPPORT_THRESHOLD,
    adjudicate_korean_span,
)

DOC = {"id": "doc", "title": "결산", "content": "기초 예산은 8억원이다.확정 예산은 12억원이다. 다음 해에는 7억원을 지급한다."}


def span(answer: str) -> dict:
    body = DOC["content"]
    start = body.index(answer)
    return {"source_id": "doc", "answer": answer, "start": start, "end": start+len(answer),
            "quote": body, "quote_start": 0, "quote_end": len(body)}


@pytest.mark.asyncio
async def test_agreement_and_clear_refusal_need_no_call() -> None:
    model = AsyncMock()
    answer = span("12억원")
    assert await adjudicate_korean_span(model, "확정 예산은?", DOC, answer, answer, -5.) == answer
    assert await adjudicate_korean_span(model, "추가 예산은?", DOC, None, answer, SUPPORT_THRESHOLD) is None
    model.generate_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_disagreement_asks_once_and_keeps_original_offsets() -> None:
    model = AsyncMock()
    model.generate_text.return_value = "[2] 12억원"
    result = await adjudicate_korean_span(model, "확정 예산은?", DOC, span("8억원"), span("12억원"), -1.)
    assert result is not None and result["answer"] == "12억원" and result["quote"] == "확정 예산은 12억원이다."
    assert DOC["content"][result["start"]:result["end"]] == result["answer"]
    assert DOC["content"][result["quote_start"]:result["quote_end"]] == result["quote"]
    model.generate_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_high_relevance_refusal_is_reviewed_and_errors_remain_errors() -> None:
    model = AsyncMock()
    model.generate_text.side_effect = ["NONE", "[2] 7억원"]
    assert await adjudicate_korean_span(model, "추가 예산은?", DOC, None, span("8억원"), 6.) is None
    with pytest.raises(ValueError, match="absent"):
        await adjudicate_korean_span(model, "추가 예산은?", DOC, None, span("8억원"), 6.)
    with pytest.raises(ValueError, match="source-anchored"):
        await adjudicate_korean_span(model, "예산은?", DOC, None, {**span("8억원"), "end": 2}, -1.)
    assert model.generate_text.await_count == 2
