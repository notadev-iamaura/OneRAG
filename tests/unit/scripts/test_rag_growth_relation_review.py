import argparse
import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from scripts import rag_growth_relation_review as runner


@pytest.mark.asyncio
async def test_offline_experiment_preserves_error_and_scores_second_document(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    docs = [{"id": "a", "title": "소식", "content": "행사가 있었다."},
            {"id": "b", "title": "접수처", "content": "내일팀은 접수처다."}]
    qs = [{"id": k, "question": q} for k, q in (("one", "어느 팀이 접수처인가?"), ("two", "언제 끝났나?"),
                                                ("three", "언제였나?"))]
    base = {q["id"]: {"id": q["id"], "retrieved": ["a"], "status": "abstained"} for q in qs}
    base["three"].update(status="error")
    spans = {k: {"retrieved": ["a", "b"], "spans": [
        {"source_id": "a", "answer": "행사", "start": 0, "end": 2},
        {"source_id": "b", "answer": "내일팀", "start": 0, "end": 3}]} for k in base}
    labels = [{"id": "one", "source_id": "b", "answerable": True, "answers": ["내일팀"],
               "spans": [{"start": 0, "end": 3, "text": "내일팀"}]},
              *[{"id": k, "source_id": "b", "answerable": False, "answers": [], "spans": []}
                for k in ("two", "three")]]
    (tmp_path / "dev.labels.json").write_text(json.dumps(labels))
    (tmp_path / "reservation.json").write_text('{"seed":37}')
    monkeypatch.setattr(runner, "PANELS", tmp_path)
    monkeypatch.setattr(runner, "load_inputs", lambda: (qs, base, spans, dict.fromkeys(base, ["a", "b"]), docs))
    async def verified(*args: Any) -> None:
        pass
    monkeypatch.setattr(runner, "verify_server", verified)
    calls = []
    def handler(request: httpx.Request) -> httpx.Response:
        data = json.loads(request.content)
        case = json.loads(data["messages"][1]["content"])
        assert set(case) == {"질문", "검색 자료"} and data["temperature"] == 0
        calls.append(case["질문"])
        response = {"a": "내일팀", "s": 2, "e": 2} if len(calls) == 1 else {"a": "", "s": 0, "e": 0}
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop",
                              "message": {"content": json.dumps(response)}}], "usage": {"completion_tokens": 11}})
    monkeypatch.setattr(runner, "local_http_client", lambda origin: httpx.AsyncClient(
        base_url=origin, transport=httpx.MockTransport(handler)))
    args = argparse.Namespace(out=tmp_path, model_file=tmp_path / "dummy", model_sha256="f"*64,
                              port=19000, model_name="local")
    await runner.run(args, {"seed": 37})
    result = json.loads((tmp_path / "metrics.json").read_bytes())
    assert result["summary"]["answerable"]["correct"] == 1
    assert result["summary"]["statuses"] == {"answered": 1, "abstained": 1, "error": 1}
    assert result["fresh_calls"] == len(calls) == 2
    assert result["reported_completion_tokens"] == 22
    assert result["rows"][-1]["route"] == "upstream_error"
    with pytest.raises(ValueError, match="already exists"):
        await runner.run(args, {"seed": 37})
