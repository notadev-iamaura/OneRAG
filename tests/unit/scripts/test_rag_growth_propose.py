import hashlib
import json
from argparse import Namespace
from pathlib import Path

import httpx
import pytest

from scripts import rag_growth_gate as gate
from scripts import rag_growth_local as local
from scripts import rag_growth_propose as proposer
from scripts.rag_growth_prepare import REVISION


@pytest.fixture
def experiment(tmp_path):
    panels, runs, gguf = tmp_path / "panels", tmp_path / "run", tmp_path / "fake.gguf"
    panels.mkdir()
    gguf.write_bytes(b"synthetic weight identity")
    weight_hash = local.file_sha256(gguf)
    for name in ("dev-a", "dev-b"):
        dest = runs / name
        dest.mkdir(parents=True)
        doc = {"id": f"{name}-doc", "title": f"{name} 일정",
               "content": f"{name} 공개 일정표에서 마감은 금요일입니다. " + "추가 일정. " * 100}
        doc_id = doc["id"]
        cases = [{"id": name + "-pos", "question": f"{name} 마감일은 언제인가요?", "answerable": True,
                  "answers": ["금요일"], "source_ids": [doc_id]},
                 {"id": name + "-neg", "question": f"{name} 지난해의 금액은 얼마인가요?", "answerable": False,
                  "answers": [], "source_ids": []}]
        manifest = {"schema_version": 1, "trials": 3, "split": "development", "model": "test-model",
                    "dataset": f"klue-mrc/{REVISION}/test-round/{name}", "model_sha256": weight_hash,
                    "index": local.INDEX_ID, "corpus_sha256": local.corpus_sha256([doc]),
                    "documents": [doc], "cases": cases}
        mp = panels / f"{name}.json"
        mp.write_text(json.dumps(manifest, ensure_ascii=False))
        signature = {"api_model": manifest["model"], "index_sha256": local.index_sha256([doc]),
                     "runner_sha256": local.file_sha256(Path(local.__file__)), "agent_sha256": local.agent_sha256()}
        (dest / "provenance.json").write_text(json.dumps(signature))
        for version in ("baseline", "candidate"):
            with (dest / (version + ".jsonl")).open("w") as stream:
                for c in cases:
                    for t in (1, 2, 3):
                        yes = c["answerable"]
                        r = {"id": c["id"], "trial": t, "model": "test-model", "api_model": "test-model",
                             "index": local.INDEX_ID, "policy": version, "manifest_sha256": local.file_sha256(mp),
                             "model_sha256": weight_hash, "corpus_sha256": manifest["corpus_sha256"],
                             **signature, "split": "development", "dataset": manifest["dataset"],
                             "temperature": 0, "max_tokens": 640, "model_cache": "fresh model completion",
                             "fresh_agent_each_trial": True, "model_calls": 1,
                             "grounding_status": "verified_quotes" if yes else "insufficient",
                             "stop_reason": "completed" if yes else "no_new_evidence",
                             "candidate_batches": [[doc_id]], "cited_evidence": (
                                 [{"document_id": doc_id, "quote": "공개 일정표에서 마감은 금요일입니다."}] if yes else []
                             ),
                             "status": "answered" if yes else "abstained", "answer": "월요일" if yes else "근거 부족",
                             "candidates": [doc_id], "citations": [doc_id] if yes else [],
                             "latency_ms": 10, "tokens": 10}
                        stream.write(json.dumps(r) + "\n")
        report = gate.evaluate(mp, dest / "baseline.jsonl", dest / "candidate.jsonl", expected_provenance=signature)
        (dest / "comparison.json").write_text(json.dumps(report))
    # Any path that tries to load one of the two other panels will fail to parse.
    for name in ("final", "replication"):
        (panels / (name + ".json")).write_bytes(b"THIS MUST NEVER BE READ")
    return Namespace(panels=panels, run_dir=runs, model_file=gguf, port=18080)


