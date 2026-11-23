"""Check the public English reader through document search, AgentFactory and user-visible citations."""

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any, cast

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import rag_growth_transfer as squad
from scripts.rag_growth_ko_eval import write_new
from scripts.rag_growth_local import TrialRetriever, agent_config, file_sha256
from scripts.rag_growth_profile import EncoderOnly


async def run(args: argparse.Namespace) -> None:
    import torch

    from app.modules.core.agent.factory import AgentFactory
    from app.modules.core.tools.factory import ToolFactory

    torch.set_num_threads(2)
    identity = {name: file_sha256(path) for name, path in {
        "dataset": args.dataset, "reader": args.reader / "model.safetensors",
        "embedding": args.embedding / "model.safetensors", "reference": args.reference,
    }.items()}
    if (identity["dataset"], identity["reader"], identity["embedding"]) != (
        squad.DATA_SHA, squad.READER_SHA, squad.E5_SHA
    ):
        raise ValueError("Inputs differ from the measured public English QA profile")
    docs, cases = squad.panels(squad.load(args.dataset)["data"])["development"]
    chosen = [case for impossible in (False, True) for case in sorted(
        (c for c in cases if c["impossible"] == impossible),
        key=lambda c: squad.key("onerag-agent-smoke-v1/" + c["id"]),
    )[:4]]
    records = [json.loads(line) for line in args.reference.read_text().splitlines()]
    expected = {row["id"]: row["candidate"] for row in records}
    if len(records) != len(expected) or set(expected) != {case["id"] for case in cases}:
        raise ValueError("Reference predictions do not cover the development panel")
    retriever = squad.LocalSpanRetriever(docs, args.embedding, args.device)
    config = agent_config(False, cast(TrialRetriever, retriever))
    config["mcp"]["agent"].update(output_language="English", extractive_reader={
        "implementation": "en_multi_passage", "model_dir": str(args.reader.resolve()),
        "top_k": 6, "device": args.device, "english_mode": "deberta", "threshold": -2,
    })
    results = []
    for case in chosen:
        server = ToolFactory.create(config)
        pred: dict[str, Any] = {"status": "error"}
        try:
            await server.initialize()
            agent = AgentFactory.create(config, EncoderOnly(), server)
            if agent is None:
                raise ValueError("Document agent unavailable")
            reply = await agent.run(case["question"])
            if reply.success and reply.grounding_status == "verified_quotes":
                source, = reply.sources
                quote, = source["cited_sentences"]
                pred = {
                    "status": "answered", "answer": reply.answer, "source_id": source["document_id"],
                    "start": source["answer_start"], "end": source["answer_end"], "quote": quote,
                    "quote_start": source["quote_start"], "quote_end": source["quote_end"],
                }
            elif (reply.success and reply.grounding_status == "insufficient"
                  and reply.answer == "Insufficient evidence" and not reply.sources):
                pred = {"status": "abstained"}
        finally:
            await server.shutdown()
        ref = expected[case["id"]]
        matches = pred["status"] != "error" and all(ref.get(k) == value for k, value in pred.items())
        results.append({"id": case["id"], "prediction": pred, "same_as_reader": matches,
                        "correct": squad.grade(case, pred, docs), "impossible": case["impossible"]})
    write_new(args.output, {"identity": identity, "device": args.device, "rows": results,
                            "agreement": sum(r["same_as_reader"] for r in results), "n": len(results)})
    if not all(r["same_as_reader"] for r in results):
        raise SystemExit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("dataset", "reader", "embedding", "reference", "output"):
        parser.add_argument("--" + key, type=Path, required=True)
    parser.add_argument("--device", choices=("cpu", "mps"), default="cpu")
    asyncio.run(run(parser.parse_args()))
