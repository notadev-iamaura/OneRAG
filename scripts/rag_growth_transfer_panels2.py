"""Reserve two article-, question- and paragraph-disjoint English TyDi panels after the first transfer."""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import rag_growth_transfer_tydi as td


def reserve(args):
    import pyarrow.parquet as pq

    if td.digest(args.input) != td.PARQUET_SHA or td.digest(args.squad) != td.SQUAD_SHA:
        raise ValueError("Unexpected Google or Stanford source")
    if td.digest(args.previous) != json.loads(args.previous_registration.read_text())["manifest_sha256"]:
        raise ValueError("First TyDi panel changed")
    old = json.loads(args.previous.read_bytes())
    squad = json.loads(args.squad.read_bytes())["data"]
    titles = {td.normalize(d["title"]) for d in old["documents"].values()} | {td.normalize(a["title"]) for a in squad}
    questions = {td.normalize(c["question"]) for c in old["cases"]} | {
        td.normalize(q["question"]) for a in squad for p in a["paragraphs"] for q in p["qas"]}
    bodies = {td.sha(td.normalize(d["content"])) for d in old["documents"].values()} | {
        td.sha(td.normalize(p["context"])) for a in squad for p in a["paragraphs"]}
    source = pq.ParquetFile(args.input)
    pool = []
    cols = ["question_text", "document_title", "annotations", "language"]
    for batch in source.iter_batches(batch_size=128, columns=cols, use_threads=False):
        for r in batch.to_pylist():
            t, q = r["document_title"], r["question_text"]
            if r["language"] == "english" and td.normalize(t) not in titles and td.normalize(q) not in questions:
                result = td.annotation(r["annotations"])
                if result is not None:
                    pool.append((td.sha(t + "\n" + q), t, q, *result))
    info = {}
    for name, n in (("development", 16), ("confirmation", 24)):
        selected, counts = {}, Counter()
        for qid, title, q, impossible, spans in sorted(pool, key=lambda s: td.sha("onerag-english-transfer-2/" + name + "/" + s[0])):
            if counts[impossible] >= n or td.normalize(title) in titles or td.normalize(q) in questions:
                continue
            selected[qid] = (title, q, impossible, spans)
            titles.add(td.normalize(title))
            questions.add(td.normalize(q))
            counts[impossible] += 1
        if counts != {True: n, False: n}:
            raise ValueError("Not enough independent unanimous-negative and agreed-positive articles")
        docs, cases = {}, {}
        cols = ["question_text", "document_title", "document_plaintext", "language", "passage_answer_candidates"]
        for batch in source.iter_batches(batch_size=32, columns=cols, use_threads=False):
            for r in batch.to_pylist():
                qid = td.sha(r["document_title"] + "\n" + r["question_text"])
                if qid not in selected or r["language"] != "english":
                    continue
                title, q, impossible, labels = selected[qid]
                raw = r["document_plaintext"].encode()
                candidates = r["passage_answer_candidates"]
                intervals = zip(candidates["plaintext_start_byte"], candidates["plaintext_end_byte"], strict=True)
                case = {"id": qid, "question": q, "impossible": impossible, "answers": [], "source": None}
                for i, (a,b) in enumerate(intervals):
                    text = raw[a:b].decode()
                    if not text.strip() or td.sha(td.normalize(text)) in bodies:
                        continue
                    doc = td.sha(title + "\n" + text)
                    docs[doc] = {"id": doc, "title": title, "content": text}
                    for index, left, right in labels:
                        if index != i:
                            continue
                        answer, offset = raw[left:right].decode(), len(raw[a:left].decode())
                        if not a <= left < right <= b or text[offset:offset + len(answer)] != answer:
                            raise ValueError("Invalid official answer offset")
                        case["answers"].append({"text": answer, "answer_start": offset})
                        case["source"] = doc
                if not impossible and not case["answers"]:
                    raise ValueError("A selected answer was excluded by the source disjointness rule")
                cases[qid] = case
        if cases.keys() != selected.keys():
            raise ValueError("Not every reserved question was recovered")
        new_bodies = {td.sha(td.normalize(d["content"])) for d in docs.values()}
        if new_bodies & bodies:
            raise ValueError("Confirmed paragraph leakage")
        bodies.update(new_bodies)
        panel = args.temp / (name + ".json")
        with panel.open("x") as stream:
            json.dump({"documents": dict(sorted(docs.items())), "cases": [cases[qid] for qid in selected]},
                      stream, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        info[name] = {"manifest_sha256": td.digest(panel), "questions_per_stratum": n, "documents": len(docs),
                      "question_ids": list(selected), "titles": len({td.normalize(d["title"]) for d in docs.values()}),
                      "observed_overlap_with_prior_titles_questions_or_bodies": 0}
    with args.registration.open("x") as stream:
        json.dump({"source_sha256": td.PARQUET_SHA, "revision": td.REV, "first_tydi_sha256": td.digest(args.previous),
                   "squad_sha256": td.SQUAD_SHA, "sampler": td.digest(Path(__file__)),
                   "shared_sampler": td.digest(Path(td.__file__)), "panels": info}, stream, indent=2)
        stream.write("\n")
    print({k: (v["documents"], v["questions_per_stratum"], v["manifest_sha256"]) for k,v in info.items()})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for field in ("input","squad","previous","previous-registration","temp","registration"):
        parser.add_argument("--" + field, type=Path, required=True)
    reserve(parser.parse_args())
