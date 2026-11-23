"""Seal a third KLUE confirmation panel without reading any previously scored answers or predictions."""
import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from tempfile import TemporaryDirectory

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.rag_growth_ko_panels import ArticleFilter, encode, history, reserve
from scripts.rag_growth_prepare import VALIDATION_SHA256, digest, identity, parquet_rows

PRIOR = "cb7cf5615742343d0ce57d83119c20c3151dc8debf2920a2ebe26e676d206a42"
SEED = "onerag-growth-03-independent-confirmation-v1"


def conflicts(article: ArticleFilter, row: dict) -> bool:
    body = identity(row["context"])
    if identity(row["title"]) in article.titles or body in article.bodies:
        return True
    words = body.split()
    grams = {" ".join(words[i:i+5]) for i in range(max(1, len(words)-4))}
    matches = Counter(uid for gram in grams for uid in article.postings.get(gram, ()))
    return any(5*n >= 4*(len(grams)+article.shingles[uid]-n) for uid, n in matches.items())


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--validation", required=True, type=Path)
    ap.add_argument("--prior-manifest", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()
    if args.out.exists():
        ap.error("Choose a new reservation directory")
    prior_raw = args.prior_manifest.read_bytes()
    if hashlib.sha256(prior_raw).hexdigest() != PRIOR:
        raise ValueError("Incorrect prior reservation")
    prior = json.loads(prior_raw)
    previous = history([Path(name) for name in prior["previous_files"]])
    if previous[-1] != prior["previous_files"]:
        raise ValueError("Earlier exposure history changed")
    data = parquet_rows(args.validation, VALIDATION_SHA256)
    # Regenerate exactly the old input partitions, verify all hashes, never read any prior predictions.
    old, _ = reserve(data, previous, {"dev": 40, "final": 80}, 512, seed=prior["seed"])
    index = ArticleFilter(set(), set())
    prior_questions, prior_ids = set(previous[0]), set()
    prior_reference_ids: set[str] = set()
    backgrounds: dict[str, dict] = {}
    for name, parts in old.items():
        for key, values in parts.items():
            if hashlib.sha256(encode(values)).hexdigest() != prior["files"][f"{name}.{key}.json"]:
                raise ValueError("Prior reservation could not be reproduced")
        for q in parts["questions"]:
            prior_ids.add(q["id"])
            prior_questions.add(identity(q["question"]))
        prior_reference_ids.update(row["source_id"] for row in parts["labels"])
        for doc in parts["corpus"]:
            if not index.accept({"title": doc["title"], "context": doc["content"]}):
                raise ValueError("Prior panel had an unexpected duplicate")
            backgrounds[doc["id"]] = doc
    untouched = [r for r in data if r["guid"] not in prior_ids and not conflicts(index, r)]
    filtered_history = (prior_questions, previous[1], previous[2], previous[3], previous[4])
    # Preregister 80+80; drop to 40+40 only if unique references are exhausted.
    deficits = []
    for count in (80, 40):
        try:
            panels, spec = reserve(untouched, filtered_history, {"final": count}, 2*count, seed=SEED)
            break
        except ValueError as e:
            deficits.append(str(e))
    else:
        raise ValueError("Fewer than 40 independently sourced questions per group")
    panel = panels["final"]
    guards = ArticleFilter(previous[1], previous[2])
    for doc in panel["corpus"]:
        if not guards.accept({"title": doc["title"], "context": doc["content"]}):
            raise ValueError("Duplicate confirmation reference")
    for r in sorted(untouched, key=lambda d: digest(f"{SEED}/background/{d['guid']}")):
        if len(panel["corpus"]) == 512:
            break
        if guards.accept(r):
            panel["corpus"].append({"id": digest(r["context"])[:20], "title": r["title"], "content": r["context"]})
    reused = 0
    for doc in sorted(backgrounds.values(), key=lambda d: digest(f"{SEED}/reuse/{d['id']}")):
        if len(panel["corpus"]) == 512:
            break
        if doc["id"] not in prior_reference_ids and guards.accept({"title": doc["title"], "context": doc["content"]}):
            panel["corpus"].append(doc)
            reused += 1
    if len(panel["corpus"]) != 512:
        raise ValueError("Fewer than 512 eligible corpus documents")
    panel["corpus"].sort(key=lambda d: d["id"])
    if any(row["source_id"] in backgrounds for row in panel["labels"]):
        raise ValueError("A prior corpus article leaked into confirmation references")
    spec.update(corpus_size_per_split=512, prior_reservation_sha256=PRIOR,
                prior_dev_final_reference_overlap=0, prior_dev_final_corpus_used_as_new_reference=0,
                prior_dev_final_background_articles_reused_as_background=reused, scarcity=deficits,
                protocol="Isolated confirmation, one frozen-policy final run. Reject all 1024 prior dev/final "
                         "corpus articles as references by normalized title/body and 80% five-word shingle Jaccard. "
                         "Earlier labeled articles and questions excluded by normalized identities. Reuse older "
                         "background-only articles where needed. Target 80+80; minimum 40+40.")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=args.out.parent) as temp:
        dest = Path(temp) / "panels"
        dest.mkdir()
        spec["files"] = {}
        for name, values in panel.items():
            raw = encode(values)
            filename = f"final.{name}.json"
            (dest / filename).write_bytes(raw)
            spec["files"][filename] = hashlib.sha256(raw).hexdigest()
        (dest / "reservation.json").write_bytes(encode(spec))
        dest.rename(args.out)
    print(json.dumps({"manifest_sha256": hashlib.sha256(encode(spec)).hexdigest(), "per_class": count,
                      "corpus_size": 512, "prior_dev_final_distractors_reused": reused,
                      "prior_historical_background_used_as_reference":
                          spec["selected_question_articles_previously_present_as_background_only"]["final"]}))


if __name__ == "__main__":
    main()
