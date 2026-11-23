from unittest.mock import AsyncMock

import pytest

from app.modules.core.generation.korean_corroborated_reader import read


@pytest.mark.asyncio
async def test_corroborated_reader_fixes_a_wrong_label_without_a_second_generation():
    body = "관측소 이름은 해오름이다. 어제 관측을 시작했다."
    doc = {"id": "S1", "content": body}
    a = body.index("해오름")
    proposal = {"source_id": "S1", "answer": "해오름", "start": a, "end": a + 3,
                "quote": body, "quote_start": 0, "quote_end": len(body), "score": 2.}
    model = AsyncMock()
    model.generate_text.return_value = "[1.2] 해오름"
    boundary, support = AsyncMock(return_value=proposal), AsyncMock(return_value=True)
    chosen = await read(model, "관측소 이름은?", doc, boundary, support, 4.)
    assert chosen is not None and chosen["start"] == a and chosen["answer"] == "해오름"
    model.generate_text.assert_awaited_once()
    boundary.assert_awaited_once()
    support.assert_awaited_once()


@pytest.mark.asyncio
async def test_original_refusal_and_transport_failure_keep_their_meanings():
    doc = {"id": "S1", "content": "관측을 시작했다."}
    model = AsyncMock()
    model.generate_text.return_value = "NONE"
    boundary = AsyncMock()
    support = AsyncMock(return_value=False)
    assert await read(model, "어디에서?", doc, boundary, support, 4.) is None
    model.generate_text.side_effect = TimeoutError("network")
    with pytest.raises(TimeoutError):
        await read(model, "어디에서?", doc, boundary, support, 4.)
    boundary.assert_not_awaited()
    support.assert_awaited_once()
