import pytest

from app.modules.core.generation.korean_evidence_mentions import FEATURES, select_mention


def anchored(source, answer):
    start = source.index(answer)
    return {"source_id": "s", "answer": answer, "start": start, "end": start + len(answer),
            "quote": source, "quote_start": 0, "quote_end": len(source)}


def test_repeated_literal_cites_the_sentence_with_the_requested_event():
    body = "로이라는 이름은 흔하다. 그날 구조대에 합류한 사람은 로이였다."
    row = anchored(body, "로이")
    chosen = select_mention("그날 구조대에 합류한 사람은?", {"id": "s", "content": body}, row, [1.] + [0.] * 7, 0.)
    assert chosen["answer"] == row["answer"]
    assert chosen["start"] == body.rindex("로이")
    assert body[chosen["quote_start"]:chosen["quote_end"]] == "그날 구조대에 합류한 사람은 로이였다."


def test_ties_and_unique_answers_preserve_the_reader_choice():
    for body in ("로이. 로이.", "로이. 지나."):
        row = anchored(body, "로이")
        assert select_mention("누가 왔나?", {"id": "s", "content": body}, row, [0.] * len(FEATURES), 0.) is row


def test_invalid_original_quote_is_an_error():
    body = "다음 역은 동백이다."
    with pytest.raises(ValueError, match="source span"):
        select_mention("어느 역?", {"id": "s", "content": body}, {**anchored(body, "동백"), "quote_end": 1},
                       [0.] * len(FEATURES), 0.)
