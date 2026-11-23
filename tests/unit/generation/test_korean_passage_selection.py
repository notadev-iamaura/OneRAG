from dataclasses import replace

import pytest

from app.modules.core.generation.korean_passage_selection import select_passage
from app.modules.core.generation.korean_reranked_passage_reader import (
    Documents,
    KoreanRerankedPassageReader,
)
from app.modules.core.generation.korean_span_reader import SpanAnswer


def test_relevant_second_passage_returns_actual_source_offsets() -> None:
    docs = [{"id": "one", "content": "하늘은 흐리다."}, {"id": "two", "content": "바다는 푸르다."}]
    a = SpanAnswer(0, "one", "흐리다", 4, 7, "하늘은 흐리다.", 0, 8, 4)
    b = SpanAnswer(1, "two", "푸르다", 4, 7, "바다는 푸르다.", 0, 8, 5)
    ranks, span = select_passage(docs, [a, b], [-1.2, 2.1], "joint", 3)
    assert ranks == ["two", "one"] and span == b


def test_abstention_gates_and_invalid_artifacts() -> None:
    doc = {"id": "id", "content": "가나다"}
    s = SpanAnswer(0, "id", "나", 1, 2, "가나다", 0, 3, 2)
    assert select_passage([doc], [s], [1], "verifier", 3)[1] == s
    assert select_passage([doc], [s], [1], "joint", 3)[1] is None
    assert select_passage([doc], [s], [-1], "verifier", 3)[1] is None
    with pytest.raises(ValueError, match="Invalid source"):
        select_passage([doc], [replace(s, start=0)], [1], "joint", 3)
    with pytest.raises(ValueError, match="Invalid source"):
        select_passage([doc], [s], [float("nan")], "joint", 3)
    with pytest.raises(ValueError, match="Repeated"):
        select_passage([doc, doc], [s, s], [1, 1], "joint", 3)


def test_reader_batches_in_rank_order_and_returns_global_document_index() -> None:
    docs = [{"id": str(i), "content": "파랑"} for i in range(9)]
    calls = []

    def score(question: str, documents: Documents) -> list[float]:
        calls.append(("score", [d["id"] for d in documents]))
        return [8 if d["id"] == "6" else -1 for d in documents]

    def predict(question: str, documents: Documents) -> list[SpanAnswer]:
        calls.append(("read", [d["id"] for d in documents]))
        return [
            SpanAnswer(i, d["id"], "파랑", 0, 2, "파랑", 0, 2, 5) for i, d in enumerate(documents)
        ]

    reader = KoreanRerankedPassageReader(lambda: score, lambda: predict, span_threshold=3)
    actual = reader.read("어떤 색?", docs)
    assert actual is not None and actual.source_id == "6" and actual.document_index == 6
    assert calls == [
        (op, ids)
        for op in ("score", "read")
        for ids in (["0", "1", "2", "3"], ["4", "5", "6", "7"])
    ]


def test_reader_retains_explicit_model_failure() -> None:
    def bad(question: str, documents: Documents) -> list[float]:
        raise RuntimeError("checkpoint unavailable")

    reader = KoreanRerankedPassageReader(lambda: bad, lambda: lambda q, d: [], span_threshold=3)
    with pytest.raises(RuntimeError, match="checkpoint unavailable"):
        reader.read("누구?", [{"id": "1", "content": "홍길동"}])
