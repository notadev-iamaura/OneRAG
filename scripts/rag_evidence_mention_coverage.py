"""Measure question-term dominance for repeated exact occurrences after the frozen KLUE boundary policy."""

from pathlib import Path

from app.modules.core.generation.korean_mention_coverage import select
from app.modules.core.retrieval.bm25_engine.tokenizer import KoreanTokenizer
from scripts.rag_evidence_corroborate import TARGET
from scripts.rag_evidence_klue_run import BASE, load
from scripts.rag_evidence_windows import recorded_context
from scripts.rag_growth_ko_eval import grade, write_new
from scripts.rag_growth_local import ROOT, file_sha256

OUT = TARGET.parent / "coverage"


def run():
    policy = ROOT / "app/modules/core/generation/korean_mention_coverage.py"
    base = TARGET / "both-development.json"
    write_new(OUT / "development-registration.json", {
        "source": file_sha256(policy), "measure": file_sha256(Path(__file__)), "original": file_sha256(base),
        "rule": "Change only the cited occurrence of the same answer when exactly one sentence strictly contains "
                "every competing sentence's matched question terms, with at least two matches. Use the existing "
                "Korean morphological tokenizer. If full development scores in both strata reach 80 percent "
                "with no regressions in either, reserve separate unseen articles for a further replication.",
    })
    qs, docs, _ = recorded_context()
    bodies = {d["id"]: d for d in docs}
    questions = {q["id"]: q["question"] for q in qs}
    tokenizer = KoreanTokenizer()
    old = load(base)
    rows = [select(questions[r["id"]], bodies[r["source_id"]], r, tokenizer.tokenize)
            if r["status"] == "answered" else r for r in old["rows"]]
    scores = grade(rows, load(BASE / "panels/dev.labels.json"), docs)
    prior = {o["id"]: o["correct"] for o in old["outcomes"]}
    flips = [o for o in scores["outcomes"] if o["correct"] != prior[o["id"]]]
    write_new(OUT / "development.json", {"rows": rows, **scores, "flips": flips,
              "moved": sum(a.get("start") != b.get("start") for a,b in zip(rows, old["rows"], strict=True))})
    print([scores["summary"][g]["correct"] for g in ("answerable", "unanswerable")], len(flips))


if __name__ == "__main__":
    run()
