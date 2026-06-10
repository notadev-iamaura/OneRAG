"""
업로드 잡 스토어 동기화 동작 테스트 (Phase 4.8)

목적:
    SQLite store의 save_all 전체 동기화 동작(단일 워커 전제)을 고정하고,
    save_upload_job이 단건만 저장(공유 스토어에서 무관 행 보존)함을 검증한다.
    멀티워커 잡 유실 방어가 회귀하지 않도록 한다.
"""

from __future__ import annotations

from pathlib import Path

from app.api.upload_job_store import SQLiteUploadJobStore


def _job(job_id: str) -> dict:
    return {"job_id": job_id, "status": "pending", "progress": 0}


def test_sqlite_save_all_full_sync(tmp_path: Path) -> None:
    """단일 워커 전제: 전체 맵 저장 시 incoming 잡만 유지된다."""
    store = SQLiteUploadJobStore(tmp_path / "jobs.db")
    store.save_all({"a": _job("a"), "b": _job("b")})
    assert set(store.load_all()) == {"a", "b"}

    # 전체 맵에서 a만 저장 → b 제거 (단일 워커 동기화 동작)
    store.save_all({"a": _job("a")})
    assert set(store.load_all()) == {"a"}


def test_sqlite_upsert_preserves_existing_when_included(tmp_path: Path) -> None:
    """incoming에 포함된 기존 잡은 보존(upsert)되어야 한다."""
    store = SQLiteUploadJobStore(tmp_path / "jobs.db")
    store.save_all({"a": _job("a"), "b": _job("b")})
    # 둘 다 포함해 저장 → 둘 다 유지
    store.save_all({"a": _job("a"), "b": _job("b")})
    assert set(store.load_all()) == {"a", "b"}
