"""Compare Korean BM25 with hybrid passage retrieval and a source-checked local reader."""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import sys
import time
from dataclasses import asdict
from importlib.metadata import version
from pathlib import Path
from typing import Any, cast

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.modules.core.generation.korean_passage_selection import Policy, select_passage
from app.modules.core.generation.korean_span_reader import KoreanSpanReader, SpanAnswer
from app.modules.core.generation.passage_sufficiency import PassageSufficiency
from app.modules.core.retrieval.retrievers.korean_hybrid_passage import KoreanHybridPassageRetriever
from scripts.rag_growth_ko_eval import grade, write_new
from scripts.rag_growth_local import ROOT, Corpus, file_sha256

Row = dict[str, Any]
OUT = ROOT / "output/rag-growth-03/tydi-ko-retrieval"
POLICIES = ("verifier", "joint")
THRESHOLD = 2.958441734313965


def load(path: Path, expected: str | None = None) -> Any:
    raw = path.read_bytes()
    if expected is not None and hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError(f"Registered file changed: {path.name}")
    return json.loads(raw)


def identity(args: argparse.Namespace) -> Row:
    files = [
        Path(__file__),
        ROOT / "app/modules/core/generation/korean_passage_selection.py",
        ROOT / "app/modules/core/generation/korean_span_reader.py",
        ROOT / "app/modules/core/generation/passage_sufficiency.py",
        ROOT / "app/modules/core/retrieval/retrievers/korean_hybrid_passage.py",
        ROOT / "app/modules/core/retrieval/retrievers/local_span_retriever.py",
        ROOT / "scripts/rag_growth_local.py",
        ROOT / "scripts/rag_growth_ko_eval.py",
        *(
            ROOT / "app/modules/core/retrieval/bm25_engine" / n
            for n in ("index.py", "tokenizer.py", "linked_titles.py")
        ),
    ]
    models = {}
    for name in ("embedding", "reader", "verifier"):
        folder = getattr(args, name)
        models[name] = {
            p.name: file_sha256(p)
            for p in sorted(folder.iterdir())
            if p.is_file()
            and (
                p.suffix == ".safetensors"
                or p.name
                in {
                    "tokenizer.json",
                    "config.json",
                    "reader_config.json",
                    "tokenizer_config.json",
                    "special_tokens_map.json",
                    "vocab.txt",
                    "sentencepiece.bpe.model",
                }
            )
        }
        if "model.safetensors" not in models[name]:
            raise ValueError(f"Missing local model: {name}")
    if (
        models["embedding"]["model.safetensors"]
        != "1a55775f53449dac10a2bcbc312469fac40b96d53198c407081a831f81c98477"
    ):
        raise ValueError("Wrong multilingual E5 checkpoint")
    if (
        models["reader"]["model.safetensors"]
        != "01ca60249063500d6d6828a14863416ae88afc907220785ac82a98e01f96317b"
    ):
        raise ValueError("Wrong mixed Korean extractive checkpoint")
    return {
        "files": {str(p.relative_to(ROOT)): file_sha256(p) for p in files},
        "models": models,
        "device": args.device,
        "packages": {k: version(k) for k in ("transformers", "torch", "kiwipiepy", "rank-bm25", "numpy")},
        "panel_registration": file_sha256(args.panels / "reservation.json"),
        "depth": 8,
        "span_threshold": THRESHOLD,
        "policies": list(POLICIES),
        "selector": "eligible first, higher worse stratum, total, fewer errors, verifier tie-break",
        "eligibility": "At least 2 more strict answers, at most one fewer valid abstention (>=12/16), higher total, OR both strata at least 80%. "
        "No additional model errors. More correct reference passages in hybrid first eight than original BM25 first one. "
        "Compare against both original one-passage verifier and matched single-passage policy.",
        "comparator": "Production linked-title Korean BM25 top one, same local QA model and verifier. Separate from other historical generative results.",
    }


def rank_questions(args: argparse.Namespace, docs: list[Row], questions: list[Row]) -> list[Row]:
    baseline = Corpus(docs).index
    hybrid = KoreanHybridPassageRetriever(docs, args.embedding, args.device)
    rows = []
    for q in questions:
        lexical = [d["id"] for d in baseline.search(q["question"], 8)]
        # Linked-title expansion depends on requested depth; record the actual independent top-one call.
        single = [d["id"] for d in baseline.search(q["question"], 1)]
        fused = hybrid.rank(q["question"], 8)
        if len(single) > 1 or len(fused) != 8 or len(set(fused)) != 8:
            raise ValueError("Missing registered Korean retrieval candidates")
        rows.append({"id": q["id"], "single": single, "lexical": lexical, "hybrid": fused})
    return rows