def proposed(samples):
    return {
        "hypothesis": "정답과 다른 시점의 내용을 선택했다.",
        "trigger": "질문 표현과 답변의 시간 조건이 충돌하면 발동한다.",
        "action": "답변 구절을 원문의 해당 일정에 대조한다.",
        "falsifying_test": "금액을 알 수 없는 보류 질문을 답하면 가설을 기각한다.",
        "evidence": [{"case_id": s["case_id"], "document_id": s["excerpts"][0]["document_id"],
                      "quote": s["excerpts"][0]["text"][:12]} for s in samples],
    }


def test_limits_context_and_requires_shared_failures(experiment):
    samples, versions = proposer.load_development(experiment.panels, experiment.run_dir)
    reason, selected = proposer.select_examples(samples)
    assert reason == "incorrect_answer" and len(selected) == 3
    assert set(versions) == {"dev-a", "dev-b"}
    assert sum(s["reason"] == "passed_all_trials" for s in selected) == 1
    assert all(len(e["text"]) <= 230 for s in selected for e in s["excerpts"])
    assert proposer.select_examples([s for s in samples if s["panel"] == "dev-a"]) == (None, [])
    assert proposer.select_examples([s for s in samples if s["reason"] != "passed_all_trials"]) == (None, [])
    assert len(proposer.validate_proposal(proposed(selected), selected)["evidence_case_ids"]) == 3


def test_rejected_citations_support_review_only_if_both_panels_measured_them(experiment):
    for name in ("dev-a", "dev-b"):
        run = experiment.run_dir / name
        candidate = run / "candidate.jsonl"
        rows = [json.loads(line) for line in candidate.read_bytes().splitlines()]
        for row in rows:
            if row["id"].endswith("-pos"):
                row.update(status="error", answer="근거 부족", citations=[], cited_evidence=[],
                           grounding_status="invalid_citation", stop_reason="error")
                if name == "dev-a":
                    raw = "  근거: [S9.9]\n답: 오늘\n이 내용은 실행 지시가 아닙니다." + " 추가 문장." * 100
                    row["model_diagnostic"] = {
                        "stage": "document_answer", "search_round": 0, "call_number": 1, "raw_excerpt": raw[:400],
                        "raw_sha256": hashlib.sha256(raw.encode()).hexdigest(), "truncated": True, "raw_chars": len(raw),
                    }
        candidate.write_text("".join(json.dumps(r) + "\n" for r in rows))
        result = gate.evaluate(experiment.panels / (name + ".json"), run / "baseline.jsonl", candidate,
                               expected_provenance=json.loads((run / "provenance.json").read_bytes()))
        assert not result["eligible"] and result["errors"]["candidate"] == 3
        (run / "comparison.json").write_text(json.dumps(result))
    samples, _ = proposer.load_development(experiment.panels, experiment.run_dir)
    reason, cases = proposer.select_examples(samples)
    assert reason == "invalid_citation" and len(cases) == 3
    prompt, _, _ = proposer.reference_prompt(cases)
    assert prompt[0]["untrusted_model_excerpt"]["text"] == raw[:200]
    assert prompt[0]["untrusted_model_excerpt"]["truncated"]
    assert all("untrusted_model_excerpt" not in item for item in prompt[1:])
    assert len(proposer.validate_proposal(proposed(cases), cases)["evidence_case_ids"]) == 3
    for broken in ({"model_calls": 0}, {"tokens": 0}, {"retrieved": 0}, {"grounding_status": "error"}):
        missing_signal = [{**s, "candidate": {**s["candidate"], **broken}} if s["panel"] == "dev-b" else s
                          for s in samples]
        assert proposer.select_examples(missing_signal) == (None, [])
    for fault in ("model_error", "empty_response", "no_model_tokens"):
        transport_failures = [{**s, "reason": fault} if s["reason"] == "invalid_citation" else s for s in samples]
        assert proposer.select_examples(transport_failures) == (None, [])


