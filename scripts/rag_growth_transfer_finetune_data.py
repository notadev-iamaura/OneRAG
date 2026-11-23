"""Prepare a balanced two-source QA fine-tune, calibration and train-validation split from official training files."""

import argparse
import json
import math
import re
import sys
from collections import Counter
from pathlib import Path

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import rag_growth_transfer_tydi as td
from scripts.rag_growth_transfer_trainset import TRAIN_SHA

SQUAD_TRAIN_SHA = "68dcfbb971bd3e96d5b46c7177b16c1a4e7d4bdef19fb204502738552dede002"
SIZES = {"calibration": 16, "validation": 16, "train": 128}


def wordset(text):
    return set(re.findall(r"[a-z0-9]+", text.casefold()))


def hard_passage(question, paragraphs):
    terms = wordset(question)
    bags = [wordset(s) for s in paragraphs]
    counts = Counter(t for b in bags for t in b & terms)

    def score(i):
        overlap = sum(math.log((len(bags) + 1) / (counts[t] + 0.5)) for t in bags[i] & terms)
        return overlap / math.sqrt(1 + len(bags[i]) / 100), -i

    return paragraphs[max(range(len(paragraphs)), key=score)]


def run(args):
    import pyarrow.parquet as pq

    if (
        td.digest(args.squad_train) != SQUAD_TRAIN_SHA
        or td.digest(args.tydi_train) != TRAIN_SHA
        or td.digest(args.tydi_valid) != td.PARQUET_SHA
        or td.digest(args.squad_valid) != td.SQUAD_SHA
    ):
        raise ValueError("Unexpected official source file")
    titles, questions, blocked = set(), set(), set()
    for b in pq.ParquetFile(args.tydi_valid).iter_batches(
        batch_size=512, columns=["document_title", "question_text", "language"], use_threads=False
    ):
        for r in b.to_pylist():
            if r["language"] == "english":
                titles.add(td.normalize(r["document_title"]))
                questions.add(td.normalize(r["question_text"]))
    for article in json.loads(args.squad_valid.read_bytes())["data"]:
        titles.add(td.normalize(article["title"]))
        for p in article["paragraphs"]:
            blocked.add(td.sha(td.normalize(p["context"])))
            questions.update(td.normalize(q["question"]) for q in p["qas"])
    for path in args.excluded:
        previous = json.loads(path.read_bytes())
        blocked.update(td.sha(td.normalize(d["content"])) for d in previous["documents"].values())
    cases = {"squad": [], "tydi": []}

    def append(source, qid, title, q, body, answers):
        if (
            td.normalize(title) in titles
            or td.normalize(q) in questions
            or td.sha(td.normalize(body)) in blocked
        ):
            return
        if any(
            body[a["answer_start"] : a["answer_start"] + len(a["text"])] != a["text"]
            for a in answers
        ):
            raise ValueError("Invalid official train answer")
        cases[source].append(
            {
                "id": qid,
                "source": source,
                "title": title,
                "question": q,
                "content": body,
                "answers": answers,
                "impossible": not answers,
            }
        )

    for a in json.loads(args.squad_train.read_bytes())["data"]:
        for p in a["paragraphs"]:
            for item in p["qas"]:
                if bool(item["is_impossible"]) != (not item["answers"]):
                    raise ValueError("Inconsistent SQuAD training label")
                append(
                    "squad", item["id"], a["title"], item["question"], p["context"], item["answers"]
                )
    for b in pq.ParquetFile(args.tydi_train).iter_batches(batch_size=32, use_threads=False):
        for r in b.to_pylist():
            t, q = r["document_title"], r["question_text"]
            if (
                r["language"] != "english"
                or td.normalize(t) in titles
                or td.normalize(q) in questions
            ):
                continue
            a = r["annotations"]
            if a["yes_no_answer"] != ["NONE"]:
                continue
            idx, left, right = (
                a["passage_answer_candidate_index"][0],
                a["minimal_answers_start_byte"][0],
                a["minimal_answers_end_byte"][0],
            )
            data = r["document_plaintext"].encode()
            pc = r["passage_answer_candidates"]
            ranges = list(zip(pc["plaintext_start_byte"], pc["plaintext_end_byte"], strict=True))
            if (idx, left, right) == (-1, -1, -1):
                options = [data[u:v].decode() for u, v in ranges]
                options = [
                    s for s in options if s.strip() and td.sha(td.normalize(s)) not in blocked
                ]
                if not options:
                    continue
                body = hard_passage(q, options)
                ans = []
            elif 0 <= idx < len(ranges) and ranges[idx][0] <= left < right <= ranges[idx][1]:
                u, v = ranges[idx]
                body = data[u:v].decode()
                ans = [
                    {"text": data[left:right].decode(), "answer_start": len(data[u:left].decode())}
                ]
            else:
                continue
            append("tydi", td.sha(t + "\n" + q), t, q, body, ans)
    info = {}
    used_q = set()
    old_bodies = set()
    for name, n in SIZES.items():
        selected = []
        for source in ("squad", "tydi"):
            counts = Counter()
            pool = sorted(cases[source], key=lambda c: td.sha("onerag-span-tuning/" + c["id"]))
            for c in pool:
                split_bucket = (
                    int(td.sha("onerag-span-tuning/article/" + td.normalize(c["title"]))[:12], 16)
                    % 8
                )
                part = (
                    "validation"
                    if split_bucket == 0
                    else ("calibration" if split_bucket == 1 else "train")
                )
                key = td.normalize(c["question"])
                if (
                    name != part
                    or counts[c["impossible"]] >= n
                    or key in used_q
                    or td.sha(td.normalize(c["content"])) in old_bodies
                ):
                    continue
                selected.append(c)
                used_q.add(key)
                counts[c["impossible"]] += 1
            if counts != {True: n, False: n}:
                raise ValueError(
                    f"Insufficient unique official records for {name}/{source}: {counts}"
                )
        old_bodies.update(td.sha(td.normalize(c["content"])) for c in selected)
        path = args.temp / (name + ".json")
        with path.open("x") as f:
            json.dump(selected, f, ensure_ascii=False, separators=(",", ":"))
        info[name] = {
            "sha256": td.digest(path),
            "questions_per_source_per_stratum": n,
            "articles": len({td.normalize(c["title"]) for c in selected}),
            "row_count": len(selected),
        }
    with args.receipt.open("x") as f:
        json.dump(
            {
                "tydi_shard_sha256": TRAIN_SHA,
                "squad_train_sha256": SQUAD_TRAIN_SHA,
                "squad_revision": "e0c66cfec263165fb3c15cb76a22175e371b71d7",
                "tydi_revision": td.REV,
                "code_sha256": td.digest(Path(__file__)),
                "splits": info,
                "method": "Assign articles by fixed hash before sampling, exclude all English evaluation articles and questions. "
                "Use official answer spans, native CLS negatives, and the most lexically related passage in the TyDi native-negative article.",
            },
            f,
            indent=2,
        )
        f.write("\n")
    print(info)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for key in ("squad-train", "tydi-train", "tydi-valid", "squad-valid", "temp", "receipt"):
        p.add_argument("--" + key, required=True, type=Path)
    p.add_argument("--excluded", required=True, nargs="+", type=Path)
    run(p.parse_args())
