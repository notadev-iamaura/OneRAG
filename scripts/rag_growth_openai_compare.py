"""One paid generation per public KLUE question using the archived Korean document agent."""

import argparse
import asyncio
import hashlib
import json
import logging
import os
import re
import sys
import tempfile
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "output/rag-growth-03"
MODEL = "gpt-5.4-2026-03-05"
ORIGIN = "https://api.openai.com/v1"
ASSETS = {
    "gemma-profile/source.zip": "b94fffef48b2bab9a5173471176ef608ded1419902502540bae3969389f8ede5",
    "gemma-profile/evaluator-support.txt": "0c6e7a73d245d0fce9bab314ecc1df03fa71271b41a2d9d186e3645fe2324a65",
    "gemma-profile/registration-v2.json": "4299957db8c41fb37afb27e523cbbfd2a905c2bcf7d3563b45df5ccbc1c5d516",
    "ko/rescue-profile.json": "6a337984e39217eae59fb834299c8ff9ac5c6be5f5d01317ec3903d155c36b01",
    "qwen/rescue-dev.json": "1d95a3c6dba24e2b1fda49a7f7085403735059d5aa0ebae043ca794440105af1",
    "qwen/prior-comparison-plan.json": "2cd004a8f91100592eceee9cec5a33a28107aa5e1dcf6f730a182706e035ebe2",
    "panels/reservation.json": "cb7cf5615742343d0ce57d83119c20c3151dc8debf2920a2ebe26e676d206a42",
}
PARAMS = {"model": MODEL, "temperature": 0, "reasoning_effort": "none", "max_completion_tokens": 100, "store": False}


