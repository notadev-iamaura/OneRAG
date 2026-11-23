"""Compare a loopback GGUF on the highest-ranked article for each reserved development question."""

import argparse
import asyncio
import json
import sys
from pathlib import Path

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.lib.llm_client import OllamaLLMClient
from app.modules.core.generation.grounded_span import read_grounded_span
from scripts.rag_growth_ko_eval import ReaderCorpus, retrieve
from scripts.rag_growth_local import file_sha256, local_http_client, verify_server


async def run(args: argparse.Namespace) -> None:
    from openai import AsyncOpenAI

    panels = args.panels
    corpus = ReaderCorpus(json.loads((panels / "dev.corpus.json").read_bytes()))
    origin = f"http://127.0.0.1:{args.port}"
    async with local_http_client(origin) as client:
        digest = file_sha256(args.model_file)
        await verify_server(client, args.model_name, args.model_file, digest)
        model = OllamaLLMClient({"model": args.model_name, "base_url": origin, "temperature": 0})
        model._client = AsyncOpenAI(base_url=origin+"/v1", api_key="not-needed", http_client=client,
                                    max_retries=0, timeout=120)
        with args.output.open("x") as stream:
            for case in json.loads((panels / "dev.questions.json").read_bytes()):
                docs = retrieve(corpus, case["question"], 1)
                row = {"id": case["id"], "retrieved": [doc["id"] for doc in docs], "weights": digest}
                try:
                    result = await read_grounded_span(model, case["question"], docs)
                    if result is None:
                        row.update(status="abstained")
                    else:
                        row.update(status="answered", **result)
                except Exception as error:
                    row.update(status="error", error=str(error)[:200])
                stream.write(json.dumps(row, ensure_ascii=False) + "\n")
                stream.flush()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--model-name", required=True)
    for name in ("panels", "model-file", "output"):
        parser.add_argument("--"+name, type=Path, required=True)
    asyncio.run(run(parser.parse_args()))
