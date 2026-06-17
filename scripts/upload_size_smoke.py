#!/usr/bin/env python3
"""업로드 사이즈 스모크 테스트 (direct 경로, 실행 중인 API 서버 대상).

바이트 정밀 PDF를 합성해 POST /api/upload(direct)로 업로드하고, 처리 완료까지
폴링한 뒤 문서 목록에서 확인하고 정리한다. 업로드 사이즈 한계는 앱 설정 +
리버스 프록시 + 배포 플랫폼 3개 층이 겹쳐 결정되므로 로컬 단위 테스트로는
검증할 수 없다. 이 스모크는 그 경계(특히 HTTP 413)를 라이브에서 확인한다.

HTTP 413(Request Entity Too Large)은 'upload size limit exceeded'로 명확히 보고한다.

사용법(라이브 서버 필요):
    uv run python scripts/upload_size_smoke.py \
        --base-url http://localhost:8000 \
        --direct-sizes-mib 3 4

인증:
    환경변수 FASTAPI_AUTH_KEY가 있으면 X-API-Key 헤더를 구성한다(e2e_rag_smoke.py 규약).
    --base-url 미지정 시 환경변수 E2E_BASE_URL(기본 http://127.0.0.1:8000) 사용.

출력/종료 코드:
    결과를 JSON으로 stdout에 출력하고, 성공 시 0 / 실패 시 1을 반환한다.

원본 대비 일반화:
    - chunked 업로드 경로 전부 제거(OneRAG에 /api/upload/chunked/* 부재).
    - 멀티테넌트 세션(create_session/upload_token/company_id) 제거.
    - Cloud Run 프론트 URL 하드코딩 제거 → --base-url/E2E_BASE_URL로 외부화.
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

DEFAULT_DIRECT_SIZES_MIB = (3, 4)


@dataclass
class UploadResult:
    """단일 업로드 시도의 결과."""

    label: str
    filename: str
    size_bytes: int
    job_id: str
    upload_status_code: int
    final_status: str
    chunk_count: int | None
    elapsed_seconds: float


def _headers() -> dict[str, str]:
    """FASTAPI_AUTH_KEY가 있으면 X-API-Key 헤더를 구성한다."""
    auth = os.getenv("FASTAPI_AUTH_KEY", "").strip()
    return {"X-API-Key": auth} if auth else {}


def require_json(response: httpx.Response, context: str) -> dict[str, Any]:
    """응답을 JSON dict로 강제하고, 4xx/5xx는 명확한 에러로 변환한다.

    413은 업로드 사이즈 한계 초과로 명시적으로 보고한다.
    """
    try:
        payload = response.json()
    except json.JSONDecodeError:
        payload = {"raw": response.text[:1000]}
    if response.status_code == 413:
        raise RuntimeError(
            f"{context} failed with HTTP 413 (upload size limit exceeded): {payload}"
        )
    if response.status_code >= 400:
        raise RuntimeError(f"{context} failed with HTTP {response.status_code}: {payload}")
    if not isinstance(payload, dict):
        raise RuntimeError(f"{context} did not return a JSON object: {payload!r}")
    return payload


def build_pdf_bytes(target_size: int, label: str) -> bytes:
    """정확히 target_size 바이트의 유효 PDF를 합성한다(외부 의존성 0).

    xref offset을 직접 계산하고, 콘텐츠 스트림에 패딩을 추가하며 수렴 루프로
    정확한 크기를 맞춘다. 목표 크기에 도달하지 못하면 RuntimeError를 던진다.
    """
    if target_size < 4096:
        raise ValueError("target_size must be at least 4096 bytes")

    content_prefix = (
        b"BT /F1 12 Tf 72 720 Td (OneRAG upload size smoke "
        + label.encode("ascii", "ignore")
        + b") Tj ET\n%"
    )

    def render(content: bytes) -> bytes:
        parts: list[bytes] = []
        offsets: list[int] = []

        def add(part: bytes) -> None:
            parts.append(part)

        def obj(number: int, body: bytes) -> None:
            offsets.append(sum(len(part) for part in parts))
            add(f"{number} 0 obj\n".encode())
            add(body)
            add(b"\nendobj\n")

        add(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        obj(1, b"<< /Type /Catalog /Pages 2 0 R >>")
        obj(2, b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>")
        obj(
            3,
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        )
        obj(4, b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
        obj(
            5,
            f"<< /Length {len(content)} >>\nstream\n".encode()
            + content
            + b"\nendstream",
        )
        xref_offset = sum(len(part) for part in parts)
        add(b"xref\n0 6\n0000000000 65535 f \n")
        for offset in offsets:
            add(f"{offset:010d} 00000 n \n".encode())
        add(
            b"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n"
            + str(xref_offset).encode()
            + b"\n%%EOF\n"
        )
        return b"".join(parts)

    # 패딩 길이를 수렴시켜 정확한 바이트 크기를 맞춘다.
    pad_len = max(0, target_size - len(render(content_prefix)))
    for _ in range(8):
        content = content_prefix + (b"x" * pad_len)
        rendered = render(content)
        delta = target_size - len(rendered)
        if delta == 0:
            return rendered
        pad_len += delta
        if pad_len < 0:
            raise RuntimeError("PDF overhead exceeded target size")
    raise RuntimeError(f"Could not render exact-size PDF for {label}")


def write_pdf(path: Path, target_size: int, label: str) -> None:
    """바이트 정밀 PDF를 파일로 기록하고 실제 크기를 검증한다."""
    path.write_bytes(build_pdf_bytes(target_size, label))
    actual_size = path.stat().st_size
    if actual_size != target_size:
        raise RuntimeError(f"{path.name} expected {target_size} bytes, got {actual_size}")


def _metadata(label: str, size_bytes: int) -> str:
    return json.dumps(
        {"smoke": "upload_size_smoke", "label": label, "size_bytes": size_bytes},
        ensure_ascii=False,
    )


def upload_direct(
    client: httpx.Client, base_url: str, path: Path, label: str
) -> tuple[str, int]:
    """direct 경로(POST /api/upload)로 업로드하고 (job_id, status_code)를 반환한다."""
    with path.open("rb") as handle:
        response = client.post(
            f"{base_url}/api/upload",
            headers=_headers(),
            data={"metadata": _metadata(label, path.stat().st_size)},
            files={"file": (path.name, handle, "application/pdf")},
            timeout=300.0,
        )
    payload = require_json(response, f"direct upload {label}")
    return str(payload["job_id"]), response.status_code


def poll_upload(
    client: httpx.Client,
    base_url: str,
    job_id: str,
    *,
    timeout_seconds: float,
    poll_interval_seconds: float,
) -> dict[str, Any]:
    """완료/실패/취소될 때까지 상태를 폴링한다."""
    deadline = time.monotonic() + timeout_seconds
    last_payload: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        response = client.get(
            f"{base_url}/api/upload/status/{job_id}",
            headers=_headers(),
            timeout=60.0,
        )
        payload = require_json(response, f"poll upload {job_id}")
        last_payload = payload
        status = str(payload.get("status") or "")
        if status == "completed":
            return payload
        if status in {"failed", "cancelled"}:
            raise RuntimeError(f"upload {job_id} ended with {status}: {payload}")
        time.sleep(poll_interval_seconds)
    raise TimeoutError(f"upload {job_id} timed out: {last_payload}")


def list_documents(client: httpx.Client, base_url: str) -> list[dict[str, Any]]:
    """문서 목록을 조회한다."""
    response = client.get(
        f"{base_url}/api/upload/documents",
        params={"page": "1", "page_size": "50"},
        headers=_headers(),
        timeout=120.0,
    )
    payload = require_json(response, "list documents")
    documents = payload.get("documents") or []
    if not isinstance(documents, list):
        raise RuntimeError(f"list documents returned invalid payload: {payload}")
    return documents


def delete_document(client: httpx.Client, base_url: str, document_id: str) -> None:
    """문서를 삭제한다."""
    response = client.delete(
        f"{base_url}/api/upload/documents/{document_id}",
        headers=_headers(),
        timeout=120.0,
    )
    require_json(response, f"delete document {document_id}")


def run(args: argparse.Namespace) -> dict[str, Any]:
    """업로드 사이즈 스모크를 실행하고 집계 결과를 반환한다."""
    base_url = args.base_url.rstrip("/")
    started = time.monotonic()
    results: list[UploadResult] = []
    cleanup_errors: list[str] = []
    oversize_result: dict[str, Any] = {"checked": False}

    with tempfile.TemporaryDirectory(prefix="onerag-upload-size-smoke-") as tmpdir:
        tmp_path = Path(tmpdir)
        with httpx.Client(timeout=httpx.Timeout(300.0, connect=30.0)) as client:
            # 1) 허용 크기 업로드: 처리 완료까지 검증.
            for size_mib in args.direct_sizes_mib:
                label = f"{size_mib}MiB-direct"
                path = tmp_path / f"onerag-smoke-{size_mib}m.pdf"
                write_pdf(path, size_mib * 1024 * 1024, label)
                upload_started = time.monotonic()
                job_id, status_code = upload_direct(client, base_url, path, label)
                final_payload = poll_upload(
                    client,
                    base_url,
                    job_id,
                    timeout_seconds=args.poll_timeout_seconds,
                    poll_interval_seconds=args.poll_interval_seconds,
                )
                results.append(
                    UploadResult(
                        label=label,
                        filename=path.name,
                        size_bytes=path.stat().st_size,
                        job_id=job_id,
                        upload_status_code=status_code,
                        final_status=str(final_payload.get("status") or ""),
                        chunk_count=final_payload.get("chunk_count"),
                        elapsed_seconds=round(time.monotonic() - upload_started, 2),
                    )
                )

            # 2) (선택) 경계 초과 업로드: 413(또는 4xx)으로 거부되는지 확인.
            if args.max_size_mib is not None:
                oversize_label = f"{args.max_size_mib}MiB-oversize"
                oversize_path = tmp_path / "onerag-smoke-oversize.pdf"
                write_pdf(oversize_path, args.max_size_mib * 1024 * 1024, oversize_label)
                rejected = False
                rejection_status = 0
                try:
                    with oversize_path.open("rb") as handle:
                        response = client.post(
                            f"{base_url}/api/upload",
                            headers=_headers(),
                            data={
                                "metadata": _metadata(
                                    oversize_label, oversize_path.stat().st_size
                                )
                            },
                            files={"file": (oversize_path.name, handle, "application/pdf")},
                            timeout=300.0,
                        )
                    rejection_status = response.status_code
                    # 4xx면 사이즈 한계로 거부된 것으로 본다(413이 이상적).
                    rejected = response.status_code >= 400
                except httpx.HTTPError as error:
                    # 프록시/플랫폼이 연결을 끊는 형태로 거부할 수도 있다.
                    rejected = True
                    rejection_status = -1
                    oversize_result["transport_error"] = (
                        f"{type(error).__name__}: {error}"
                    )
                oversize_result = {
                    "checked": True,
                    "size_mib": args.max_size_mib,
                    "rejection_status": rejection_status,
                    "rejected": rejected,
                    **{
                        k: v
                        for k, v in oversize_result.items()
                        if k == "transport_error"
                    },
                }

            # 3) 업로드된 문서가 목록 첫 페이지에 보이는지 확인.
            documents = list_documents(client, base_url)
            job_ids = {result.job_id for result in results}
            listed_job_ids = {str(document.get("id") or "") for document in documents}
            missing = sorted(job_ids - listed_job_ids)
            if missing:
                raise RuntimeError(
                    f"completed smoke documents missing from listing: {missing}"
                )

            # 4) 정리(기본): 업로드한 스모크 문서를 삭제한다.
            if not args.keep_documents:
                for result in results:
                    try:
                        delete_document(client, base_url, result.job_id)
                    except Exception as error:  # noqa: BLE001 - 정리 오류는 집계만
                        cleanup_errors.append(f"{result.job_id}: {error}")

            remaining_documents = list_documents(client, base_url)

    # 성공 판정: 허용 크기 업로드가 모두 completed이고, 경계 검사 시 거부됐어야 한다.
    all_completed = all(result.final_status == "completed" for result in results)
    oversize_ok = (not oversize_result.get("checked")) or bool(
        oversize_result.get("rejected")
    )
    success = bool(results) and all_completed and oversize_ok and not cleanup_errors

    return {
        "base_url": base_url,
        "results": [result.__dict__ for result in results],
        "oversize_check": oversize_result,
        "cleanup": {
            "kept_documents": bool(args.keep_documents),
            "errors": cleanup_errors,
            "remaining_count": len(remaining_documents),
        },
        "success": success,
        "total_elapsed_seconds": round(time.monotonic() - started, 2),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        default=os.getenv("E2E_BASE_URL", "http://127.0.0.1:8000"),
        help="API 서버 베이스 URL (기본: 환경변수 E2E_BASE_URL 또는 http://127.0.0.1:8000)",
    )
    parser.add_argument(
        "--direct-sizes-mib",
        type=int,
        nargs="+",
        default=list(DEFAULT_DIRECT_SIZES_MIB),
        help="허용 범위 내에서 업로드해 완료를 검증할 크기(MiB) 목록",
    )
    parser.add_argument(
        "--max-size-mib",
        type=int,
        default=None,
        help="지정 시 이 크기(MiB) PDF가 413/4xx로 거부되는지 경계 검증(앱 max_file_size 초과 권장)",
    )
    parser.add_argument("--poll-timeout-seconds", type=float, default=900.0)
    parser.add_argument("--poll-interval-seconds", type=float, default=5.0)
    parser.add_argument(
        "--keep-documents",
        action="store_true",
        help="설정 시 업로드한 스모크 문서를 삭제하지 않는다.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = run(args)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
