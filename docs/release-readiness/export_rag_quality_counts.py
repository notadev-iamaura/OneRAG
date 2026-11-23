"""Export aggregate counts from completed local score receipts. Uses only the standard library."""

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def compact(summary: dict[str, Any]) -> dict[str, int]:
    pos, neg = summary["answerable"], summary["unanswerable"]
    statuses = summary["statuses"]
    n = pos["n"]
    if neg["n"] != n or sum(statuses.values()) != 2 * n:
        raise ValueError("Invalid balanced-panel denominator")
    displayed = statuses.get("answered", 0)
    if summary["answered_precision"]["n"] != displayed or summary["answered_precision"]["correct"] != pos["correct"]:
        raise ValueError("Displayed-answer denominator or numerator differs")
    return {
        "per_stratum": n,
        "grounded_answers": pos["correct"],
        "correct_abstentions": neg["correct"],
        "positive_reference_retrieved": summary["answerable_reference_retrieved"]["correct"],
        "answers_displayed": displayed,
        "answers_displayed_on_negatives": displayed - summary["answerable_answered"]["correct"],
        "errors": statuses.get("error", 0),
    }


def build(output: Path) -> dict[str, Any]:
    checksums: dict[str, str] = {}

    def read(name: str) -> dict[str, Any]:
        contents = (output / name).read_bytes()
        checksums[name] = hashlib.sha256(contents).hexdigest()
        parsed = json.loads(contents)
        if not isinstance(parsed, dict):
            raise ValueError(f"Expected a score receipt object: {name}")
        return parsed

    reports = {
        "klue_1": ("release-check/first160/report.json", "candidate", "retrospective"),
        "klue_2": ("release-check/second64/report.json", "candidate", "retrospective"),
        "klue_3": ("release-check/third160/report.json", "candidate", "registered_before_scores"),
        "tydi_1": ("paired-trials/tydi/score.json", "control", "independent"),
        "tydi_2": ("paired-trials/tydi-replication/score.json", "control", "independent"),
    }
    latest = {}
    for key, (receipt_name, retained, scope) in reports.items():
        report = read("rag-evidence-selection/" + receipt_name)
        latest[key] = {
            "scope": scope,
            "retained": retained,
            "control": compact(report["summaries"]["control"]),
            "candidate": compact(report["summaries"]["candidate"]),
        }

    audit = read("rag-growth-03/openai-luna-klue24/audit.json")
    screen = read("rag-growth-03/openai-luna-klue24/screen-report.json")
    if audit["sources"]["luna_report_sha256"] != checksums["rag-growth-03/openai-luna-klue24/screen-report.json"]:
        raise ValueError("Audit and product receipt disagree")
    if audit["layers"]["product"]["summary"]["luna"] != screen["openai_summary"]:
        raise ValueError("Product and independently regraded counts differ")
    label_bytes = (output / "rag-growth-03/panels/dev.labels.json").read_bytes()
    if hashlib.sha256(label_bytes).hexdigest() != audit["sources"]["shared_dev_files"]["dev.labels.json"]:
        raise ValueError("Development labels differ from the audited source")
    labels = json.loads(label_bytes)
    by_id = {label["id"]: label for label in labels}
    rows = screen["product_rows"]
    if len(rows) != 24 or len({row["id"] for row in rows}) != 24:
        raise ValueError("Expected 24 distinct development cases")
    if not all(len(row["tool_retrieved"]) == 8 and row["tool_retrieved"][:1] == row["retrieved"] for row in rows):
        raise ValueError("Unexpected retrieval depth or order")
    positive_rows = [row for row in rows if by_id[row["id"]]["answerable"]]
    if len(positive_rows) != 12:
        raise ValueError("Expected 12 answerable development cases")
    tool_hits = sum(by_id[row["id"]]["source_id"] in row["tool_retrieved"] for row in positive_rows)
    layers = {
        layer: {arm: compact(audit["layers"][layer]["summary"][arm]) for arm in ("qwen", "gpt54", "luna")}
        for layer in ("product", "raw_first_literal", "raw_source_occurrence")
    }
    prefix = "rag-growth-03/openai-luna-klue24/"
    plan = read(prefix + "protocol.json")
    registered_ids = plan["screen_ids"]
    ids_sha = hashlib.sha256(json.dumps(registered_ids, separators=(",", ":")).encode()).hexdigest()
    if len(registered_ids) != 24 or set(registered_ids) != {row["id"] for row in rows}:
        raise ValueError("Responses differ from the registered development panel")
    luna = read(prefix + "current-policy-replay.json")
    qwen = read(prefix + "current-qwen-policy-replay.json")
    if (luna["same_panel_ids_sha256"] != ids_sha or qwen["panel_ids_sha256"] != ids_sha
            or qwen["source_sha256"]["luna_current_replay"] != checksums[prefix + "current-policy-replay.json"]):
        raise ValueError("Replay panels or paired replay receipts differ")
    if (luna["same_question_source_prompt_verified"] != 24 or luna["old_rows_matching_status_answer_source_quote_offsets"] != 24
            or qwen["system_user_messages_match_luna_prompt_digest"] != 24 or qwen["original_identical_spans_and_status"] != 24
            or qwen["recorded_completed_qwen_responses"] != 24):
        raise ValueError("Unable to reconstruct the original responses and prompts")
    replay = {}
    for arm, receipt in (("luna", luna), ("qwen", qwen)):
        now, old = receipt["current"], receipt["old"]
        published = layers["product"][arm]
        if (old["answerable"] != [published["grounded_answers"], 12]
                or old["unanswerable"] != [published["correct_abstentions"], 12]
                or now["answerable"][1] != 12 or now["unanswerable"][1] != 12
                or receipt["cases"] != 24 or sum(now["statuses"].values()) != 24
                or now["errors"] != now["statuses"].get("error", 0) or receipt["real_model_calls"] != 0):
            raise ValueError("Replay does not match the original product or panel denominator")
        replay[arm] = {
            "cases": receipt["cases"], "per_stratum": 12, "real_model_calls": receipt["real_model_calls"],
            "grounded_answers": now["answerable"][0], "correct_abstentions": now["unanswerable"][0],
            "answers_displayed": now["statuses"]["answered"], "errors": now["errors"],
        }
    suite = read("rag-growth-03/public-suite-result.json")
    panels = {
        key: {"per_stratum": row["answerable"]["n"], "grounded_answers": row["answerable"]["correct"],
              "correct_abstentions": row["unanswerable"]["correct"], "errors": len(row["errors"])}
        for key, row in suite["panels"].items()
    }
    return {
        "schema_version": 1,
        "korean_policy_comparisons": latest,
        "reused_klue_development": {"positive_tool_top8_hits": tool_hits, "layers": layers,
                                   "offline_current_policy_replay": replay},
        "earlier_bilingual_suite": {"passed": suite["passed"], "panels": panels},
        "local_score_receipts_sha256": checksums,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", required=True, type=Path, help="Directory of the preserved local runs")
    parser.add_argument("--check", type=Path, help="Compare with a published JSON file")
    args = parser.parse_args()
    report = build(args.source_root)
    if args.check:
        if report != json.loads(args.check.read_text(encoding="utf-8")):
            parser.exit(1, "Counts or source receipt checksums differ.\n")
    else:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
