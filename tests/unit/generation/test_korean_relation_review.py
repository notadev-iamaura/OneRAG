import json

import pytest

from app.modules.core.generation.korean_relation_review import (
    LIMITS,
    InvalidReview,
    decode_review,
    review,
    review_input,
)


def test_second_document_evidence_and_unicode_offsets() -> None:
    question = "접수한 팀은 어디인가?"
    docs = [{"id": "one", "title": "다른 글", "content": "지원팀은 운영을 맡았다."},
            {"id": "two", "title": "담당", "content": "🙂 달빛팀이 새로 생겼다. 그 팀이 접수를 맡았다."}]
    parsed = review_input(question, docs, [])
    pair = decode_review('{"a":"달빛팀","s":2,"e":3}', "stop", question, parsed)
    assert pair is not None and pair["source_id"] == "two"
    article = docs[1]["content"]
    for text, start, end in (("answer", "start", "end"), ("quote", "quote_start", "quote_end"),
                             ("relation_quote", "relation_start", "relation_end")):
        assert article[pair[start]:pair[end]] == pair[text]
    assert pair["relation_quote"] == "그 팀이 접수를 맡았다."
    for raw in ('{"a":"달빛팀","s":2,"e":1}', '{"a":"다른팀","s":2,"e":3}', '{"a":"","s":2,"e":0}',
                '{"a":"", "a":"x", "s":0, "e":0}', '{"a":"","s":false,"e":0}'):
        with pytest.raises(InvalidReview):
            decode_review(raw, "stop", question, parsed)
    assert decode_review('{"a":"","s":0,"e":0}', "stop", question, parsed) is None


def test_excerpt_is_bounded_source_ordered_and_cannot_bridge_hidden_text() -> None:
    question = "영수증 보관 부서는?"
    original = "도입부. " + " ".join("일반 문단입니다." for _ in range(40)) + " 영수증은 비용팀에서 보관한다."
    docs = [{"id": "a", "title": "담당", "content": original}]
    start = original.index("비용팀")
    candidate = {"source_id": "a", "answer": "비용팀", "start": start, "end": start+3}
    result = review_input(question, docs, [candidate])
    assert len(result.positions) <= 6 and len(result.prompt) < 1600
    answer_id = next(k for k, (_, _, u) in result.positions.items() if "비용팀" in u.text)
    with pytest.raises(InvalidReview):
        decode_review(json.dumps({"a": "비용팀", "s": answer_id, "e": 1}), "stop", question, result)
    with pytest.raises(ValueError, match="anchor"):
        review_input(question, docs, [{**candidate, "start": 0}])
    with pytest.raises(ValueError, match="distinct"):
        review_input(question, [docs[0], docs[0]], [])


@pytest.mark.asyncio
async def test_length_and_invalid_citations_get_one_retry_only() -> None:
    prepared = review_input("누가 맡았나?", [{"id": "a", "content": "수기팀이 맡았다."}], [])
    limits = []
    async def shortened(system: str, prompt: str, limit: int) -> tuple[str, str]:
        limits.append(limit)
        if len(limits) == 1:
            return '{"a":"","s":0,"e":0}', "length"
        assert "형식을 다시" in system
        return '{"a":"수기팀","s":1,"e":1}', "stop"
    reply = await review("누가 맡았나?", prepared, shortened)
    assert reply and reply["answer"] == "수기팀" and limits == list(LIMITS)
    calls = 0
    async def unsupported(system: str, prompt: str, limit: int) -> tuple[str, str]:
        nonlocal calls
        calls += 1
        return '{"a":"없는팀","s":1,"e":1}', "stop"
    with pytest.raises(InvalidReview):
        await review("누가 맡았나?", prepared, unsupported)
    assert calls == 2


@pytest.mark.asyncio
async def test_transport_error_is_neither_retried_nor_abstained() -> None:
    prepared = review_input("누구?", [{"id": "a", "content": "북쪽 부서가 맡았다."}], [])
    calls = 0
    async def offline(system: str, prompt: str, limit: int) -> tuple[str, str]:
        nonlocal calls
        calls += 1
        raise ConnectionError
    with pytest.raises(ConnectionError):
        await review("누구?", prepared, offline)
    assert calls == 1
