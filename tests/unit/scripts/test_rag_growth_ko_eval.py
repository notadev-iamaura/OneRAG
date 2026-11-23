import asyncio
import hashlib
import json
from argparse import Namespace
from types import SimpleNamespace

import pytest

from scripts import rag_growth_ko_eval as runner
from scripts import rag_growth_ko_panels as panels


def test_native_no_passage_has_no_reference_retrieval_denominator():
    docs = [{"id": "article", "content": "문서", "title": "자료"}]
    labels = [{"id": "q", "answerable": False, "source_id": None, "answers": [], "spans": []}]
    rows = [{"id": "q", "status": "abstained", "retrieved": ["article"]}]
    result = runner.grade(rows, labels, docs)
    assert result["summary"]["unanswerable"]["correct"] == 1
    assert result["summary"]["unanswerable_reference_retrieved"]["n"] == 0
    assert result["summary"]["unanswerable_reference_retrieved"]["percent"] is None
    assert result["outcomes"][0]["source_retrieved"] is None


def test_reservation_blocks_prior_articles_duplicate_bodies_and_cross_split_overlap():
    rows = []
    for i in range(40):
        body = f"기사 {i}의 내용은 {i}입니다."
        answer = str(i)
        rows.append({"guid": str(i), "question": f"{i}번째 질문은?", "title": f"제목 {i}",
                     "context": body, "is_impossible": bool(i % 2),
                     "answers": {"answer_start": [body.rindex(answer)], "text": [answer]}})
    old = ({rows[1]["question"]}, {rows[2]["title"]}, {rows[3]["context"]}, set(), {})
    prepared, manifest = panels.reserve(rows, old, {"dev": 2, "final": 3}, 8)
    assert manifest["per_split_per_stratum"] == {"dev": 2, "final": 3}
    docs = [d for part in prepared.values() for d in part["corpus"]]
    assert len({d["id"] for d in docs}) == len({d["title"] for d in docs}) == 16
    assert all(d["title"] != rows[2]["title"] and d["content"] != rows[3]["context"] for d in docs)
    for split, n in (("dev", 2), ("final", 3)):
        part = prepared[split]
        assert {q["id"] for q in part["questions"]} == {c["id"] for c in part["labels"]}
        assert all(set(q) == {"id", "question"} and q["question"] != rows[1]["question"] for q in part["questions"])
        assert sum(c["answerable"] for c in part["labels"]) == n
        assert len(part["labels"]) == 2*n
    index = panels.ArticleFilter(set(), set())
    text = " ".join(f"단어{i}" for i in range(60))
    assert index.accept({"title": "제목 A", "context": text})
    assert not index.accept({"title": "제목 B", "context": text+" 새 문장 하나"})


def test_source_checked_aliases_native_abstentions_errors_and_exact_denominators(monkeypatch):
    body = "답은 12, 다음에는 12"
    doc = {"id": "doc", "title": "공개 기사", "content": body}
    qs = [{"id": str(i), "question": f"q{i}"} for i in range(6)]
    source = {"start": 3, "end": 5, "text": "12"}
    labels = [{"id": q["id"], "source_id": "doc", "answerable": i < 3, "answers": ["12"] if i < 3 else [],
               "spans": [source] if i < 3 else []} for i, q in enumerate(qs)]
    monkeypatch.setattr(runner, "retrieve", lambda corpus, question, k: [doc] if question != "q5" else [])

    async def read(question, retrieved):
        assert set(retrieved[0]) == {"id", "title", "content"}
        if question == "q3":
            return None
        if question == "q4":
            raise RuntimeError("failed")
        a = 3 if question == "q0" else body.rindex("12")
        return {"source_id": "doc" if question != "q2" else "unretrieved", "answer": "12",
                "start": a, "end": a+2, "quote": body, "quote_start": 0, "quote_end": len(body)}

    rows = asyncio.run(runner.evaluate_cases(None, qs, read))
    result = runner.grade(rows, labels, [doc])["summary"]
    assert result["answerable"]["correct"] == 1 and result["answerable"]["n"] == 3
    assert result["answerable_text_exact"]["correct"] == 3
    assert result["unanswerable"]["correct"] == 1 and result["unanswerable"]["n"] == 3
    assert result["unanswerable_with_reference_retrieved"]["n"] == 2
    assert result["statuses"] == {"answered": 3, "abstained": 1, "error": 2}
    with pytest.raises(ValueError, match="Missing"):
        runner.grade(rows[:-1], labels, [doc])
    with pytest.raises(ValueError, match="Missing"):
        runner.grade(rows[:-1]+[rows[0]], labels, [doc])


def test_freeze_and_single_open_use_only_prediction_inputs(tmp_path, monkeypatch):
    directory = tmp_path / "panels"
    directory.mkdir()
    body = "본문"
    parts = {"corpus": [{"id": "doc", "title": "제목", "content": body}],
             "questions": [{"id": "q", "question": "문제"}],
             "labels": [{"id": "q", "answerable": False, "answers": [], "spans": [], "source_id": "doc"}]}
    files = {}
    for key, value in parts.items():
        path = directory / f"final.{key}.json"
        path.write_bytes(panels.encode(value))
        files[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    (directory / "reservation.json").write_text(json.dumps({"files": files}))
    args = Namespace(panels=directory, split="freeze", freeze=tmp_path/"frozen.json", output=tmp_path/"answers.json",
                     top_k=1, adapter="testreader:read")
    identity = {"hash": "pinned"}
    monkeypatch.setattr(runner, "policy_identity", lambda args: dict(identity))
    monkeypatch.setattr(runner, "ReaderCorpus", lambda docs: docs)
    monkeypatch.setattr(runner, "retrieve", lambda docs, query, top: docs)
    loaded = []
    read = runner.read_part

    def trace(args, reservation, part):
        loaded.append(part)
        return read(args, reservation, part)

    def callback(q, docs):
        assert q == "문제" and loaded == ["corpus", "questions"]
        assert set(docs[0]) == {"id", "title", "content"}
        return None

    monkeypatch.setattr(runner, "read_part", trace)
    monkeypatch.setattr(runner.importlib, "import_module", lambda _: SimpleNamespace(read=callback))
    asyncio.run(runner.run(args))
    assert not loaded
    args.split = "final"
    identity["hash"] = "changed"
    with pytest.raises(ValueError, match="matching policy"):
        asyncio.run(runner.run(args))
    assert not loaded
    identity["hash"] = "pinned"
    asyncio.run(runner.run(args))
    assert json.loads(args.output.read_bytes())["summary"]["unanswerable"]["correct"] == 1
    assert loaded == ["corpus", "questions", "labels"]
    with pytest.raises(ValueError, match="unoccupied"):
        asyncio.run(runner.run(args))
    args.output = tmp_path/"another.json"
    with pytest.raises(FileExistsError):
        asyncio.run(runner.run(args))
