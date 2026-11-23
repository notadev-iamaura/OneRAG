"""Reserve and resume a development-only Korean relation review using a loopback GGUF."""

import argparse
import asyncio
import fcntl
import hashlib
import json
import math
import re
import sys
from pathlib import Path
from typing import Any

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.modules.core.generation import korean_relation_review as policy
from scripts.rag_growth_ko_eval import grade, write_new
from scripts.rag_growth_local import ROOT, file_sha256, local_http_client, verify_server

DATA = ROOT / "output/rag-growth-03"
PANELS = DATA / "panels"
SOURCE = DATA / "qwen/rescue-dev.json"
SPANS = DATA / "ko-alt/mps-fp32/dev-spans.jsonl"
RANKS = DATA / "ko-alt/dev-ranks.json"
QWEN = Path.home() / "Models/moe/Qwen3.6-35B-A3B-UD-Q2_K_XL.gguf"
QWEN_SHA = "96b9c0af5c77a4ecaabe3983175112b5ece763261c1ece12b2494b692a70dad7"
Row = dict[str, Any]


def keyed(records: list[Row]) -> dict[str, Row]:
    result = {row["id"]: row for row in records}
    if len(result) != len(records):
        raise ValueError("Repeated case ID in cache")
    return result


def plan(args: argparse.Namespace) -> Row:
    if not 0 < args.port < 65536 or not re.fullmatch(r"[a-f0-9]{64}", args.model_sha256):
        raise ValueError("A valid local port and immutable model SHA-256 are required")
    reserved = json.loads((PANELS / "reservation.json").read_bytes())
    files = {p.name: file_sha256(p) for p in (SOURCE, SPANS, RANKS, Path(__file__), Path(policy.__file__),
             Path(policy.__file__).with_name("grounded_span.py"), ROOT / "scripts/rag_growth_ko_eval.py",
             ROOT / "scripts/rag_growth_gate.py", ROOT / "scripts/rag_growth_local.py",
             ROOT / "app/lib/evidence_sentences.py")}
    for key in ("questions", "corpus", "labels"):
        name = f"dev.{key}.json"
        if file_sha256(PANELS / name) != reserved["files"][name]:
            raise ValueError("Development files differ from their original reservation")
        files[name] = reserved["files"][name]
    return {"scope": "development_only", "files": files, "model_name": args.model_name,
            "model_file": str(args.model_file.resolve()), "model_sha256": args.model_sha256, "port": args.port,
            "temperature": 0, "seed": 37, "retrieval_depth": 2, "max_tokens": list(policy.LIMITS),
            "sample": "all 80 in reserved order, carry upstream errors; 79 eligible fresh reviews",
            "selection": "one fixed policy, success requires both grounded answer accuracy and genuine refusal >=80%; "
                         "all cases, all errors retained. Development findings do not establish generalization."}


def load_inputs() -> tuple[list[Row], dict[str, Row], dict[str, Row], dict[str, list[str]], list[Row]]:
    qs = json.loads((PANELS / "dev.questions.json").read_bytes())
    docs: list[Row] = json.loads((PANELS / "dev.corpus.json").read_bytes())
    baseline = keyed(json.loads(SOURCE.read_bytes())["rows"])
    spans = keyed([json.loads(line) for line in SPANS.read_bytes().splitlines()])
    rank = json.loads(RANKS.read_bytes())
    ids = set(keyed(qs))
    if (len(ids) != 80 or any(set(q) != {"id", "question"} for q in qs)
            or rank["dev_questions_sha256"] != file_sha256(PANELS / "dev.questions.json")
            or any(ids != set(values) for values in (baseline, spans, rank["retrieved"]))):
        raise ValueError("Incomplete or mismatched development inputs")
    return qs, baseline, spans, rank["retrieved"], docs


def inputs(case: Row, base: Row, proposals: Row, retrieved: list[str],
           documents: dict[str, Row]) -> policy.ReviewInput | None:
    first_two = retrieved[:2]
    if (len(first_two) != 2 or len(set(first_two)) != 2 or base["retrieved"] != first_two[:1]
            or proposals["retrieved"][:2] != first_two or base["status"] not in {"answered", "abstained", "error"}):
        raise ValueError("Upstream views do not share the reserved retrieval ranking")
    if base["status"] == "error":
        return None
    options = [s for s in proposals["spans"] if s["source_id"] in first_two]
    if len(options) != 2 or {s["source_id"] for s in options} != set(first_two):
        raise ValueError("Expected exactly one span proposal for each reviewed document")
    if base["status"] == "answered":
        options = [base, *options]
    elif any(base.get(key) for key in ("answer", "source_id", "quote")):
        raise ValueError("An upstream abstention contains an answer")
    return policy.review_input(case["question"], [documents[key] for key in first_two], options)


