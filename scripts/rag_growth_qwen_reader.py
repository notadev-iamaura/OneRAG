"""Local GGUF adapter and replay for the existing, exposed development questions."""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.modules.core.generation.grounded_span import read_grounded_span
from scripts.rag_growth_local import Corpus

_model = None


async def local_reader(question: str, documents: list[dict[str, Any]]) -> dict[str, Any] | None:
    from app.lib.llm_client import OllamaLLMClient

    global _model
    if _model is None:
        _model = OllamaLLMClient({"model": "onerag-growth-qwen", "base_url": "http://127.0.0.1:18759",
                                  "timeout": 120})
    return await read_grounded_span(_model, question, documents)


async def replay(manifest: Path, output: Path) -> None:
    panel = json.loads(manifest.read_bytes())
    if panel["split"] != "development":
        raise ValueError("Replay is available only for exposed development cases")
    corpus = Corpus(panel["documents"])
    by_id = {d["id"]: d for d in panel["documents"]}
    with output.open("x") as stream:
        for case in panel["cases"]:
            hits = [by_id[hit["id"]] for hit in corpus.index.search(case["question"], 3)]
            row = {"id": case["id"], "hits": [d["id"] for d in hits]}
            try:
                answer = await local_reader(case["question"], hits)
                row.update(result=answer, status="answered" if answer else "abstained")
            except Exception as error:
                row.update(status="error", error=type(error).__name__, detail=str(error)[:160])
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
            stream.flush()


if __name__ == "__main__":
    os.environ["LANGFUSE_ENABLED"] = "false"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    asyncio.run(replay(args.manifest, args.output))
