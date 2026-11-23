"""Run the frozen source-corroboration policy on its reserved KLUE questions with one shared local response."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
from typing import Any

from app.lib.llm_client import OllamaLLMClient
from app.modules.core.agent.extractive_reader import _CompletedResponse
from app.modules.core.generation.grounded_span import read_grounded_span
from scripts.rag_evidence_corroborate import TARGET, select
from scripts.rag_evidence_klue_paired import prepare
from scripts.rag_evidence_klue_record import CompletionTrace
from scripts.rag_evidence_klue_run import MODEL, SHA, WEIGHTS, apply_rescue, load
from scripts.rag_growth_ko_eval import checked_span, write_new
from scripts.rag_growth_local import file_sha256, local_http_client, verify_server

PANEL = TARGET.parent / "panels/klue-replication"
OUT = TARGET / "replication"
LOCK = TARGET.parent / "paired-trials/klue-replication/started.json"


class Recorded:
    def __init__(self, raw: str):
        self.raw = raw

    async def generate_text(self, **kwargs: Any) -> str:
        return self.raw


def inputs():
    lock = load(LOCK)
    # Check the exact prospective policy paths, including the driver and registered replication files.
    if lock.get("domain", lock.get("panel")) != "klue-replication":
        raise ValueError("Wrong replication gate")
    for key in ("common_sources", "candidate_sources", "control_sources"):
        if any(file_sha256(Path(name)) != digest for name, digest in lock[key].items()):
            raise ValueError("Frozen replication inputs changed")
    q, d = PANEL / "final.questions.json", PANEL / "final.corpus.json"
    if any(file_sha256(p) != lock["files"][p.name] for p in (q, d)):
        raise ValueError("The reserved question set or retrieval corpus has changed")
    return load(q), load(d), file_sha256(LOCK)


def cache():
    qs, docs, lock_sha = inputs()
    states = prepare(OUT, qs, docs)
    if len(states) != len(qs):
        raise ValueError("Incomplete original reader cache")
    write_new(OUT / "encoder-receipt.json", {"start_sha256": lock_sha, "encoders": file_sha256(OUT / "encoders.json")})


async def measure():
    from openai import AsyncOpenAI

    qs, docs, lock_sha = inputs()
    cache_path = OUT / "encoders.json"
    if load(OUT / "encoder-receipt.json") != {"start_sha256": lock_sha, "encoders": file_sha256(cache_path)}:
        raise ValueError("The shared encoder results have changed")
    states = load(cache_path)
    documents = {d["id"]: d for d in docs}
    bodies = {key: d["content"] for key, d in documents.items()}
    mode = load(TARGET / "selected.json")["selection"]
    origin = "http://127.0.0.1:18759"
    rows: list[dict[str, Any]] = []
    async with local_http_client(origin) as http:
        await verify_server(http, MODEL, WEIGHTS, SHA)
        sdk = OllamaLLMClient({"base_url": origin, "model": MODEL, "timeout": 120})
        sdk._client = AsyncOpenAI(base_url=origin + "/v1", api_key="local", http_client=http, max_retries=0)
        for i, q in enumerate(qs):
            dest = OUT / "rows" / f"{i:04d}.json"
            if dest.exists():
                saved = load(dest)
                if saved["id"] != q["id"] or saved["lock_sha256"] != lock_sha:
                    raise ValueError("This row belongs to another experiment")
                rows.append(saved)
                continue
            state = states[q["id"]]
            doc = documents[state["doc"]]
            basic = {"id": q["id"], "retrieved": [doc["id"]]}
            prefix = f"{i:04d}-shared"
            trace_dir = OUT / "raw"
            req, resp = (trace_dir / (prefix + "." + tail + ".json") for tail in ("request", "response"))
            trace = CompletionTrace(trace_dir, [(i, "shared", q["id"])])
            delivered = req.exists()
            if not delivered:
                http.event_hooks["request"].append(trace.request)
                http.event_hooks["response"].append(trace.response)
            raw = None
            generated = None
            try:
                if delivered:
                    reply = load(resp) if resp.exists() else {}
                    choices = reply.get("choices") or []
                    if reply.get("status_code") != 200 or len(choices) != 1 or choices[0]["finish_reason"] != "stop":
                        raise ValueError("Prior dispatched request produced no complete reply")
                    model = Recorded(choices[0]["content"] or "")
                else:
                    model = _CompletedResponse(sdk)
                generated = await read_grounded_span(model, q["question"], [doc])
                first = {**basic, **({"status": "answered", **generated} if generated else {"status": "abstained"})}
                if generated is None and "support_error" in state:
                    raise ValueError(state["support_error"])
                if (generated is not None or state.get("support", 0) > 0) and "boundary_error" in state:
                    raise ValueError(state["boundary_error"])
                control = apply_rescue(first, state.get("proposal", {}), state.get("support", 0), q["question"])
                if control["status"] == "answered" and not checked_span(control, bodies):
                    raise ValueError("Unverified initial evidence")
            except Exception as exc:
                control = {**basic, "status": "error", "error": f"{type(exc).__name__}: {exc}"[:300]}
            finally:
                if not delivered:
                    http.event_hooks["request"].remove(trace.request)
                    http.event_hooks["response"].remove(trace.response)
            if resp.exists():
                reply = load(resp)
                if reply["id"] != q["id"] or reply["request_sha256"] != load(req)["request_sha256"]:
                    raise ValueError("Local model response identity mismatch")
                choices = reply.get("choices") or []
                if reply["status_code"] == 200 and len(choices) == 1 and choices[0].get("finish_reason") == "stop":
                    raw = choices[0].get("content")
            try:
                after = select(mode, q["question"], doc, state.get("support", 0), state.get("proposal", {}),
                               control, generated, raw)
                if after["status"] == "answered" and not checked_span(after, bodies):
                    raise ValueError("Unverified selected evidence")
            except Exception as exc:
                after = {**basic, "status": "error", "error": f"{type(exc).__name__}: {exc}"[:300]}
            record = {"id": q["id"], "lock_sha256": lock_sha, "control": control, "candidate": after,
                      "request_sha256": file_sha256(req) if req.exists() else None,
                      "response_sha256": file_sha256(resp) if resp.exists() else None}
            write_new(dest, record)
            rows.append(record)
            if (i + 1) % 8 == 0:
                print("replication", i + 1, "/", len(qs), flush=True)
    for arm in ("control", "candidate"):
        data = {"rows": [r[arm] for r in rows], "lock_sha256": lock_sha}
        dest = OUT / (arm + ".json")
        if not dest.exists():
            write_new(dest, data)
        elif load(dest) != data:
            raise ValueError("Conflicting previously saved final predictions")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("stage", choices=("prepare", "measure"))
    if ap.parse_args().stage == "prepare":
        cache()
    else:
        asyncio.run(measure())
