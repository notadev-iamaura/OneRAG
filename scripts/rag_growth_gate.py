"""Compare two Korean document QA policies on every registered question and trial."""

import argparse
import hashlib
import json
import math
import random
import sys
import unicodedata
from collections import Counter
from pathlib import Path
from statistics import mean
from tempfile import TemporaryDirectory
from typing import Any

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import rag_growth_integrity as integrity

TRIALS = (1, 2, 3)
TOKEN_LIMIT = 1.5
REFUSALS = {
    "근거 부족", "근거가 부족합니다", "정보 부족", "정보가 부족합니다",
    "근거가 충분하지 않습니다", "확인할 수 없습니다", "알 수 없습니다",
    "제공된 자료로는 확인할 수 없습니다", "insufficient evidence",
}
EXECUTION_FAILURES = {"model_error", "invalid_citation", "empty_response", "no_model_tokens", "inconsistent_status"}
NEXT_ACTION = {
    "model_error": "모델의 종료 사유와 호출 제한을 확인하고 같은 조건에서 오류를 재현한다.",
    "invalid_citation": "모델이 출력한 인용 표기와 실제로 제공된 문장 식별자를 대조한다.",
    integrity.SPAN_FAILURE: "인용한 문장에 질문이 요구한 정답 구절이 실제로 들어 있는지 대조한다.",
    "empty_response": "빈 모델 출력을 생성 실패로 처리하고 종료 사유를 기록한다.",
    "no_model_tokens": "완료로 기록된 행의 실제 모델 호출과 토큰 계측을 대조한다.",
    "inconsistent_status": "모델 응답 본문과 구조화된 보류 상태가 일치하도록 파서를 수정한다.",
    "retrieval_miss": "검색에 빠진 필수 문서가 들어오도록 질의 확장 또는 검색 범위를 비교한다.",
    "unnecessary_abstention": "검색된 원문의 인접 문장에서 질문 조건이 충족되는지 다시 확인한다.",
    "unsupported_answer": "답변 전에 원문이 질문의 주체와 조건을 모두 뒷받침하는지 검증한다.",
    "cited_abstention": "보류 응답의 실제 인용을 비우고 검색 후보와 구분한다.",
    "citation_outside_candidates": "모델이 인용한 문서 ID를 이번 요청이 검색한 후보에 대조한다.",
    "incorrect_sources": "답변을 지지하는 모든 필수 문서를 선택하고 추가 인용을 제거한다.",
    "incorrect_answer": "선택한 원문에서 질문이 요구한 이름·수량·시점을 단답으로 추출한다.",
}


def normalized(value: str) -> str:
    # Keep signs, unit separators and internal punctuation (1.5 is distinct from 15).
    text = " ".join(unicodedata.normalize("NFKC", value).casefold().split())
    return text.removesuffix(".").removesuffix("。").strip()


def strings(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(v, str) and v.strip() for v in value)


def nonblank(row: dict[str, Any], fields: tuple[str, ...]) -> bool:
    return all(isinstance(row.get(k), str) and row[k].strip() for k in fields)


def read_manifest(raw: bytes) -> dict[str, Any]:
    manifest = json.loads(raw)
    if not isinstance(manifest, dict) or not nonblank(manifest, ("model", "index", "dataset")):
        raise ValueError("Missing manifest metadata")
    if (type(manifest.get("schema_version")) is not int or manifest["schema_version"] != 1
            or type(manifest.get("trials")) is not int or manifest["trials"] != len(TRIALS)
            or manifest.get("split") not in ("development", "holdout")
            or not isinstance(manifest.get("cases"), list)):
        raise ValueError("Expected schema 1, a registered split, and three trials")
    ids, questions, bins = set(), set(), set()
    for case in manifest["cases"]:
        if not isinstance(case, dict) or not nonblank(case, ("id", "question")):
            raise ValueError("Invalid manifest case")
        if (type(case.get("answerable")) is not bool or not strings(case.get("answers"))
                or not strings(case.get("source_ids"))):
            raise ValueError("Invalid answerability or reference types")
        if case["answerable"] != bool(case["answers"]) or (
            case["answerable"] and (not case["source_ids"] or not all(map(normalized, case["answers"])))
        ):
            raise ValueError("Answerable cases require aliases and sources; unanswerable cases require empty aliases")
        question = normalized(case["question"])
        if not question or case["id"] in ids or question in questions:
            raise ValueError("Empty or duplicate question, or duplicate case ID")
        ids.add(case["id"])
        questions.add(question)
        bins.add(case["answerable"])
    if bins != {True, False}:
        raise ValueError("Both answerable and unanswerable strata are required")
    return manifest


