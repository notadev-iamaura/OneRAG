#!/usr/bin/env python3
"""로컬 코퍼스를 실행 중인 API를 통해 일괄 재색인하는 운영 스크립트.

로컬 디렉토리를 순회하며 지원 포맷 문서를 찾아, (선택) Weaviate를 리셋한 뒤
POST /api/upload(direct)로 업로드하고 처리 완료까지 폴링한다. 표준 라이브러리
(urllib)만 사용한다.

안전 가드(JapanRAG에서 차용한 핵심 가치):
  - --allow-remote-reset: --reset이 비로컬 서버를 향할 때 차단(프로덕션 인덱스
    실수 삭제 방지). backend-url 호스트가 localhost/127.0.0.1/::1이 아니면 거부.
  - --allow-zero-embeddings: 리셋 전 서버 /ready 준비 상태를 확인한다. 준비되지
    않았으면(임베딩/검색 미준비로 재색인 후 빈 인덱스가 될 위험) 리셋을 거부.
    의도적 BM25-only 등 예외 상황에서만 이 플래그로 우회한다.

사용법(라이브 서버 필요):
    uv run python scripts/reindex_documents.py \
        --backend-url http://localhost:8000 \
        --source-dir ./data/sample_corpus \
        --reset

    # 미리보기(업로드 없이 계획만 출력)
    uv run python scripts/reindex_documents.py --source-dir ./corpus --dry-run

인증:
    --api-key 또는 --api-key-env(기본 FASTAPI_AUTH_KEY)에서 X-API-Key를 구성한다.

출력/종료 코드:
    --json 지정 시 결과를 JSON으로 출력. 실패한 파일이 있으면 1, 없으면 0.

JapanRAG 원본 대비 일반화:
    - chunked 업로드 경로 전부 제거(OneRAG에 /api/upload/chunked/* 부재).
    - LibreOffice(soffice) .doc/.pptx 변환 제거(LoaderFactory가 직접 지원 여부 판단).
    - Cloud Run 하드코딩 backend-url / 한국어 기본 소스 디렉토리 제거 → 인자로 외부화.
    - status 폴링 시 company_id 쿼리 파라미터 제거(OneRAG는 단일 테넌트).
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.modules.core.documents.loaders import LoaderFactory  # noqa: E402

TERMINAL_STATUSES = {"completed", "failed", "cancelled"}
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", ""}


def candidate_files(source_dir: Path) -> list[Path]:
    """소스 디렉토리 하위의 모든 파일을 정렬해 반환한다."""
    return sorted(path for path in source_dir.rglob("*") if path.is_file())


def supported_files(source_dir: Path) -> list[Path]:
    """LoaderFactory가 지원하는 파일만 반환한다."""
    return [path for path in candidate_files(source_dir) if LoaderFactory.is_supported(path)]


def selected_supported_files(source_dir: Path, selected_files: list[Path]) -> list[Path]:
    """--file로 지정된 파일만 검증 후 반환한다(상대경로는 source_dir 기준)."""
    files: list[Path] = []
    for selected in selected_files:
        path = selected.expanduser()
        if not path.is_absolute():
            path = source_dir / path
        path = path.resolve()
        if not path.is_file():
            raise RuntimeError(f"Selected file does not exist: {path}")
        if not LoaderFactory.is_supported(path):
            raise RuntimeError(f"Selected file is not supported locally: {path}")
        files.append(path)
    return files


def build_plan(files: list[Path], source_dir: Path, backend_url: str) -> dict[str, Any]:
    """업로드 계획(파일 수 / 확장자별 카운트)을 구성한다."""
    counts: dict[str, int] = {}
    for path in files:
        suffix = path.suffix.lower().lstrip(".") or "<none>"
        counts[suffix] = counts.get(suffix, 0) + 1
    return {
        "backend_url": backend_url,
        "source_dir": str(source_dir),
        "supported_file_count": len(files),
        "by_extension": dict(sorted(counts.items())),
    }


def resolve_api_key(args: argparse.Namespace) -> str | None:
    """--api-key 또는 --api-key-env 환경변수에서 API 키를 해석한다(없으면 None)."""
    if args.api_key:
        return str(args.api_key)
    if args.api_key_env:
        value = os.getenv(args.api_key_env, "").strip()
        if value:
            return value
    return None


def request_json(
    method: str,
    url: str,
    *,
    api_key: str | None,
    body: bytes | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 60.0,
) -> dict[str, Any]:
    """urllib로 JSON 요청을 보내고 dict 응답을 반환한다."""
    request_headers = {"Accept": "application/json"}
    if api_key:
        request_headers["X-API-Key"] = api_key
    request_headers.update(headers or {})
    request = urllib.request.Request(url, data=body, headers=request_headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - 운영 도구
            payload = response.read()
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {url} failed: HTTP {error.code}: {detail}") from error
    if not payload:
        return {}
    return json.loads(payload.decode("utf-8"))


def _is_local_host(url: str) -> bool:
    """backend-url 호스트가 로컬인지 판단한다(원격 리셋 가드용)."""
    parsed = urlparse(url)
    return (parsed.hostname or "") in LOCAL_HOSTS


def guard_remote_reset(backend_url: str, *, allow_remote_reset: bool) -> None:
    """비로컬 서버에 대한 --reset을 차단한다(프로덕션 인덱스 실수 삭제 방지)."""
    if allow_remote_reset:
        return
    if not _is_local_host(backend_url):
        raise RuntimeError(
            "Refusing to reset a non-local backend. "
            f"backend-url={backend_url}. "
            "Pass --allow-remote-reset only if this is intentional."
        )


def guard_zero_embeddings(
    backend_url: str, *, api_key: str | None, allow_zero_embeddings: bool
) -> None:
    """리셋 전 서버 준비 상태(/ready)를 확인한다.

    준비되지 않은 서버를 리셋하면 재색인 후 빈/저품질 인덱스가 될 수 있으므로,
    ready가 아니면 거부한다. --allow-zero-embeddings로 의도적 우회 가능.
    """
    if allow_zero_embeddings:
        return
    try:
        ready = request_json(
            "GET", f"{backend_url}/ready", api_key=api_key, timeout=30.0
        )
    except Exception as error:  # noqa: BLE001 - 준비 상태 확인 실패는 안전 측 거부
        raise RuntimeError(
            f"Could not verify server readiness before reset: {error}. "
            "Pass --allow-zero-embeddings to bypass only for an intentional test index."
        ) from error
    status = str(ready.get("status") or "")
    if status not in {"ready", "degraded"}:
        raise RuntimeError(
            f"Server is not ready (status={status!r}); refusing to reset. "
            "Re-indexing now risks an empty index. "
            "Pass --allow-zero-embeddings to bypass."
        )


def reset_weaviate(backend_url: str, api_key: str | None) -> dict[str, Any]:
    """POST /api/admin/weaviate/reset 으로 인덱스를 초기화한다."""
    url = f"{backend_url}/api/admin/weaviate/reset"
    result = request_json("POST", url, api_key=api_key, timeout=300.0)
    if not result.get("success"):
        raise RuntimeError(f"Weaviate reset failed: {result}")
    return result


def multipart_upload_body(
    path: Path, *, metadata: dict[str, Any]
) -> tuple[bytes, str]:
    """direct 업로드용 multipart 바디(file + metadata)를 구성한다."""
    boundary = f"----onerag-{uuid.uuid4().hex}"
    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    file_bytes = path.read_bytes()
    parts = [
        (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="metadata"\r\n\r\n'
            f"{json.dumps(metadata, ensure_ascii=False)}\r\n"
        ).encode(),
        (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="{path.name}"\r\n'
            f"Content-Type: {content_type}\r\n\r\n"
        ).encode(),
        file_bytes,
        f"\r\n--{boundary}--\r\n".encode(),
    ]
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def upload_file(
    backend_url: str, api_key: str | None, path: Path, source_dir: Path
) -> str:
    """direct 경로로 파일 1건을 업로드하고 job_id를 반환한다.

    company_id는 별도 폼 필드로 보내지 않고, 출처 정보는 metadata에 접는다.
    """
    relative = path.relative_to(source_dir).as_posix()
    metadata = {
        "source": relative,
        "source_file": path.name,
        "reindex_source": "reindex_documents_script",
    }
    body, content_type = multipart_upload_body(path, metadata=metadata)
    result = request_json(
        "POST",
        f"{backend_url}/api/upload",
        api_key=api_key,
        body=body,
        headers={"Content-Type": content_type},
        timeout=300.0,
    )
    job_id = str(result.get("job_id") or "")
    if not job_id:
        raise RuntimeError(f"Upload response did not include job_id: {result}")
    return job_id


def wait_for_job(
    backend_url: str,
    api_key: str | None,
    *,
    job_id: str,
    poll_interval: float,
    timeout: float,
) -> dict[str, Any]:
    """업로드 잡이 종료 상태가 될 때까지 폴링한다(company_id 쿼리 없음)."""
    deadline = time.monotonic() + timeout
    url = f"{backend_url}/api/upload/status/{job_id}"
    while True:
        status = request_json("GET", url, api_key=api_key, timeout=60.0)
        current = str(status.get("status") or "")
        if current in TERMINAL_STATUSES:
            return status
        if time.monotonic() >= deadline:
            raise TimeoutError(f"Upload job timed out: {job_id}")
        time.sleep(poll_interval)


def run(args: argparse.Namespace) -> dict[str, Any]:
    """재색인을 실행하고 결과 요약(dict)을 반환한다."""
    source_dir = args.source_dir.expanduser().resolve()
    backend_url = args.backend_url.rstrip("/")
    if not source_dir.is_dir():
        raise RuntimeError(f"source-dir is not a directory: {source_dir}")

    files = (
        selected_supported_files(source_dir, args.selected_files)
        if args.selected_files
        else supported_files(source_dir)
    )
    if args.limit is not None:
        files = files[: args.limit]
    plan = build_plan(files, source_dir, backend_url)

    if args.dry_run:
        return {"dry_run": True, "plan": plan, "success": True}

    api_key = resolve_api_key(args)
    reset_result: dict[str, Any] = {"skipped": True}
    if args.reset:
        # 안전 가드: 비로컬 리셋 차단 + 서버 준비 상태 확인.
        guard_remote_reset(backend_url, allow_remote_reset=args.allow_remote_reset)
        guard_zero_embeddings(
            backend_url,
            api_key=api_key,
            allow_zero_embeddings=args.allow_zero_embeddings,
        )
        reset_result = reset_weaviate(backend_url, api_key)

    completed = 0
    failed: list[dict[str, Any]] = []
    for path in files:
        relative = path.relative_to(source_dir).as_posix()
        try:
            job_id = upload_file(backend_url, api_key, path, source_dir)
            status = wait_for_job(
                backend_url,
                api_key,
                job_id=job_id,
                poll_interval=args.poll_interval,
                timeout=args.job_timeout,
            )
            if status.get("status") == "completed":
                completed += 1
            else:
                failed.append(
                    {
                        "file": relative,
                        "status": status.get("status"),
                        "error": status.get("error_message"),
                    }
                )
        except Exception as error:  # noqa: BLE001 - 파일별 실패를 집계만 하고 계속 진행
            failed.append({"file": relative, "error": str(error)})

    return {
        "dry_run": False,
        "plan": plan,
        "reset": reset_result,
        "completed": completed,
        "failed": failed,
        "failed_count": len(failed),
        "success": not failed,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--backend-url",
        default="http://localhost:8000",
        help="API 서버 베이스 URL (기본: http://localhost:8000)",
    )
    parser.add_argument(
        "--source-dir",
        type=Path,
        required=True,
        help="재색인할 로컬 코퍼스 디렉토리",
    )
    parser.add_argument("--api-key-env", default="FASTAPI_AUTH_KEY", help="API 키 환경변수명")
    parser.add_argument("--api-key", default=None, help="API 키 직접 지정(환경변수보다 우선)")
    parser.add_argument("--reset", action="store_true", help="업로드 전 Weaviate 인덱스 리셋")
    parser.add_argument(
        "--allow-remote-reset",
        action="store_true",
        help="비로컬 backend-url에 대한 --reset 허용(프로덕션 삭제 방지 가드 우회)",
    )
    parser.add_argument(
        "--allow-zero-embeddings",
        action="store_true",
        help="서버 미준비 상태에서도 리셋 허용(의도적 빈/BM25-only 인덱스 전용)",
    )
    parser.add_argument("--dry-run", action="store_true", help="업로드 없이 계획만 출력")
    parser.add_argument("--limit", type=int, default=None, help="업로드할 최대 파일 수")
    parser.add_argument(
        "--file",
        dest="selected_files",
        action="append",
        type=Path,
        default=[],
        help="이 파일만 업로드(반복 지정 가능, 상대경로는 --source-dir 기준)",
    )
    parser.add_argument("--poll-interval", type=float, default=5.0, help="상태 폴링 간격(초)")
    parser.add_argument("--job-timeout", type=float, default=1800.0, help="잡 처리 타임아웃(초)")
    parser.add_argument("--json", action="store_true", help="결과를 JSON으로 출력")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = run(args)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        plan = result["plan"]
        print(f"Backend: {plan['backend_url']}")
        print(f"Source: {plan['source_dir']}")
        print(f"Supported files: {plan['supported_file_count']}")
        for suffix, count in plan["by_extension"].items():
            print(f"  {suffix}: {count}")
        if not result.get("dry_run"):
            print(f"Completed: {result['completed']}")
            print(f"Failed: {result['failed_count']}")
            for item in result["failed"][:20]:
                print(f"  - {item}")
    return 0 if result["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