def score_questions(
    args: argparse.Namespace, docs: Row, questions: list[Row], ranks: list[Row], *, support: bool
) -> list[Row]:
    model: Any = (
        PassageSufficiency(args.verifier, args.device)
        if support
        else KoreanSpanReader(args.reader, device=args.device)
    )
    results = []
    for n, (q, r) in enumerate(zip(questions, ranks, strict=True), 1):
        if q["id"] != r["id"]:
            raise ValueError("Mismatched rank cache")
        ids = list(dict.fromkeys([*r["hybrid"], *r["single"]]))
        values: Row = {}
        for first in range(0, len(ids), 4):
            keys = ids[first : first + 4]
            selected = [docs[i] for i in keys]
            try:
                if support:
                    scores = model.scores(q["question"], selected)
                    values.update(zip(keys, scores, strict=True))
                else:
                    spans = model.predict_spans(q["question"], selected)
                    if [s.source_id for s in spans] != keys:
                        raise ValueError("Reader reordered spans")
                    values.update((s.source_id, asdict(s)) for s in spans)
            except Exception as exc:
                values.update((k, {"error": f"{type(exc).__name__}: {exc}"}) for k in keys)
        results.append({"id": q["id"], "values": values})
        if n % 8 == 0:
            print("sufficiency" if support else "reader", n, "/", len(questions), flush=True)
    return results


def predict(
    ranks: list[Row], scores: list[Row], spans: list[Row], docs: Row, arm: str, policy: Policy
) -> list[Row]:
    rows = []
    for rank, v, s in zip(ranks, scores, spans, strict=True):
        if rank["id"] != v["id"] or rank["id"] != s["id"]:
            raise ValueError("Question identity mismatch")
        ids = rank[arm]
        row: Row = {"id": rank["id"], "retrieved": ids, "reranked": []}
        try:
            for key in ids:
                for val in (v["values"][key], s["values"][key]):
                    if isinstance(val, dict) and "error" in val:
                        raise ValueError(val["error"])
            order, span = select_passage(
                [docs[k] for k in ids],
                [SpanAnswer(**s["values"][k]) for k in ids],
                [v["values"][k] for k in ids],
                policy,
                THRESHOLD,
            )
            row["reranked"] = order
            row.update(
                {"status": "abstained"} if span is None else {"status": "answered", **asdict(span)}
            )
        except (ValueError, TypeError) as exc:
            row.update(status="error", error=str(exc))
        rows.append(row)
    return rows


def counts(result: Row) -> tuple[int, int, int]:
    s = result["summary"]
    return s["answerable"]["correct"], s["unanswerable"]["correct"], s["statuses"].get("error", 0)


def improves(candidate: tuple[int, int, int], baseline: tuple[int, int, int], n: int) -> bool:
    p, z, e = candidate
    bp, bz, be = baseline
    return e <= be and (
        (5 * p >= 4 * n and 5 * z >= 4 * n)
        or (p >= bp + 2 and z >= bz - 1 and 4 * z >= 3 * n and p + z > bp + bz)
    )


def assess(
    args: argparse.Namespace,
    docs: list[Row],
    labels: list[Row],
    ranks: list[Row],
    pred: Row,
    modes: list[str],
) -> Row:
    positive = {label["id"]: label["source_id"] for label in labels if label["answerable"]}
    n = len(positive)
    if len(labels) != 2 * n or n != (16 if args.split == "dev" else 24):
        raise ValueError("Unexpected answerability strata")

    def hits(rows: list[Row], field: str, depth: int) -> int:
        return sum(positive[r["id"]] in r[field][:depth] for r in rows if r["id"] in positive)

    retrieval = {
        "positive_n": n,
        "bm25_single": hits(ranks, "single", 1),
        "bm25_at8": hits(ranks, "lexical", 8),
        "hybrid_at1": hits(ranks, "hybrid", 1),
        "hybrid_at8": hits(ranks, "hybrid", 8),
    }
    metrics = {key: grade(rows, labels, docs) for key, rows in pred.items()}
    options = []
    for mode in modes:
        key = "hybrid_" + mode
        positive_count, neg_count, errors = counts(metrics[key])
        retrieval[key + "_reranked_at1"] = hits(pred[key], "reranked", 1)
        retrieval[key + "_reranked_at8"] = hits(pred[key], "reranked", 8)
        qualified = retrieval["hybrid_at8"] > retrieval["bm25_single"] and all(
            improves(counts(metrics[key]), counts(metrics[c]), n)
            for c in {"single_verifier", "single_" + mode}
        )
        options.append(
            (
                qualified,
                min(positive_count, neg_count),
                positive_count + neg_count,
                -errors,
                mode == "verifier",
                mode,
            )
        )
    chosen = max(options)
    return {
        "retrieval": retrieval,
        "metrics": metrics,
        "selected": chosen[-1],
        "eligible": chosen[0],
        "both_at_least_80": metrics["hybrid_" + chosen[-1]]["summary"]["both_at_least_80"],
    }