def read_run(raw: bytes, manifest: dict[str, Any], digest: str) -> tuple[str, dict]:
    expected = {(c["id"], t) for c in manifest["cases"] for t in TRIALS}
    rows, policies = {}, set()
    for line in raw.splitlines():
        row = json.loads(line)
        if not isinstance(row, dict) or not nonblank(row, ("policy", "id")):
            raise ValueError("Missing policy or case ID")
        if (row.get("manifest_sha256") != digest or row.get("model") != manifest["model"]
                or row.get("index") != manifest["index"]):
            raise ValueError("Manifest, model or index differs from the registered input")
        trial = row.get("trial")
        if type(trial) is not int or (row["id"], trial) not in expected or (row["id"], trial) in rows:
            raise ValueError("Unexpected or duplicate question/trial")
        if (row.get("status") not in ("answered", "abstained", "error")
                or not isinstance(row.get("answer"), str) or not strings(row.get("citations"))
                or not strings(row.get("candidates"))):
            raise ValueError("Invalid response or evidence fields")
        latency = row.get("latency_ms")
        if (type(row.get("tokens")) is not int or row["tokens"] < 0
                or type(latency) not in (int, float) or not math.isfinite(latency) or latency < 0):
            raise ValueError("Invalid token or latency measurement")
        rows[row["id"], trial] = row
        policies.add(row["policy"])
    if rows.keys() != expected or len(policies) != 1:
        raise ValueError("Every case needs three trials under a single policy")
    return policies.pop(), rows


def failure(case: dict, row: dict, document_bodies: dict[str, str] | None = None) -> str | None:
    answer = normalized(row["answer"])
    if row["status"] == "error":
        generated_bad_reference = (
            row.get("grounding_status") == "invalid_citation" and row.get("stop_reason") == "error"
            and row.get("tokens", 0) > 0 and row.get("model_calls", 0) > 0 and not row.get("error_type")
        )
        return "invalid_citation" if generated_bad_reference else "model_error"
    if not answer:
        return "empty_response"
    if row["tokens"] == 0:
        return "no_model_tokens"
    abstained = row["status"] == "abstained"
    if abstained != (answer in REFUSALS):
        return "inconsistent_status"
    cited, retrieved, required = (set(values) for values in (row["citations"], row["candidates"], case["source_ids"]))
    if abstained and cited:
        return "cited_abstention"
    if not case["answerable"]:
        return None if abstained else "unsupported_answer"
    if cited - retrieved:
        return "citation_outside_candidates"
    if not required <= retrieved:
        return "retrieval_miss"
    if abstained:
        return "unnecessary_abstention"
    if cited != required:
        return "incorrect_sources"
    if answer not in {normalized(a) for a in case["answers"]}:
        return "incorrect_answer"
    return integrity.answer_evidence_failure(case, row, document_bodies) if document_bodies is not None else None


def paired_outcomes(pairs: list[tuple[bool, bool]]) -> dict:
    n = len(pairs)
    before = sum(a for a, _ in pairs)
    after = sum(b for _, b in pairs)
    improved = sum(b and not a for a, b in pairs)
    regressed = sum(a and not b for a, b in pairs)
    differences = [int(b) - int(a) for a, b in pairs]
    sampler = random.Random(17)
    draws = 2000
    ordered = sorted(sum(sampler.choices(differences, k=n)) / n for _ in range(draws))
    return {"n": n, "baseline": before, "candidate": after, "baseline_rate": before / n,
            "candidate_rate": after / n, "improved": improved, "regressed": regressed,
            "unchanged": n - improved - regressed,
            "rate_difference": {"estimate": (after - before) / n,
                                "ci95": [ordered[math.ceil(.025 * draws) - 1], ordered[math.ceil(.975 * draws) - 1]],
                                "method": "paired_question_percentile_bootstrap", "resamples": draws, "seed": 17,
                                "n_questions": n}}


def resources(rows: dict) -> dict:
    delays = sorted(r["latency_ms"] for r in rows.values())
    tokens = sum(r["tokens"] for r in rows.values())
    return {"n": len(rows), "tokens_total": tokens, "tokens_mean": tokens / len(rows),
            "latency_ms_mean": mean(delays), "latency_ms_p95": delays[math.ceil(.95 * len(delays)) - 1]}


