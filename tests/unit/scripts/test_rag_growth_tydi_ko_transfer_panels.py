from typing import Any

import pytest

from scripts import rag_growth_tydi_ko_transfer_panels as panels


def source(title: str, answerable: bool, votes: int) -> dict[str, Any]:
    # Each source has two distinct Korean paragraphs so the corpus must retain both, including backgrounds.
    part1, part2 = title+" 소식이다.", title+"의 담당은 회계팀이다."
    body = part1+"\n"+part2
    start = len(body[:body.index("회계팀")].encode())
    p, a, b = (1, start, start+len("회계팀".encode())) if answerable else (-1, -1, -1)
    return {"document_title": title, "question_text": title+"의 담당은?", "document_plaintext": body,
            "annotations": {"yes_no_answer": ["NONE"]*votes, "passage_answer_candidate_index": [p]*votes,
                            "minimal_answers_start_byte": [a]*votes, "minimal_answers_end_byte": [b]*votes},
            "passage_answer_candidates": {"plaintext_start_byte": [0, len((part1+"\n").encode())],
                                          "plaintext_end_byte": [len(part1.encode()), len(body.encode())]}}


def test_train_single_vote_does_not_enter_confirmation_or_create_negative_source() -> None:
    one = source("부서1", False, 1)
    assert panels.single(one["annotations"]) == (False, None)
    assert panels.td.consensus(one["annotations"]) is None
    two = source("부서2", True, 3)
    assert panels.single(two["annotations"]) is None
    assert panels.single({**one["annotations"], "yes_no_answer": ["YES"]}) is None
    assert panels.single({**one["annotations"], "passage_answer_candidate_index": [1]}) is None


def test_panels_distinct_including_whole_background_articles_and_reproducible() -> None:
    dev_source = [source(f"팀{i}", i % 2 == 0, 1) for i in range(6)]
    heldout_source = [source(f"팀{i}", i % 2 == 0, 3) for i in range(3, 13)]
    dev, meta, sig = panels.reserve("dev", dev_source, [], 1, 1)
    assert panels.reserve("dev", list(reversed(dev_source)), [], 1, 1) == (dev, meta, sig)
    final, seal, fp = panels.reserve("final", heldout_source, [sig], 1, 1)
    assert not any(fp.overlap(sig).values())
    for data, manifest in [(dev, meta), (final, seal)]:
        assert len(data["corpus"]) == 6 and len(data["questions"]) == len(data["labels"]) == 2
        assert all(set(q) == {"id","question"} for q in data["questions"])
        assert sum(r["case_id"] is None for r in manifest["articles"]) == 1
        for label in data["labels"]:
            if label["answerable"]:
                text = next(d["content"] for d in data["corpus"] if d["id"] == label["source_id"])
                s, = label["spans"]
                assert text[s["start"]:s["end"]] == "회계팀"
            else:
                assert label["source_id"] is None and not label["spans"]


def test_full_body_and_passage_cross_collisions_exclude_entire_article() -> None:
    rows = [source("첫팀", False, 1),source("둘팀", True, 1)]
    article = panels.td.fingerprint(rows[0]["document_plaintext"])
    passage = panels.td.fingerprint(rows[0]["document_plaintext"].split("\n")[0])
    for previous in (panels.Footprint(article={passage}), panels.Footprint(passage={article}),
                     panels.Footprint(question={panels.td.fingerprint(rows[1]["question_text"])})):
        with pytest.raises(ValueError, match="Insufficient"):
            panels.reserve("dev", rows, [previous], 1, 0)
