#!/usr/bin/env python3
"""동시 /chat 부하 스모크 테스트 (실행 중인 API 서버 대상).

N개의 동시 요청을 /chat에 발사하고, 각 요청마다 아래 게이트를 적용한다:
  - 지연 임계치(--threshold-seconds) 초과 여부
  - 검색 소스 존재 여부(sources 비어 있으면 실패)
  - 폴백 답변 마커 포함 여부(--fallback-marker, 지정 시에만 게이트)
  - 기대 용어 포함 여부(--expect-term)

순차 e2e로는 잡지 못하는 동시 부하 회귀(폴백 답변 양산, 지연 폭증)를
운영/CI에서 진단하기 위한 도구다.

사용법(라이브 서버 필요):
    uv run python scripts/chat_concurrency_smoke.py \
        --backend-url http://localhost:8000 \
        --question "RAG란 무엇인가요?" \
        --concurrency 10 --threshold-seconds 10

인증:
    --api-key-file 또는 환경변수 FASTAPI_AUTH_KEY가 있으면 X-API-Key 헤더를 구성한다.
    (e2e_rag_smoke.py와 동일 규약)

출력/종료 코드:
    결과를 JSON으로 stdout에 출력하고, 모든 요청이 통과하면 0, 아니면 1을 반환한다.

원본 대비 일반화:
    - 멀티테넌트 전용 company_id 제거(/chat 바디는 {"message": ...}만 필수).
    - 하드코딩 FALLBACK_MARKERS 제거 → --fallback-marker로 외부화.
    - async 경로 생략(KISS), ThreadPoolExecutor 동기 경로만 채택.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import httpx


@dataclass
class ChatProbe:
    """단일 동시 요청 1건의 측정/판정 결과."""

    index: int
    status_code: int
    elapsed_seconds: float
    source_count: int
    answer_excerpt: str
    passed: bool
    failures: list[str]


def _resolve_api_key(api_key_file: str | None) -> str | None:
    """API 키를 파일(--api-key-file) 또는 환경변수(FASTAPI_AUTH_KEY)에서 해석한다."""
    if api_key_file:
        value = Path(api_key_file).read_text(encoding="utf-8").strip()
        return value or None
    env_value = os.getenv("FASTAPI_AUTH_KEY", "").strip()
    return env_value or None


def _probe_sync(
    client: httpx.Client,
    *,
    backend_url: str,
    question: str,
    expect_terms: list[str],
    fallback_markers: list[str],
    threshold_seconds: float,
    index: int,
    headers: dict[str, str],
) -> ChatProbe:
    """동기 클라이언트로 /chat 요청 1건을 보내고 게이트를 적용한다."""
    started = time.monotonic()
    failures: list[str] = []
    payload: dict[str, Any] = {}
    status_code = 0
    try:
        response = client.post(
            f"{backend_url}/api/chat",
            headers=headers,
            json={"message": question},
        )
        status_code = response.status_code
        if response.status_code == 200:
            payload = response.json()
        else:
            failures.append(f"http_status={response.status_code}")
    except Exception as error:  # noqa: BLE001 - 진단 도구: 모든 요청 오류를 실패로 집계
        failures.append(f"request_error={type(error).__name__}: {error}")

    elapsed = round(time.monotonic() - started, 2)
    answer = str(payload.get("answer") or "")
    sources = payload.get("sources") or []

    # 게이트 1: 지연 임계치
    if elapsed > threshold_seconds:
        failures.append(f"elapsed>{threshold_seconds:g}s")
    # 게이트 2: 소스 존재
    if not sources:
        failures.append("missing_sources")
    # 게이트 3: 폴백 답변 마커(지정 시에만)
    if fallback_markers and any(marker in answer for marker in fallback_markers):
        failures.append("fallback_answer")
    # 게이트 4: 기대 용어
    for term in expect_terms:
        if term not in answer:
            failures.append(f"missing_term={term}")

    return ChatProbe(
        index=index,
        status_code=status_code,
        elapsed_seconds=elapsed,
        source_count=len(sources),
        answer_excerpt=answer[:180],
        passed=not failures,
        failures=failures,
    )


def run(args: argparse.Namespace) -> dict[str, Any]:
    """동시 부하 스모크를 실행하고 집계 결과를 반환한다."""
    backend_url = args.backend_url.rstrip("/")
    api_key = _resolve_api_key(args.api_key_file)
    headers = {"X-API-Key": api_key} if api_key else {}
    limits = httpx.Limits(
        max_connections=max(args.concurrency, 10),
        max_keepalive_connections=max(args.concurrency, 10),
    )

    with httpx.Client(
        limits=limits,
        timeout=httpx.Timeout(args.timeout, connect=30.0),
    ) as client:
        # 사전 워밍업: /health(liveness)로 서버가 떠 있는지 확인한다.
        try:
            client.get(f"{backend_url}/health", headers=headers)
        except Exception as error:  # noqa: BLE001 - 워밍업 실패는 치명적이지 않음(경고만)
            print(f"[warn] health 워밍업 실패: {type(error).__name__}: {error}")

        with ThreadPoolExecutor(max_workers=max(args.concurrency, 1)) as executor:
            probes = list(
                executor.map(
                    lambda index: _probe_sync(
                        client,
                        backend_url=backend_url,
                        question=args.question,
                        expect_terms=args.expect_term,
                        fallback_markers=args.fallback_marker,
                        threshold_seconds=args.threshold_seconds,
                        index=index,
                        headers=headers,
                    ),
                    range(args.concurrency),
                )
            )

    passed = sum(1 for probe in probes if probe.passed)
    max_elapsed = max((probe.elapsed_seconds for probe in probes), default=0.0)
    return {
        "backend_url": backend_url,
        "concurrency": args.concurrency,
        "threshold_seconds": args.threshold_seconds,
        "passed": passed,
        "failed": args.concurrency - passed,
        "max_elapsed_seconds": max_elapsed,
        "success": passed == args.concurrency,
        "probes": [asdict(probe) for probe in probes],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend-url", required=True, help="API 서버 베이스 URL (예: http://localhost:8000)")
    parser.add_argument("--question", required=True, help="동시에 보낼 질의 메시지")
    parser.add_argument("--concurrency", type=int, default=10, help="동시 요청 수")
    parser.add_argument("--threshold-seconds", type=float, default=10.0, help="요청별 지연 임계치(초)")
    parser.add_argument("--timeout", type=float, default=60.0, help="HTTP 요청 타임아웃(초)")
    parser.add_argument(
        "--fallback-marker",
        action="append",
        default=[],
        help="폴백 답변으로 간주할 문자열(반복 지정 가능). 비어 있으면 폴백 게이트를 건너뛴다.",
    )
    parser.add_argument(
        "--expect-term",
        action="append",
        default=[],
        help="답변에 반드시 포함되어야 하는 용어(반복 지정 가능).",
    )
    parser.add_argument("--api-key-file", help="X-API-Key 값을 담은 파일 경로(없으면 FASTAPI_AUTH_KEY 사용)")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = run(args)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
