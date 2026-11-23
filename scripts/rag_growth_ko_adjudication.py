"""Evaluate a frozen conditional adjudicator using captured initial outputs on Korean development only."""

import argparse
import asyncio
import hashlib
import json
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from openai import AsyncOpenAI

from app.lib.llm_client import OllamaLLMClient
from app.modules.core.generation.korean_adjudication import (
    SUPPORT_THRESHOLD,
    adjudicate_korean_span,
    adjudication_route,
)
from scripts.rag_growth_ko_eval import SPAN_FIELDS, grade, write_new
from scripts.rag_growth_local import file_sha256, local_http_client, verify_server

WEIGHTS = "96b9c0af5c77a4ecaabe3983175112b5ece763261c1ece12b2494b692a70dad7"
ALIAS = "onerag-growth-qwen"
ORIGIN = "http://127.0.0.1:18759"


def captures(path: Path) -> dict[str, dict]:
    raw = path.read_bytes()
    complete = raw[:raw.rfind(b"\n")+1]
    rows = [json.loads(line) for line in complete.splitlines()]
    keyed = {r["id"]: r for r in rows}
    if len(rows) != len(keyed):
        raise ValueError("Duplicate development prediction")
    return keyed


def checked_part(panels: Path, manifest: dict, part: str) -> list[dict]:
    name = f"dev.{part}.json"
    raw = (panels / name).read_bytes()
    if hashlib.sha256(raw).hexdigest() != manifest["files"][name]:
        raise ValueError("Development input differs from reservation")
    values = json.loads(raw)
    if not isinstance(values, list) or any(not isinstance(row, dict) for row in values):
        raise ValueError("A reserved development input must be a list of records")
    return values


class MeasuredModel(OllamaLLMClient):
    def __init__(self, client: AsyncOpenAI, attempts: Path):
        super().__init__({"base_url": ORIGIN, "model": ALIAS, "temperature": 0})
        self._client = client
        self.attempts = attempts
        self.case_id = ""
        self.usage: dict[str, Any] = {}
        self.last_text = ""

    async def generate_text(self, prompt: str, system_prompt: str | None = None, **kwargs: Any) -> str:
        with self.attempts.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"id": self.case_id, "messages_sha256":
                                hashlib.sha256(json.dumps([system_prompt, prompt], ensure_ascii=False).encode()).hexdigest()})
                    + "\n")
        self.last_text = await super().generate_text(prompt=prompt, system_prompt=system_prompt, **kwargs)
        return self.last_text

    def _emit_generation(self, **usage: Any) -> None:
        self.usage = {k: usage[k] for k in ("prompt_tokens", "completion_tokens", "total_tokens")}


