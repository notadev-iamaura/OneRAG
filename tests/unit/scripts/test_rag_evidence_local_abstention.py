import pytest

from scripts.rag_evidence_local_abstention import decide, ranges


def test_three_windows_keep_the_real_second_occurrence():
    text = "먼저 확인했다. 바로 오늘이다. 다음 주도 열린다."
    start = text.index("오늘")
    row = {"id": "x", "retrieved": ["doc"], "status": "answered", "source_id": "doc",
           "answer": "오늘", "start": start, "end": start+2, "quote": text,
           "quote_start": 0, "quote_end": len(text)}
    windows = ranges({"id": "doc", "content": text}, row)
    assert len(windows) == 3
    assert [text[a:b] for a,b in windows] == ["바로 오늘이다.", "먼저 확인했다. 바로 오늘이다.", "바로 오늘이다. 다음 주도 열린다."]
    assert decide(row, row, 0., [-1.,0.,-2.]) == {"id": "x", "status": "abstained", "retrieved":["doc"]}
    assert decide(row, row, -1., [0.,.01]) == row
    assert decide(row, row, 1., []) == row
    assert decide(row, dict(row, status="error"), -1., []) == row
    with pytest.raises(ValueError, match="did not complete"):
        decide(row, row, -1., [float("nan")])
