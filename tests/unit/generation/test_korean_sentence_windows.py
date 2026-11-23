from unittest.mock import AsyncMock

import pytest

from app.modules.core.generation.korean_sentence_windows import (
    read_windows,
    select_anchored_windows,
    select_windows,
)


def test_ranked_windows_keep_offsets_and_do_not_cross_decimal_points():
    body = "가격은 2.5원이다.회계 기준이 바뀌었다.마감은 월요일이다. 다음 자료가 있다.끝이다."
    doc = {"id": "a", "title": "공지", "content": body}
    ranked = []

    def score(_q, candidates):
        ranked.extend(d["content"] for d in candidates)
        return [5.0 if d["content"].startswith("회계") else 0.0 for d in candidates]

    result = select_windows("회계 마감일?", doc, score)
    assert ranked[0] == "가격은 2.5원이다.회계 기준이 바뀌었다."
    assert [body[a:b] for a, b in result] == ["회계 기준이 바뀌었다.마감은 월요일이다.", "다음 자료가 있다.끝이다."]


@pytest.mark.asyncio
async def test_same_answer_in_a_later_window_is_mapped_to_that_occurrence():
    body = "예전 일정은 월요일. 안내 생략. 새 일정은 월요일."
    doc = {"id": "article-7", "title": "일정", "content": body}
    left = body.index("새 일정")
    model = AsyncMock()
    model.generate_text.return_value = "[2.1] 월요일"
    result = await read_windows(model, "새 일정은?", doc, [(0, body.index(" 안내")), (left, len(body))])
    assert result["source_id"] == doc["id"]
    assert result["start"] == body.rindex("월요일")
    assert (result["quote_start"], result["quote_end"]) == (left, len(body))
    assert result["quote"] == body[left:]


@pytest.mark.asyncio
async def test_overlapping_or_out_of_bounds_windows_never_reach_the_model():
    doc = {"id": "a", "title": "일정", "content": "기록된 원문."}
    model = AsyncMock()
    for spans in ([(0, 5), (4, 7)], [(0, 20)]):
        with pytest.raises(ValueError, match="Invalid evidence range"):
            await read_windows(model, "언제?", doc, spans)
    model.generate_text.assert_not_awaited()


def test_boundary_guidance_keeps_the_whole_article_when_the_verifier_is_unsure():
    body = "하나이다. 둘이다. 셋이다. 넷이다. 다섯이다. 여섯이다. 일곱이다."
    doc = {"id": "article-a", "content": body}
    offset = body.index("일곱")
    anchor = {"source_id": doc["id"], "start": offset, "end": offset + 2, "answer": "일곱"}
    assert select_anchored_windows("첫 순서는?", doc, anchor, 0) == [(0, len(body))]
    windows = select_anchored_windows("첫 순서는?", doc, anchor, 2)
    assert len(windows) <= 3
    assert any(start <= offset < offset + 2 <= end for start, end in windows)
    with pytest.raises(ValueError, match="Unverified boundary"):
        select_anchored_windows("첫 순서는?", doc, {**anchor, "start": 0}, 2)
