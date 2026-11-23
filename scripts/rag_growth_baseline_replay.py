"""Replay the previous document-agent policy on a fixed subset of the Korean development panel."""

import argparse
import asyncio
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.rag_growth_ko_eval import grade, write_new
from scripts.rag_growth_local import (
    Corpus,
    agent_sha256,
    local_http_client,
    run_trial,
    verify_server,
)

GGUF_SHA = "96b9c0af5c77a4ecaabe3983175112b5ece763261c1ece12b2494b692a70dad7"


def reserved_ids(labels: list[dict[str, Any]]) -> list[str]:
    ids = []
    for flag in (True, False):
        group = [label["id"] for label in labels if label["answerable"] is flag]
        ids.extend(sorted(group, key=lambda x: hashlib.sha256(("onerag-paired-before-03/" + x).encode()).digest())[:12])
    return sorted(ids)


def align(result: dict[str, Any], docs: dict[str, str]) -> dict[str, Any]:
    row = {"status": result["status"], "retrieved": result["candidates"]}
    if result["status"] == "answered":
        row.update(answer=result["answer"])
        if len(set(result["citations"])) == 1:
            for citation in result["cited_evidence"]:
                doc_id, quote = citation["document_id"], citation["quote"]
                left = docs[doc_id].find(quote)
                offset = quote.find(result["answer"])
                if left >= 0 and offset >= 0:
                    row.update(source_id=doc_id, quote=quote, start=left + offset,
                               end=left + offset + len(result["answer"]), quote_start=left,
                               quote_end=left + len(quote))
                    break
    return row


async def run(args: argparse.Namespace) -> None:
    labels = json.loads((args.panels / "dev.labels.json").read_bytes())
    ids = reserved_ids(labels)
    if args.reserve:
        write_new(args.reserve, {"split": "dev", "ids": ids, "per_class": 12,
                                 "agent_sha256": agent_sha256(), "gguf_sha256": GGUF_SHA})
        return
    if not args.output or not args.plan or not args.model_file:
        raise ValueError("Provide --plan, --model-file and a new --output for replay")
    plan = json.loads(args.plan.read_bytes())
    if plan["ids"] != ids or plan["agent_sha256"] != agent_sha256() or args.output.exists():
        raise ValueError("Changed baseline inputs or occupied output")
    from openai import AsyncOpenAI

    from app.lib.llm_client import OllamaLLMClient

    questions = json.loads((args.panels / "dev.questions.json").read_bytes())
    documents = json.loads((args.panels / "dev.corpus.json").read_bytes())
    corpus = Corpus(documents)
    rows = []
    origin = "http://127.0.0.1:18759"
    alias = "onerag-growth-qwen"
    async with local_http_client(origin) as client:
        await verify_server(client, alias, args.model_file, GGUF_SHA)
        model = OllamaLLMClient({"model": alias, "base_url": origin, "temperature": 0, "max_tokens": 640})
        model._client = AsyncOpenAI(base_url=origin+"/v1", api_key="not-needed", http_client=client,
                                    max_retries=0, timeout=120)
        for q in questions:
            if q["id"] in ids:
                result = await run_trial(q["question"], corpus, model, False)
                row = align(result, {d["id"]: d["content"] for d in documents})
                rows.append({"id": q["id"], **row, "agent_result": result})
                print(q["id"], row["status"], flush=True)
    verdict = grade(rows, [label for label in labels if label["id"] in ids], documents)
    write_new(args.output, {"plan": plan, "rows": rows, **verdict})


if __name__ == "__main__":
    os.environ.update(ENVIRONMENT="test", LANGFUSE_ENABLED="false")
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("panels", "reserve", "plan", "model-file", "output"):
        parser.add_argument("--"+name, type=Path, required=name == "panels")
    asyncio.run(run(parser.parse_args()))
