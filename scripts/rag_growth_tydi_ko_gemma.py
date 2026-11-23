"""Run a preregistered, blinded Gemma read of the top three joint-ranked Korean TyDi passages."""

import argparse
import asyncio
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx
from openai import AsyncOpenAI

from app.lib.llm_client import OllamaLLMClient
from app.modules.core.agent.extractive_reader import ExtractiveReaderConfig, extract_from_sources
from scripts.rag_growth_ko_eval import grade, write_new
from scripts.rag_growth_local import ROOT, file_sha256, local_http_client, verify_server

BASE = ROOT/"output/rag-growth-03/tydi-ko-retrieval"
OUT = BASE/"gemma-blind"
PANEL = "84d12821aaa1ed48dd7af86277de71c01b19dab0a00b7af8c88510edeba41ded"
PRED = "0ae6f5b1bcbef022a02438168e83b2662b6f5d94609c539be84fc18391ea2921"
COMPARE = "ccf38cb886cd3d1595a81ed344d38e132a3f23df7ced42cd82f877e00029b18f"
MODEL_FILE = Path.home()/"Models/gemma-4-12b/gemma-4-12b-it-Q4_K_M.gguf"
MODEL = "onerag-growth-gemma"
ORIGIN = "http://127.0.0.1:18761"
WEIGHTS = "0a270ec9fe6b34f4a0d33992b6135117b484ebc4766ab76b51d4ae8c457e4c42"
FRESH_SEED = "onerag-tydi-ko-gemma-fresh-transfer-01"
Row = dict[str, Any]


def load(path: Path, sha: str | None = None) -> Any:
    raw = path.read_bytes()
    if sha and hashlib.sha256(raw).hexdigest() != sha:
        raise ValueError(f"Changed input: {path.name}")
    return json.loads(raw)


def dev_inputs() -> tuple[list[Row], list[Row], list[Row], str]:
    manifest = load(BASE/"panels/reservation.json", PANEL)
    questions = load(BASE/"panels/dev.questions.json", manifest["files"]["dev.questions.json"])
    docs = load(BASE/"panels/dev.corpus.json", manifest["files"]["dev.corpus.json"])
    cache = load(BASE/"run/dev.predictions.json", PRED)["hybrid_joint"]
    ranking = [{"id": r["id"], "passages": r["reranked"][:3]} for r in cache]
    return questions, docs, ranking, manifest["files"]["dev.labels.json"]


def checked_inputs(questions: list[Row], docs: list[Row], ranks: list[Row], n: int) -> dict[str, Row]:
    expected = [r["id"] for r in questions]
    corpus = {d["id"]: d for d in docs}
    if (len(corpus) != len(docs) or any(set(d) != {"id", "title", "content"} for d in docs)
            or any(set(r) != {"id", "question"} for r in questions) or len(set(expected)) != n
            or expected != [r["id"] for r in ranks] or len(expected) != n):
        raise ValueError("Incomplete, repeated, mismatched or labelled inference inputs")
    for r in ranks:
        ids = r["passages"]
        if (set(r) != {"id", "passages"} or len(ids) != 3 or len(set(ids)) != 3
                or any(i not in corpus or not corpus[i]["content"].strip() for i in ids)):
            raise ValueError("Expected three different complete registered ranking results")
    return corpus


def target(summary: Row, denominator: int = 16) -> bool:
    p, z = summary["answerable"], summary["unanswerable"]
    if p["n"] != denominator or z["n"] != denominator:
        raise ValueError("Unexpected stratum denominator")
    if summary["statuses"].get("error", 0):
        return False
    both80 = min(p["correct"], z["correct"]) * 5 >= 4 * denominator
    return both80 or (denominator == 16 and p["correct"] >= 10 and z["correct"] >= 15)


def registration(ranks: list[Row]) -> Row:
    compare = load(BASE/"run/dev.metrics.json", COMPARE)
    for name, values in (("single_verifier", (5, 12)), ("hybrid_joint", (9, 15))):
        s = compare["metrics"][name]["summary"]
        if (s["answerable"]["correct"], s["unanswerable"]["correct"]) != values or s["statuses"].get("error", 0):
            raise ValueError("Unregistered development comparator")
    files = [Path(__file__), ROOT/"scripts/rag_growth_ko_eval.py", ROOT/"scripts/rag_growth_gate.py",
             ROOT/"scripts/rag_growth_local.py", ROOT/"app/lib/llm_client.py", ROOT/"app/lib/evidence_sentences.py",
             ROOT/"app/modules/core/generation/grounded_span.py", ROOT/"app/modules/core/agent/extractive_reader.py",
             ROOT/"scripts/rag_growth_tydi_ko_retrieval.py", ROOT/"app/modules/core/generation/korean_passage_selection.py"]
    return {"policy": "Gemma full passage blind extraction / frozen joint ranking top 3", "port": 18761,
            "model": MODEL, "gguf_sha256": WEIGHTS, "temperature": 0, "max_tokens": 100, "max_retries": 0,
            "timeout_seconds": 120, "files_sha256": {str(p.relative_to(ROOT)): file_sha256(p) for p in files},
            "panel_sha256": PANEL, "joint_predictions_sha256": PRED, "comparisons_sha256": COMPARE,
            "rank_only_sha256": hashlib.sha256(json.dumps(ranks, sort_keys=True).encode()).hexdigest(),
            "sources": "Unmodified question and full texts of the top 3 joint-ranked passages only; each input is "
                       "checked against the production 3600-character per-passage ceiling. Each complete answer "
                       "requires a verbatim passage, sentence and source character offsets; explicit NONE abstains.",
            "development": "32 cases, 16+16; no errors AND either both >=13/16 or answerable>=10/16 AND "
                           "unanswerable>=15/16. No post-hoc policy selections or second decode.",
            "confirmation": "Only after a passing development result: another 24+24 TyDi KO validation panel, "
                            "16+16 only if insufficient eligible articles, full official passages and 16 independent "
                            "background articles, same joint ranker+Gemma. Exclude both earlier TyDi validation "
                            "panels, their backgrounds, KLUE, mixed 512+64 and current train development questions, "
                            "titles, articles and passages. No exposed confirmation reader scores reused.",
            "confirmation_seed": FRESH_SEED}


