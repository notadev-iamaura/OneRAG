import json
from argparse import Namespace
from unittest.mock import AsyncMock, patch

import pytest

from app.modules.core.evaluation.models import EvaluationResult
from scripts.production_corpus_e2e import _evaluate_case, run_production
from scripts.run_eval import load_dataset, run_evaluation


def test_numbers_and_both_citations_are_required():
    case = {
        "id": "limit", "doc_id": "a", "document_filename": "contract.pdf",
        "question": "What is the limit?", "expected_answer": "limit 100 units",
        "expected_answer_contains": ["limit", "100 units"],
        "grading": {"min_expected_terms": 2, "required_terms": ["100 units"],
                    "required_sources": [{"filename": "contract.pdf"}, {"filename": "appendix.pdf", "page": 3}]},
    }
    sources = [{"document_name": "contract.pdf"}, {"document_name": "appendix.pdf", "page": 3}]
    def grade(answer, evidence):
        return _evaluate_case(case, {"answer": answer, "sources": evidence}, "job-example")["verdict"]
    assert grade("Limit 100 units", sources) == "PASS"
    assert grade("Limit 400 units", sources) == "FAIL"
    assert grade("Limit 1100 units", sources) == "FAIL"
    assert grade("100 entries; limit 1100 units", sources) == "FAIL"
    assert grade("Limit -100 units", sources) == "FAIL"
    assert grade("Limit 100 units", sources[:1]) == "FAIL"
    assert grade("Limit 100 units", [{"document_name": "old-contract.pdf"}, sources[1]]) == "FAIL"
    assert grade("Limit 100 units", [sources[0], dict(sources[1], page=4)]) == "FAIL"
    case["grading"] = {"required_sources": [{"filename": "contract.pdf", "contains": ["100 units"]}]}
    assert grade("Limit 100 units", [dict(sources[0], content_preview="limit 400 units")]) == "FAIL"
    correct_source = [dict(sources[0], content_preview="limit 100 units")]
    assert grade("Limit 400 units", correct_source) == "FAIL"
    assert grade("Limit 100 units", correct_source) == "PASS"
    assert _evaluate_case(case, {
        "answer": "Limit 100 units", "sources": correct_source, "cited_sources": [],
    }, None)["verdict"] == "FAIL"


def test_agent_runner_counts_fallback_as_error_and_reuses_followup_session(tmp_path, monkeypatch):
    cases = [
        {"id": name, "doc_id": name, "question": name, "expected_answer": "100 units",
         "document_filename": "contract.md", "session_group": "contract"}
        for name in ("first", "followup")
    ]
    golden = tmp_path / "golden.json"
    golden.write_text(json.dumps({"cases": cases}))
    create_session = patch("scripts.production_corpus_e2e._create_session", return_value="shared")

    def answer(_client, _url, session, question, _key, *, use_agent):
        assert session == "shared" and use_agent
        metadata = {"mode": "agent", "stop_reason": "completed"} if question == "first" else {}
        return {"answer": "100 units", "sources": [{"document": "contract.md"}],
                "metadata": metadata, "tokens_used": 20}

    monkeypatch.setattr("scripts.production_corpus_e2e._chat_answer", answer)
    with create_session as create:
        summary = run_production(Namespace(
            corpus_dir=tmp_path, golden=golden, output_dir=tmp_path / "results",
            backend_url="http://test", api_key_env=None, skip_upload=True,
            skip_qa=False, case_limit=0, use_agent=True,
        ))
    create.assert_called_once()
    assert summary["qa_cases_run"] == 2 and summary["qa_pass"] == 1
    assert summary["joint_accuracy"] == 0.5 and summary["tokens_per_pass"] == 40
    assert summary["p95_request_seconds"] >= 0 and not summary["success"]
    rows = json.loads((tmp_path / "results" / "qa_results.json").read_text())
    assert rows[0]["stop_reason"] == "completed"
    assert rows[1]["verdict"] == "ERROR"


def test_failed_session_and_chat_still_count_all_expected_abstentions(tmp_path):
    cases = [
        {"id": str(i), "doc_id": "a", "document_filename": "a.md", "question": f"missing fact {i}?",
         "grading": {"expected_outcome": "abstain"}}
        for i in range(3)
    ]
    golden = tmp_path / "golden.json"
    golden.write_text(json.dumps({"cases": cases}))
    args = Namespace(corpus_dir=tmp_path, golden=golden, output_dir=tmp_path / "results",
                     backend_url="http://test", api_key_env=None, skip_upload=True,
                     skip_qa=False, case_limit=0, use_agent=True)
    refusal = {"answer": "근거 부족", "cited_sources": [], "metadata": {"mode": "agent", "grounding_status": "insufficient"}}
    with (
        patch("scripts.production_corpus_e2e._create_session", side_effect=[TimeoutError(), "session"]),
        patch("scripts.production_corpus_e2e._chat_answer", side_effect=[TimeoutError(), refusal]),
    ):
        summary = run_production(args)
    assert summary["expected_abstentions"] == summary["qa_cases_run"] == 3
    assert summary["correct_abstentions"] == summary["qa_pass"] == 1
    assert summary["qa_fail_or_error"] == 2 and not summary["success"]


@pytest.mark.parametrize(("status","expected"),[
    ("insufficient","PASS"),("invalid_citation","FAIL"),("error","FAIL"),(None,"FAIL"),
])
def test_abstention_requires_verified_outcome(status, expected):
    case = {"id":"absent","doc_id":"A","question":"q","document_filename":"a",
            "grading":{"expected_outcome":"abstain"}}
    payload = {"answer":"근거 부족","sources":[],"metadata":{"grounding_status":status}}
    assert _evaluate_case(case,payload,None)["verdict"] == expected


@pytest.mark.asyncio
async def test_missing_and_empty_dataset_are_execution_errors(tmp_path):
    path = tmp_path / "eval.json"
    with pytest.raises(FileNotFoundError):
        await load_dataset(str(path))
    path.write_text("[]")
    with pytest.raises(ValueError):
        await load_dataset(str(path))
    path.write_text(json.dumps([{"query": "q", "answer": "a", "context": "evidence"}]))
    assert (await load_dataset(str(path)))[0]["context"] == ["evidence"]


@pytest.mark.asyncio
async def test_unscored_fallback_cannot_pass_a_low_threshold():
    evaluator = AsyncMock()
    evaluator.is_available = lambda: True
    samples = [{"query": "q", "answer": "a", "context": ["evidence"]}]
    with patch("app.lib.config_loader.load_config", return_value={}), patch(
        "app.core.di_container.create_evaluator_instance", new=AsyncMock(return_value=evaluator)
    ):
        evaluator.batch_evaluate.return_value = [EvaluationResult(0.5, 0.5, 0.5)]
        with pytest.raises(RuntimeError, match="유효한 채점"):
            await run_evaluation(samples, provider="ragas", threshold=0.1)
        evaluator.batch_evaluate.return_value = [
            EvaluationResult(0.5, 0.5, 0.5, raw_scores={"faithfulness": 0.5, "answer_relevancy": 0.5})
        ]
        assert (await run_evaluation(samples, provider="ragas", threshold=0.5))["passed"]