def evaluate(manifest_path: Path, baseline_path: Path, candidate_path: Path, *, expected_provenance=None) -> dict:
    raw = manifest_path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    manifest = read_manifest(raw)
    paths = (baseline_path, candidate_path)
    payloads = [p.read_bytes() for p in paths]
    (before_id, baseline), (after_id, candidate) = [read_run(b, manifest, digest) for b in payloads]
    integrity.validate_paired(manifest, baseline, candidate, manifest_sha256=digest,
                              expected_provenance=expected_provenance)
    documents = {d["id"]: d["content"] for d in manifest["documents"]} if "documents" in manifest else None
    bins, failures, errors = {}, [], {"baseline": 0, "candidate": 0}
    histograms: dict[str, Counter] = {"baseline": Counter(), "candidate": Counter()}
    affected: dict[str, set] = {}
    reasons = ["missing_source_provenance"] if documents is None else []
    improved = False
    for name, answerable in (("answerable", True), ("unanswerable", False)):
        by_trial: dict[int, list] = {i: [] for i in TRIALS}
        all_three = []
        for case in manifest["cases"]:
            if case["answerable"] != answerable:
                continue
            outcomes = []
            for trial in TRIALS:
                key = (case["id"], trial)
                before, after = (failure(case, r[key], documents) for r in (baseline, candidate))
                passed = (before is None, after is None)
                by_trial[trial].append(passed)
                outcomes.append(passed)
                for version, cause in (("baseline", before), ("candidate", after)):
                    if cause:
                        histograms[version][cause] += 1
                        errors[version] += cause in EXECUTION_FAILURES
                if after and manifest["split"] == "development":
                    affected.setdefault(after, set()).add(case["id"])
                    row = candidate[key]
                    failures.append({"id": case["id"], "trial": trial, "question": case["question"],
                                     "answerable": answerable, "expected_answers": case["answers"],
                                     "required_sources": case["source_ids"], "answer": row["answer"],
                                     "citations": row["citations"], "candidates": row["candidates"],
                                     "cited_evidence": row.get("cited_evidence", []),
                                     "reason": after, "baseline_reason": before})
            all_three.append((all(a for a, _ in outcomes), all(b for _, b in outcomes)))
        trials = {str(i): paired_outcomes(by_trial[i]) for i in TRIALS}
        first, all3 = trials["1"], paired_outcomes(all_three)
        bins[name] = {"cases": len(all_three), "first": first, "all3": all3, "trials": trials}
        if any(g["candidate"] < g["baseline"] for g in (*trials.values(), all3)):
            reasons.append(f"{name}_regression")
        improved |= any(g["candidate"] > g["baseline"] for g in (first, all3))
    old, new = resources(baseline), resources(candidate)
    if before_id == after_id:
        reasons.append("same_policy")
    if not improved:
        reasons.append("no_first_or_all3_improvement")
    # A measured baseline citation failure can be fixed. An incomplete baseline call cannot establish a gain.
    if errors["candidate"] or errors["baseline"] > histograms["baseline"]["invalid_citation"]:
        reasons.append("execution_errors")
    if new["tokens_total"] > TOKEN_LIMIT * old["tokens_total"]:
        reasons.append("token_budget_exceeded")
    if manifest["split"] == "holdout":
        for name, minimum, target in (("answerable", 24, 20), ("unanswerable", 12, 9)):
            n = bins[name]["cases"]
            if n < minimum or bins[name]["all3"]["candidate"] * minimum < target * n:
                reasons.append(f"{name}_holdout_requirement")
    decision = "rejected" if reasons else (
        "eligible_for_holdout" if manifest["split"] == "development" else "confirmed_on_panel"
    )
    if documents is None:
        decision = "unverified"
    return {
        "schema_version": 1, "scoring_version": 2,
        "evidence_status": "verified_provenance_and_quotes" if documents is not None else "diagnostic_only",
        **{k: manifest[k] for k in ("split", "dataset", "model", "index", "trials")},
        "manifest_sha256": digest, "baseline_sha256": hashlib.sha256(payloads[0]).hexdigest(),
        "candidate_sha256": hashlib.sha256(payloads[1]).hexdigest(),
        "baseline_policy": before_id, "candidate_policy": after_id, "eligible": not reasons,
        "decision": decision, "reasons": reasons, "release_certified": False, "bins": bins,
        "budget": {"max_token_ratio": TOKEN_LIMIT, "baseline": old, "candidate": new,
                   "token_ratio": new["tokens_total"] / old["tokens_total"] if old["tokens_total"] else None},
        "errors": errors, "failure_counts": histograms, "development_failures": failures,
        "policy_suggestions": [
            {"reason": reason, "failed_cases": len(ids), "failed_trials": histograms["candidate"][reason],
             "action": NEXT_ACTION[reason]} for reason, ids in sorted(affected.items(), key=lambda v: (-len(v[1]), v[0]))
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("manifest", "baseline", "candidate", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--expected-provenance", type=Path,
                        help="Independently registered index, runner, agent SHA256s and API model ID")
    args = parser.parse_args(argv)
    try:
        if args.output.resolve() in {p.resolve() for p in (args.manifest, args.baseline, args.candidate,
                                                            args.expected_provenance) if p is not None}:
            raise ValueError("Output must be separate from the inputs")
        try:
            registered = json.loads(args.expected_provenance.read_bytes()) if args.expected_provenance else None
            result = evaluate(args.manifest, args.baseline, args.candidate, expected_provenance=registered)
            code = 0 if result["eligible"] else 1
        except (OSError, ValueError, OverflowError) as exc:
            result = {"schema_version": 1, "decision": "invalid", "eligible": False,
                      "release_certified": False, "reasons": [str(exc)]}
            code = 2
        args.output.parent.mkdir(exist_ok=True, parents=True)
        with TemporaryDirectory(dir=args.output.parent) as tmp:
            path = Path(tmp) / "report.json"
            path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            path.replace(args.output)
        return code
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