async def measure(split: str, questions: list[Row], docs: list[Row], ranks: list[Row],
                  label_file: Path, label_sha: str, prefix: Path, n: int) -> None:
    corpus = checked_inputs(questions, docs, ranks, n)
    request_path = OUT/"registration.json"
    receipt = prefix.with_suffix(".started.json")
    logfile = prefix.with_suffix(".rows.jsonl")
    reportfile = prefix.with_suffix(".metrics.json")
    if receipt.exists() or logfile.exists() or reportfile.exists():
        raise ValueError("The registered one-shot run is already occupied")
    profile = ExtractiveReaderConfig(implementation="generative", top_k=3)
    rows: list[Row] = []
    capture: list[Row] = []
    async def response_hook(response: httpx.Response) -> None:
        if response.request.url.path != "/v1/chat/completions":
            return
        raw = await response.aread()
        capture.append({"http_status": response.status_code, "request": json.loads(response.request.content),
                        "response_utf8": raw.decode("utf-8", errors="replace"), "response_sha256": hashlib.sha256(raw).hexdigest()})
    async with local_http_client(ORIGIN) as client:
        await verify_server(client, MODEL, MODEL_FILE, WEIGHTS)
        client.event_hooks["response"].append(response_hook)
        model = OllamaLLMClient({"base_url": ORIGIN, "model": MODEL, "temperature": 0, "timeout": 120})
        model._client = AsyncOpenAI(base_url=ORIGIN+"/v1", api_key="not-needed",
                                    timeout=120, max_retries=0, http_client=client)
        write_new(receipt, {"split": split, "registration_sha256": file_sha256(request_path),
                            "expected_ids": [q["id"] for q in questions], "verified_model_sha256": WEIGHTS})
        with logfile.open("x", encoding="utf-8") as stream:
            for q, rank in zip(questions, ranks, strict=True):
                row: Row = {"id": q["id"], "retrieved": rank["passages"]}
                evidence = {key: ({"document_id": key, "title": corpus[key]["title"]}, corpus[key]["content"])
                            for key in rank["passages"]}
                capture.clear()
                start = time.monotonic()
                try:
                    if any(len(body) > 3600 for _, body in evidence.values()):
                        raise ValueError("Full passage exceeds registered production input length")
                    result = await extract_from_sources(profile, model, q["question"], evidence)
                    if result is None:
                        row.update(status="abstained")
                    else:
                        answer, citation = result
                        quote, = citation["cited_sentences"]
                        row.update(status="answered", answer=answer, source_id=citation["document_id"], quote=quote,
                                   start=citation["answer_start"], end=citation["answer_end"],
                                   quote_start=citation["quote_start"], quote_end=citation["quote_end"])
                except Exception as err:
                    row.update(status="error", error=f"{type(err).__name__}: {err}"[:350])
                row.update(elapsed_s=time.monotonic()-start, observed_http=list(capture))
                stream.write(json.dumps(row, ensure_ascii=False)+"\n")
                stream.flush()
                rows.append(row)
                print(split, len(rows), "/",n, row["status"], flush=True)
    labels = load(label_file, label_sha)
    verdict = grade(rows, labels, docs)
    report = {"split": split, "registration_sha256": file_sha256(request_path),
              "rows_sha256": file_sha256(logfile), **verdict, "eligible": target(verdict["summary"], n//2)}
    if split == "dev":
        refs = load(BASE/"run/dev.metrics.json", COMPARE)["metrics"]
        report["baselines"] = {key: refs[key]["summary"] for key in ("single_verifier", "hybrid_joint")}
    write_new(reportfile, report)
    print(report["summary"], flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("reserve","dev"))
    args = parser.parse_args()
    questions, docs, ranks, label_sha = dev_inputs()
    corpus = checked_inputs(questions, docs, ranks, 32)
    reg = registration(ranks)
    if args.operation == "reserve":
        if any(len(corpus[key]["content"]) > 3600 for r in ranks for key in r["passages"]):
            raise ValueError("The development arm cannot receive every full selected passage")
        write_new(OUT/"registration.json", reg)
        print(file_sha256(OUT/"registration.json"))
    else:
        if load(OUT/"registration.json") != reg:
            raise ValueError("Registered policy changed")
        asyncio.run(measure("dev", questions, docs, ranks, BASE/"panels/dev.labels.json", label_sha, OUT/"dev", 32))


if __name__ == "__main__":
    main()
