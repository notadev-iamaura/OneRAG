"""Verify local paired measurements and whether a cited passage contains a gold answer span."""

from __future__ import annotations

import math
import re
import unicodedata
from collections.abc import Mapping
from pathlib import Path

from scripts import rag_growth_local as local

SPAN_FAILURE = "answer_span_not_in_citation"
_PARTICLES = re.compile(
    r"(?:에게서|한테서|으로부터|로부터|에서는|에서도|에서|에게|한테|으로|로|까지|부터|처럼|보다|마다|"
    r"이라고|라고|이라는|라는|이란|란|이었다|였다|이다|입니다|이었고|였고|이며|이고|"
    r"은|는|이|가|을|를|와|과|의|에|도|만|께|뿐)(?:은|는|도|만)?"
)
_UNITS = re.compile(r"(?:명|개|건|회|번|원|년|월|일|시|분|초|살|세|차례|대|위|층|호|점|배|쪽|권|곳|시간)")


def _normal(text):
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def _term_in_quote(term, quote):
    term, quote = _normal(term).rstrip(".。"), _normal(quote)
    if not term:
        return False
    for match in re.finditer(re.escape(term), quote):
        start, end = match.span()
        before, after = quote[:start], quote[end:]
        if before and term[0].isalnum() and (before[-1].isalnum() or before[-1] == "_"):
            continue
        if term[0].isdigit() and re.search(r"(?:[+−-]|\d[.,:/])$", before):
            continue
        if term[-1].isdigit() and re.match(r"(?:\d|[.,:/]\d)", after):
            continue
        if term.endswith("%") and re.match(r"[a-z]", after):
            continue
        if after and term[-1].isalnum() and (after[0].isalnum() or after[0] == "_"):
            tail = re.match(r"\w+", after)[0]
            if term[-1].isdigit():
                tail = _UNITS.sub("", tail, count=1) if _UNITS.match(tail) else tail
            if tail and not _PARTICLES.fullmatch(tail):
                continue
        return True
    return False


def _contents(documents):
    if isinstance(documents, Mapping):
        return documents
    return {doc["id"]: doc["content"] for doc in documents}


def _validate_spans(case, bodies):
    spans = case.get("answer_spans")
    if spans is None:
        return
    if not isinstance(spans, list) or bool(spans) != case["answerable"]:
        raise ValueError(f"{case['id']}: invalid answer_spans")
    for span in spans:
        if not isinstance(span, dict):
            raise ValueError(f"{case['id']}: invalid answer span")
        doc, text, start = (span.get(k) for k in ("document_id", "text", "start"))
        if (not isinstance(doc, str) or doc not in case["source_ids"] or doc not in bodies
                or not isinstance(text, str) or text not in case["answers"]
                or type(start) is not int or start < 0 or not bodies[doc].startswith(text, start)):
            raise ValueError(f"{case['id']}: gold answer offset differs from source")


def answer_evidence_failure(case, row, documents=None):
    """Call after basic scoring. Optional official offsets refer to characters of the raw body."""
    from scripts.rag_growth_gate import normalized

    if (not case["answerable"] or row["status"] != "answered"
            or set(row["citations"]) != set(case["source_ids"])
            or normalized(row["answer"]) not in {normalized(a) for a in case["answers"]}):
        return None
    evidence = [(entry["document_id"], entry["quote"]) for entry in row.get("cited_evidence", [])
                if entry["document_id"] in case["source_ids"]]
    if "answer_spans" in case:
        if documents is None:
            raise ValueError("Raw document bodies are needed to verify registered offsets")
        bodies = _contents(documents)
        _validate_spans(case, bodies)
        for span in case["answer_spans"]:
            doc, start, text = span["document_id"], span["start"], span["text"]
            for quoted_doc, quote in evidence:
                if doc != quoted_doc or not quote:
                    continue
                # A quote may occur more than once; require it to cover the annotated location.
                low = max(0, start + len(text) - len(quote))
                if bodies[doc].find(quote, low, start + len(quote)) != -1:
                    return None
        return SPAN_FAILURE
    if documents is not None:
        bodies = _contents(documents)
        evidence = [(doc, quote) for doc, quote in evidence if doc in bodies and quote in bodies[doc]]
    return None if any(_term_in_quote(alias, quote) for _, quote in evidence for alias in case["answers"]) else SPAN_FAILURE


def _validate_trace(row, bodies):
    def invalid(message):
        raise ValueError(f"{row['id']} trial {row['trial']}: {message}")

    batches = row.get("candidate_batches")
    if not isinstance(batches, list) or len(batches) > 2:
        invalid("invalid candidate_batches")
    for i, batch in enumerate(batches):
        if (not isinstance(batch, list) or len(batch) > (8 if i == 0 else 3)
                or any(not isinstance(doc, str) or doc not in bodies for doc in batch)
                or len(batch) != len(set(batch))):
            invalid("unknown or duplicate candidates, or invalid batch size")
    if row["candidates"] != list(dict.fromkeys(doc for batch in batches for doc in batch)):
        invalid("candidate order differs from retrieval batches")
    calls, tokens = row.get("model_calls"), row["tokens"]
    if (type(calls) is not int or type(tokens) is not int or not 0 <= calls <= tokens
            or bool(calls) != bool(tokens)):
        invalid("inconsistent model calls and tokens")
    status = row["status"]
    if status not in ("answered", "abstained", "error"):
        invalid("unknown status")
    evidence = row.get("cited_evidence")
    if not isinstance(evidence, list) or any(not isinstance(e, dict) or not isinstance(e.get("document_id"), str)
                                            or not isinstance(e.get("quote"), str) or not e["quote"].strip()
                                            for e in evidence):
        invalid("invalid cited_evidence")
    if status == "error":
        return  # An invalid model citation remains an observed failure in the denominator.
    if not batches or (not calls and any(batches)):
        invalid("missing retrieval or model call")
    if status == "abstained":
        if (row.get("grounding_status") != "insufficient" or row["citations"] or evidence
                or row["answer"] != "근거 부족" or row.get("stop_reason") not in ("no_new_evidence", "max_iterations")):
            invalid("inconsistent abstention")
        return
    citations = row["citations"]
    if (not calls or row.get("grounding_status") != "verified_quotes" or row.get("stop_reason") != "completed"
            or not citations or len(set(citations)) != len(citations) or not set(citations) <= set(row["candidates"])
            or set(citations) != {e["document_id"] for e in evidence}):
        invalid("inconsistent answered status or missing cited evidence")
    if any(e["quote"] not in bodies[e["document_id"]] for e in evidence):
        invalid("cited quote differs from registered source")


