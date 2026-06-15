"""운영 감사 이벤트 스토어(SQLiteAuditEventStore) 단위 테스트.

검증 대상(#36):
    - append-only 기록 및 조회 라운드트립
    - 경로/URL형 식별자의 sha256 레덕션(safe_audit_identifier)
    - company_id nullable 일반화(단일 테넌트 기본값 허용)
    - 기록 실패가 호출자를 막지 않는 non-blocking 설계는 upload 통합 테스트에서 검증
"""

from __future__ import annotations

from pathlib import Path

from app.api.audit_event_store import (
    SQLiteAuditEventStore,
    safe_audit_identifier,
)


def test_record_and_list_round_trip(tmp_path: Path) -> None:
    """이벤트를 기록하면 동일 페이로드를 조회할 수 있어야 한다."""
    store = SQLiteAuditEventStore(tmp_path / "audit.sqlite3")
    stored = store.record_event(
        {
            "action": "document.delete.succeeded",
            "target_type": "document",
            "target_id": "doc-1",
            "document_id": "doc-1",
            "metadata": {"requested_by": "admin"},
        }
    )
    assert stored["event_id"]
    assert stored["action"] == "document.delete.succeeded"
    events = store.list_events()
    assert len(events) == 1
    assert events[0]["target_id"] == "doc-1"
    assert events[0]["metadata"] == {"requested_by": "admin"}


def test_company_id_defaults_when_missing(tmp_path: Path) -> None:
    """company_id가 없으면 단일 테넌트 기본값('default')으로 일반화되어야 한다."""
    store = SQLiteAuditEventStore(tmp_path / "audit.sqlite3")
    stored = store.record_event(
        {
            "action": "document.delete_all",
            "target_type": "collection",
            "target_id": "all",
        }
    )
    assert stored["company_id"] == "default"
    # company_id 필터 없이도 조회 가능
    assert len(store.list_events()) == 1
    # 기본값으로 필터링도 가능
    assert len(store.list_events(company_id="default")) == 1


def test_safe_audit_identifier_redacts_paths_and_urls() -> None:
    """로컬 경로/URL형 식별자는 sha256으로 레덕션되어야 한다."""
    assert safe_audit_identifier(None) is None
    assert safe_audit_identifier("") is None
    # 일반 문서 id는 그대로 보존
    assert safe_audit_identifier("doc-123") == "doc-123"
    # 경로/URL은 레덕션
    redacted = safe_audit_identifier("/tmp/uploads/secret.pdf")
    assert redacted is not None and redacted.startswith("redacted-sha256:")
    assert "secret.pdf" not in redacted
    assert safe_audit_identifier("https://bucket/key").startswith("redacted-sha256:")


def test_target_id_redaction_applied_on_record(tmp_path: Path) -> None:
    """기록 시 target_id/document_id도 레덕션 규칙이 적용되어야 한다."""
    store = SQLiteAuditEventStore(tmp_path / "audit.sqlite3")
    stored = store.record_event(
        {
            "action": "document.delete.succeeded",
            "target_type": "document",
            "target_id": "/var/data/private.bin",
        }
    )
    assert stored["target_id"].startswith("redacted-sha256:")


def test_list_empty_when_no_database(tmp_path: Path) -> None:
    """DB 파일이 없으면 빈 목록을 반환해야 한다(조회만으로 파일 생성 금지)."""
    store = SQLiteAuditEventStore(tmp_path / "missing.sqlite3")
    assert store.list_events() == []
