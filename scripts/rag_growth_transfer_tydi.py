"""Reserve authentic English TyDi QA answerable and unanimously unanswerable questions from new articles."""

import argparse
import hashlib
import json
import unicodedata
from collections import Counter
from pathlib import Path

REV = "da78f23f9119363459acbaf46bf89426ff26c259"
PARQUET_SHA = "2e9557a6ea4bfd65f381c64b91122c90554e4b00f86e15a8b4f1353be1c81510"
SQUAD_SHA = "80a5225e94905956a6446d296ca1093975c4d3b3260f1d6c8f68bc2ab77182d8"


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def digest(path):
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def normalize(text):
    return " ".join(unicodedata.normalize("NFKC", text).casefold().replace("_", " ").split())


def annotation(a):
    if any(x != "NONE" for x in a["yes_no_answer"]):
        return None
    triples = list(zip(a["passage_answer_candidate_index"], a["minimal_answers_start_byte"],
                       a["minimal_answers_end_byte"], strict=True))
    if len(triples) < 3:
        return None
    if all(t == (-1, -1, -1) for t in triples):
        return True, ()
    supporters = [t for t in triples if t[0] >= 0 and 0 <= t[1] < t[2]]
    votes = Counter(supporters).most_common()
    if not votes or votes[0][1] < 2:
        return None
    passage = votes[0][0][0]
    return False, tuple(sorted({t for t in supporters if t[0] == passage}))


def prepare(args):
    import pyarrow.parquet as pq

    if digest(args.input) != PARQUET_SHA or digest(args.squad) != SQUAD_SHA:
        raise ValueError("Unexpected benchmark source")
    old = json.loads(args.squad.read_bytes())["data"]
    old_titles = {normalize(a["title"]) for a in old}
    old_questions = {normalize(q["question"]) for a in old for p in a["paragraphs"] for q in p["qas"]}
    old_bodies = {sha(p["context"]) for a in old for p in a["paragraphs"]}
    f = pq.ParquetFile(args.input)
    candidates = []
    cols = ["question_text", "document_title", "language", "annotations"]
    for batch in f.iter_batches(batch_size=128, columns=cols, use_threads=False):
        for row in batch.to_pylist():
            title, question = row["document_title"], row["question_text"]
            if row["language"] != "english" or normalize(title) in old_titles or normalize(question) in old_questions:
                continue
            a = annotation(row["annotations"])
            if a:
                qid = sha(title + "\n" + question)
                candidates.append((qid, title, question, *a))
    candidates.sort(key=lambda c: sha("onerag-tydi-transfer-03/fresh/" + c[0]))
    selected, titles, questions = {}, set(), set()
    totals = Counter()
    for qid, title, q, impossible, spans in candidates:
        if totals[impossible] >= 24 or normalize(title) in titles or normalize(q) in questions:
            continue
        selected[qid] = (title, q, impossible, spans)
        totals[impossible] += 1
        titles.add(normalize(title))
        questions.add(normalize(q))
    if totals != {True: 24, False: 24}:
        raise ValueError("Insufficient TyDi English consensus questions")
    docs, cases = {}, {}
    cols = ["question_text", "document_title", "document_plaintext", "language", "passage_answer_candidates"]
    for batch in f.iter_batches(batch_size=32, columns=cols, use_threads=False):
        for row in batch.to_pylist():
            title, q = row["document_title"], row["question_text"]
            qid = sha(title + "\n" + q)
            if row["language"] != "english" or qid not in selected:
                continue
            data = row["document_plaintext"].encode()
            intervals = list(zip(row["passage_answer_candidates"]["plaintext_start_byte"],
                                 row["passage_answer_candidates"]["plaintext_end_byte"], strict=True))
            _, _, impossible, answers = selected[qid]
            result = {"id": qid, "question": q, "source": None, "answers": [], "impossible": impossible}
            for i, (start, end) in enumerate(intervals):
                body = data[start:end].decode()
                doc_id = sha(title + "\n" + body)
                if not body.strip() or sha(body) in old_bodies:
                    continue
                docs[doc_id] = {"id": doc_id, "title": title, "content": body}
                for ref, left, right in answers:
                    if i == ref:
                        if not start <= left < right <= end:
                            raise ValueError("Official answer outside the annotated passage")
                        offset = len(data[start:left].decode())
                        text = data[left:right].decode()
                        if body[offset:offset + len(text)] != text:
                            raise ValueError("Official byte offsets did not map to a source substring")
                        result["source"] = doc_id
                        result["answers"].append({"text": text, "answer_start": offset})
            if not impossible and not result["answers"]:
                raise ValueError("Registered answer has no matching official passage")
            cases[qid] = result
    if cases.keys() != selected.keys():
        raise ValueError("Some selected official records were missing")
    payload = {"documents": dict(sorted(docs.items())), "cases": [cases[k] for k in selected]}
    with args.corpus.open("x") as fp:
        json.dump(payload, fp, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    report = {"dataset": "Google Research TyDi QA v1.0 primary task, English validation",
              "revision": REV, "source_sha256": PARQUET_SHA, "source": "https://huggingface.co/datasets/google-research-datasets/tydiqa",
              "manifest_sha256": digest(args.corpus), "script_sha256": digest(Path(__file__)),
              "case_ids": list(selected), "documents": len(docs), "questions_per_stratum": 24, "unique_titles": len(titles),
              "previous_squad_title_overlap": len(titles & old_titles), "previous_squad_question_overlap": len(questions & old_questions),
              "scope": "One question and one distinct source article per case. Index every nonempty official passage "
                       "from the 48 selected articles as a shared candidate corpus, excluding exact SQuAD passages. "
                       "Native negatives require three unanimous non-passage, non-minimal, non-yes/no judgements. "
                       "Positives require two exact span and passage votes. Yes/no and ambiguous cases excluded."}
    with args.registration.open("x") as fp:
        json.dump(report, fp, ensure_ascii=False, indent=2)
        fp.write("\n")
    print(report["manifest_sha256"], len(docs), len(cases))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("input", "squad", "corpus", "registration"):
        parser.add_argument("--" + name, required=True, type=Path)
    prepare(parser.parse_args())
