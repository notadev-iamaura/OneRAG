"""Exercise the local /chat agent and a selected reader with two synthetic Korean requests.

With no arguments, both retrieval and generation use small deterministic doubles. A
selected profile can later be supplied with real linked-title BM25 or local E5 search,
and local encoders or a checksum-verified loopback GGUF. No benchmark panel is read.
"""

import argparse
import asyncio
import functools
import hashlib
import importlib
import inspect
import json
import os
import re
import sys
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from typing import Any
from unittest.mock import patch
from uuid import uuid4

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

Row = dict[str, Any]
NOTICE = "📚 별빛 도서관은 수요일에 책장을 정리합니다. 별빛 도서관의 독서 모임은 매주 수요일 저녁에 열립니다."
ANSWER_QUERY = "별빛 도서관의 독서 모임은 무슨 요일에 열리나요?"
NO_ANSWER_QUERY = "별빛 도서관의 독서 모임 참가비는 얼마인가요?"
DEFAULT_HOOK = "app.modules.core.agent.extractive_reader:read_grounded_span"


def documents() -> list[Row]:
    result = [{"id": "library", "title": "별빛 도서관 독서 모임", "content": NOTICE}]
    for i, title in enumerate(("박물관", "미술관", "수영장", "극장", "정원", "카페", "체육관"), 1):
        result.append({"id": f"place-{i}", "title": f"{title} 운영 안내", "content": f"{title} 입구에 안내 데스크가 있습니다."})
    return result


@contextmanager
def observe(target: str) -> Iterator[tuple[list[Row], str]]:
    module, sep, dotted = target.partition(":")
    if not sep or not module.startswith(("app.modules.core.generation.", "app.modules.core.agent.")):
        raise ValueError("Observe a product reader function at a Python module:qualname")
    obj = importlib.import_module(module)
    parts = dotted.split(".")
    if not all(p.isidentifier() for p in parts):
        raise ValueError("Invalid observer qualname")
    owner: Any = obj
    for name in parts[:-1]:
        owner = getattr(owner, name)
    name = parts[-1]
    original = inspect.getattr_static(owner, name)
    if not inspect.isfunction(original):
        raise ValueError("The observation target must be a plain function or an instance method")
    path = inspect.getsourcefile(original)
    if path is None:
        raise ValueError("The selected implementation has no local source file")
    fingerprint = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    calls: list[Row] = []

    def begin() -> Row:
        event = {"outcome": "raised"}
        calls.append(event)
        return event

    @functools.wraps(original)
    async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
        event = begin()
        value = await original(*args, **kwargs)
        event["outcome"] = "no_span" if value is None else "returned"
        return value

    @functools.wraps(original)
    def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
        event = begin()
        value = original(*args, **kwargs)
        event["outcome"] = "no_span" if value is None else "returned"
        return value

    observer = async_wrapper if inspect.iscoroutinefunction(original) else sync_wrapper
    with patch.object(owner, name, observer):
        yield calls, fingerprint


class FakeSearch:
    async def search(self, query: str, top_k: int, **kwargs: Any) -> list[Any]:
        from app.modules.core.retrieval.interfaces import SearchResult

        return [SearchResult(id=d["id"], content=d["content"], score=1/(i+1),
                             metadata={"document_id": d["id"], "title": d["title"], "source_file": d["title"]})
                for i, d in enumerate(documents()[:top_k])]


class TraceSearch:
    def __init__(self, real: Any) -> None:
        self.real = real
        self.calls: list[Row] = []

    async def search(self, query: str, top_k: int, **kwargs: Any) -> list[Any]:
        results = await self.real.search(query, top_k=top_k, **kwargs)
        self.calls.append({"query": query, "ids": [r.id for r in results], "content": {r.id: r.content for r in results}})
        return list(results)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.real, name)


class MemorySession:
    def __init__(self) -> None:
        self.messages: dict[str, list[Row]] = {}

    async def create_session(self, metadata: Row, session_id: str | None = None) -> Row:
        key = session_id or str(uuid4())
        self.messages[key] = []
        return {"session_id": key}

    async def get_context_string(self, session_id: str) -> str:
        return "\n".join(m["user"] + "\n" + m["assistant"] for m in self.messages[session_id])

    async def get_conversation(self, session_id: str, max_exchanges: int = 5) -> list[Row]:
        return self.messages[session_id][-max_exchanges:]

    async def add_conversation(self, key: str, q: str, a: str, metadata: Row) -> None:
        self.messages[key].append({"user": q, "assistant": a})


