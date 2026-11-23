import argparse
import hashlib
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from scripts import rag_growth_local as growth
from scripts.rag_growth_prepare import REVISION


def manifest():
    docs = [
        {"id": "d1", "title": "서울 소설", "content": "서울 소설의 작가는 민수다."},
        {"id": "d2", "title": "도시 지도", "content": "도시 지도를 발간했다."},
    ]
    return {
        "schema_version": 1, "trials": 3, "model": "local-fixture", "index": growth.INDEX_ID,
        "split": "development", "dataset": "public-fixture", "documents": docs,
        "model_sha256": hashlib.sha256(b"fixture").hexdigest(), "corpus_sha256": growth.corpus_sha256(docs),
        "cases": [{"id": "one", "question": "서울 소설의 작가는 누구인가?", "answerable": True,
                   "answers": ["민수"], "source_ids": ["d1"]}],
    }


def test_manifest_binds_order_and_source_ids():
    data = manifest()
    growth.validate_manifest(data)
    data["documents"].reverse()
    with pytest.raises(ValueError, match="corpus_sha256"):
        growth.validate_manifest(data)
    data["documents"].reverse()
    data["cases"][0]["source_ids"] = ["absent"]
    with pytest.raises(ValueError, match="source IDs"):
        growth.validate_manifest(data)


def test_raw_diagnostics_require_pinned_public_development_manifest():
    data = manifest()
    data["cases"][0]["id"] = "klue-mrc-v1_train_12"
    for doc in data["documents"]:
        doc["id"] = hashlib.sha256(doc["content"].encode()).hexdigest()[:20]
    data["dataset"] = f"klue-mrc/{REVISION}/round-1/dev-a"
    assert growth.public_development_diagnostics(data)
    for change in ({"split": "holdout"}, {"dataset": "private"}, {"dataset": f"klue-mrc/{REVISION}/round-1/final"},
                   {"cases": [{"id": "user-conversation"}]}, {"documents": [{"id": "changed", "content": "본문"}]}):
        assert not growth.public_development_diagnostics(data | change)


@pytest.mark.asyncio
async def test_recorder_forwards_calls_and_keeps_only_last_actual_reply():
    raw = "  앞문장\n" + "댓" * 400
    model = SimpleNamespace(generate_text=AsyncMock(side_effect=[raw, "bad verifier", "follow up", OSError("offline")]))
    trace = SimpleNamespace(search_attempts=1)
    recorder = growth.DevelopmentModelRecorder(model, trace, candidate=True)
    assert await recorder.generate_text("sensitive prompt", system_prompt="private instructions") == raw
    model.generate_text.assert_awaited_with("sensitive prompt", system_prompt="private instructions")
    assert recorder.last == {"stage": "document_answer", "call_number": 1, "search_round": 1,
                             "raw_excerpt": raw[:400], "raw_chars": len(raw), "truncated": True,
                             "raw_sha256": hashlib.sha256(raw.encode()).hexdigest()}
    await recorder.generate_text("second")
    assert recorder.last["stage"] == "premise_check" and recorder.last["raw_excerpt"] == "bad verifier"
    trace.search_attempts = 2
    await recorder.generate_text("third")
    assert recorder.last["stage"] == "document_answer" and recorder.last["search_round"] == 2
    with pytest.raises(OSError):
        await recorder.generate_text("fourth")
    assert recorder.last is None


@pytest.mark.asyncio
async def test_failed_public_trial_preserves_model_response_separately_from_product_fallback():
    from app.lib.request_cost import get_current_ledger

    raw = "  EVIDENCE: [S999.1]\nANSWER: 민수  "

    class Model:
        async def generate_text(self, **kwargs):
            get_current_ledger().add(total_tokens=12)
            return raw

    corpus = growth.Corpus(manifest()["documents"])
    for public in (True, False):
        result = await growth.run_trial("작가는?", corpus, Model(), False, public_development=public)
        assert result["status"] == "error" and result["grounding_status"] == "invalid_citation"
        assert result["answer"] == "근거 부족"
        if public:
            assert result["model_diagnostic"]["raw_excerpt"] == raw
        else:
            assert "model_diagnostic" not in result


