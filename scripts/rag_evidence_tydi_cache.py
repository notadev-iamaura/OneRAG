"""Collect source-checked Korean logits and sentence relevance on a fixed top-eight retrieval."""

import argparse
import gc
import json
import os
import sys
from dataclasses import asdict, replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))

from app.modules.core.generation.korean_span_reader import SpanAnswer
from app.modules.core.generation.passage_sufficiency import PassageSufficiency
from app.modules.core.generation.tydi_evidence_spans import KoreanEvidenceProposer
from app.modules.core.retrieval.retrievers.korean_hybrid_passage import KoreanHybridPassageRetriever
from scripts.rag_growth_ko_eval import write_new
from scripts.rag_growth_local import file_sha256

OLD = ROOT / "output/rag-growth-03/tydi-ko-retrieval"
OUT = ROOT / "output/rag-evidence-selection/tydi"
MODEL_BASE = ROOT / "models/rag-growth-03"
READER = MODEL_BASE / "ko-mixed-512"
VERIFIER = MODEL_BASE / "ko-sufficiency"
E5 = Path.home() / ".cache/huggingface/hub/models--intfloat--multilingual-e5-small/snapshots/614241f622f53c4eeff9890bdc4f31cfecc418b3"


def read(path):
    return json.loads(path.read_bytes())


