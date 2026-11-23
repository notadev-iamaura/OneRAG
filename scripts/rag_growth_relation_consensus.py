"""Register one development-only consensus before scoring, then replay the completed relation run."""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.modules.core.generation import korean_relation_consensus as chooser
from app.modules.core.generation.korean_relation_review import decode_review
from scripts import rag_growth_relation_review as source
from scripts.rag_growth_ko_eval import grade, write_new
from scripts.rag_growth_local import file_sha256

LOCATION = source.DATA / "relation-review"
REG = LOCATION / "consensus-registration.json"
UPSTREAM = "d11bf9222dd0724fecf91ed1d89996f665e9561eb1213a9b7d05a28550fd9291"
Row = dict[str, Any]


def registration() -> Row:
    if file_sha256(LOCATION/"reservation.json") != UPSTREAM:
        raise ValueError("Unexpected upstream development policy")
    return {"scope": "One development-only replay after the raw relation experiment completes, no inference",
            "upstream_reservation_sha256": UPSTREAM,
            "files": {path.name: file_sha256(path) for path in (Path(__file__), Path(chooser.__file__),
                      source.SOURCE, source.SPANS, source.RANKS, source.PANELS/"dev.questions.json",
                      source.PANELS/"dev.labels.json", source.PANELS/"dev.corpus.json")},
            "target": "at least 32/40 grounded positives AND 32/40 native abstentions; errors retained",
            "order": ["Initial error stays an error", "Keep initial if exact encoder anchor agrees",
                      "On review error keep only an anchored initial positive, or preserve the error",
                      "Accept explicit review abstention", "Accept reviewed positive iff exact source, text and "
                      "character endpoints agree with initial or an encoder on either rank",
                      "Otherwise retain the original verified answer or genuine initial abstention"],
            "exposure": "Proposed after observing baseline development results and partial raw relation statuses and "
                        "invalid format/anchor examples; before complete scores or a consensus replay. "
                        "The reviewer saw the candidate texts; agreement is not statistical independence."}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("reserve", "score"))
    args = parser.parse_args()
    spec = registration()
    if args.operation == "reserve":
        if (LOCATION/"metrics.json").exists():
            raise ValueError("Late reservations are not allowed")
        write_new(REG, spec)
        print(file_sha256(REG))
        return
    if spec != json.loads(REG.read_bytes()):
        raise ValueError("Development replay differs from its registration")
    raw_path = LOCATION/"metrics.json"
    observed = json.loads(raw_path.read_bytes())
    if observed["reservation_sha256"] != UPSTREAM:
        raise ValueError("Raw observations came from another policy")
    reviews = source.keyed(observed["rows"])
    questions, base, spans, ranks, docs = source.load_inputs()
    corpus = source.keyed(docs)
    if list(reviews) != [q["id"] for q in questions]:
        raise ValueError("Raw observations incomplete or reordered")
    result, evidence = [], []
    for q in questions:
        key = q["id"]
        initial, reviewer = base[key], reviews[key]
        ids = ranks[key][:2]
        prepared = source.inputs(q, initial, spans[key], ranks[key], corpus)
        if reviewer["status"] != "error":
            last = reviewer["attempts"][-1]
            if prepared is None:
                raise ValueError("A review exists after an upstream error")
            decoded = decode_review(last["response"], last["finish"], q["question"], prepared)
            if (decoded is None) != (reviewer["status"] == "abstained") or (
                    decoded and any(reviewer[k] != value for k, value in decoded.items())):
                raise ValueError("Stored review fails to reproduce from its original raw response")
        options = [s for s in spans[key]["spans"] if s["source_id"] in ids]
        chosen, route = chooser.decide(initial, options, reviewer, {i: corpus[i]["content"] for i in ids})
        row: Row = {"id": key, "status": chosen["status"], "retrieved": reviewer["retrieved"]}
        if row["status"] == "answered":
            row.update({k: chosen[k] for k in (*chooser.FIELDS, *chooser.QUOTE)})
        elif row["status"] == "error":
            row["error"] = chosen["error"]
        result.append(row)
        evidence.append({"id": key, "route": route, "original_status": initial["status"],
                         "original_error": initial.get("error"), "review_status": reviewer["status"],
                         "review_error": reviewer.get("error"), "status": row["status"],
                         "changed_from_baseline": any(row.get(k) != initial.get(k) for k in
                                                      ("status", *chooser.FIELDS, *chooser.QUOTE)),
                         "chosen_rank": ids.index(row["source_id"])+1 if row["status"] == "answered" else None})
    labels = json.loads((source.PANELS/"dev.labels.json").read_bytes())
    base_grade = grade(list(base.values()), labels, docs)
    raw_grade = grade(list(reviews.values()), labels, docs)
    if raw_grade["summary"] != observed["summary"] or base_grade["summary"] != observed["baseline"]:
        raise ValueError("Independent grades disagree with the completed original experiment")
    verdict = grade(result, labels, docs)
    before = source.keyed(base_grade["outcomes"])
    pairs: dict[str, Counter[str]] = {"answerable": Counter(), "unanswerable": Counter()}
    for o, record in zip(verdict["outcomes"], evidence, strict=True):
        first, last = before[o["id"]]["correct"], o["correct"]
        change = ("both_correct" if first else "improved") if last else ("regressed" if first else "both_incorrect")
        pairs["answerable" if o["answerable"] else "unanswerable"][change] += 1
        record["paired"] = change
    report = {"registration_sha256": file_sha256(REG), "raw_relation_measurement_sha256": file_sha256(raw_path),
              "baseline": base_grade["summary"], "raw_relation": raw_grade["summary"], **verdict,
              "rows": result, "provenance": evidence, "paired_vs_baseline": pairs,
              "routes": dict(Counter(r["route"] for r in evidence))}
    write_new(LOCATION/"consensus-dev.json", report)
    print(json.dumps({"summary": verdict["summary"], "paired": pairs}, ensure_ascii=False))


if __name__ == "__main__":
    main()