@pytest.mark.asyncio
async def test_wrong_server_or_model_bytes_fail_before_inference(tmp_path):
    model_file = tmp_path / "local.gguf"
    model_file.write_bytes(b"original")
    replies = {"/props": {"model_path": str(model_file)}, "/v1/models": {"data": [{"id": "alias"}]}}
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json=replies[r.url.path]))
    async with httpx.AsyncClient(base_url="http://127.0.0.1:2001", transport=transport) as client:
        with pytest.raises(ValueError, match="exactly"):
            await growth.verify_server(client, "wrong", model_file, growth.file_sha256(model_file))
        with pytest.raises(ValueError, match="model_sha256"):
            await growth.verify_server(client, "alias", model_file, "a" * 64)
        replies["/props"] = {"model_path": "relative.gguf"}
        with pytest.raises(ValueError, match="model_path"):
            await growth.verify_server(client, "alias", model_file, growth.file_sha256(model_file))


@pytest.mark.parametrize(("status", "answer", "source", "expected"), [
    ("insufficient", "근거 부족", None, "abstained"),
    ("invalid_citation", "근거 부족", None, "error"),
    ("verified_quotes", "홍길동", {"document_id": "d", "cited_sentences": ["후보 밖"]}, "error"),
    ("verified_quotes", "홍길동", {"document_id": "x", "cited_sentences": ["원문"]}, "error"),
    ("verified_quotes", "홍길동", {"document_id": "d", "cited_sentences": ["원문"]}, "answered"),
])
def test_evidence_status_requires_verified_citation(status, answer, source, expected):
    retriever = SimpleNamespace(batches=[["d"]], corpus=SimpleNamespace(docs={"d": {"content": "원문"}}))
    result = SimpleNamespace(success=True, answer=answer, sources=[source] if source else [], grounding_status=status)
    assert growth.classify(result, retriever)[0] == expected


@pytest.mark.asyncio
async def test_paired_cli_runs_real_search_agent_and_accounts_failed_rows(tmp_path, monkeypatch):
    data = manifest()
    source = tmp_path / "manifest.json"
    source.write_text(json.dumps(data, ensure_ascii=False))
    model = tmp_path / "fixture.gguf"
    model.write_bytes(b"fixture")
    args = argparse.Namespace(
        manifest=source, model_file=model, baseline=tmp_path / "base.jsonl", candidate=tmp_path / "cand.jsonl",
        port=2001, baseline_policy="base", candidate_policy="premise", api_model="alias",
    )
    calls = []

    def respond(request):
        assert request.url.host == "127.0.0.1" and request.url.port == 2001
        if request.url.path == "/props":
            return httpx.Response(200, json={"model_path": str(model)})
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": "alias"}]})
        assert request.url.path == "/v1/chat/completions"
        payload = json.loads(request.content)
        assert payload["model"] == "alias" and payload["temperature"] == 0
        calls.append(payload)
        if len(calls) == 2:
            return httpx.Response(503, json={"error": {"message": "test failure"}})
        text = "근거 부족" if len(calls) == 3 else "EVIDENCE: [S1.1]\nANSWER: 민수"
        return httpx.Response(200, json={
            "id": "local", "object": "chat.completion", "created": 1, "model": "alias",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
        })

    monkeypatch.setattr(growth, "local_http_client", lambda origin: httpx.AsyncClient(
        base_url=origin, transport=httpx.MockTransport(respond)
    ))
    await growth.run(args)
    rows = []
    for path, policy in ((args.baseline, "base"), (args.candidate, "premise")):
        arm = [json.loads(line) for line in path.read_text().splitlines()]
        assert [r["trial"] for r in arm] == [1, 2, 3]
        assert all(r["policy"] == policy and r["id"] == "one" for r in arm)
        assert all(r["manifest_sha256"] == growth.file_sha256(source) for r in arm)
        assert all(r["candidate_batches"][0][0] == "d1" for r in arm)
        rows.extend(arm)
    assert len(calls) == 6
    assert sum(r["status"] == "error" for r in rows) == 1
    assert sum(r["status"] == "abstained" for r in rows) == 1
    assert sum(r["status"] == "answered" and r["citations"] == ["d1"] for r in rows) == 4
    assert all(r["cited_evidence"] == [{"document_id": "d1", "quote": "서울 소설의 작가는 민수다."}]
               for r in rows if r["status"] == "answered")
    assert all(len(r["agent_sha256"]) == 64 and len(r["runner_sha256"]) == 64 for r in rows)
    assert sum(r["tokens"] for r in rows) == 5 * 12
    assert all("model_diagnostic" not in r for r in rows)
    with pytest.raises(ValueError, match="distinct, new"):
        await growth.run(args)
