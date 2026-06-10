"""UploadJobStore(SQLite/JSON/Postgres) 어댑터와 upload.py 통합 테스트."""

import pytest

from app.api import upload
from app.api.upload_job_store import (
    JsonUploadJobStore,
    PostgresUploadJobStore,
    SQLiteUploadJobStore,
    _should_preserve_existing_payload,
)


def test_sqlite_upload_job_store_persists_jobs_and_events(tmp_path):
    db_path = tmp_path / "upload_jobs.sqlite3"
    store = SQLiteUploadJobStore(db_path)

    jobs = {
        "job-1": {
            "job_id": "job-1",
            "filename": "contract.pdf",
            "status": "pending",
            "progress": 0,
            "message": "queued",
            "start_time": 1.0,
        }
    }

    store.save_all(jobs)
    jobs["job-1"].update(
        {
            "status": "processing",
            "progress": 30,
            "message": "loading",
        }
    )
    store.save_all(jobs)

    reloaded_store = SQLiteUploadJobStore(db_path)
    loaded_jobs = reloaded_store.load_all()
    events = reloaded_store.list_events("job-1")

    assert loaded_jobs["job-1"]["status"] == "processing"
    assert loaded_jobs["job-1"]["progress"] == 30
    assert loaded_jobs["job-1"]["created_at"]
    assert loaded_jobs["job-1"]["updated_at"]
    assert [event["event_type"] for event in events] == ["created", "status_changed"]


def test_sqlite_upload_job_store_deletes_stale_jobs_on_full_save(tmp_path):
    db_path = tmp_path / "upload_jobs.sqlite3"
    store = SQLiteUploadJobStore(db_path)

    store.save_all(
        {
            "job-a": {"job_id": "job-a", "status": "pending"},
            "job-b": {"job_id": "job-b", "status": "pending"},
        }
    )
    store.save_all(
        {
            "job-a": {
                "job_id": "job-a",
                "status": "completed",
            }
        }
    )

    loaded_jobs = store.load_all()

    assert set(loaded_jobs) == {"job-a"}
    assert loaded_jobs["job-a"]["status"] == "completed"


def test_sqlite_upload_job_store_persists_retry_count_without_path_metadata(tmp_path):
    db_path = tmp_path / "upload_jobs.sqlite3"
    store = SQLiteUploadJobStore(db_path)
    jobs = {
        "job-retry": {
            "job_id": "job-retry",
            "status": "failed",
            "progress": 0,
            "message": "failed",
            "retry_count": 0,
            "original_file_path": str(tmp_path / "private.pdf"),
        }
    }

    store.save_all(jobs)
    jobs["job-retry"].update(
        {
            "status": "pending",
            "progress": 0,
            "message": "retry queued",
            "retry_count": 1,
            "temp_file_path": str(tmp_path / "retry.pdf"),
        }
    )
    store.save_all(jobs)

    events = store.list_events("job-retry")

    assert events[-1]["event_type"] == "status_changed"
    assert events[-1]["metadata"]["retry_count"] == 1
    # 이벤트에는 서버 내부 파일 경로가 노출되면 안 된다.
    serialized_events = str(events)
    assert "private.pdf" not in serialized_events
    assert "retry.pdf" not in serialized_events
    assert str(tmp_path) not in serialized_events


def test_sqlite_upload_job_store_claims_pending_jobs(tmp_path):
    db_path = tmp_path / "upload_jobs.sqlite3"
    store = SQLiteUploadJobStore(db_path)
    store.save_all(
        {
            "job-pending": {
                "job_id": "job-pending",
                "status": "pending",
                "progress": 0,
                "message": "queued",
            }
        }
    )

    claimed = store.claim_next(worker_id="worker-a", now=100.0)

    assert claimed is not None
    assert claimed["job_id"] == "job-pending"
    assert claimed["status"] == "processing"
    assert claimed["claimed_by"] == "worker-a"


def test_json_upload_job_store_remains_available_as_explicit_fallback(tmp_path):
    json_path = tmp_path / "jobs.json"
    store = JsonUploadJobStore(json_path)

    store.save_all(
        {
            "job-1": {
                "job_id": "job-1",
                "status": "completed",
            }
        }
    )

    assert store.load_all()["job-1"]["status"] == "completed"