class RecordedModel:
    def __init__(self) -> None:
        self.force_error = False

    async def generate_text(self, *, prompt: str, require_complete: bool = False, **kwargs: Any) -> str:
        if not require_complete:
            raise ValueError("A grounded generation must require a complete response")
        if self.force_error:
            return "[999.999] 근거 문장에 없는 답"
        if NO_ANSWER_QUERY in prompt:
            return "NONE"
        match = re.search(r"^\[(\d+\.\d+)\] .*매주 수요일", prompt, re.M)
        if ANSWER_QUERY not in prompt or match is None:
            raise ValueError("The synthetic source and question did not reach the actual decoder")
        return f"[{match[1]}] 수요일"


@asynccontextmanager
async def generation(args: argparse.Namespace) -> AsyncIterator[Any]:
    if args.backend == "recorded":
        yield RecordedModel()
    elif args.backend == "encoder":
        from scripts.rag_growth_profile import EncoderOnly

        yield EncoderOnly()
    else:
        from openai import AsyncOpenAI

        from app.lib.llm_client import OllamaLLMClient
        from scripts.rag_growth_local import local_http_client, verify_server

        if not args.model_file or not args.model_alias or not args.port or not re.fullmatch("[a-f0-9]{64}", args.gguf_sha256 or ""):
            raise ValueError("A real GGUF run needs its absolute path, model alias, port and pinned SHA-256")
        origin = f"http://127.0.0.1:{args.port}"
        async with local_http_client(origin) as client:
            await verify_server(client, args.model_alias, args.model_file, args.gguf_sha256)
            model = OllamaLLMClient({"base_url": origin, "model": args.model_alias, "temperature": 0, "timeout": 120})
            model._client = AsyncOpenAI(base_url=origin + "/v1", api_key="local-only", max_retries=0, timeout=120,
                                        http_client=client)
            yield model


def verify_response(body: Row, http_status: int, hits: list[Row], hooks: list[Row], question: str, expected: str) -> Row:
    if http_status != 200:
        raise ValueError(f"HTTP status {http_status}")
    meta, sources = body["metadata"], body["sources"]
    if (meta["mode"] != "agent" or "search_weaviate" not in meta["tools_used"]
            or not any(b["query"] == question and b["ids"] for b in hits) or not hooks):
        raise ValueError("The expected search and selected reader did not both run")
    if expected != "error" and not any(event["outcome"] in ("returned", "no_span") for event in hooks):
        raise ValueError("The expected reader raised instead of completing this request")
    status = meta["grounding_status"]
    if expected == "error":
        if meta["success"] is not False or status not in ("error", "invalid_citation") or sources:
            raise ValueError("A malformed completion was returned as an answer or a successful refusal")
    elif meta["success"] is not True:
        raise ValueError("The in-process agent returned an unsuccessful response")
    elif expected == "abstained":
        if status != "insufficient" or sources or body["answer"] != "근거 부족":
            raise ValueError("Expected a genuine source-free refusal")
    else:
        if status != "verified_quotes" or len(sources) != 1 or body["answer"] != "수요일":
            raise ValueError("The grounded answer did not identify the requested day")
        source, = sources
        evidence = source["additional_metadata"]
        a, b, left, right = (evidence[k] for k in ("answer_start", "answer_end", "quote_start", "quote_end"))
        quote, = evidence["cited_sentences"]
        if not (source["document_id"] == "library" and any(h["content"].get("library") == NOTICE for h in hits)
                and evidence["offset_basis"] == "retrieved_chunk" and evidence["offset_unit"] == "unicode_codepoint"
                and all(type(i) is int for i in (left, a, b, right))
                and 0 <= left <= a < b <= right <= len(NOTICE)
                and a == NOTICE.rindex("수요일") and NOTICE[a:b] == body["answer"] and NOTICE[left:right] == quote):
            raise ValueError("Citation does not point to the meeting's actual occurrence in the retrieved chunk")
        return {"status": status, "document": "library", "answer": body["answer"],
                "answer_range": [a, b], "quote_range": [left, right], "quote": quote}
    return {"status": status, "source_count": len(sources)}


