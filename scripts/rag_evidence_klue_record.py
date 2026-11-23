"""Observe a frozen paired study's actual local model requests and completions without changing its inputs."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any
from unittest.mock import patch

import httpx

from scripts import rag_evidence_klue_paired as paired
from scripts.rag_growth_ko_eval import write_new
from scripts.rag_growth_local import file_sha256, local_http_client

RequestID = tuple[int, str, str]


class CompletionTrace:
    def __init__(self, path: Path, pending: Iterable[RequestID]) -> None:
        self.path, self.pending = path, iter(pending)
        self.active: dict[int, tuple[str, dict[str, Any]]] = {}
        self.sent = 0
        self.received = 0

    async def request(self, request: httpx.Request) -> None:
        if request.method != "POST" or request.url.path != "/v1/chat/completions":
            return
        index, arm, qid = next(self.pending)
        key = f"{index:04d}-{arm}"
        body = await request.aread()
        decoded = json.loads(body)
        fields = {"id": qid, "arm": arm, "request_sha256": hashlib.sha256(body).hexdigest()}
        # Only the public messages and QA generation settings, never HTTP authentication headers.
        allowed = ("messages", "model", "max_tokens", "temperature", "stream", "seed")
        recorded = {k: decoded[k] for k in allowed if k in decoded}
        write_new(self.path / (key + ".request.json"), {**fields, "request": recorded})
        self.active[id(request)] = key, fields
        self.sent += 1

    async def response(self, response: httpx.Response) -> None:
        current = self.active.pop(id(response.request), None)
        if current is None:
            return
        key, fields = current
        body = await response.aread()
        result: dict[str, Any] = {**fields, "status_code": response.status_code,
                                  "response_sha256": hashlib.sha256(body).hexdigest()}
        try:
            reply = json.loads(body)
            choices = reply.get("choices", [])
            result["usage"] = reply.get("usage")
            result["choices"] = [
                {"index": c.get("index"), "content": c.get("message", {}).get("content"),
                 "finish_reason": c.get("finish_reason")} for c in choices
            ]
        except (TypeError, ValueError, AttributeError):
            result["unparseable"] = True
        write_new(self.path / (key + ".response.json"), result)
        self.received += 1


async def run(questions: Path, corpus: Path, output: Path, freeze_sha: str) -> None:
    registered = paired.load(questions)
    pending = [(i, arm, q["id"]) for i, q in enumerate(registered)
               for arm in (("control", "candidate") if i % 2 == 0 else ("candidate", "control"))
               if not (output / "rows" / f"{i:04d}-{arm}.json").exists()]
    trace = CompletionTrace(output / "raw-model", pending)

    def observed_client(origin: str) -> httpx.AsyncClient:
        client = local_http_client(origin)
        client.event_hooks["request"].append(trace.request)
        client.event_hooks["response"].append(trace.response)
        return client

    with patch.object(paired, "local_http_client", observed_client):
        await paired.measure(questions, corpus, output, freeze_sha, cache_only=False)
    if trace.sent != len(pending):
        raise ValueError("Trace did not see every expected model dispatch")
    write_new(output / "raw-model-receipt.json", {
        "questions": file_sha256(questions), "corpus": file_sha256(corpus), "freeze": freeze_sha,
        "recorder": file_sha256(Path(__file__)), "expected_new_calls": len(pending),
        "sent": trace.sent, "http_responses": trace.received,
        "artifacts": {p.name: file_sha256(p) for p in sorted((output / "raw-model").glob("*.json"))},
    })


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--questions", required=True, type=Path)
    parser.add_argument("--corpus", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--freeze-sha", required=True)
    arguments = parser.parse_args()
    asyncio.run(run(arguments.questions, arguments.corpus, arguments.output, arguments.freeze_sha))