def test_upload_store_resolver_accepts_postgres(monkeypatch):
    class FakePostgresUploadJobStore:
        def __init__(self, database_url):
            self.database_url = database_url

        def load_all(self):
            return {}

        def save_all(self, jobs):
            return None

    monkeypatch.setenv("ONERAG_UPLOAD_JOB_STORE", "postgres")
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@db.example/onerag")
    monkeypatch.setattr(upload, "PostgresUploadJobStore", FakePostgresUploadJobStore)
    monkeypatch.setattr(upload, "_upload_job_store", None)
    monkeypatch.setattr(upload, "_upload_job_store_signature", None)

    store = upload._resolve_upload_job_store()

    assert isinstance(store, FakePostgresUploadJobStore)
    assert store.database_url == "postgresql://user:pass@db.example/onerag"


def test_shared_upload_store_reload_refreshes_stale_local_cache(monkeypatch):
    monkeypatch.setattr(upload, "_is_shared_upload_job_store", lambda: True)
    monkeypatch.setattr(
        upload,
        "load_upload_jobs",
        lambda: {
            "job-1": {
                "job_id": "job-1",
                "status": "completed",
                "progress": 100,
            }
        },
    )
    monkeypatch.setattr(
        upload,
        "upload_jobs",
        {
            "job-1": {
                "job_id": "job-1",
                "status": "pending",
                "progress": 0,
            }
        },
    )

    upload._reload_upload_jobs_if_needed("job-1")

    assert upload.upload_jobs["job-1"]["status"] == "completed"
    assert upload.upload_jobs["job-1"]["progress"] == 100


def test_postgres_upload_store_fails_closed_in_production(monkeypatch):
    class FailingUploadJobStore:
        def load_all(self):
            raise RuntimeError("database unavailable")

    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("ONERAG_UPLOAD_JOB_STORE", "postgres")
    monkeypatch.delenv("ONERAG_UPLOAD_JOB_STORE_FAIL_OPEN", raising=False)
    monkeypatch.setattr(upload, "_resolve_upload_job_store", lambda: FailingUploadJobStore())

    with pytest.raises(RuntimeError, match="database unavailable"):
        upload.load_upload_jobs()


def test_shared_upload_store_runs_native_retention_cleanup(monkeypatch):
    calls: list[object] = []

    class FakeStore:
        def cleanup_expired(self, *, retention_seconds):
            calls.append(retention_seconds)
            return 1

        def load_all(self):
            return {}

    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("ONERAG_UPLOAD_JOB_STORE", "postgres")
    monkeypatch.setenv("ONERAG_UPLOAD_JOB_RETENTION_SECONDS", "123")
    monkeypatch.setattr(upload, "_resolve_upload_job_store", lambda: FakeStore())

    assert upload.load_upload_jobs() == {}
    assert calls == [123]


def test_shared_store_initial_upload_jobs_does_not_connect_at_import(monkeypatch):
    def fail_load_upload_jobs():
        raise AssertionError("shared store should not load at import")

    monkeypatch.setattr(upload, "_is_shared_upload_job_store", lambda: True)
    monkeypatch.setattr(upload, "load_upload_jobs", fail_load_upload_jobs)

    assert upload._initial_upload_jobs() == {}


def test_shared_store_full_map_save_is_disabled(monkeypatch):
    monkeypatch.setattr(upload, "_is_shared_upload_job_store", lambda: True)
    monkeypatch.setattr(upload, "_upload_job_store_fail_closed", lambda: True)

    with pytest.raises(RuntimeError, match="Full-map upload job saves are disabled"):
        upload.save_upload_jobs({"job-1": {"job_id": "job-1"}})


def test_shared_store_save_upload_job_persists_only_target_job(monkeypatch):
    saved_payloads: list[dict[str, dict[str, object]]] = []

    class FakeStore:
        def save_all(self, jobs):
            saved_payloads.append(dict(jobs))

    monkeypatch.setattr(upload, "_is_shared_upload_job_store", lambda: True)
    monkeypatch.setattr(upload, "_resolve_upload_job_store", lambda: FakeStore())
    monkeypatch.setattr(upload, "_upload_job_store_fail_closed", lambda: True)
    monkeypatch.setattr(
        upload,
        "upload_jobs",
        {
            "job-target": {"job_id": "job-target", "status": "processing"},
            "job-stale": {"job_id": "job-stale", "status": "pending"},
        },
    )

    upload.save_upload_job("job-target")

    assert saved_payloads == [
        {"job-target": {"job_id": "job-target", "status": "processing"}}
    ]


