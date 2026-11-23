"""Reserve an unscored SQuAD2 challenger with untouched questions, reference passages and candidate corpus."""

import argparse
import itertools
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import rag_growth_transfer as tr


def rows(path):
    return {r["id"]: r for r in map(json.loads, path.read_text().splitlines())}


def reserve(dataset, root):
    if tr.file_sha256(dataset) != tr.DATA_SHA:
        raise ValueError("Unregistered Stanford source")
    articles = tr.load(dataset)["data"]
    panels = tr.panels(articles)
    dev_docs, dev_cases = panels["development"]
    previous = list(itertools.chain.from_iterable(cases for _, cases in panels.values()))
    old_ids = {c["id"] for c in previous}
    old_questions = {tr.normalize(c["question"]) for c in previous}
    excluded = {c["source"] for c in previous}
    original = rows(root / "development.jsonl")
    second = rows(root / "two-reader/development.jsonl")
    corrected = rows(root / "independent-arms/development.jsonl")
    recovered = {}
    for case in dev_cases:
        qid = case["id"]
        a, b = original[qid], second[qid]
        excluded.update(a.get("spans", {}))
        if "error" not in b:
            excluded.update(b["lexical"] + b["hybrid"])
        else:
            c = corrected[qid]
            if len(c["lexical_ids"]) != 6 or len(c["hybrid_ids"]) != 6:
                raise ValueError("Missing previously used candidates")
            recovered[qid] = {"lexical": c["lexical_ids"], "hybrid": c["hybrid_ids"]}
            excluded.update(c["lexical_ids"] + c["hybrid_ids"])
    docs = {k: v for k, v in dev_docs.items() if k not in excluded}
    by_title = defaultdict(list)
    for a in articles:
        title = a["title"].replace("_", " ")
        for p in a["paragraphs"]:
            source = tr.key(p["context"])
            if source not in docs:
                continue
            for q in p["qas"]:
                if q["id"] in old_ids or tr.normalize(q["question"]) in old_questions:
                    continue
                if any(p["context"][ans["answer_start"]:ans["answer_start"] + len(ans["text"])] != ans["text"] for ans in q["answers"]):
                    raise ValueError("Official offset mismatch")
                by_title[title].append({"id": q["id"], "question": q["question"], "impossible": q["is_impossible"],
                                         "source": source, "answers": q["answers"]})
    for choices in by_title.values():
        choices.sort(key=lambda c: tr.key("onerag-fresh-full-reader-v1/question/" + c["id"]))
    titles = sorted(by_title, key=lambda t: tr.key("onerag-fresh-full-reader-v1/title/" + t))
    selected, used_docs, used_q = [], set(), set()
    counts = Counter()
    while counts[True] < 32 or counts[False] < 32:
        n = len(selected)
        for title in titles:
            for negative in (False, True):
                if counts[negative] == 32:
                    continue
                case = next((c for c in by_title[title] if c["impossible"] == negative
                             and c["source"] not in used_docs and tr.normalize(c["question"]) not in used_q), None)
                if case:
                    selected.append(case)
                    used_docs.add(case["source"])
                    used_q.add(tr.normalize(case["question"]))
                    counts[negative] += 1
        if len(selected) == n:
            raise ValueError("Insufficient unexposed paragraphs for the registered sample")
    info = {
        "dataset_sha256": tr.DATA_SHA, "data_revision": tr.DATA_REV, "script_sha256": tr.file_sha256(Path(__file__)),
        "previous_panel_registration_sha256": tr.file_sha256(root / "preregistration.json"),
        "previous_v1_development_sha256": tr.file_sha256(root / "development.jsonl"),
        "previous_v2_development_sha256": tr.file_sha256(root / "two-reader/development.jsonl"),
        "recovered_rankings": recovered, "manifest_sha256": tr.json_sha256([docs, selected]),
        "questions_per_stratum": 32, "background_documents": len(docs), "title_count": len(titles),
        "previous_development_background_overlap": len(docs.keys() & dev_docs.keys()),
        "previous_scored_paragraph_overlap": len(docs.keys() & excluded), "previous_selected_title_overlap": len(titles),
        "final_and_confirmation_background_overlap": len(docs.keys() & (panels["final"][0].keys() | panels["confirmation"][0].keys())),
        "case_ids": [c["id"] for c in selected], "source_ids": [c["source"] for c in selected],
        "normalized_question_sha256": [tr.key(tr.normalize(c["question"])) for c in selected],
        "case_counts_by_title": dict(Counter(docs[c["source"]]["title"] for c in selected)),
        "policy": "Reserve 32 official answerable and 32 native impossible questions. "
                  "Select previously unread passage bodies from earlier development articles only, "
                  "round robin across titles and strata by fixed hashes. Exclude every earlier scored "
                  "question ID, normalized question, reference passage and previously supplied reader passage. "
                  "All remaining development-background passages form the search corpus. No labels given to models.",
    }
    return docs, selected, info


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if (args.output / "independent-arms/final-report.json").exists():
        raise ValueError("Register before seeing the incumbent final score")
    _, cases, info = reserve(args.dataset, args.output)
    dest = args.output / "fresh-full-reader"
    dest.mkdir(exist_ok=True)
    tr.dump(dest / "preregistration.json", info)
    print(info["manifest_sha256"], info["background_documents"], len(cases), info["title_count"])