def run(args: argparse.Namespace) -> None:
    import torch

    torch.set_num_threads(2)
    args.output.mkdir(parents=True, exist_ok=True)
    regfile = args.output / "policy-registration.json"
    ident = identity(args)
    if args.split == "register":
        write_new(regfile, ident)
        return
    if load(regfile) != ident:
        raise ValueError("Registered retrieval policy or corpus changed")
    marker = args.output / (args.split + ".started.json")
    modes = list(POLICIES)
    if args.split == "final":
        selected = load(args.output / "selected.json")
        development = load(args.output / "dev.metrics.json", selected["development_sha256"])
        if (
            not selected["eligible"]
            or development["eligible"] is not True
            or selected["mode"] != development["selected"]
            or selected["registration_sha256"] != file_sha256(regfile)
            or selected["development_sha256"] != file_sha256(args.output / "dev.metrics.json")
        ):
            raise ValueError("No eligible, frozen development policy")
        modes = [selected["mode"]]
    write_new(
        marker, {"split": args.split, "modes": modes, "registration_sha256": file_sha256(regfile)}
    )
    reservation = load(args.panels / "reservation.json")

    def part(name: str) -> list[Row]:
        f = f"{args.split}.{name}.json"
        return list(load(args.panels / f, reservation["files"][f]))

    questions, docs = part("questions"), part("corpus")
    if any(set(q) != {"id", "question"} for q in questions):
        raise ValueError("Unexpected fields in inference input")
    by_id = {d["id"]: d for d in docs}
    start = time.monotonic()

    def save(name: str, obj: Any) -> None:
        write_new(args.output / (args.split + "." + name + ".json"), obj)

    def unload() -> None:
        gc.collect()
        if args.device == "mps":
            torch.mps.empty_cache()

    ranks = rank_questions(args, docs, questions)
    save("rankings", ranks)
    print("rankings complete", len(questions), "questions", len(docs), "passages", flush=True)
    unload()
    scores = score_questions(args, by_id, questions, ranks, support=True)
    save("sufficiency", scores)
    unload()
    spans = score_questions(args, by_id, questions, ranks, support=False)
    save("spans", spans)
    unload()
    preds = {}
    for arm, policy in dict.fromkeys(
        [("single", "verifier"), *((a, p) for a in ("hybrid", "single") for p in modes)]
    ):
        preds[arm + "_" + policy] = predict(ranks, scores, spans, by_id, arm, cast(Policy, policy))
    save("predictions", preds)
    result = assess(args, docs, part("labels"), ranks, preds, modes)
    result.update(
        seconds=time.monotonic() - start,
        registration_sha256=file_sha256(regfile),
        predictions_sha256=file_sha256(args.output / (args.split + ".predictions.json")),
    )
    save("metrics", result)
    if args.split == "dev":
        write_new(
            args.output / "selected.json",
            {
                "eligible": result["eligible"],
                "mode": result["selected"],
                "registration_sha256": file_sha256(regfile),
                "development_sha256": file_sha256(args.output / "dev.metrics.json"),
            },
        )
    print(
        result["selected"],
        result["eligible"],
        result["retrieval"],
        {k: counts(v) for k, v in result["metrics"].items()},
        flush=True,
    )


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("split", choices=["register", "dev", "final"])
    ap.add_argument("--panels", type=Path, default=OUT / "panels")
    ap.add_argument("--output", type=Path, default=OUT / "run")
    ap.add_argument("--reader", type=Path, default=ROOT / "models/rag-growth-03/ko-mixed-512")
    ap.add_argument("--verifier", type=Path, default=ROOT / "models/rag-growth-03/ko-sufficiency")
    ap.add_argument(
        "--embedding",
        type=Path,
        default=Path.home()
        / ".cache/huggingface/hub/models--intfloat--multilingual-e5-small/snapshots/614241f622f53c4eeff9890bdc4f31cfecc418b3",
    )
    ap.add_argument("--device", choices=("mps", "cpu"), default="mps")
    run(ap.parse_args())