def test_postgres_store_releases_connection_permit_when_pool_creation_fails(monkeypatch):
    store = PostgresUploadJobStore(
        "postgresql://user:pass@127.0.0.1:5432/onerag",
        min_connections=1,
        max_connections=1,
    )
    store.pool_wait_timeout = 1
    calls = 0

    def fail_pool_creation():
        nonlocal calls
        calls += 1
        raise RuntimeError("pool unavailable")

    monkeypatch.setattr(store, "_get_pool", fail_pool_creation)

    # 풀 생성 실패가 세마포어 permit을 소진하면 두 번째 호출이 hang/timeout 된다.
    with pytest.raises(RuntimeError, match="pool unavailable"):
        store.load_all()
    with pytest.raises(RuntimeError, match="pool unavailable"):
        store.load_all()
    assert calls == 2


def test_postgres_payload_merge_protects_newer_cancel_and_terminal_state():
    assert _should_preserve_existing_payload(
        {"status": "cancelling", "cancel_requested": True},
        {"status": "processing", "progress": 50, "cancel_requested": False},
    )
    assert _should_preserve_existing_payload(
        {"status": "completed", "progress": 100},
        {"status": "processing", "progress": 70},
    )
    assert not _should_preserve_existing_payload(
        {"status": "cancelling", "cancel_requested": True},
        {"status": "completed", "progress": 100},
    )
    assert not _should_preserve_existing_payload(
        {"status": "failed", "retry_count": 0},
        {"status": "pending", "retry_count": 1, "retried_at": 100.0},
    )


@pytest.mark.asyncio
async def test_shared_store_worker_entrypoint_uses_atomic_claim(monkeypatch, tmp_path):
    calls: list[str] = []

    class FakeStore:
        def recover_stale(self):
            calls.append("recover_stale")
            return 0

        def claim_next(self, *, worker_id, lease_seconds=300):
            calls.append(f"claim_next:{worker_id}:{lease_seconds}")
            return {
                "job_id": "job-claim",
                "status": "processing",
                "filename": "doc.txt",
                "file_type": "txt",
                "temp_file_path": str(tmp_path / "doc.txt"),
            }

        def update_claimed_job(self, *, job_id, worker_id, updates, lease_seconds=300, now=None):
            calls.append(f"update_claimed_job:{job_id}:{worker_id}:{lease_seconds}")
            return {
                "job_id": job_id,
                "status": "processing",
                "filename": "doc.txt",
                "file_type": "txt",
                "temp_file_path": str(tmp_path / "doc.txt"),
                **updates,
            }

    async def fake_process_document_background(job_id, file_path, filename, file_type):
        calls.append(f"process:{job_id}")
        upload.upload_jobs[job_id]["status"] = "completed"

    monkeypatch.setattr(upload, "_is_shared_upload_job_store", lambda: True)
    monkeypatch.setattr(upload, "_resolve_upload_job_store", lambda: FakeStore())
    monkeypatch.setattr(upload, "_reload_upload_jobs_if_needed", lambda job_id=None: None)
    monkeypatch.setattr(
        upload,
        "process_document_background",
        fake_process_document_background,
    )
    monkeypatch.setattr(upload, "upload_jobs", {})

    result = await upload.process_queued_upload_job_once(worker_id="worker-a")

    assert result == {"processed": True, "job_id": "job-claim", "status": "completed"}
    assert calls[:2] == ["recover_stale", "claim_next:worker-a:7200"]
    assert "update_claimed_job:job-claim:worker-a:7200" in calls
    assert "process:job-claim" in calls


def test_cleanup_upload_jobs_removes_only_expired_terminal_jobs():
    jobs = {
        "completed-old": {
            "job_id": "completed-old",
            "status": "completed",
            "completed_at": 100.0,
        },
        "failed-old": {
            "job_id": "failed-old",
            "status": "failed",
            "failed_at": 200.0,
        },
        "completed-fresh": {
            "job_id": "completed-fresh",
            "status": "completed",
            "completed_at": 950.0,
        },
        "processing-old": {
            "job_id": "processing-old",
            "status": "processing",
            "start_time": 100.0,
        },
    }

    removed_count = upload.cleanup_upload_jobs(jobs, now=1000.0, retention_seconds=300)

    assert removed_count == 2
    assert set(jobs) == {"completed-fresh", "processing-old"}


def test_cleanup_upload_jobs_can_be_disabled():
    jobs = {
        "completed-old": {
            "job_id": "completed-old",
            "status": "completed",
            "completed_at": 100.0,
        }
    }

    removed_count = upload.cleanup_upload_jobs(jobs, now=1000.0, retention_seconds=0)

    assert removed_count == 0
    assert set(jobs) == {"completed-old"}
