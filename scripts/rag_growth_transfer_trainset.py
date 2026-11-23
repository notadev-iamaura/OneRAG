"""Create a ground-truth training corpus from one official TyDi train shard, excluding all validation topics."""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import rag_growth_transfer_tydi as td

TRAIN_SHA = "700742a20446def778bc9a0cbc3b352767e6744a5095cade74916aa4bec8545f"


def build(args):
    import pyarrow.parquet as pq

    if td.digest(args.train) != TRAIN_SHA or td.digest(args.validation) != td.PARQUET_SHA or td.digest(args.squad) != td.SQUAD_SHA:
        raise ValueError("Unregistered public train/validation input")
    validation = pq.ParquetFile(args.validation)
    titles, questions = set(), set()
    for batch in validation.iter_batches(batch_size=256,columns=["document_title","question_text","language"],use_threads=False):
        for r in batch.to_pylist():
            if r["language"] == "english":
                titles.add(td.normalize(r["document_title"]))
                questions.add(td.normalize(r["question_text"]))
    squad = json.loads(args.squad.read_bytes())["data"]
    titles.update(td.normalize(a["title"]) for a in squad)
    questions.update(td.normalize(q["question"]) for a in squad for p in a["paragraphs"] for q in p["qas"])
    blocked = set()
    for path in (args.first, args.dev, args.final):
        p = json.loads(path.read_bytes())
        blocked.update(td.sha(td.normalize(d["content"])) for d in p["documents"].values())
    blocked.update(td.sha(td.normalize(p["context"])) for a in squad for p in a["paragraphs"])
    candidates = []
    columns = ["document_title","question_text","language","annotations"]
    train = pq.ParquetFile(args.train)
    for batch in train.iter_batches(batch_size=256,columns=columns,use_threads=False):
        for r in batch.to_pylist():
            if r["language"] != "english" or td.normalize(r["document_title"]) in titles or td.normalize(r["question_text"]) in questions:
                continue
            a = r["annotations"]
            if a["yes_no_answer"] != ["NONE"]:
                continue
            label = (a["passage_answer_candidate_index"][0],a["minimal_answers_start_byte"][0],a["minimal_answers_end_byte"][0])
            if label != (-1,-1,-1) and not (label[0] >= 0 and 0 <= label[1] < label[2]):
                continue
            qid = td.sha(r["document_title"] + "\n" + r["question_text"])
            candidates.append((qid,r["document_title"],r["question_text"],label))
    chosen, counts = {}, Counter()
    for qid,t,q,label in sorted(candidates,key=lambda c: td.sha("onerag-tydi-train-v1/" + c[0])):
        negative = label == (-1,-1,-1)
        if counts[negative] == 48 or td.normalize(t) in titles or td.normalize(q) in questions:
            continue
        titles.add(td.normalize(t))
        questions.add(td.normalize(q))
        chosen[qid] = (t,q,negative,label)
        counts[negative] += 1
    if counts != {True:48,False:48}:
        raise ValueError("Insufficient disjoint official training records")
    cases,docs = {},{}
    for batch in train.iter_batches(batch_size=32,columns=["language","document_title","question_text","document_plaintext","passage_answer_candidates"],use_threads=False):
        for r in batch.to_pylist():
            qid = td.sha(r["document_title"] + "\n" + r["question_text"])
            if r["language"] != "english" or qid not in chosen:
                continue
            t,q,negative,label = chosen[qid]
            case = {"id":qid,"question":q,"impossible":negative,"source":None,"answers":[]}
            data = r["document_plaintext"].encode()
            bounds = r["passage_answer_candidates"]
            for i,(a,b) in enumerate(zip(bounds["plaintext_start_byte"],bounds["plaintext_end_byte"],strict=True)):
                body = data[a:b].decode()
                if not body.strip() or td.sha(td.normalize(body)) in blocked:
                    continue
                doc = td.sha(t + "\n" + body)
                docs[doc] = {"id":doc,"title":t,"content":body}
                if not negative and i == label[0]:
                    _,left,right = label
                    answer = data[left:right].decode()
                    offset = len(data[a:left].decode())
                    if not a <= left < right <= b or body[offset:offset+len(answer)] != answer:
                        raise ValueError("Incorrect train span offset")
                    case["source"],case["answers"] = doc,[{"text":answer,"answer_start":offset}]
            if not negative and not case["answers"]:
                raise ValueError("Missing nonoverlapping official train span")
            cases[qid] = case
    if set(cases) != set(chosen):
        raise ValueError("Incomplete training material")
    data = {"documents":dict(sorted(docs.items())),"cases":[cases[k] for k in chosen]}
    with args.corpus.open("x") as f:
        json.dump(data,f,sort_keys=True,separators=(",",":"),ensure_ascii=False)
    info = {"source":"google-research-datasets/tydiqa/primary_task/train-00000-of-00012.parquet",
            "revision":td.REV,"shard_sha256":TRAIN_SHA,"validation_sha256":td.PARQUET_SHA,
            "corpus_sha256":td.digest(args.corpus),"code_sha256":td.digest(Path(__file__)),
            "questions_per_stratum":48,"articles":96,"documents":len(docs),"case_ids":list(chosen),
            "rule":"Single official train annotation; exclude all official English validation and SQuAD article names and questions and all measured SQuAD/TyDi paragraph bodies, including the sealed confirmation."}
    with args.receipt.open("x") as f:
        json.dump(info,f,indent=2)
        f.write("\n")
    print(info["documents"],info["corpus_sha256"])


if __name__ == "__main__":
    p=argparse.ArgumentParser(description=__doc__)
    for arg in ("train","validation","squad","first","dev","final","corpus","receipt"):
        p.add_argument("--"+arg,type=Path,required=True)
    build(p.parse_args())
