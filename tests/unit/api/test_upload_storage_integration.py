"""업로드/스토리지 개선(#10/#11/#22/#30/#36) 통합 단위 테스트.

httpx ASGITransport in-process 방식으로 upload 라우터를 검증한다. 외부 DB/네트워크
의존 없이 동작하도록 retrieval/document_processor를 fake로 주입하고, 잡 스토어는
SQLite(임시 경로)를 사용한다.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI

from app.api import upload
from app.lib.auth import create_upload_access_token


class FakeDocumentProcessor:
    """문서 로드/분할/임베딩을 단순 모킹하는 프로세서."""

    async def load_document(self, file_path: str, metadata: dict[str, Any]) -> list[str]:
        return [file_path]

    async def split_documents(self, docs: list[str]) -> list[str]:
        return ["chunk-1", "chunk-2"]

    async def embed_chunks_parallel(self, chunks: list[str]) -> list[dict[str, Any]]:
        return [
            {"content": "a", "embedding": [0.1], "metadata": {}},
            {"content": "b", "embedding": [0.2], "metadata": {}},
        ]


class FakeRetrievalModule:
    """add/delete/get_document_chunks를 모킹하는 검색 모듈."""

    def __init__(self) -> None:
        self.deleted: list[str] = []

    async def add_documents(self, documents: list[dict[str, Any]]) -> dict[str, Any]:
        return {"success_count": len(documents), "error_count": 0, "total_count": len(documents)}

    async def delete_document(self, document_id: str) -> bool:
        self.deleted.append(document_id)
        return True

    async def get_document_chunks(self, document_id: str) -> list[dict[str, Any]]:
        return [{"content": "재결합", "metadata": {"source_file": "x.txt", "chunk_index": 0}}]


@pytest.fixture()
def upload_app(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> FastAPI:
    """upload 라우터를 SQLite 잡 스토어 + fake 모듈로 격리 구성한 앱."""
    # 잡 스토어/업로드 디렉토리 격리
    monkeypatch.setenv("ONERAG_UPLOAD_JOB_STORE", "sqlite")
    monkeypatch.setenv("ONERAG_UPLOAD_JOB_DB_PATH", str(tmp_path / "jobs.sqlite3"))
    monkeypatch.setenv("ONERAG_AUDIT_EVENT_DB_PATH", str(tmp_path / "audit.sqlite3"))
    monkeypatch.delenv("ONERAG_ORIGINAL_STORAGE_BACKEND", raising=False)

    # 모듈 전역 상태 초기화
    monkeypatch.setattr(upload, "upload_jobs", {})
    monkeypatch.setattr(upload, "_upload_job_store", None)
    monkeypatch.setattr(upload, "_upload_job_store_signature", None)
    monkeypatch.setattr(upload, "_audit_event_store", None)
    monkeypatch.setattr(upload, "_audit_event_store_signature", None)
    monkeypatch.setattr(upload, "_privacy_masker", None)

    # 인증 싱글톤을 테스트 키로 고정한다. 키가 없으면 업로드 API는 fail-closed(401)이므로
    # 테스트 클라이언트(_client)는 기본으로 X-API-Key 헤더를 보낸다.
    from app.lib import auth as auth_module

    auth_instance = auth_module.get_api_key_auth()
    monkeypatch.setattr(auth_instance, "api_key", TEST_API_KEY)

    fake_retrieval = FakeRetrievalModule()
    upload.set_dependencies(
        {"document_processor": FakeDocumentProcessor(), "retrieval": fake_retrieval},
        {"uploads": {"directory": str(tmp_path / "uploads")}, "privacy": {"enabled": False}},
    )

    app = FastAPI()
    app.include_router(upload.router, prefix="/api")
    app.state.fake_retrieval = fake_retrieval
    return app


TEST_API_KEY = "test-upload-api-key-0123456789"


def _client(app: FastAPI, *, with_api_key: bool = True) -> Any:
    """테스트 클라이언트. 기본은 운영자(API 키) 자격, with_api_key=False면 무자격."""
    from fastapi.testclient import TestClient

    headers = {"X-API-Key": TEST_API_KEY} if with_api_key else {}
    return TestClient(app, headers=headers)


def _token_headers(session_id: str) -> dict[str, str]:
    """세션에 바인딩된 단기 업로드 토큰 헤더(브라우저 사용자 자격)."""
    token = create_upload_access_token(session_id, TEST_API_KEY, ttl_seconds=900)
    return {"X-OneRAG-Upload-Token": token, "X-OneRAG-Session-Id": session_id}


def test_upload_stores_original_and_download_original(upload_app: FastAPI) -> None:
    """업로드 시 원본을 보관하고 /original로 원본 바이트를 그대로 받아야 한다(#10)."""
    client = _client(upload_app)
    content = b"%PDF-1.4 original binary content"
    response = client.post(
        "/api/upload",
        files={"file": ("doc.pdf", content, "application/pdf")},
    )
    assert response.status_code == 200, response.text
    job_id = response.json()["job_id"]

    # 백그라운드 처리는 TestClient가 동기로 실행 → 완료 대기 불필요
    status = client.get(f"/api/upload/status/{job_id}")
    assert status.status_code == 200
    assert status.json()["status"] == "completed"

    # 원본 다운로드: 텍스트 재결합이 아닌 원본 바이트
    original = client.get(f"/api/upload/documents/{job_id}/original")
    assert original.status_code == 200, original.text
    assert original.content == content


def test_download_original_404_when_no_original(upload_app: FastAPI) -> None:
    """보관 원본이 없는 임의 문서의 /original은 404여야 한다(#10)."""
    client = _client(upload_app)
    response = client.get("/api/upload/documents/nonexistent/original")
    assert response.status_code == 404


def test_source_detail_returns_full_content(upload_app: FastAPI) -> None:
    """source_id 상세 조회는 content_preview가 아닌 전체 청크 본문을 반환해야 한다."""
    client = _client(upload_app)
    response = client.get("/api/upload/documents/doc-1/sources/rag:doc-1:na:0")

    assert response.status_code == 200, response.text
    assert response.json()["source_id"] == "rag:doc-1:na:0"
    assert response.json()["document_id"] == "doc-1"
    assert response.json()["full_content"] == "재결합"


def test_chunked_upload_flow(upload_app: FastAPI) -> None:
    """분할 업로드 start→chunk→complete 정상 흐름(#11)."""
    client = _client(upload_app)
    payload = b"0123456789" * 3  # 30 bytes
    start = client.post(
        "/api/upload/chunked/start",
        json={"filename": "big.txt", "content_type": "text/plain", "file_size": len(payload)},
    )
    assert start.status_code == 200, start.text
    job_id = start.json()["job_id"]

    # 첫 조각(0~15), 둘째 조각(15~30)
    first = client.post(
        f"/api/upload/chunked/{job_id}/chunk",
        files={"chunk": ("part", payload[:15])},
        data={"offset": "0"},
    )
    assert first.status_code == 200, first.text
    second = client.post(
        f"/api/upload/chunked/{job_id}/chunk",
        files={"chunk": ("part", payload[15:])},
        data={"offset": "15"},
    )
    assert second.status_code == 200, second.text

    complete = client.post(f"/api/upload/chunked/{job_id}/complete", json={})
    assert complete.status_code == 200, complete.text
    status = client.get(f"/api/upload/status/{job_id}")
    assert status.json()["status"] == "completed"


def test_chunked_upload_offset_mismatch_409(upload_app: FastAPI) -> None:
    """offset 순차성 위반 시 409여야 한다(#11)."""
    client = _client(upload_app)
    start = client.post(
        "/api/upload/chunked/start",
        json={"filename": "big.txt", "content_type": "text/plain", "file_size": 20},
    )
    job_id = start.json()["job_id"]
    bad = client.post(
        f"/api/upload/chunked/{job_id}/chunk",
        files={"chunk": ("part", b"xxxxx")},
        data={"offset": "5"},  # 기대 offset은 0
    )
    assert bad.status_code == 409


def test_chunked_upload_oversize_400(upload_app: FastAPI) -> None:
    """선언 크기 초과 조각은 400이어야 한다(#11)."""
    client = _client(upload_app)
    start = client.post(
        "/api/upload/chunked/start",
        json={"filename": "big.txt", "content_type": "text/plain", "file_size": 5},
    )
    job_id = start.json()["job_id"]
    oversize = client.post(
        f"/api/upload/chunked/{job_id}/chunk",
        files={"chunk": ("part", b"0123456789")},  # 10 > 5
        data={"offset": "0"},
    )
    assert oversize.status_code == 400


def test_chunked_complete_size_mismatch_409(upload_app: FastAPI) -> None:
    """완료 시 수신 크기가 선언 크기와 다르면 409여야 한다(#11)."""
    client = _client(upload_app)
    start = client.post(
        "/api/upload/chunked/start",
        json={"filename": "big.txt", "content_type": "text/plain", "file_size": 20},
    )
    job_id = start.json()["job_id"]
    client.post(
        f"/api/upload/chunked/{job_id}/chunk",
        files={"chunk": ("part", b"0123456789")},  # 10/20만 수신
        data={"offset": "0"},
    )
    complete = client.post(f"/api/upload/chunked/{job_id}/complete", json={})
    assert complete.status_code == 409


def test_cancel_pending_job(upload_app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> None:
    """pending 잡은 즉시 취소되어야 한다(#30)."""
    client = _client(upload_app)
    # pending 상태로 멈추도록 백그라운드 처리를 no-op으로 교체
    monkeypatch.setattr(upload, "process_document_background_guarded", _noop_background)
    response = client.post(
        "/api/upload",
        files={"file": ("doc.txt", b"hello", "text/plain")},
    )
    job_id = response.json()["job_id"]
    cancel = client.post(f"/api/upload/status/{job_id}/cancel")
    assert cancel.status_code == 200, cancel.text
    assert cancel.json()["status"] == "cancelled"


def test_cancel_terminal_job_conflict(upload_app: FastAPI) -> None:
    """완료된 잡 취소는 409여야 한다(#30)."""
    client = _client(upload_app)
    response = client.post(
        "/api/upload",
        files={"file": ("doc.txt", b"hello", "text/plain")},
    )
    job_id = response.json()["job_id"]
    # 동기 백그라운드로 completed 상태
    cancel = client.post(f"/api/upload/status/{job_id}/cancel")
    assert cancel.status_code == 409


def test_audit_event_recorded_on_delete(upload_app: FastAPI) -> None:
    """문서 삭제 시 운영 감사 이벤트가 기록되어야 한다(#36)."""
    from app.api.audit_event_store import SQLiteAuditEventStore

    client = _client(upload_app)
    response = client.post(
        "/api/upload",
        files={"file": ("doc.txt", b"hello", "text/plain")},
    )
    job_id = response.json()["job_id"]
    deleted = client.delete(f"/api/upload/documents/{job_id}")
    assert deleted.status_code == 200

    store = upload._resolve_audit_event_store()
    assert isinstance(store, SQLiteAuditEventStore)
    events = store.list_events()
    assert any(event["action"] == "document.delete.succeeded" for event in events)


@pytest.mark.asyncio
async def test_cooperative_cancel_during_processing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """처리 루프가 취소 플래그를 확인해 협조적으로 중단해야 한다(#30)."""
    monkeypatch.setenv("ONERAG_UPLOAD_JOB_STORE", "sqlite")
    monkeypatch.setenv("ONERAG_UPLOAD_JOB_DB_PATH", str(tmp_path / "jobs.sqlite3"))
    monkeypatch.setattr(upload, "upload_jobs", {})
    monkeypatch.setattr(upload, "_upload_job_store", None)
    monkeypatch.setattr(upload, "_upload_job_store_signature", None)
    monkeypatch.setattr(upload, "_privacy_masker", None)

    retrieval = FakeRetrievalModule()
    monkeypatch.setattr(
        upload,
        "modules",
        {"document_processor": FakeDocumentProcessor(), "retrieval": retrieval},
    )
    monkeypatch.setattr(upload, "config", {"uploads": {"directory": str(tmp_path)}})

    job_id = "job-cancel"
    file_path = tmp_path / "f.txt"
    file_path.write_text("data", encoding="utf-8")
    # cancel_requested가 이미 켜진 상태로 진입 → 첫 체크포인트에서 중단
    upload.upload_jobs[job_id] = {
        "job_id": job_id,
        "start_time": 1.0,
        "status": "cancelling",
        "cancel_requested": True,
        "temp_file_path": str(file_path),
    }
    await upload.process_document_background(job_id, file_path, "f.txt", "txt")
    assert upload.upload_jobs[job_id]["status"] == "cancelled"
    # 협조적 취소는 처리를 멈추므로 인덱싱(add_documents)이 일어나지 않음


@pytest.mark.asyncio
async def test_stale_processing_attempt_ignored(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """이전 attempt의 늦은 처리는 현재 attempt를 덮어쓰지 않아야 한다(#30)."""
    monkeypatch.setenv("ONERAG_UPLOAD_JOB_STORE", "sqlite")
    monkeypatch.setenv("ONERAG_UPLOAD_JOB_DB_PATH", str(tmp_path / "jobs.sqlite3"))
    monkeypatch.setattr(upload, "upload_jobs", {})
    monkeypatch.setattr(upload, "_upload_job_store", None)
    monkeypatch.setattr(upload, "_upload_job_store_signature", None)
    monkeypatch.setattr(upload, "_privacy_masker", None)
    monkeypatch.setattr(
        upload,
        "modules",
        {"document_processor": FakeDocumentProcessor(), "retrieval": FakeRetrievalModule()},
    )
    monkeypatch.setattr(upload, "config", {"uploads": {"directory": str(tmp_path)}})

    job_id = "job-stale"
    file_path = tmp_path / "f.txt"
    file_path.write_text("data", encoding="utf-8")
    upload.upload_jobs[job_id] = {
        "job_id": job_id,
        "start_time": 1.0,
        "status": "pending",
        "processing_attempt_id": "current-attempt",
        "temp_file_path": str(file_path),
    }
    # stale attempt id로 진입 → 즉시 반환(상태 변경 없음)
    await upload.process_document_background(
        job_id, file_path, "f.txt", "txt", processing_attempt_id="stale-attempt"
    )
    assert upload.upload_jobs[job_id]["status"] == "pending"


async def _noop_background(*args: Any, **kwargs: Any) -> None:
    """백그라운드 처리를 건너뛰는 no-op(취소 테스트용)."""
    await asyncio.sleep(0)


def test_get_upload_access_allows_valid_token(upload_app: FastAPI) -> None:
    """서버 API 키가 설정된 경우, 단기 업로드 토큰으로 업로드가 허용되어야 한다(#22)."""
    client = _client(upload_app, with_api_key=False)
    # 토큰만으로 업로드 (X-API-Key 없이)
    response = client.post(
        "/api/upload",
        files={"file": ("doc.txt", b"hello", "text/plain")},
        headers=_token_headers("sess-1"),
    )
    assert response.status_code == 200, response.text
    job_id = response.json()["job_id"]
    # 토큰 자격으로 만든 작업에는 소유 세션이 기록된다.
    assert upload.upload_jobs[job_id]["owner_session_id"] == "sess-1"


def test_get_upload_access_rejects_without_credentials(upload_app: FastAPI) -> None:
    """API 키가 설정된 경우, 토큰/키 둘 다 없으면 401이어야 한다(#22)."""
    client = _client(upload_app, with_api_key=False)
    response = client.post(
        "/api/upload",
        files={"file": ("doc.txt", b"hello", "text/plain")},
    )
    assert response.status_code == 401


def test_upload_api_is_fail_closed_without_server_key(
    upload_app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    """서버 키가 없으면 개발 환경이라도 업로드 API는 모두 401이어야 한다(fail-closed)."""
    from app.lib import auth as auth_module

    monkeypatch.setattr(auth_module.get_api_key_auth(), "api_key", None)
    monkeypatch.setenv("ENVIRONMENT", "development")

    client = _client(upload_app, with_api_key=False)
    assert client.get("/api/upload/documents").status_code == 401
    assert client.delete("/api/upload/documents/any").status_code == 401
    # 아무 값이나 넣은 X-API-Key도 통과하면 안 된다.
    assert (
        client.get("/api/upload/documents", headers={"X-API-Key": "whatever"}).status_code == 401
    )


def test_upload_token_cannot_delete_documents(upload_app: FastAPI) -> None:
    """세션 생성만으로 받는 업로드 토큰으로는 공유 코퍼스를 삭제할 수 없어야 한다."""
    client = _client(upload_app, with_api_key=False)
    upload_response = client.post(
        "/api/upload",
        files={"file": ("doc.txt", b"hello", "text/plain")},
        headers=_token_headers("sess-del"),
    )
    assert upload_response.status_code == 200
    job_id = upload_response.json()["job_id"]

    single = client.delete(f"/api/upload/documents/{job_id}", headers=_token_headers("sess-del"))
    assert single.status_code == 403
    assert single.json()["detail"]["error_code"] == "UPLOAD-403"

    bulk = client.post(
        "/api/upload/documents/bulk-delete",
        json={"ids": [job_id]},
        headers=_token_headers("sess-del"),
    )
    assert bulk.status_code == 403

    # 운영자(API 키)는 여전히 삭제할 수 있다.
    admin = _client(upload_app)
    assert admin.delete(f"/api/upload/documents/{job_id}").status_code == 200


def test_upload_token_can_only_cancel_own_jobs(
    upload_app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    """취소는 작업을 만든 세션만 가능하고, 다른 세션 토큰은 403이어야 한다."""
    monkeypatch.setattr(upload, "process_document_background_guarded", _noop_background)
    client = _client(upload_app, with_api_key=False)
    response = client.post(
        "/api/upload",
        files={"file": ("doc.txt", b"hello", "text/plain")},
        headers=_token_headers("owner-sess"),
    )
    assert response.status_code == 200
    job_id = response.json()["job_id"]

    other = client.post(
        f"/api/upload/status/{job_id}/cancel", headers=_token_headers("other-sess")
    )
    assert other.status_code == 403

    own = client.post(f"/api/upload/status/{job_id}/cancel", headers=_token_headers("owner-sess"))
    assert own.status_code == 200
    assert own.json()["status"] in {"cancelled", "cancelling"}


def test_api_key_can_cancel_any_job(
    upload_app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    """운영자(API 키)는 소유 세션과 무관하게 작업을 취소할 수 있어야 한다."""
    monkeypatch.setattr(upload, "process_document_background_guarded", _noop_background)
    browser = _client(upload_app, with_api_key=False)
    response = browser.post(
        "/api/upload",
        files={"file": ("doc.txt", b"hello", "text/plain")},
        headers=_token_headers("someone"),
    )
    job_id = response.json()["job_id"]

    admin = _client(upload_app)
    assert admin.post(f"/api/upload/status/{job_id}/cancel").status_code == 200