def collect(name, panels, out, *, device="cpu", reuse=None, reuse_ranks=None):
    import torch

    if device != "cpu":
        raise ValueError("The registered evidence experiment uses CPU inference")
    torch.set_num_threads(4)
    os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", TOKENIZERS_PARALLELISM="false")
    manifest = read(panels / "reservation.json")
    def part(kind):
        key = f"{name}.{kind}.json"
        if file_sha256(panels / key) != manifest["files"][key]:
            raise ValueError(f"Registered public input changed: {key}")
        return read(panels / key)

    documents, questions = part("corpus"), part("questions")
    if any(set(q) != {"id", "question"} for q in questions):
        raise ValueError("QA inference may only read public questions and documents")
    docs = {d["id"]: d for d in documents}
    expected = {q["id"] for q in questions}
    if len(expected) != len(questions) or len(docs) != len(documents):
        raise ValueError("Repeated source or question ID")
    out.mkdir(parents=True, exist_ok=True)
    pinned = read(OLD / "run/policy-registration.json")["models"]
    for k, folder in (("embedding", E5), ("reader", READER), ("verifier", VERIFIER)):
        if any(file_sha256(folder / f) != h for f, h in pinned[k].items()):
            raise ValueError("Frozen retrieval, QA or relevance weights changed")
    receipt = {"panel_sha256": file_sha256(panels / "reservation.json"),
               "corpus_sha256": manifest["files"][f"{name}.corpus.json"],
               "questions_sha256": manifest["files"][f"{name}.questions.json"],
               "model_pins_sha256": file_sha256(OLD / "run/policy-registration.json"),
               "collector_sha256": file_sha256(Path(__file__)), "device": device, "depth": 8, "nbest": 6}
    cached_spans, cached_scores = {}, {}
    if reuse_ranks is not None:
        if name == "final" or reuse is not None:
            raise ValueError("Rank-only recovery is restricted to prior development/fit inference")
        initial = read(reuse_ranks / (name + ".cache-started.json"))
        if any(initial[key] != receipt[key] for key in (
            "panel_sha256", "corpus_sha256", "questions_sha256", "model_pins_sha256", "device", "depth"
        )):
            raise ValueError("Prior physical rank computation does not match these sources")
        receipt["reused_ranks_sha256"] = file_sha256(reuse_ranks / (name + ".ranks.json"))
    if reuse is not None:
        if name == "final":
            raise ValueError("Independent confirmation must use fresh inference")
        earlier = read(reuse / (name + ".cache.json"))
        if any(earlier[key] != receipt[key] for key in (
            "panel_sha256", "corpus_sha256", "questions_sha256", "model_pins_sha256", "device", "depth", "nbest"
        )) or any(file_sha256(reuse / f) != h for f, h in earlier["files"].items()):
            raise ValueError("Previously measured data or models changed")
        receipt["recovered_from_sha256"] = file_sha256(reuse / (name + ".cache.json"))
        cached_spans = {r["id"]: r for r in map(json.loads, (reuse / (name + ".spans.jsonl")).read_text().splitlines())}
        cached_scores = {r["id"]: r for r in map(json.loads, (reuse / (name + ".support.jsonl")).read_text().splitlines())}
        if cached_spans.keys() != expected or cached_scores.keys() != expected:
            raise ValueError("Incomplete original prediction files")
        # Repeat one previously successful row to check numerical equality across token-type handling.
        receipt["repeat_success_id"] = next((i for i in cached_spans if "error" not in cached_spans[i]), None)
    write_new(out / (name + ".cache-started.json"), receipt)
    if name == "dev":
        if panels.resolve() != (OLD / "panels").resolve():
            raise ValueError("The development cache is restricted to established official train questions")
        ranks = {r["id"]: r["hybrid"] for r in read(OLD / "run/dev.rankings.json")}
        full_scores = {r["id"]: r["values"] for r in read(OLD / "run/dev.sufficiency.json")}
        receipt["old_rank_sha256"] = file_sha256(OLD / "run/dev.rankings.json")
        receipt["old_support_sha256"] = file_sha256(OLD / "run/dev.sufficiency.json")
    elif reuse is not None or reuse_ranks is not None:
        ranks, full_scores = read((reuse if reuse is not None else reuse_ranks) / (name + ".ranks.json")), {}
    else:
        search = KoreanHybridPassageRetriever(documents, E5, device)
        ranks = {q["id"]: search.rank(q["question"], 8) for q in questions}
        del search
        gc.collect()
        full_scores = {}
    if ranks.keys() != expected or any(len(ids) != 8 or len(set(ids)) != 8 or not set(ids) <= docs.keys() for ids in ranks.values()):
        raise ValueError("Incomplete genuine top-eight retrieval")
    write_new(out / (name + ".ranks.json"), ranks)
    reader = KoreanEvidenceProposer(READER, device)
    spanfile = out / (name + ".spans.jsonl")
    with spanfile.open("x") as handle:
        for no, q in enumerate(questions, 1):
            qid = q["id"]
            ranked = [docs[key] for key in ranks[qid]]
            cached = cached_spans.get(qid, {})
            if cached and "error" not in cached and qid != receipt.get("repeat_success_id"):
                handle.write(json.dumps(cached, ensure_ascii=False) + "\n")
                continue
            try:
                candidates = []
                for i in range(0, len(ranked), 4):
                    proposals = reader.propose(q["question"], ranked[i : i + 4], 6)
                    candidates.extend([[asdict(replace(s, document_index=i + n)) for s in group]
                                       for n, group in enumerate(proposals)])
                row = {"id": qid, "candidates": candidates}
            except Exception as exc:
                row = {"id": qid, "error": f"{type(exc).__name__}: {exc}"[:200]}
            if name == "final":
                try:
                    original = []
                    for i in range(0, len(ranked), 4):
                        old = reader.predict_spans(q["question"], ranked[i : i + 4])
                        original.extend([asdict(replace(s, document_index=i+n)) for n, s in enumerate(old)])
                    row["incumbent_spans"] = original
                except Exception as exc:
                    row["incumbent_error"] = f"{type(exc).__name__}: {exc}"[:200]
            if qid == receipt.get("repeat_success_id") and row != cached:
                raise ValueError("Previously successful raw logits/offsets changed on direct replay")
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            handle.flush()
            if no % 8 == 0:
                print(name, "nbest", no, flush=True)
    del reader
    gc.collect()
    verifier = PassageSufficiency(VERIFIER, device)
    scorefile = out / (name + ".support.jsonl")
    with spanfile.open() as raw, scorefile.open("x") as dest:
        for no, (q, line) in enumerate(zip(questions, raw, strict=True), 1):
            item = json.loads(line)
            qid = q["id"]
            assert qid == item["id"]
            ranked = [docs[key] for key in ranks[qid]]
            row = {"id": qid}
            cached = cached_scores.get(qid, {})
            if cached and "error" not in cached:
                dest.write(json.dumps(cached, ensure_ascii=False) + "\n")
                continue
            try:
                def score(batch, question=q["question"]):
                    return [s for i in range(0, len(batch), 4) for s in verifier.scores(question, batch[i : i + 4])]
                full = ([full_scores[qid][d["id"]] for d in ranked] if qid in full_scores else score(ranked))
                row["full"] = full
                if item.get("error"):
                    raise ValueError(item["error"])
                reduced, contexts = {}, {}
                for d, candidates, doc_score in zip(ranked, item["candidates"], full, strict=True):
                    spans = [SpanAnswer(**s) for s in candidates]
                    quotes = list(dict.fromkeys(s.quote for s in spans))[:2]
                    reduced[d["id"]] = {}
                    for quote in quotes:
                        if quote == d["content"]:
                            reduced[d["id"]][quote] = doc_score
                        else:
                            contexts[(d["id"], quote)] = {"id": d["id"], "title": d["title"], "content": quote}
                for (source, quote), val in zip(contexts, score(list(contexts.values())), strict=True):
                    reduced[source][quote] = val
                row.update(full=full, sentence=reduced)
            except Exception as exc:
                row["error"] = f"{type(exc).__name__}: {exc}"[:200]
            dest.write(json.dumps(row, ensure_ascii=False) + "\n")
            dest.flush()
            if no % 8 == 0:
                print(name, "support", no, flush=True)
    receipt["files"] = {p.name: file_sha256(p) for p in (spanfile, scorefile, out / (name + ".ranks.json"))}
    write_new(out / (name + ".cache.json"), receipt)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("name", choices=("fit", "dev"))
    p.add_argument("--panels", type=Path, required=True)
    p.add_argument("--output", type=Path, default=OUT)
    p.add_argument("--reuse", type=Path)
    p.add_argument("--reuse-ranks", type=Path)
    a = p.parse_args()
    collect(a.name, a.panels, a.output, reuse=a.reuse, reuse_ranks=a.reuse_ranks)