async def run(args: argparse.Namespace, registration: Row) -> None:
    digest = file_sha256(args.out / "reservation.json")
    qs, baseline, spans, ranks, docs = load_inputs()
    doc_index = keyed(docs)
    cache = args.out / "cases"
    cache.mkdir(exist_ok=True)
    rows = []
    origin = f"http://127.0.0.1:{args.port}"
    with (args.out / "run.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if (args.out / "metrics.json").exists():
            raise ValueError("Completed run already exists")
        async with local_http_client(origin) as client:
            await verify_server(client, args.model_name, args.model_file, args.model_sha256)
            for case in qs:
                qid = case["id"]
                name = hashlib.sha256(qid.encode()).hexdigest()
                output = cache / f"{name}.json"
                if output.exists():
                    row = json.loads(output.read_bytes())
                    if row["id"] != qid or row["reservation_sha256"] != digest:
                        raise ValueError("Cached row belongs to another run")
                    rows.append(row)
                    continue
                prepared = inputs(case, baseline[qid], spans[qid], ranks[qid], doc_index)
                row = {"id": qid, "retrieved": ranks[qid][:2] if prepared else baseline[qid]["retrieved"],
                       "reservation_sha256": digest, "attempts": []}
                if prepared is None:
                    row.update(status="error", error=baseline[qid].get("error"), route="upstream_error")
                else:
                    marker = cache / f"{name}.started"
                    if marker.exists():
                        raise ValueError(f"Found an interrupted case with unknown usage; outstanding ID {qid}")
                    write_new(marker, {"id": qid, "reservation_sha256": digest})

                    async def complete(system: str, prompt: str, limit: int,
                                       attempts: list[Row] = row["attempts"]) -> tuple[str, str]:
                        messages = [{"role": "system", "content": system}, {"role": "user", "content": prompt}]
                        record: Row = {"max_tokens": limit, "prompt_sha256":
                                       hashlib.sha256(json.dumps(messages, ensure_ascii=False).encode()).hexdigest()}
                        attempts.append(record)
                        response = await client.post("/v1/chat/completions", json={
                            "model": args.model_name, "messages": messages, "temperature": 0, "seed": registration["seed"],
                            "max_tokens": limit, "stream": False, "chat_template_kwargs": {"enable_thinking": False},
                            "response_format": {"type": "json_schema", "json_schema": {"name": "relation_review",
                                                "strict": True, "schema": policy.SCHEMA}}})
                        resp = response.raise_for_status().json()
                        choice, = resp["choices"]
                        text = choice["message"].get("content")
                        record.update(finish=choice["finish_reason"], usage=resp.get("usage"), response=text)
                        if not isinstance(text, str) and choice["finish_reason"] == "stop":
                            raise ValueError("Missing completed response text")
                        return text if isinstance(text, str) else "", choice["finish_reason"]

                    try:
                        answer = await policy.review(case["question"], prepared, complete)
                        row.update({"status": "answered", **answer} if answer else {"status": "abstained"})
                    except Exception as err:
                        row.update(status="error", error=f"{type(err).__name__}: {err}"[:320])
                write_new(output, row)
                rows.append(row)
                print(len(rows), qid, row["status"], flush=True)
        labels = json.loads((PANELS / "dev.labels.json").read_bytes())
        verdict = grade(rows, labels, docs)
        before = grade(list(baseline.values()), labels, docs)
        fresh = [a for r in rows for a in r["attempts"]]
        write_new(args.out / "metrics.json", {"reservation_sha256": digest, "baseline": before["summary"],
                  **verdict, "rows": rows, "fresh_calls": len(fresh),
                  "reported_completion_tokens": sum((a.get("usage") or {}).get("completion_tokens", 0) for a in fresh),
                  "calls_with_usage": sum(bool(a.get("usage")) for a in fresh)})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("reserve", "run"))
    parser.add_argument("--model-file", type=Path, default=QWEN)
    parser.add_argument("--model-sha256", default=QWEN_SHA)
    parser.add_argument("--model-name", default="onerag-growth-qwen")
    parser.add_argument("--port", type=int, default=18759)
    parser.add_argument("--out", type=Path, default=DATA / "relation-review")
    args = parser.parse_args()
    registration = plan(args)
    target = args.out / "reservation.json"
    if args.operation == "reserve":
        qs, baselines, spans, ranks, docs = load_inputs()
        corpus = keyed(docs)
        sizes = sorted(len(p.prompt) for q in qs if
                       (p := inputs(q, baselines[q["id"]], spans[q["id"]], ranks[q["id"]], corpus)) is not None)
        if len(sizes) != 79:
            raise ValueError("The fixed development experiment expects one inherited upstream error")
        registration["observed_review_inputs"] = {"count": len(sizes), "max_prompt_chars": max(sizes),
               "median_prompt_chars": sizes[len(sizes)//2], "p95_prompt_chars": sizes[math.ceil(len(sizes)*.95)-1]}
        write_new(target, registration)
        print(registration["observed_review_inputs"], file_sha256(target))
    else:
        registered = json.loads(target.read_bytes())
        if {k: v for k, v in registered.items() if k != "observed_review_inputs"} != registration:
            raise ValueError("Development inputs, model identity, or policy changed after reservation")
        asyncio.run(run(args, registered))


if __name__ == "__main__":
    main()