def digest(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def read(path):
    return json.loads(path.read_bytes())


def fingerprint(data):
    raw = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def persist(path, data):
    """Publish a complete, durable record exactly once across concurrent processes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent) as tmp:
        tmp.write(json.dumps(data, ensure_ascii=False, sort_keys=True, allow_nan=False).encode())
        tmp.flush()
        os.fsync(tmp.fileno())
        os.link(tmp.name, path)


def bind(path, data):
    try:
        persist(path, data)
    except FileExistsError:
        if read(path) != data:
            raise ValueError(f"Changed registered evidence: {path.name}") from None


class ProviderBlocked(RuntimeError):
    """The following question must never be sent after this condition."""


class PublicPromptReady(BaseException):
    """Exit the dry agent at generation, before either a model request or local QA inference."""


def messages(prompt, system_prompt, kwargs):
    from app.modules.core.generation.grounded_span import _INSTRUCTIONS

    if system_prompt != _INSTRUCTIONS or kwargs != {"temperature": 0, "max_tokens": 100, "require_complete": True}:
        raise ProviderBlocked("Unexpected model use outside the registered public reading policy")
    return [{"role": "system", "content": system_prompt}, {"role": "user", "content": prompt}]


class CapturePrompt:
    def __init__(self):
        self.sha = None

    async def generate_text(self, *, prompt, system_prompt, **kwargs):
        self.sha = fingerprint(messages(prompt, system_prompt, kwargs))
        raise PublicPromptReady


class PaidQuestion:
    def __init__(self, client, directory, question_id, identity, prompt_sha):
        self.client, self.directory = client, directory
        self.prefix = {"id": question_id, "protocol_sha256": identity, "prompt_sha256": prompt_sha}
        self.record = None
        self.fatal = None

    def stop(self, detail):
        self.fatal = detail
        raise ProviderBlocked(detail) from None

    async def generate_text(self, *, prompt, system_prompt, **kwargs):
        try:
            public = messages(prompt, system_prompt, kwargs)
        except ProviderBlocked as exc:
            self.stop(str(exc))
        if fingerprint(public) != self.prefix["prompt_sha256"] or self.record is not None:
            self.stop("Unexpected or repeated generation; no request was sent")
        base = self.directory / self.prefix["id"]
        raw_file, intent = base.with_suffix(".response.json"), base.with_suffix(".intent.json")
        if raw_file.exists():
            record = read(raw_file)
            if (not intent.exists() or read(intent) != self.prefix
                    or any(record.get(k) != v for k, v in self.prefix.items())):
                self.stop("Cached response does not match this registered public question")
        else:
            try:
                persist(intent, self.prefix)
            except FileExistsError:
                self.stop(f"{self.prefix['id']} has an unresolved previous request; automatic retransmission is disabled")
            try:
                result = await self.client.chat.completions.create(messages=public, **PARAMS)
            except Exception as exc:
                # Provider exception messages can contain credentials. Persist only a class and numeric HTTP status.
                status = getattr(exc, "status_code", None)
                record = {**self.prefix, "type": type(exc).__name__, "http_status": status if type(status) is int else None}
                persist(base.with_suffix(".failure.json"), record)
                self.stop(f"OpenAI request stopped at {self.prefix['id']}: {record['type']} (HTTP {record['http_status']})")
            if not result.choices:
                self.stop("Provider response had no choice; automatic retransmission is disabled")
            choice = result.choices[0]
            record = {
                **self.prefix, "provider_model": result.model, "response_id": result.id,
                "request_id": getattr(result, "_request_id", None), "finish_reason": choice.finish_reason,
                "text": choice.message.content or "", "usage": result.usage.model_dump() if result.usage else None,
            }
            persist(raw_file, record)
        self.record = record
        if record["provider_model"] != MODEL or not isinstance(record["usage"], dict):
            self.stop("Unexpected provider model or missing usage; comparison stopped")
        if record["finish_reason"] != "stop":
            raise ValueError("Incomplete provider generation")
        return record["text"]


async def trial(q, corpus, articles, reader, model):
    from app.modules.core.agent.factory import AgentFactory
    from app.modules.core.tools.factory import ToolFactory
    from scripts.rag_growth_local import agent_config
    from scripts.rag_growth_profile import PublicArticleRetriever

    start = time.monotonic()
    retriever = PublicArticleRetriever(corpus, articles)
    config = agent_config(False, retriever)
    config["mcp"]["agent"]["extractive_reader"] = reader
    server = ToolFactory.create(config)
    try:
        await server.initialize()
        agent = AgentFactory.create(config, model, server)
        if agent is None:
            raise ValueError("The archived document agent could not initialize")
        result = await agent.run(q["question"])
    except PublicPromptReady:
        if not isinstance(model, CapturePrompt):
            raise
        result = None
    finally:
        await server.shutdown()
    hits = list(dict.fromkeys(h for batch in retriever.batches for h in batch))
    row = {"id": q["id"], "retrieved": hits[:reader["top_k"]], "tool_retrieved": hits,
           "latency_ms": (time.monotonic() - start) * 1000}
    if isinstance(model, CapturePrompt):
        if not model.sha:
            raise ValueError("Public question did not generate a reader prompt")
        return row
    if model.fatal:
        raise ProviderBlocked(model.fatal)
    if model.record is None:
        raise ProviderBlocked("The agent did not reach registered provider generation")
    if result.success and result.grounding_status == "verified_quotes" and len(result.sources) == 1:
        source, = result.sources
        quote, = source["cited_sentences"]
        row.update(status="answered", answer=result.answer, source_id=source["document_id"],
                   start=source["answer_start"], end=source["answer_end"], quote=quote,
                   quote_start=source["quote_start"], quote_end=source["quote_end"])
    elif result.success and result.grounding_status == "insufficient" and result.answer == "근거 부족" and not result.sources:
        row["status"] = "abstained"
    else:
        row.update(status="error", error=f"Agent outcome {result.grounding_status}")
    return row


def inputs():
    if any(digest(EVIDENCE / key) != sha for key, sha in ASSETS.items()):
        raise ValueError("Previously registered public input changed")
    manifest = read(EVIDENCE / "panels/reservation.json")
    parts = {}
    for k in ("questions", "labels", "corpus"):
        p = EVIDENCE / "panels" / f"dev.{k}.json"
        if digest(p) != manifest["files"][p.name]:
            raise ValueError("Public development file changed")
        parts[k] = read(p)
    screen = read(EVIDENCE / "qwen/prior-comparison-plan.json")["ids"]
    if len(set(screen)) != 24 or len(screen) != 24 or len(parts["questions"]) != 80 or len(parts["corpus"]) != 512:
        raise ValueError("Unexpected public benchmark size")
    if any(set(q) != {"id", "question"} or not re.fullmatch(r"klue-mrc-v1_dev_\d{5}", q["id"]) for q in parts["questions"]):
        raise ValueError("Not the public KLUE diagnostic question panel")
    return parts, screen


def install_frozen(root):
    with zipfile.ZipFile(EVIDENCE / "gemma-profile/source.zip") as z:
        z.extractall(root)
    (root / "scripts/rag_growth_integrity.py").write_bytes((EVIDENCE / "gemma-profile/evaluator-support.txt").read_bytes())
    sys.path.insert(0, str(root))
    os.chdir(root)


def provider_client(key):
    import httpx
    from openai import AsyncOpenAI

    # Do not inherit proxy, redirect, custom endpoint, organization or project routing from the host.
    client = AsyncOpenAI(api_key=key, base_url=ORIGIN, organization="", project="", webhook_secret="",
                         max_retries=0, timeout=120, http_client=httpx.AsyncClient(timeout=120,
                         trust_env=False, follow_redirects=False))
    client.organization, client.project = None, None
    return client


async def run(args, parts, screen):
    from scripts.rag_growth_ko_eval import grade
    from scripts.rag_growth_local import Corpus

    control = read(EVIDENCE / "qwen/rescue-dev.json")
    controls = {r["id"]: r for r in control["rows"]}
    cfg = read(EVIDENCE / "ko/rescue-profile.json")["reader"]
    weight_digests = read(EVIDENCE / "gemma-profile/registration-v2.json")
    for label in ("boundary", "sufficiency"):
        folder = Path(cfg[label + "_model_dir"])
        if any(digest(folder / file) != sha for file, sha in weight_digests[label].items()):
            raise ValueError("Historical local encoder weights changed")
    queries = parts["questions"]
    if len(controls) != 80 or {q["id"] for q in queries} != controls.keys() or not set(screen) <= controls.keys():
        raise ValueError("Question IDs differ from the paired Qwen results")
    corpus = Corpus(parts["corpus"])
    articles = {d["id"]: d["content"] for d in parts["corpus"]}
    manifest = {}
    saved_level = logging.root.manager.disable
    logging.disable(logging.INFO)
    try:
        for q in queries:
            capture = CapturePrompt()
            row = await trial(q, corpus, articles, cfg, capture)
            if row["retrieved"] != controls[q["id"]]["retrieved"] or len(row["retrieved"]) != 1:
                raise ValueError("Actual public-agent retrieval differs from the historical Qwen result")
            manifest[q["id"]] = {"question_sha256": fingerprint(q["question"]), "prompt_sha256": capture.sha,
                                 "retrieved": row["retrieved"]}
    finally:
        logging.disable(saved_level)
    plan = {"assets": ASSETS, "model_parameters": PARAMS, "endpoint": ORIGIN,
            "controller_sha256": digest(Path(__file__).resolve()), "questions": manifest,
            "screen_ids": screen, "dataset_files": read(EVIDENCE / "panels/reservation.json")["files"]}
    identity = fingerprint(plan)
    bind(args.output / "protocol.json", plan)
    cases = [q for q in queries if args.scope == "development" or q["id"] in screen]
    ids = {q["id"] for q in cases}
    labels = [label for label in parts["labels"] if label["id"] in ids]
    base = grade([controls[q["id"]] for q in cases], labels, parts["corpus"])
    preflight = {"scope": args.scope, "n": len(cases), "protocol_sha256": identity,
                 "qwen_summary": base["summary"], "public_retrieval_checked": len(manifest)}
    bind(args.output / (args.scope + "-preflight.json"), preflight)
    if args.phase == "preflight":
        print(json.dumps(preflight, ensure_ascii=False))
        return
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        raise ProviderBlocked("OPENAI_API_KEY is unavailable in the process environment; no request was sent")
    rows, total_tokens = [], 0
    async with provider_client(key) as client:
        for q in cases:
            qid = q["id"]
            rec = PaidQuestion(client, args.output / "cases", qid, identity, manifest[qid]["prompt_sha256"])
            dest = args.output / "cases" / (qid + ".product.json")
            if dest.exists():
                saved = read(dest)
                response = args.output / "cases" / (qid + ".response.json")
                raw = read(response)
                if (saved["protocol_sha256"] != identity or saved["id"] != qid
                        or saved["response_sha256"] != digest(response) or raw["prompt_sha256"] != rec.prefix["prompt_sha256"]
                        or raw["protocol_sha256"] != identity or raw["provider_model"] != MODEL):
                    raise ValueError("Saved product verdict does not match its provider response")
                row = saved["product"]
            else:
                row = await trial(q, corpus, articles, cfg, rec)
                raw = rec.record
                response = args.output / "cases" / (qid + ".response.json")
                persist(dest, {"id": qid, "protocol_sha256": identity, "response_sha256": digest(response), "product": row})
            if row["id"] != qid or row["retrieved"] != controls[qid]["retrieved"]:
                raise ValueError("Actual paired retrieval changed")
            rows.append(row)
            total_tokens += raw["usage"]["total_tokens"]
    candidate = grade(rows, labels, parts["corpus"])
    old = {r["id"]: r["correct"] for r in base["outcomes"]}
    paired = [{"id": r["id"], "answerable": r["answerable"], "qwen": old[r["id"]], "openai": r["correct"]}
              for r in candidate["outcomes"]]
    result = {**preflight, "openai_summary": candidate["summary"], "paired": paired, "provider_usage_total_tokens": total_tokens,
              "product_rows": rows, "response_files": {q["id"]: digest(args.output / "cases" / (q["id"] + ".response.json"))
                                                       for q in cases}}
    bind(args.output / (args.scope + "-report.json"), result)
    print(json.dumps({"scope": args.scope, "n": len(rows), "openai": candidate["summary"],
                      "qwen": base["summary"], "total_tokens": total_tokens}, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("preflight", "run"))
    parser.add_argument("--model", choices=(MODEL,), required=True)
    parser.add_argument("--scope", choices=("screen", "development"), default="screen")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output = args.output.resolve()
    # Only use immutable code and public inputs, never load project environment files or telemetry.
    os.environ.update(ENVIRONMENT="test", LANGFUSE_ENABLED="false", PYTHON_DOTENV_DISABLED="1",
                      HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", OPENAI_LOG="error")
    parts, screen = inputs()
    with tempfile.TemporaryDirectory(prefix="onerag-public-openai-") as temp:
        install_frozen(Path(temp))
        asyncio.run(run(args, parts, screen))


if __name__ == "__main__":
    try:
        main()
    except (ProviderBlocked, ValueError, FileNotFoundError, FileExistsError) as error:
        sys.exit(str(error))
