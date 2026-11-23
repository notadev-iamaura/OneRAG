import hashlib
import json
from pathlib import Path

import httpx
import pytest

from scripts.rag_evidence_klue_record import CompletionTrace


@pytest.mark.asyncio
async def test_traces_original_messages_and_finish_without_headers(tmp_path: Path) -> None:
    tracer = CompletionTrace(tmp_path, [(2, "candidate", "q3")])
    request_seen: list[bytes] = []
    reply = {"choices": [{"index": 0, "message": {"content": "[1.2] 부산"}, "finish_reason": "stop"}],
             "usage": {"prompt_tokens": 21, "completion_tokens": 6}}

    def local(request: httpx.Request) -> httpx.Response:
        request_seen.append(request.content)
        return httpx.Response(200, json=reply)

    messages = [{"role": "user", "content": "문서 1 [1.2] 부산에서 열렸다."}]
    hooks = {"request": [tracer.request], "response": [tracer.response]}
    async with httpx.AsyncClient(transport=httpx.MockTransport(local), event_hooks=hooks) as client:
        response = await client.post("http://127.0.0.1/v1/chat/completions",
                                     headers={"x-test-header": "omit-this-header"},
                                     json={"model": "local", "temperature": 0, "messages": messages})
    assert response.json() == reply
    assert len(request_seen) == tracer.sent == tracer.received == 1
    sent = json.loads((tmp_path / "0002-candidate.request.json").read_bytes())
    received = json.loads((tmp_path / "0002-candidate.response.json").read_bytes())
    assert sent["request"]["messages"] == messages
    assert sent["request_sha256"] == hashlib.sha256(request_seen[0]).hexdigest()
    assert received["id"] == "q3" and received["arm"] == "candidate"
    assert received["choices"][0]["content"] == "[1.2] 부산"
    assert received["choices"][0]["finish_reason"] == "stop"
    assert all("omit-this-header" not in p.read_text() for p in tmp_path.iterdir())
