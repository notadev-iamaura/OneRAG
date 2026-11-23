import json
from argparse import Namespace

import pytest

from scripts import rag_growth_round as growth
from scripts.rag_growth_prepare import build_panels


def article(index):
    return {
        "guid": str(index), "title": f"기사 {index}", "context": f"본문 {index}",
        "question": f"질문 {index}?", "is_impossible": bool(index % 2),
        "answers": {"text": ["본문"], "answer_start": [0]},
    }


def test_preparation_excludes_previous_titles_bodies_and_questions():
    rows = [article(i) for i in range(18)]
    previous = {"docs": [{"title": rows[0]["title"], "content": rows[1]["context"]}],
                "cases": [{"question": rows[2]["question"]}]}
    sizes = {"dev-a": (1, 1), "final": (1, 1)}
    panels = build_panels(rows, [rows[3]], [previous], "r1", sizes, 4)
    assert panels == build_panels(rows[::-1], [rows[3]], [previous], "r1", sizes, 4)
    all_docs = [d for p in panels.values() for d in p["documents"]]
    assert len({d["id"] for d in all_docs}) == 8
    assert {d["title"] for d in all_docs}.isdisjoint({"기사 0", "기사 3"})
    assert "본문 1" not in {d["content"] for d in all_docs}
    assert "질문 2?" not in {c["question"] for p in panels.values() for c in p["cases"]}
    for p in panels.values():
        assert all(c["context_source_id"] for c in p["cases"])
        assert all(bool(c["answer_spans"]) == c["answerable"] for c in p["cases"])


@pytest.fixture
def paths(tmp_path, monkeypatch):
    sizes = dict.fromkeys(("dev-a", "dev-b", "final", "replication"), (1, 1))
    monkeypatch.setattr(growth, "PANEL_SIZES", sizes)
    monkeypatch.setattr(growth, "source_digest", lambda: "frozen")
    source = tmp_path / "panels"
    source.mkdir()
    for name, panel in build_panels([article(i) for i in range(30)], [], [], "r1", sizes, 3).items():
        manifest = dict(panel, model="local", model_sha256="0" * 64, index=growth.local.INDEX_ID,
                        trials=3, schema_version=1)
        (source / f"{name}.json").write_text(json.dumps(manifest))
    return Namespace(panels=source, model_file=tmp_path / "model", port=12345, output_dir=tmp_path / "run")


def test_preflight_blocks_overlap_even_when_both_files_have_valid_hashes(paths):
    dev_a = paths.panels / "dev-a.json"
    (paths.panels / "dev-b.json").write_bytes(dev_a.read_bytes())
    with pytest.raises(ValueError, match="overlap"):
        growth.reserve(paths.panels)


@pytest.mark.parametrize("development_pass", [True, False])
def test_holdout_opens_once_and_only_after_both_development_checks(paths, monkeypatch, development_pass):
    seen = []

    def evaluate(cmd, check):
        from pathlib import Path
        seen.append(Path(cmd[cmd.index("--manifest") + 1]).stem)
        assert check

    def grade(argv):
        from pathlib import Path
        eligible = seen[-1] != "dev-b" or development_pass
        Path(argv[-1]).write_text(json.dumps({"eligible": eligible, "decision": "test", "reasons": []}))
        return 0 if eligible else 1

    monkeypatch.setattr(growth.subprocess, "run", evaluate)
    monkeypatch.setattr(growth.gate, "main", grade)
    assert growth.run(paths) == (0 if development_pass else 1)
    assert seen == (["dev-a", "dev-b", "final", "replication"] if development_pass else ["dev-a", "dev-b"])
    assert (paths.panels / "holdout-opened.json").exists() == development_pass
    assert not json.loads((paths.output_dir / "round.json").read_bytes())["release_certified"]
    if development_pass:
        paths.output_dir = paths.output_dir.with_name("second-attempt")
        with pytest.raises(FileExistsError):
            growth.run(paths)
        assert seen[-2:] == ["dev-a", "dev-b"]