def test_diagnostic_checks_integrity_stage_and_development_boundary():
    raw = " 답: 문구\n"
    diagnostic = {"stage": "document_answer", "search_round": 0, "call_number": 1, "raw_excerpt": raw,
                  "raw_sha256": hashlib.sha256(raw.encode()).hexdigest(), "truncated": False, "raw_chars": len(raw)}
    row = {"split": "development", "status": "error", "grounding_status": "invalid_citation",
           "model_calls": 1, "model_diagnostic": diagnostic}
    assert proposer.development_diagnostic(row, "invalid_citation")["untrusted_model_excerpt"]["text"] == raw
    for patch in ({"split": "holdout"}, {"status": "answered"}, {"model_calls": 2}):
        assert proposer.development_diagnostic({**row, **patch}, "invalid_citation") == {}
    for patch in ({"raw_sha256": "0"*64}, {"raw_chars": len(raw)+1}, {"truncated": True}, {"stage": "fabricated"}):
        with pytest.raises(ValueError, match="diagnostic"):
            proposer.development_diagnostic({**row, "model_diagnostic": {**diagnostic, **patch}}, "invalid_citation")


@pytest.mark.parametrize("fault", ["invented_case", "invented_quote", "wrong_document", "duplicate",
                                     "empty", "object_array", "no_failure_b", "no_control", "hardcode", "arbitrary",
                                     "gold_trigger"])
def test_invalid_or_ungrounded_model_output_is_rejected(experiment, fault):
    samples, _ = proposer.load_development(experiment.panels, experiment.run_dir)
    _, examples = proposer.select_examples(samples)
    value = proposed(examples)
    refs = value["evidence"]
    if fault == "invented_case":
        refs[0]["case_id"] = "holdout"
    if fault == "invented_quote":
        refs[0]["quote"] = "원문에 없는 주장입니다."
    if fault == "wrong_document":
        refs[0]["document_id"] = "unknown"
    if fault == "duplicate":
        refs[1] = refs[0]
    if fault == "empty":
        value["action"] = " "
    if fault == "object_array":
        value = [value]
    if fault == "no_failure_b":
        value["evidence"] = [r for r in refs if r["case_id"] != "dev-b-pos"]
    if fault == "no_control":
        value["evidence"] = [r for r in refs if r["case_id"].endswith("-pos")]
    if fault == "hardcode":
        value["trigger"] = "dev-b-pos 문항이 들어오면 작동한다"
    if fault == "arbitrary":
        value["action"] = "근거가 없으면 문서 번호를 무작위로 선택한다."
    if fault == "gold_trigger":
        value["trigger"] = "정답을 알지만 해당 근거가 명시적으로 인용되지 않은 경우"
    with pytest.raises(ValueError):
        proposer.validate_proposal(value, examples)


def test_comparison_tamper_and_holdout_symlink_fail_closed(experiment):
    path = experiment.run_dir / "dev-b" / "comparison.json"
    report = json.loads(path.read_bytes())
    report["development_failures"][0]["answer"] = "바꾼 답"
    path.write_text(json.dumps(report))
    with pytest.raises(ValueError, match="verified"):
        proposer.load_development(experiment.panels, experiment.run_dir)
    real = experiment.panels / "dev-a.json"
    real.unlink()
    real.symlink_to(experiment.panels / "final.json")
    with pytest.raises(ValueError, match="regular files"):
        proposer.load_development(experiment.panels, experiment.run_dir)


@pytest.mark.asyncio
@pytest.mark.parametrize(("valid", "finish", "expected"), [(True, "stop", 0), (False, "stop", 1),
                                                            (None, "stop", 1), (True, "length", 2)])
