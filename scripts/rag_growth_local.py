"""Run paired Korean document-agent trials against a local llama.cpp GGUF server.

Run with `python scripts/rag_growth_local.py --help`. Both policies independently
search the same ordered corpus. Gold labels are used only when validating inputs.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import sys
import time
from importlib.metadata import version
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))

SCHEMA_VERSION = 1
INDEX_ID = "onerag-ko-bm25-linked-v1"
TRIALS = 3


def json_sha256(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def corpus_sha256(documents: list[dict[str, Any]]) -> str:
    """Hash ordered UTF-8 source IDs, titles and unmodified bodies."""
    return json_sha256([{key: doc[key] for key in ("id", "title", "content")} for doc in documents])


def file_sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def index_sha256(documents: list[dict[str, Any]]) -> str:
    engine = ROOT / "app/modules/core/retrieval/bm25_engine"
    return json_sha256({
        "index": INDEX_ID,
        "corpus": corpus_sha256(documents),
        "code": {name: file_sha256(engine / name) for name in ("index.py", "tokenizer.py", "linked_titles.py")},
        "packages": {name: version(name) for name in ("rank-bm25", "kiwipiepy", "kiwipiepy_model", "numpy")},
        "format": "metadata(document_id=id,source_file=title,title=title);content=title+LF+body",
    })


def agent_sha256() -> str:
    files = [
        "agent/factory.py", "agent/orchestrator.py", "agent/interfaces.py", "agent/planner.py",
        "agent/executor.py", "agent/synthesizer.py", "tools/factory.py", "tools/server.py",
        "tools/vector_search.py",
    ]
    checksums = {name: file_sha256(ROOT / "app/modules/core" / name) for name in files}
    for name in ("llm_client.py", "evidence_sentences.py", "request_cost.py"):
        checksums[name] = file_sha256(ROOT / "app/lib" / name)
    return json_sha256(checksums)


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def validate_manifest(data: dict[str, Any]) -> None:
    if not isinstance(data, dict):
        raise ValueError("Expected a JSON object for the manifest")
    if (type(data.get("schema_version")) is not int or data["schema_version"] != SCHEMA_VERSION
            or type(data.get("trials")) is not int or data["trials"] != TRIALS):
        raise ValueError("This runner requires schema_version 1 and exactly 3 trials")
    if data.get("split") not in ("development", "holdout") or data.get("index") != INDEX_ID:
        raise ValueError(f"Expected development or holdout split and index {INDEX_ID}")
    if not _text(data.get("model")) or not _text(data.get("dataset")):
        raise ValueError("model and dataset must be nonempty strings")
    if not re.fullmatch("[0-9a-f]{64}", str(data.get("model_sha256"))):
        raise ValueError("model_sha256 must be a lowercase SHA256 digest")
    docs = data.get("documents")
    cases = data.get("cases")
    if not isinstance(docs, list) or not docs or not isinstance(cases, list) or not cases:
        raise ValueError("Nonempty documents and cases arrays are required")
    if any(not isinstance(doc, dict) or not all(_text(doc.get(key)) for key in ("id", "title", "content"))
           for doc in docs):
        raise ValueError("Every document must supply id, title and content")
    doc_ids = {doc["id"] for doc in docs}
    if len(doc_ids) != len(docs) or data.get("corpus_sha256") != corpus_sha256(docs):
        raise ValueError("Duplicate document ID or corpus_sha256 mismatch")
    case_ids = set()
    for case in cases:
        if (not isinstance(case, dict) or not _text(case.get("id")) or not _text(case.get("question"))
                or case["id"] in case_ids):
            raise ValueError("Expected a unique case ID and a nonempty question")
        case_ids.add(case["id"])
        for key in ("answers", "source_ids"):
            values = case.get(key)
            if not isinstance(values, list) or any(not _text(value) for value in values):
                raise ValueError(f"{case['id']} has invalid {key}")
        if type(case.get("answerable")) is not bool or bool(case["answers"]) != case["answerable"]:
            raise ValueError(f"{case['id']} has inconsistent answerability/answers")
        if (case["answerable"] and not case["source_ids"]) or not doc_ids.issuperset(case["source_ids"]):
            raise ValueError(f"{case['id']} has missing or unknown source IDs")


async def verify_server(client: httpx.AsyncClient, api_model: str, path: Path, digest: str) -> None:
    models = (await client.get("/v1/models")).raise_for_status().json()["data"]
    if [model["id"] for model in models] != [api_model]:
        raise ValueError(f"Expected the loopback server to serve exactly {api_model!r}")
    props = (await client.get("/props")).raise_for_status().json()
    served_path = props.get("model_path")
    if not _text(served_path) or not Path(served_path).is_absolute() or not path.samefile(served_path):
        raise ValueError("The GGUF path does not match the model_path served by /props")
    if file_sha256(path) != digest:
        raise ValueError("The served GGUF does not match model_sha256")


def local_http_client(origin: str) -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url=origin, timeout=120, trust_env=False, follow_redirects=False)


class Corpus:
    def __init__(self, documents: list[dict[str, Any]]) -> None:
        from app.modules.core.retrieval.bm25_engine import BM25Index, KoreanTokenizer

        self.docs = {d["id"]: {
            "id": d["id"], "content": d["title"] + "\n" + d["content"],
            "metadata": {"document_id": d["id"], "source_file": d["title"], "title": d["title"]},
        } for d in documents}
        self.index = BM25Index(KoreanTokenizer(), linked_titles=True)
        self.index.build(list(self.docs.values()))


class TrialRetriever:
    def __init__(self, corpus: Corpus) -> None:
        self.corpus = corpus
        self.batches: list[list[str]] = []
        self.search_attempts = 0

    async def search(self, query: str, top_k: int, **kwargs: Any) -> list[Any]:
        from app.modules.core.retrieval.interfaces import SearchResult

        self.search_attempts += 1
        hits = self.corpus.index.search(query, top_k)
        self.batches.append([hit["id"] for hit in hits])
        return [SearchResult(**hit) for hit in hits]

    async def get_document_chunks(self, document_id: str) -> list[dict[str, Any]]:
        doc = self.corpus.docs.get(document_id)
        return [doc] if doc is not None else []


def public_development_diagnostics(manifest: dict[str, Any]) -> bool:
    """Only the public KLUE train panels built by our pinned preparation pipeline are eligible."""
    from scripts.rag_growth_prepare import REVISION

    parts = manifest["dataset"].split("/")
    return (
        manifest["split"] == "development" and len(parts) == 4
        and parts[:2] == ["klue-mrc", REVISION] and bool(parts[2]) and parts[3] in {"dev-a", "dev-b"}
        and all(re.fullmatch(r"klue-mrc-v1_train_\d+", c["id"]) for c in manifest["cases"])
        and all(hashlib.sha256(d["content"].encode()).hexdigest()[:20] == d["id"] for d in manifest["documents"])
    )


class DevelopmentModelRecorder:
    """Forward the real call unmodified. Keep only the bounded last completion of this trial."""

    def __init__(self, model: Any, retriever: TrialRetriever, candidate: bool) -> None:
        self.model = model
        self.retriever = retriever
        self.candidate = candidate
        self.call_number = 0
        self.previous_round = -1
        self.calls_in_round = 0
        self.last: dict[str, Any] | None = None

    async def generate_text(self, *args: Any, **kwargs: Any) -> str:
        self.call_number += 1
        search_round = self.retriever.search_attempts
        self.calls_in_round = self.calls_in_round + 1 if self.previous_round == search_round else 1
        self.previous_round = search_round
        # A transport error must not be attributed to an earlier successful completion.
        self.last = None
        raw: str = await self.model.generate_text(*args, **kwargs)
        stage = "other"
        if search_round and self.calls_in_round == 1:
            stage = "document_answer"
        elif search_round and self.candidate and self.calls_in_round == 2:
            stage = "premise_check"
        self.last = {"stage": stage, "search_round": search_round, "call_number": self.call_number,
                     "raw_excerpt": raw[:400], "raw_sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
                     "raw_chars": len(raw), "truncated": len(raw) > 400}
        return raw


def agent_config(candidate: bool, retriever: TrialRetriever) -> dict[str, Any]:
    from app.modules.core.tools.factory import SUPPORTED_TOOLS

    return {
        "retriever": retriever,
        "mcp": {
            "enabled": True,
            "tools": {name: {"enabled": name in {"get_document_by_id", "search_weaviate"}}
                      for name in SUPPORTED_TOOLS},
            "agent": {
                "max_tool_calls": 5, "enable_reflection": False, "output_language": "한국어",
                "require_evidence_quotes": True, "verify_question_conditions": False,
                "verify_premise_mismatch": candidate,
            },
        },
    }


def classify(result: Any, retriever: TrialRetriever) -> tuple[str, list[str]]:
    citations = [str(source.get("document_id") or "") for source in result.sources]
    if not result.success:
        return "error", citations
    if result.grounding_status == "insufficient" and not citations and result.answer == "근거 부족":
        return "abstained", []
    if result.grounding_status != "verified_quotes" or not citations or not _text(result.answer):
        return "error", citations
    seen = {item for batch in retriever.batches for item in batch}
    for document_id, source in zip(citations, result.sources, strict=True):
        quotes = source.get("cited_sentences")
        if document_id not in seen or not isinstance(quotes, list) or not quotes:
            return "error", citations
        body = retriever.corpus.docs[document_id]["content"]
        if any(not _text(quote) or quote not in body for quote in quotes):
            return "error", citations
    return "answered", citations


async def run_trial(question: str, corpus: Corpus, model: Any, candidate: bool, *,
                    public_development: bool = False) -> dict[str, Any]:
    from app.lib.request_cost import bind_request_cost_ledger
    from app.modules.core.agent.factory import AgentFactory
    from app.modules.core.tools.factory import ToolFactory

    start = time.perf_counter()
    retriever = TrialRetriever(corpus)
    recorder = DevelopmentModelRecorder(model, retriever, candidate) if public_development else None
    outcome: dict[str, Any] = {"status": "error", "answer": "", "citations": [], "cited_evidence": []}
    with bind_request_cost_ledger() as ledger:
        try:
            config = agent_config(candidate, retriever)
            if AgentFactory.create_config(config).verify_premise_mismatch != candidate:
                raise ValueError("Agent configuration did not apply the requested policy")
            server = ToolFactory.create(config)
            await server.initialize()
            try:
                agent = AgentFactory.create(config, recorder or model, server)
                if agent is None:
                    raise RuntimeError("Document agent unavailable")
                result = await agent.run(question)
                status, citations = classify(result, retriever)
                outcome.update(status=status, answer=result.answer, citations=citations,
                               grounding_status=result.grounding_status, stop_reason=result.stop_reason)
                outcome["cited_evidence"] = [
                    {"document_id": source.get("document_id"), "quote": quote}
                    for source in result.sources for quote in (source.get("cited_sentences") or [])
                ]
                if status == "answered" and ledger.call_count == 0:
                    raise ValueError("Cannot account for model usage")
            finally:
                await server.shutdown()
        except Exception as exc:
            outcome.update(status="error", error_type=type(exc).__name__)
        outcome.update(tokens=ledger.total_tokens, model_calls=ledger.call_count)
    if (outcome["status"] == "error" and recorder and recorder.last
            and recorder.last["search_round"] == retriever.search_attempts):
        outcome["model_diagnostic"] = recorder.last
    return {
        **outcome, "latency_ms": round((time.perf_counter() - start) * 1000, 3),
        "candidates": list(dict.fromkeys(doc for batch in retriever.batches for doc in batch)),
        "candidate_batches": retriever.batches,
    }


async def run(args: argparse.Namespace) -> None:
    # Product observability is optional and must stay offline in this benchmark.
    os.environ["LANGFUSE_ENABLED"] = "false"
    os.environ["ENVIRONMENT"] = "test"
    manifest_bytes = args.manifest.read_bytes()
    manifest = json.loads(manifest_bytes)
    validate_manifest(manifest)
    public_development = public_development_diagnostics(manifest)
    model_id = args.api_model or manifest["model"]
    identity = {
        "model": manifest["model"], "api_model": model_id, "model_sha256": manifest["model_sha256"],
        "index": INDEX_ID, "index_sha256": index_sha256(manifest["documents"]),
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "corpus_sha256": manifest["corpus_sha256"], "split": manifest["split"], "dataset": manifest["dataset"],
        "runner_sha256": file_sha256(Path(__file__)), "agent_sha256": agent_sha256(),
        "temperature": 0, "max_tokens": 640, "fresh_agent_each_trial": True,
        "model_cache": "fresh completion request; server prefix/KV cache may be shared",
    }
    if "index_sha256" in manifest and manifest["index_sha256"] != identity["index_sha256"]:
        raise ValueError("index_sha256 differs from the registered corpus/engine")
    files = (args.baseline, args.candidate)
    if files[0].resolve() == files[1].resolve() or any(path.exists() for path in files):
        raise ValueError("Choose two distinct, new JSONL output files")
    policies = (args.baseline_policy, args.candidate_policy)
    if not all(_text(policy) for policy in policies) or policies[0] == policies[1]:
        raise ValueError("Two distinct nonempty policy IDs are required")
    if not 1 <= args.port <= 65535:
        raise ValueError("Invalid loopback port")
    origin = f"http://127.0.0.1:{args.port}"
    async with local_http_client(origin) as client:
        await verify_server(client, model_id, args.model_file, manifest["model_sha256"])
        from openai import AsyncOpenAI

        from app.lib.llm_client import OllamaLLMClient

        corpus = Corpus(manifest["documents"])
        model = OllamaLLMClient({"model": model_id, "base_url": origin, "temperature": 0, "max_tokens": 640})
        model._client = AsyncOpenAI(base_url=origin + "/v1", api_key="not-needed", http_client=client,
                                    max_retries=0, timeout=120)
        with files[0].open("x", encoding="utf-8") as baseline, files[1].open("x", encoding="utf-8") as candidate:
            streams = (baseline, candidate)
            for trial in range(1, TRIALS + 1):
                for case_number, case in enumerate(manifest["cases"]):
                    # Counterbalance shared model/server cache and warm-up effects.
                    first = (trial - 1 + case_number) % 2
                    for arm in (first, 1 - first):
                        outcome = await run_trial(case["question"], corpus, model, bool(arm),
                                                  public_development=public_development)
                        row = {
                            **identity, "id": case["id"], "trial": trial, "policy": policies[arm],
                            "policy_mode": "premise_mismatch" if arm else "document_quotes",
                            "verify_premise_mismatch": bool(arm), **outcome,
                        }
                        streams[arm].write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")
                        streams[arm].flush()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("manifest", "baseline", "candidate", "model-file"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--port", type=int, required=True, help="llama.cpp server on 127.0.0.1")
    parser.add_argument("--api-model", help="Exact served model ID if the manifest uses a descriptive label")
    parser.add_argument("--baseline-policy", default="baseline-v1")
    parser.add_argument("--candidate-policy", default="premise-mismatch-v1")
    args = parser.parse_args()
    try:
        asyncio.run(run(args))
    except (ValueError, OSError, KeyError, httpx.HTTPError) as exc:
        parser.exit(2, f"Evaluation could not start or finish: {exc}\n")


if __name__ == "__main__":
    main()