async def experiment(args: argparse.Namespace) -> None:
    source = Path(__file__).resolve().parents[1] / "app/modules/core/generation"
    reservation = json.loads((args.panels / "reservation.json").read_bytes())
    documents = checked_part(args.panels, reservation, "corpus")
    questions = checked_part(args.panels, reservation, "questions")
    if any(set(c) != {"id", "question"} for c in questions) or len(questions) != 80:
        raise ValueError("Use the reserved 80 development questions")
    by_doc = {d["id"]: d for d in documents}
    proposals, gates = captures(args.proposals), captures(args.sufficiency)
    if set(gates) != set(proposals) or set(proposals) != {c["id"] for c in questions}:
        raise ValueError("Development encoder rows missing or unknown")
    register = {"split": "development", "target_n": len(questions), "source": "top1 BM25 article only",
                "policy": "Preserve literal Qwen/encoder agreement. Preserve explicit refusal at or below the "
                "train-calibrated gate. Otherwise request one shortest literal plus sentence label or NONE. Fail "
                "invalid upstream results, malformed replies and out-of-source literals. Never retry.",
                "refusal_threshold": SUPPORT_THRESHOLD, "gguf_sha256": WEIGHTS,
                "proposals_sha256": file_sha256(args.proposals), "sufficiency_sha256": file_sha256(args.sufficiency),
                "corpus_sha256": reservation["files"]["dev.corpus.json"],
                "questions_sha256": reservation["files"]["dev.questions.json"],
                "code": {p.name: file_sha256(p) for p in
                         (Path(__file__), source/"korean_adjudication.py", source/"grounded_span.py")},
                "input_generated": str(args.generated), "existing_first_pass_calls_reused": len(questions)}
    args.out.mkdir(parents=True, exist_ok=False)
    write_new(args.out / "preregistration.json", register)
    attempts = args.out / "fresh-attempts.jsonl"
    attempts.touch(exist_ok=False)
    rows, baselines = [], []
    async with local_http_client(ORIGIN) as client:
        served = (await client.get("/props")).raise_for_status().json()["model_path"]
        await verify_server(client, ALIAS, Path(served), WEIGHTS)
        model = MeasuredModel(AsyncOpenAI(base_url=ORIGIN+"/v1", api_key="not-needed", http_client=client,
                                         max_retries=0, timeout=120), attempts)
        with (args.out/"development.jsonl").open("x", encoding="utf-8") as stream:
            for case in questions:
                key = case["id"]
                deadline = time.monotonic() + 1200
                while key not in (known := captures(args.generated)):
                    if time.monotonic() >= deadline:
                        raise ValueError("Timed out waiting for the original development pass")
                    await asyncio.sleep(3)
                raw = known[key]
                if raw["weights"] != WEIGHTS or len(raw["retrieved"]) != 1:
                    raise ValueError("Different upstream model or retrieval configuration")
                doc_id = raw["retrieved"][0]
                if gates[key]["ids"][0] != doc_id or proposals[key]["retrieved"][0] != doc_id:
                    raise ValueError("The three independent predictions did not see the same first article")
                baseline = {**raw}
                baselines.append(baseline)
                row: dict[str, Any] = {"id": key, "retrieved": [doc_id], "route": "upstream_error"}
                started = time.monotonic()
                model.case_id, model.usage, model.last_text = key, {}, ""
                try:
                    if raw["status"] == "error":
                        raise ValueError(f"Upstream error: {raw.get('error')}")
                    if raw["status"] not in {"answered", "abstained"}:
                        raise ValueError("Unknown upstream status")
                    initial = {k: raw[k] for k in SPAN_FIELDS} if raw["status"] == "answered" else None
                    if initial is None and any(raw.get(k) for k in SPAN_FIELDS):
                        raise ValueError("An upstream refusal carried an answer")
                    span = next(s for s in proposals[key]["spans"] if s["source_id"] == doc_id)
                    support = gates[key]["scores"][0]
                    row["route"] = adjudication_route(initial, span, support)
                    answer = await adjudicate_korean_span(model, case["question"], by_doc[doc_id], initial, span, support)
                    row.update({"status": "answered", **answer} if answer else {"status": "abstained"})
                except Exception as e:
                    row.update(status="error", error=f"{type(e).__name__}: {e}"[:300])
                row.update(elapsed_ms=(time.monotonic()-started)*1000, usage=model.usage)
                if model.last_text:
                    row["raw_adjudication"] = model.last_text
                stream.write(json.dumps(row, ensure_ascii=False) + "\n")
                stream.flush()
                rows.append(row)
    labels = checked_part(args.panels, reservation, "labels")
    measurements = grade(rows, labels, documents)
    inherited = grade(baselines, labels, documents)
    ledger = captures(attempts)
    write_new(args.out / "metrics.json", {"baseline": inherited["summary"], "adjudicated": measurements["summary"],
              "routes": dict(Counter(r["route"] for r in rows)), "fresh_invocations": len(ledger),
              "total_fresh_tokens": sum(r["usage"].get("total_tokens", 0) or 0 for r in rows),
              "attempts_with_reported_usage": sum(bool(r["usage"]) for r in rows),
              "unchanged_first_pass_sha256": file_sha256(args.generated), "outcomes": measurements["outcomes"]})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("panels", "proposals", "sufficiency", "generated", "out"):
        parser.add_argument("--"+name, type=Path, required=True)
    asyncio.run(experiment(parser.parse_args()))
