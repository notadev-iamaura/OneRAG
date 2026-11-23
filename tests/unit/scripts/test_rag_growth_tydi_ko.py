from typing import Any

import pytest

from scripts.rag_growth_tydi_ko import consensus, fingerprint, passages, reserve


def fixture_row(title: str, positive: bool) -> dict[str, Any]:
    prefix, body = "🙂 첫 문단.\n", title + "의 답은 코끼리입니다."
    article = prefix + body
    start = len(article[:article.index("코끼리")].encode())
    vote = (1, start, start + len("코끼리".encode()))
    votes = [vote, vote, (-1, -1, -1)] if positive else [(-1, -1, -1)] * 3
    annotations = dict(zip(("passage_answer_candidate_index", "minimal_answers_start_byte",
                            "minimal_answers_end_byte"), map(list, zip(*votes, strict=True)), strict=True))
    return {"document_title": title, "document_plaintext": article, "language": "korean",
            "question_text": f"{title}에서 설명한 동물은?", "annotations": {**annotations, "yes_no_answer": ["NONE"]*3},
            "passage_answer_candidates": {"plaintext_start_byte": [0, len(prefix.encode())],
                                          "plaintext_end_byte": [len(prefix.encode()) - 1, len(article.encode())]}}


def test_positive_requires_two_exact_votes_and_maps_utf8_offsets() -> None:
    row = fixture_row("한국어", True)
    decision = consensus(row["annotations"])
    assert decision and decision[0] is True and decision[1]
    docs, label = passages(row, decision[1])
    span, = label["spans"]
    assert label["source_id"] == docs[1]["id"]
    assert docs[1]["content"][span["start"]:span["end"]] == span["text"] == "코끼리"
    row["annotations"]["minimal_answers_end_byte"][1] -= 1
    assert consensus(row["annotations"]) is None
    with pytest.raises(ValueError, match="outside"):
        passages(row, (0, decision[1][1], decision[1][2]))


def test_negative_requires_three_complete_nulls_and_has_no_gold_passage() -> None:
    row = fixture_row("바다", False)
    annotations = row["annotations"]
    assert consensus(annotations) == (False, None)
    assert passages(row, None)[1] == {"answerable": False, "answers": [], "spans": [], "source_id": None}
    for field, value in (("yes_no_answer", "YES"), ("passage_answer_candidate_index", 1),
                         ("minimal_answers_start_byte", 0), ("minimal_answers_end_byte", 3)):
        assert consensus({**annotations, field: [value, *annotations[field][1:]]}) is None
    assert consensus({field: values[:2] for field, values in annotations.items()}) is None


def test_reservation_keeps_complete_passage_pool_and_excludes_klue_hashes() -> None:
    rows = [fixture_row("신문 A", True), fixture_row("신문 B", True), fixture_row("신문 C", False)]
    prior = {"title": {fingerprint("신문_a")}, "question": set(), "article": set()}
    first = reserve(rows, prior, 1)
    assert first == reserve(list(reversed(rows)), prior, 1)
    panel, stats = first
    assert stats["unique_articles"] == 2 and len(panel["corpus"]) == 4
    assert {doc["title"] for doc in panel["corpus"]} == {"신문 B", "신문 C"}
    assert all(set(q) == {"id", "question"} for q in panel["questions"])
    assert all(set(d) == {"id", "title", "content"} for d in panel["corpus"])
    assert set(stats["klue_hash_overlap"].values()) == {0}
    for key, value in (("question", rows[1]["question_text"]), ("article", rows[1]["document_plaintext"]),
                       ("article", rows[1]["document_plaintext"].splitlines()[1])):
        with pytest.raises(ValueError, match="Insufficient"):
            reserve(rows, {**prior, key: {fingerprint(value)}}, 1)
