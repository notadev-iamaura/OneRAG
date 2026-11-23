"""Evaluate the local generative reader with public, independently computed passage rankings."""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.modules.core.generation.english_grounded_answer import read_english_answer
from scripts import rag_growth_transfer as squad
from scripts.rag_growth_baseline_replay import GGUF_SHA
from scripts.rag_growth_ko_eval import confidence, write_new
from scripts.rag_growth_local import ROOT, file_sha256, local_http_client, verify_server


async def run(args: argparse.Namespace) -> None:
    from openai import AsyncOpenAI

    from app.lib.llm_client import OllamaLLMClient

    if not args.register and (args.output.exists() or args.output.with_suffix(".jsonl").exists()):
        raise ValueError("Provide a new destination")
    if file_sha256(args.dataset) != squad.DATA_SHA:
        raise ValueError("Unexpected SQuAD version")
    if args.panel:
        from scripts.rag_growth_transfer_challenger_rank import load_challenger
        docs, cases = load_challenger(args.dataset, args.panel)
        provenance = squad.load(args.panel.parent / "ranking-provenance.json")
        if (file_sha256(args.rankings) != provenance["rankings_sha256"]
                or file_sha256(args.panel) != provenance["panel_sha256"]):
            raise ValueError("Rankings no longer match registered retrieval")
    else:
        docs, cases = squad.panels(squad.load(args.dataset)["data"])["development"]
    rankings = {}
    for line in args.rankings.read_text().splitlines():
        row = json.loads(line)
        rankings[row["id"]] = row["hybrid"][:3]
    if set(rankings) != {c["id"] for c in cases} or any(
        not 0 < len(ids) <= 3 or len(set(ids)) != len(ids) or not set(ids) <= docs.keys()
        for ids in rankings.values()
    ):
        raise ValueError("Invalid preregistered ranking coverage")
    code = ("scripts/rag_growth_english_generation.py", "scripts/rag_growth_transfer.py",
            "scripts/rag_growth_transfer_reserve.py", "scripts/rag_growth_transfer_challenger_rank.py",
            "app/modules/core/generation/english_grounded_answer.py",
            "app/modules/core/generation/grounded_span.py", "app/lib/llm_client.py", "app/lib/evidence_sentences.py")
    identity = {"weights_sha256": GGUF_SHA, "rankings": file_sha256(args.rankings),
                "panel": file_sha256(args.panel) if args.panel else "development",
                "code": {name: file_sha256(ROOT/name) for name in code}}
    if args.register:
        if not args.panel or not args.freeze:
            raise ValueError("Register a fresh panel and its fixed policy together")
        write_new(args.freeze, identity)
        return
    if args.panel:
        if not args.freeze or squad.load(args.freeze) != identity:
            raise ValueError("Register the model and policy before the fresh panel")
        write_new(args.freeze.with_suffix(".started.json"), identity)
    alias = "onerag-growth-qwen"
    origin = "http://127.0.0.1:18759"
    rows = []
    async with local_http_client(origin) as client:
        await verify_server(client, alias, args.model_file, GGUF_SHA)
        model = OllamaLLMClient({"model": alias, "base_url": origin, "temperature": 0})
        model._client = AsyncOpenAI(base_url=origin+"/v1", api_key="not-needed", http_client=client,
                                    max_retries=0, timeout=120)
        with args.output.with_suffix(".jsonl").open("x") as stream:
            for case in cases:
                ids = rankings[case["id"]]
                try:
                    span = await read_english_answer(model, case["question"], [docs[k] for k in ids])
                    row = {"status": "answered", **span} if span else {"status": "abstained"}
                except Exception as exc:
                    row = {"status": "error", "error": str(exc)[:240]}
                row.update(id=case["id"], retrieved=ids)
                stream.write(json.dumps(row, ensure_ascii=False) + "\n")
                stream.flush()
                rows.append(row)
    metrics = {}
    for name, impossible in (("answerable", False), ("unanswerable", True)):
        group = [(c, r) for c, r in zip(cases, rows, strict=True) if c["impossible"] == impossible]
        metrics[name] = confidence(sum(squad.grade(c, r, docs) for c, r in group), len(group))
    write_new(args.output, {"metrics": metrics, "rows": len(rows), "identity": identity,
                            "both_at_least_80": all(m["percent"] >= 80 for m in metrics.values()),
                            "rankings_sha256": file_sha256(args.rankings), "errors": sum(r["status"]=="error" for r in rows)})


if __name__ == "__main__":
    os.environ.update(ENVIRONMENT="test", LANGFUSE_ENABLED="false")
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("dataset", "rankings", "model-file", "output", "panel", "freeze"):
        parser.add_argument("--"+name, type=Path, required=name not in ("panel", "freeze"))
    parser.add_argument("--register", action="store_true")
    asyncio.run(run(parser.parse_args()))
