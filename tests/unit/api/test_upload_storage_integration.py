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

    # 인증 싱글톤이 다른 테스트에서 api_key를 설정해 둘 수 있으므로 dev 모드로 격리한다.
    # (api_key=None → get_upload_access가 dev-skip하여 헤더 없이 업로드 허용)
    from app.lib import auth as auth_module

    auth_instance = auth_module.get_api_key_auth()
    monkeypatch.setattr(auth_instance, "api_key", None)

    fake_retrieval = FakeRetrievalModule()
    upload.set_dependencies(
        {"document_processor": FakeDocumentProcessor(), "retrieval": fake_retrieval},
        {"uploads": {"directory": str(tmp_path / "uploads")}, "privacy": {"enabled": False}},
    )

    app = FastAPI()
    app.include_router(upload.router, prefix="/api")
    app.state.fake_retrieval = fake_retrieval
    return app


def _client(app: FastAPI) -> Any:
    from fastapi.testclient import TestClient

    return TestClient(app)


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


def test_get_upload_access_allows_valid_token(
    upload_app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    """서버 API 키가 설정된 경우, 단기 업로드 토큰으로 업로드가 허용되어야 한다(#22)."""
    from app.lib import auth as auth_module

    # 인증 활성화: api_key 설정
    auth_instance = auth_module.get_api_key_auth()
    monkeypatch.setattr(auth_instance, "api_key", "server-secret")
    token = create_upload_access_token("sess-1", "server-secret", ttl_seconds=900)

    client = _client(upload_app)
    # 토큰만으로 업로드 (X-API-Key 없이)
    response = client.post(
        "/api/upload",
        files={"file": ("doc.txt", b"hello", "text/plain")},
        headers={"X-OneRAG-Upload-Token": token, "X-OneRAG-Session-Id": "sess-1"},
    )
    assert response.status_code == 200, response.text


def test_get_upload_access_rejects_without_credentials(
    upload_app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    """API 키가 설정된 경우, 토큰/키 둘 다 없으면 401이어야 한다(#22)."""
    from app.lib import auth as auth_module

    auth_instance = auth_module.get_api_key_auth()
    monkeypatch.setattr(auth_instance, "api_key", "server-secret")

    client = _client(upload_app)
    response = client.post(
        "/api/upload",
        files={"file": ("doc.txt", b"hello", "text/plain")},
    )
    assert response.status_code == 401