def validate_paired(manifest, baseline_rows, candidate_rows, *, manifest_sha256, expected_provenance=None):
    """Check a pair returned by gate.read_run. Legacy manifests without public-source fields are skipped.

    By default the checked-out runner and dependencies are the reference. For a historical run,
    pass independently archived expected index_sha256, agent_sha256 and runner_sha256 values.
    """
    if expected_provenance is not None and (not isinstance(expected_provenance, dict) or set(expected_provenance) != {
        "api_model", "agent_sha256", "runner_sha256", "index_sha256",
    }):
        raise ValueError("Expected registered api_model and agent, runner, index SHA256s")
    if "documents" not in manifest and "model_sha256" not in manifest:
        return
    local.validate_manifest(manifest)
    if not re.fullmatch("[0-9a-f]{64}", manifest_sha256):
        raise ValueError("Invalid manifest SHA256")
    documents = manifest["documents"]
    bodies = _contents(documents)
    for case in manifest["cases"]:
        _validate_spans(case, bodies)
    expected = {key: manifest[key] for key in ("model", "index", "corpus_sha256", "model_sha256", "split", "dataset")}
    expected["manifest_sha256"] = manifest_sha256
    attested = expected_provenance or {}
    for key, fallback in (
        ("index_sha256", lambda: local.index_sha256(documents)),
        ("agent_sha256", local.agent_sha256),
        ("runner_sha256", lambda: local.file_sha256(Path(local.__file__))),
    ):
        value = attested[key] if key in attested else fallback()
        if not isinstance(value, str) or not re.fullmatch("[0-9a-f]{64}", value) or manifest.get(key, value) != value:
            raise ValueError(f"Conflicting or invalid registered {key}")
        expected[key] = value
    expected["api_model"] = attested.get("api_model", manifest.get("api_model", manifest["model"]))
    if "api_model" in manifest and expected["api_model"] != manifest["api_model"]:
        raise ValueError("Conflicting registered API model IDs")
    keys = {(c["id"], trial) for c in manifest["cases"] for trial in range(1, manifest["trials"] + 1)}
    common_sampler, modes, first_searches, trial_seeds = None, [], {}, {}
    for arm, rows in enumerate((baseline_rows, candidate_rows)):
        if rows.keys() != keys:
            raise ValueError("Incomplete or unexpected question/trial keys")
        arm_modes = set()
        for (case_id, trial), row in rows.items():
            if row.get("id") != case_id or row.get("trial") != trial or any(row.get(k) != v for k, v in expected.items()):
                raise ValueError(f"{case_id}: row identity differs from registered provenance")
            api_model, temp, limit = row.get("api_model"), row.get("temperature"), row.get("max_tokens")
            if (not isinstance(api_model, str) or not api_model.strip() or type(temp) not in (int, float)
                    or not math.isfinite(temp) or temp < 0 or type(limit) is not int or limit <= 0
                    or row.get("fresh_agent_each_trial") is not True or not isinstance(row.get("model_cache"), str)
                    or not row["model_cache"].strip() or ("seed" in row and type(row["seed"]) is not int)):
                raise ValueError(f"{case_id}: invalid sampler or API model identity")
            sampler = (api_model, temp, limit, row["model_cache"])
            if ((common_sampler is not None and common_sampler != sampler)
                    or trial_seeds.setdefault(trial, row.get("seed")) != row.get("seed")):
                raise ValueError(f"{case_id}: sampler or served model differs within the pair")
            common_sampler = sampler
            mode = row.get("policy_mode")
            if mode is not None and (not isinstance(mode, str) or not mode.strip()):
                raise ValueError("Invalid policy_mode")
            flag = row.get("verify_premise_mismatch")
            if "verify_premise_mismatch" in row and (type(flag) is not bool or flag != bool(arm)):
                raise ValueError("Policy flag differs from the registered arm")
            arm_modes.add((row["policy"], mode, flag))
            _validate_trace(row, bodies)
            if row["candidate_batches"]:
                first = row["candidate_batches"][0]
                if first_searches.setdefault(case_id, first) != first:
                    raise ValueError(f"{case_id}: initial retrieval differs between paired trials")
        if len(arm_modes) != 1:
            raise ValueError("Inconsistent policy identity within an arm")
        modes.append(arm_modes.pop())
    (base, base_mode, base_flag), (cand, cand_mode, cand_flag) = modes
    if (base == cand or (base_mode is None) != (cand_mode is None)
            or (base_flag is None) != (cand_flag is None) or (base_mode is not None and base_mode == cand_mode)):
        raise ValueError("Missing or indistinguishable paired policy identity")