async def exercise(reader: Row, hook: str, model: Any, retriever: Any, include_fault: bool) -> Row:
    import httpx
    from fastapi import FastAPI
    from starlette.config import Config

    from app.api.services.chat_service import ChatService
    from app.modules.core.agent.factory import AgentFactory
    from app.modules.core.tools.factory import ToolFactory
    from scripts.rag_growth_local import agent_config

    # SlowAPI normally loads a CWD environment file when constructing the router limiter.
    # The smoke uses its in-memory defaults and needs no external configuration.
    with patch("slowapi.extension.Config", return_value=Config(environ={})):
        chat_router = importlib.import_module("app.api.routers.chat_router")
    observed = TraceSearch(retriever)
    config = agent_config(False, observed)
    config["mcp"]["agent"]["extractive_reader"] = reader
    server = ToolFactory.create(config)
    await server.initialize()
    results = []
    try:
        session = MemorySession()
        agent = AgentFactory.create(config, model, server)
        if agent is None:
            raise ValueError("The document agent could not initialize")
        # The public default router language normally comes from merged local configuration.
        with patch("app.modules.core.routing.rule_based_router.RuleBasedRouter._resolve_rule_language", return_value="ko"):
            service = ChatService({"agent_orchestrator": agent, "session": session}, config)
        api = FastAPI()
        api.include_router(chat_router.router)
        with (patch.object(chat_router, "chat_service", service),
              patch.object(chat_router, "_record_chat_analytics", return_value=None),
              observe(hook) as (events, source_sha)):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api), base_url="http://test") as client:
                cases = [(ANSWER_QUERY, "answered"), (NO_ANSWER_QUERY, "abstained")]
                if include_fault:
                    cases.append((ANSWER_QUERY, "error"))
                for q, expected in cases:
                    start, event_start = len(observed.calls), len(events)
                    if isinstance(model, RecordedModel):
                        model.force_error = expected == "error"
                    response = await client.post("/chat", json={"message": q, "use_agent": True})
                    hits, calls = observed.calls[start:], events[event_start:]
                    row: Row = {"expected": expected, "http_status": response.status_code, "calls": calls,
                                "retrieved_ids": [b["ids"] for b in hits]}
                    try:
                        body = response.json()
                        row["actual"] = verify_response(body, response.status_code, hits, calls, q, expected)
                        if session.messages[body["session_id"]] != [{"user": q, "assistant": body["answer"]}]:
                            raise ValueError("The session does not contain exactly the returned exchange")
                    except (ValueError, KeyError, TypeError) as exc:
                        row["error"] = str(exc)
                    results.append(row)
    finally:
        await server.shutdown()
    return {"passed": all("error" not in r for r in results), "hook": hook, "hook_source_sha256": source_sha, "rows": results}


async def run(args: argparse.Namespace) -> Row:
    if args.backend != "recorded" and (not args.profile or not args.observe or args.retriever == "fixture"):
        raise ValueError("For an actual model, supply its product profile, real retriever and policy-specific hook")
    if args.output is not None and args.output.exists():
        raise FileExistsError(args.output)
    reader = json.loads(args.profile.read_bytes())["reader"] if args.profile else {"implementation": "generative", "top_k": 1}
    retriever: Any
    if args.retriever == "fixture":
        retriever = FakeSearch()
    elif args.retriever == "bm25":
        from scripts.rag_growth_local import Corpus
        from scripts.rag_growth_profile import PublicArticleRetriever

        retriever = PublicArticleRetriever(Corpus(documents()), {d["id"]: d["content"] for d in documents()})
    else:
        from app.modules.core.retrieval.retrievers.korean_hybrid_passage import (
            KoreanHybridPassageRetriever,
        )

        if not args.embedding_dir or not args.embedding_dir.is_dir():
            raise ValueError("Hybrid retrieval requires a local E5 directory")
        retriever = KoreanHybridPassageRetriever(documents(), args.embedding_dir, device="cpu")
    async with generation(args) as model:
        report = await exercise(reader, args.observe or DEFAULT_HOOK, model, retriever, args.backend == "recorded")
    report.update(scope="Synthetic API wiring check", backend=args.backend, retriever=args.retriever,
                  profile_sha256=hashlib.sha256(args.profile.read_bytes()).hexdigest() if args.profile else None,
                  model_sha256=args.gguf_sha256 if args.backend == "gguf" else None)
    if args.output:
        from scripts.rag_growth_ko_eval import write_new

        write_new(args.output, report)
    return report


if __name__ == "__main__":
    os.environ.update(ENVIRONMENT="test", LANGFUSE_ENABLED="false", PYTHON_DOTENV_DISABLED="1",
                      HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--profile", type=Path, help="JSON with the selected product reader configuration under 'reader'")
    ap.add_argument("--observe", help="Exact selected callable at its product lookup site, e.g. module:Reader.read")
    ap.add_argument("--backend", choices=("recorded", "encoder", "gguf"), default="recorded")
    ap.add_argument("--retriever", choices=("fixture", "bm25", "hybrid"), default="fixture")
    ap.add_argument("--embedding-dir", type=Path)
    ap.add_argument("--model-file", type=Path)
    ap.add_argument("--model-alias")
    ap.add_argument("--port", type=int)
    ap.add_argument("--gguf-sha256")
    ap.add_argument("--output", type=Path)
    result = asyncio.run(run(ap.parse_args()))
    print(json.dumps(result, ensure_ascii=False))
    sys.exit(0 if result["passed"] else 1)
