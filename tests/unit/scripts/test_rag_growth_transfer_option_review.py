from dataclasses import replace
from unittest.mock import AsyncMock

import pytest

from app.modules.core.generation import english_option_review as review
from app.modules.core.generation.korean_span_reader import SpanAnswer


def test_verifies_answer_and_citation_in_the_same_source_before_rendering_raw_context():
    docs = {"doc": {"id": "doc", "title": "Ocean", "content": "Lee sailed. She arrived in June."}}
    span = SpanAnswer(0, "doc", "June", 27, 31, "She arrived in June.", 12, 32, 1.2)
    prompt = review.make_prompt("When did Lee arrive?", [span], docs)
    assert "Lee sailed. She arrived in June." in prompt
    assert '"id":"A"' in prompt
    for invalid in (replace(span, start=26), replace(span, quote_start=11), replace(span, quote="bogus")):
        with pytest.raises(ValueError, match="original passage"):
            review.make_prompt("When?", [invalid], docs)


@pytest.mark.asyncio
async def test_only_complete_offered_id_or_none_can_become_a_verdict():
    span = SpanAnswer(0, "doc", "June", 0, 4, "June", 0, 4, 1.2)
    model = AsyncMock()
    model.generate_text.return_value = " A\n"
    assert await review.review(model, "prompt", [span]) == ("A", span)
    kwargs = model.generate_text.await_args.kwargs
    assert kwargs["require_complete"] is True and kwargs["max_tokens"] == 8
    assert review.resolve("NONE", [span]) is None
    for bad in ["B", "", "A.", "A or NONE", "none"]:
        with pytest.raises(ValueError, match="offered"):
            review.resolve(bad, [span])
    model.generate_text.side_effect = ValueError("Incomplete local model response")
    with pytest.raises(ValueError, match="Incomplete"):
        await review.review(model, "prompt", [span])