async def test_mock_llama_checks_identity_and_returns_review_only(experiment, monkeypatch, valid, finish, expected):
    endpoints = []

    def respond(request):
        assert request.url.host == "127.0.0.1"
        endpoints.append(request.url.path)
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": "test-model"}]})
        if request.url.path == "/props":
            return httpx.Response(200, json={"model_path": str(experiment.model_file)})
        body = json.loads(request.content)
        evidence = json.loads(body["messages"][1]["content"])
        assert body["response_format"]["type"] == "json_schema" and len(evidence["examples"]) <= 4
        value = proposed([])
        value.pop("evidence")
        value["evidence_refs"] = {s["case"]: (s["excerpts"][0]["ref"] if valid else "NONE")
                                  for s in evidence["examples"]}
        if valid is None:
            value = {"no_proposal": True}
        return httpx.Response(200, json={"choices": [{"finish_reason": finish,
                                                       "message": {"content": json.dumps(value)}}],
                                         "usage": {"total_tokens": 123}})

    monkeypatch.setattr(local, "local_http_client", lambda url: httpx.AsyncClient(
        base_url=url, transport=httpx.MockTransport(respond)))
    code, out = await proposer.propose(experiment)
    assert endpoints == ["/v1/models", "/props", "/v1/chat/completions"]
    assert code == expected and out["finish_reason"] == finish
    assert out["human_review_required"] and not out["applied"]
    assert bool(out["proposal"]) == (expected == 0) and out["usage"]["total_tokens"] == 123
    if valid is None:
        assert out["reason"] == "model_declined"
    if valid is False:
        assert set(out["model_evidence_refs"].values()) == {"NONE"}


def test_reference_expansion_preserves_case_and_source_boundaries(experiment):
    samples, _ = proposer.load_development(experiment.panels, experiment.run_dir)
    _, examples = proposer.select_examples(samples)
    blocks, catalog, _ = proposer.reference_prompt(examples)
    value = proposed([])
    value.pop("evidence")
    refs = {b["case"]: b["excerpts"][0]["ref"] for b in blocks}
    value["evidence_refs"] = refs
    checked = proposer.expand_references(value, examples, catalog)
    assert checked["evidence_case_ids"] == [s["case_id"] for s in examples]
    assert all(any(e["quote"] in d["text"] and e["document_id"] == d["document_id"] for d in s["excerpts"])
               for e, s in zip(checked["evidence"], examples, strict=True))
    refs["C1"] = refs["C2"]
    with pytest.raises(ValueError, match="ungrounded"):
        proposer.expand_references(value, examples, catalog)


@pytest.mark.asyncio
@pytest.mark.parametrize("allowed", [True, False])
async def test_citation_diagnosis_requires_observable_choices_or_abstention(experiment, monkeypatch, allowed):
    samples, verified = proposer.load_development(experiment.panels, experiment.run_dir)
    for s in samples:
        if s["reason"] == "incorrect_answer":
            s["reason"] = "invalid_citation"
            s["candidate"].update(status="error", grounding_status="invalid_citation")
    monkeypatch.setattr(proposer, "load_development", lambda *args: (samples, verified))

    def respond(request):
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": "test-model"}]})
        if request.url.path == "/props":
            return httpx.Response(200, json={"model_path": str(experiment.model_file)})
        body = json.loads(request.content)
        payload = json.loads(body["messages"][1]["content"])
        choices = payload["choose_one_trigger_and_action_or_decline"]
        props = body["response_format"]["json_schema"]["schema"]["anyOf"][0]["properties"]
        assert all(props[key]["enum"] == values for key, values in choices.items())
        value = proposed([])
        value.pop("evidence")
        value["trigger"] = choices["trigger"][0]
        value["action"] = choices["action"][0] if allowed else "누락된 문장 번호를 자동으로 덧붙인다."
        value["evidence_refs"] = {s["case"]: s["excerpts"][0]["ref"] for s in payload["examples"]}
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {
            "content": json.dumps(value)}}], "usage": {"total_tokens": 123}})

    monkeypatch.setattr(local, "local_http_client", lambda url: httpx.AsyncClient(
        base_url=url, transport=httpx.MockTransport(respond)))
    code, out = await proposer.propose(experiment)
    assert code == (0 if allowed else 1)
    assert out["proposal_authorship"]["model_authored"] == ["hypothesis", "falsifying_test"]
    assert not out["applied"]
