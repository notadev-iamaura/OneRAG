"""Reserve independent answerable/unanswerable article panels from official KLUE-MRC validation."""

import argparse
import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from tempfile import TemporaryDirectory

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.rag_growth_prepare import REVISION, VALIDATION_SHA256, digest, identity, parquet_rows

SEED = "onerag-growth-03-ko-validation-v1"


def encode(data):
    return (json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def history(paths):
    questions, source_titles, source_bodies, seen_bodies, hashes = set(), set(), set(), set(), {}
    for path in paths:
        raw = path.read_bytes()
        item = json.loads(raw)
        docs = {doc["id"]: doc for doc in item.get("documents", item.get("docs", []))}
        seen_bodies.update(identity(d["content"]) for d in docs.values())
        for c in item["cases"]:
            questions.add(identity(c["question"]))
            refs = c.get("gold") or ([c["context_source_id"]] if c.get("context_source_id") else c.get("source_ids"))
            # Legacy no-answer rows without article IDs require excluding their entire corpus from sampling.
            for doc_id in refs or docs:
                doc = docs[doc_id]
                source_titles.add(identity(doc["title"]))
                source_bodies.add(identity(doc["content"]))
        hashes[str(path)] = hashlib.sha256(raw).hexdigest()
    return questions, source_titles, source_bodies, seen_bodies, hashes


class ArticleFilter:
    """Reject exact titles/bodies and >=80% Jaccard overlap of normalized five-word shingles."""

    def __init__(self, old_titles, old_bodies):
        self.titles = set(old_titles)
        self.bodies = set(old_bodies)
        self.shingles = []
        self.postings = defaultdict(list)

    def accept(self, row):
        title, body = identity(row["title"]), identity(row["context"])
        if not title or not body or title in self.titles or body in self.bodies:
            return False
        tokens = body.split()
        grams = {" ".join(tokens[i:i+5]) for i in range(max(1, len(tokens)-4))}
        overlap = Counter(other for gram in grams for other in self.postings[gram])
        if any(5 * n >= 4 * (len(grams) + self.shingles[other] - n) for other, n in overlap.items()):
            return False
        idx = len(self.shingles)
        self.shingles.append(len(grams))
        for gram in grams:
            self.postings[gram].append(idx)
        self.titles.add(title)
        self.bodies.add(body)
        return True


def reserve(rows, previous, sizes, corpus_size, seed=SEED):
    questions, titles, bodies, old_seen, hashes = previous
    used_questions = set(questions)
    articles = ArticleFilter(titles, bodies)
    panels = {name: {"corpus": [], "questions": [], "labels": []} for name in sizes}
    before_seen = {}
    for name, count in sizes.items():
        if corpus_size < 2 * count:
            raise ValueError("The corpus must contain one distinct source for each question")
        chosen = Counter()
        for r in sorted(rows, key=lambda r: digest(f"{seed}/{name}/questions/{r['guid']}")):
            pos = not r["is_impossible"]
            q = identity(r["question"])
            if chosen[pos] >= count or not q or q in used_questions:
                continue
            spans = []
            if pos:
                for start, text in zip(r["answers"]["answer_start"], r["answers"]["text"], strict=True):
                    if text and start >= 0 and r["context"].startswith(text, start):
                        span = {"start": start, "end": start+len(text), "text": text}
                        if span not in spans:
                            spans.append(span)
                if not spans:
                    continue
            if not articles.accept(r):
                continue
            doc_id = digest(r["context"])[:20]
            panel = panels[name]
            panel["corpus"].append({"id": doc_id, "title": r["title"], "content": r["context"]})
            panel["questions"].append({"id": r["guid"], "question": r["question"]})
            panel["labels"].append({"id": r["guid"], "answerable": pos, "source_id": doc_id, "spans": spans,
                                    "answers": sorted({s["text"] for s in spans})})
            chosen[pos] += 1
            used_questions.add(q)
            if chosen[True] == chosen[False] == count:
                break
        if chosen != {True: count, False: count}:
            raise ValueError(f"Insufficient independent validation questions for {name}")
        before_seen[name] = sum(identity(d["content"]) in old_seen for d in panels[name]["corpus"])
    for name, panel in panels.items():
        for r in sorted(rows, key=lambda r: digest(f"{seed}/{name}/background/{r['guid']}")):
            if len(panel["corpus"]) == corpus_size:
                break
            if articles.accept(r):
                panel["corpus"].append({"id": digest(r["context"])[:20], "title": r["title"], "content": r["context"]})
        if len(panel["corpus"]) != corpus_size:
            raise ValueError(f"Insufficient disjoint background articles for {name}")
        panel["corpus"].sort(key=lambda d: d["id"])
    manifest = {"schema_version": 1, "dataset": "klue/klue mrc validation", "revision": REVISION,
                "source_sha256": VALIDATION_SHA256, "seed": seed, "corpus_size_per_split": corpus_size,
                "per_split_per_stratum": sizes, "previous_questions_excluded": len(questions),
                "previous_labeled_article_texts_excluded": len(bodies), "previous_files": hashes,
                "selected_question_articles_previously_present_as_background_only": before_seen,
                "deduplication": "Normalized question/title/body, one question per article, "
                "all selected articles across/within splits less than 0.80 five-word shingle Jaccard."}
    return panels, manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--validation", type=Path, required=True)
    parser.add_argument("--exclude", type=Path, nargs="+", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Choose a new reservation directory")
    previous = history(args.exclude)
    panels, reservation = reserve(parquet_rows(args.validation, VALIDATION_SHA256), previous,
                                  {"dev": 40, "final": 80}, 512)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=args.output.parent) as temp:
        dest = Path(temp) / "reservation"
        dest.mkdir()
        files = {}
        for split, parts in panels.items():
            for key, data in parts.items():
                path = dest / f"{split}.{key}.json"
                raw = encode(data)
                path.write_bytes(raw)
                files[path.name] = hashlib.sha256(raw).hexdigest()
        reservation["files"] = files
        (dest / "reservation.json").write_bytes(encode(reservation))
        dest.rename(args.output)
    print(json.dumps(reservation, ensure_ascii=False))


if __name__ == "__main__":
    main()
