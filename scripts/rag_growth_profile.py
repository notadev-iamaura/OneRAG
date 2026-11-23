"""Evaluate the configured document agent with real tool retrieval and local weights."""

import hashlib
import json
import time
from pathlib import Path
from typing import Any

from app.modules.core.agent.extractive_reader import ExtractiveReaderConfig
from scripts.rag_growth_local import (
    ROOT,
    Corpus,
    TrialRetriever,
    agent_config,
    agent_sha256,
    file_sha256,
    local_http_client,
    verify_server,
)


def profile_identity(path: Path) -> dict:
    raw = path.read_bytes()
    profile = json.loads(raw)
    reader = ExtractiveReaderConfig(**profile["reader"])
    identity: dict[str, Any] = {"profile": hashlib.sha256(raw).hexdigest(), "agent": agent_sha256()}
    for key, directory in (("reader", reader.model_dir), ("second", reader.second_model_dir),
                           ("boundary", reader.boundary_model_dir),
                           ("sufficiency", reader.sufficiency_model_dir)):
        if directory:
            files = {p.name: file_sha256(p) for p in Path(directory).iterdir() if p.is_file()
                     and (p.suffix == ".safetensors" or p.name in {
                         "config.json", "reader_config.json", "tokenizer.json", "vocab.txt",
                         "spm.model", "tokenizer_config.json", "special_tokens_map.json", "added_tokens.json",
                     })}
            if not files.get("config.json") or not any(k.endswith(".safetensors") for k in files):
                raise ValueError("Local encoder weights or configuration missing")
            identity[key] = files
    if reader.implementation in {"generative", "en_generative"}:
        identity["gguf"] = file_sha256(Path(profile["gguf"]["file"]))
    for name in ("agent/extractive_reader.py", "generation/grounded_span.py", "generation/korean_span_reader.py",
                 "generation/english_span_reader.py", "generation/english_consensus_reader.py", "generation/english_grounded_answer.py",
                 "generation/passage_sufficiency.py"):
        identity[name] = file_sha256(ROOT / "app/modules/core" / name)
    if reader.evidence_policy == "verified_korean_spans":
        for name in ("korean_checked_evidence_reader", "korean_evidence_safety", "korean_corroborated_evidence",
                     "korean_corroborated_reader", "korean_mention_coverage", "korean_adjudication", "korean_evidence_selection"):
            identity[name] = file_sha256(ROOT / "app/modules/core/generation" / (name + ".py"))
        identity["evidence_tokenizer"] = file_sha256(ROOT / "app/modules/core/retrieval/bm25_engine/tokenizer.py")
    identity["evaluator"] = file_sha256(Path(__file__))
    return identity


class PublicArticleRetriever(TrialRetriever):
    def __init__(self, corpus: Corpus, articles: dict[str, str]) -> None:
        super().__init__(corpus)
        self.articles = articles

    async def search(self, query: str, top_k: int, **kwargs: Any) -> list[Any]:
        hits: list[Any] = await super().search(query, top_k, **kwargs)
        for h in hits:
            h.content = self.articles[h.id]
        return hits

    async def get_document_chunks(self, document_id: str) -> list[dict[str, Any]]:
        rows = await super().get_document_chunks(document_id)
        return [{**row, "content": self.articles[row["id"]]} for row in rows]


class EncoderOnly:
    async def generate_text(self, **kwargs: Any) -> str:
        raise RuntimeError("A local encoder profile unexpectedly requested text generation")


async def run_profile(
    documents: list[dict[str, Any]], questions: list[dict[str, Any]], profile_file: Path, identity: dict[str, Any]
) -> list[dict[str, Any]]:
    from app.lib.llm_client import OllamaLLMClient
    from app.modules.core.agent.factory import AgentFactory
    from app.modules.core.tools.factory import ToolFactory

    raw = profile_file.read_bytes()
    if hashlib.sha256(raw).hexdigest() != identity["profile"]:
        raise ValueError("Agent profile changed after registration")
    profile = json.loads(raw)
    reader = profile["reader"]
    model: Any = EncoderOnly()
    if reader["implementation"] in {"generative", "en_generative"}:
        gguf = profile["gguf"]
        origin = f"http://127.0.0.1:{int(gguf['port'])}"
        async with local_http_client(origin) as client:
            await verify_server(client, gguf["name"], Path(gguf["file"]), identity["gguf"])
        model = OllamaLLMClient({"model": gguf["name"], "base_url": origin, "timeout": 120})
    corpus = Corpus(documents)
    articles = {d["id"]: d["content"] for d in documents}
    rows = []
    for index, question in enumerate(questions, 1):
        start = time.perf_counter()
        retriever = PublicArticleRetriever(corpus, articles)
        config = agent_config(False, retriever)
        config["mcp"]["agent"]["extractive_reader"] = reader
        server = ToolFactory.create(config)
        try:
            await server.initialize()
            agent = AgentFactory.create(config, model, server)
            if agent is None:
                raise ValueError("Document agent failed to initialize")
            result = await agent.run(question["question"])
            if result.success and result.grounding_status == "verified_quotes" and len(result.sources) == 1:
                source, = result.sources
                quote, = source["cited_sentences"]
                row = {"status": "answered", "source_id": source["document_id"], "answer": result.answer,
                       "quote": quote, "start": source["answer_start"], "end": source["answer_end"],
                       "quote_start": source["quote_start"], "quote_end": source["quote_end"]}
            elif (result.success and result.grounding_status == "insufficient"
                  and result.answer == "근거 부족" and not result.sources):
                row = {"status": "abstained"}
            else:
                raise ValueError(f"Agent outcome {result.grounding_status}")
        except Exception as error:
            row = {"status": "error", "error": f"{type(error).__name__}: {error}"[:240]}
        finally:
            await server.shutdown()
        hits = list(dict.fromkeys(h for batch in retriever.batches for h in batch))
        rows.append(dict(id=question["id"], retrieved=hits[:reader.get("top_k", 3)], tool_retrieved=hits,
                         latency_ms=(time.perf_counter()-start)*1000, **row))
        if index % 10 == 0:
            print(f"Document agent completed {index}/{len(questions)} questions", flush=True)
    return rows
