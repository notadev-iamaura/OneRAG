"""Compare source-offset and answer-boundary policies on the same captured development outputs."""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.modules.core.agent.extractive_reader import refine_boundaries
from app.modules.core.generation.grounded_span import answer_offset
from scripts.rag_growth_ko_eval import grade, write_new


def read_rows(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.open(encoding="utf-8")]


def compare(
    panels: Path, generated: list[dict[str, Any]], proposals: list[dict[str, Any]]
) -> dict[str, Any]:
    documents = json.loads((panels / "dev.corpus.json").read_bytes())
    labels = json.loads((panels / "dev.labels.json").read_bytes())
    questions = {q["id"]: q["question"] for q in json.loads((panels / "dev.questions.json").read_bytes())}
    spans = {r["id"]: {s["source_id"]: s for s in r["spans"]} for r in proposals}
    reports = {}
    for mode in ("literal", "source_occurrence", "boundary_refinement"):
        rows = []
        for raw in generated:
            row = dict(raw)
            if mode != "literal" and row["status"] == "answered":
                offset = answer_offset(questions[row["id"]], row["quote"], row["answer"])
                if offset < 0:
                    raise ValueError("Answer missing from the cited quote")
                row["start"] = row["quote_start"] + offset
                row["end"] = row["start"] + len(row["answer"])
                if mode == "boundary_refinement":
                    row = refine_boundaries(row, spans[row["id"]][row["source_id"]])
            rows.append(row)
        reports[mode] = {"rows": rows, **grade(rows, labels, documents)}
    return reports


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("panels", "generated", "proposals", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    args = parser.parse_args()
    result = compare(args.panels, read_rows(args.generated), read_rows(args.proposals))
    write_new(args.output, result)
