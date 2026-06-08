#!/usr/bin/env python3
"""RAG 전체 파이프라인 e2e 스모크 테스트 (실행 중인 API 서버 대상).

검증 흐름(업로드 → 적재 → 검색 → 리랭킹 → LLM 생성 → SSE 스트리밍):
  1. GET /health, /ready
  2. POST /api/upload (문서 적재)
  3. GET /api/upload/status/{job} 폴링 (completed 대기)
  4. POST /api/chat/stream (문서 내용 질의) → 답변이 문서 내용을 인용하는지 확인

사용법(Docker 불필요, ChromaDB 모드 권장):
    VECTOR_DB_PROVIDER=chroma uv run python -m uvicorn main:app --port 8000 &
    uv run python scripts/e2e_rag_smoke.py

환경변수:
    E2E_BASE_URL   (기본 http://127.0.0.1:8000)
    FASTAPI_AUTH_KEY  (.env에서 로드, 인증 필요 시)

성공 시 종료 코드 0, 실패 시 1.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request

BASE = os.getenv("E2E_BASE_URL", "http://127.0.0.1:8000")
AUTH = os.getenv("FASTAPI_AUTH_KEY", "")

_DOC = (
    'OneRAG 프로젝트의 마스코트 동물은 보라색 수달입니다. '
    '이 수달의 이름은 "라구"이며, 매주 금요일에 코드 리뷰를 담당합니다.'
)
_QUESTION = "OneRAG 마스코트 동물과 그 이름을 알려줘"


def _headers() -> dict[str, str]:
    return {"X-API-Key": AUTH} if AUTH else {}


def _get(path: str) -> dict:
    req = urllib.request.Request(BASE + path, headers=_headers())
    with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310 - 로컬 e2e 전용
        return json.loads(resp.read().decode())


def _upload() -> str:
    boundary = "----onerag-e2e-boundary"
    body = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="file"; filename="e2e_doc.txt"\r\n'
        "Content-Type: text/plain\r\n\r\n"
        f"{_DOC}\r\n"
        f"--{boundary}--\r\n"
    ).encode()
    headers = {**_headers(), "Content-Type": f"multipart/form-data; boundary={boundary}"}
    req = urllib.request.Request(BASE + "/api/upload", data=body, headers=headers)
    with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310
        return str(json.loads(resp.read().decode())["job_id"])


def _wait_ingest(job: str, timeout: float = 60.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = _get(f"/api/upload/status/{job}")
        if status.get("status") == "completed":
            return
        if status.get("status") == "failed":
            raise RuntimeError(f"ingestion failed: {status.get('error_message')}")
        time.sleep(2)
    raise TimeoutError("ingestion did not complete in time")


def _chat() -> tuple[str, dict]:
    payload = json.dumps({"message": _QUESTION}).encode()
    headers = {**_headers(), "Content-Type": "application/json"}
    req = urllib.request.Request(BASE + "/api/chat/stream", data=payload, headers=headers)
    answer = ""
    done: dict = {}
    with urllib.request.urlopen(req, timeout=90) as resp:  # noqa: S310
        for raw in resp:
            line = raw.decode("utf-8").strip()
            if not line.startswith("data:"):
                continue
            try:
                event = json.loads(line[5:].strip())
            except json.JSONDecodeError:
                continue
            if event.get("event") == "chunk":
                answer += str(event.get("data", ""))
            elif event.get("event") == "done":
                done = event.get("data", {})
    return answer, done


def main() -> int:
    print(f"[e2e] base={BASE}")
    health = _get("/health")
    assert health.get("status") == "OK", f"/health unexpected: {health}"
    ready = _get("/ready")
    assert ready.get("status") in {"ready", "degraded"}, f"/ready unexpected: {ready}"
    print(f"[e2e] health=OK ready={ready.get('status')}")

    job = _upload()
    print(f"[e2e] uploaded job={job}")
    _wait_ingest(job)
    print("[e2e] ingestion completed")

    answer, done = _chat()
    print(f"[e2e] answer: {answer}")
    print(f"[e2e] done: search/ranked tokens={done.get('tokens_used')}")

    # 답변이 업로드 문서 내용을 인용하는지 확인 (전체 RAG 파이프라인 검증)
    assert "수달" in answer and "라구" in answer, (
        f"answer did not reference the uploaded document: {answer!r}"
    )
    print("[e2e] PASS: full RAG pipeline returned a grounded LLM answer")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (AssertionError, RuntimeError, TimeoutError, urllib.error.URLError) as exc:
        print(f"[e2e] FAIL: {exc}", file=sys.stderr)
        sys.exit(1)
