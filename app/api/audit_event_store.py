"""운영 감사 이벤트 스토어 (append-only).

파괴적 운영 작업(문서 삭제/일괄 삭제 등)을 영속·질의 가능한 감사 레코드로
남기기 위한 모듈입니다. 의존성 0(파이썬 표준 라이브러리 sqlite3만 사용)을 원칙으로
하며, 기본 백엔드는 SQLite(WAL)입니다.

주요 구성:
    - AuditEventStore: 감사 이벤트 기록 계약(Protocol)
    - SQLiteAuditEventStore: SQLite 기반 append-only 구현(로컬/단일 인스턴스 기준선)
    - safe_audit_identifier: 경로/URL형 식별자를 sha256으로 레덕션하는 헬퍼

설계 노트:
    - JapanRAG의 멀티테넌트(company_id NOT NULL) 모델을 OneRAG 단일 테넌트에 맞춰
      nullable로 일반화하고, 누락 시 'default'로 채운다(범용성).
    - 기록 실패를 호출자에게 전파하지 않는 non-blocking 사용은 호출부
      (upload.py의 _record_operational_audit_event)에서 보장한다.
    - 추후 Cloud SQL/PostgreSQL 어댑터로 교체 가능하도록 테이블 형태를 단순하게 유지.

의존성: 표준 라이브러리(sqlite3, json, hashlib)만 사용. 외부 패키지 없음.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

# 단일 테넌트 기본 company_id (멀티테넌트 일반화용 기본값)
DEFAULT_AUDIT_COMPANY_ID = "default"


class AuditEventStore(Protocol):
    """append-only 운영 감사 이벤트 저장 계약."""

    def record_event(self, event: dict[str, Any]) -> dict[str, Any]:
        """감사 이벤트 1건을 영속하고 저장된 페이로드를 반환한다."""


class SQLiteAuditEventStore:
    """SQLite 기반 append-only 감사 이벤트 스토어.

    로컬/단일 인스턴스 기준선이며, 테이블 형태는 프로덕션 ERD 방향을 따르되
    의존성 없이 유지한다. 추후 Cloud SQL/PostgreSQL 어댑터로 교체 가능하다.
    """

    def __init__(self, path: Path) -> None:
        """스토어를 초기화한다.

        Args:
            path: SQLite 데이터베이스 파일 경로.
        """
        self.path = path

    def record_event(self, event: dict[str, Any]) -> dict[str, Any]:
        """감사 이벤트 1건을 기록한다.

        Args:
            event: 감사 이벤트 딕셔너리. action/target_type은 필수.

        Returns:
            정규화·저장된 이벤트 페이로드.
        """
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = _stored_event_payload(event)
        with self._connect() as connection:
            self._ensure_schema(connection)
            connection.execute(
                """
                INSERT INTO audit_events (
                    event_id,
                    company_id,
                    action,
                    target_type,
                    target_id,
                    document_id,
                    source_id,
                    page,
                    chunk,
                    metadata,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload["event_id"],
                    payload["company_id"],
                    payload["action"],
                    payload["target_type"],
                    payload["target_id"],
                    payload["document_id"],
                    payload["source_id"],
                    payload["page"],
                    payload["chunk"],
                    json.dumps(payload["metadata"], ensure_ascii=False, default=str),
                    payload["created_at"],
                ),
            )
            connection.commit()
        return payload

    def list_events(self, company_id: str | None = None) -> list[dict[str, Any]]:
        """기록된 감사 이벤트를 시간순으로 조회한다.

        Args:
            company_id: 지정 시 해당 테넌트만 필터링. None이면 전체.

        Returns:
            이벤트 딕셔너리 목록. DB 파일이 없으면 빈 목록.
        """
        if not self.path.exists():
            return []
        with self._connect() as connection:
            self._ensure_schema(connection)
            if company_id is None:
                rows = connection.execute(
                    """
                    SELECT event_id, company_id, action, target_type, target_id,
                           document_id, source_id, page, chunk, metadata, created_at
                    FROM audit_events
                    ORDER BY created_at, event_id
                    """
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT event_id, company_id, action, target_type, target_id,
                           document_id, source_id, page, chunk, metadata, created_at
                    FROM audit_events
                    WHERE company_id = ?
                    ORDER BY created_at, event_id
                    """,
                    (company_id,),
                ).fetchall()
        return [_event_from_row(row) for row in rows]

    def _connect(self) -> sqlite3.Connection:
        """WAL 모드 연결을 생성한다(동시 읽기 안전성)."""
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    def _ensure_schema(self, connection: sqlite3.Connection) -> None:
        """테이블/인덱스를 멱등 생성한다(company_id는 nullable로 일반화)."""
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS audit_events (
                event_id TEXT PRIMARY KEY,
                company_id TEXT,
                action TEXT NOT NULL,
                target_type TEXT NOT NULL,
                target_id TEXT NOT NULL,
                document_id TEXT,
                source_id TEXT,
                page INTEGER,
                chunk INTEGER,
                metadata TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_audit_events_company_created
            ON audit_events(company_id, created_at)
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_audit_events_target
            ON audit_events(target_type, target_id)
            """
        )


def _stored_event_payload(event: dict[str, Any]) -> dict[str, Any]:
    """입력 이벤트를 저장 가능한 정규 페이로드로 변환한다.

    - company_id 누락 시 단일 테넌트 기본값으로 채운다.
    - 식별자류는 safe_audit_identifier로 경로/URL 노출을 차단한다.
    """
    now = datetime.now().isoformat()
    document_id = safe_audit_identifier(event.get("document_id"))
    source_id = safe_audit_identifier(event.get("source_id"))
    target_id = safe_audit_identifier(event.get("target_id"))
    company_id = event.get("company_id")
    return {
        "event_id": str(event.get("event_id") or uuid4()),
        "company_id": str(company_id) if company_id else DEFAULT_AUDIT_COMPANY_ID,
        "action": str(event["action"]),
        "target_type": str(event["target_type"]),
        "target_id": target_id or f"audit-target:{uuid4().hex}",
        "document_id": document_id,
        "source_id": source_id,
        "page": _optional_int(event.get("page")),
        "chunk": _optional_int(event.get("chunk")),
        "metadata": event.get("metadata") if isinstance(event.get("metadata"), dict) else {},
        "created_at": str(event.get("created_at") or now),
    }


def _event_from_row(row: sqlite3.Row) -> dict[str, Any]:
    """SQLite Row를 이벤트 딕셔너리로 복원한다."""
    return {
        "event_id": row["event_id"],
        "company_id": row["company_id"],
        "action": row["action"],
        "target_type": row["target_type"],
        "target_id": row["target_id"],
        "document_id": row["document_id"],
        "source_id": row["source_id"],
        "page": row["page"],
        "chunk": row["chunk"],
        "metadata": json.loads(row["metadata"]) if row["metadata"] else {},
        "created_at": row["created_at"],
    }


def safe_audit_identifier(value: Any) -> str | None:
    """식별자를 감사 기록용으로 안전하게 정규화한다.

    경로/URL형 식별자는 원본 노출을 막기 위해 sha256 단축 다이제스트로 레덕션한다.

    Args:
        value: 원본 식별자(문서 id, 소스 id 등).

    Returns:
        안전한 식별자 문자열. 비어 있으면 None.
    """
    raw_value = _optional_str(value)
    if raw_value is None or raw_value == "":
        return None
    if _is_private_identifier(raw_value):
        digest = hashlib.sha256(raw_value.encode("utf-8")).hexdigest()[:16]
        return f"redacted-sha256:{digest}"
    return raw_value


def _is_private_identifier(value: str) -> bool:
    """경로/URL 등 민감한 형태의 식별자인지 판단한다."""
    return (
        "://" in value
        or value.startswith(("/", "~"))
        or "\\" in value
        or "/tmp" in value
        or "/private" in value
    )


def _optional_str(value: Any) -> str | None:
    """None이 아니면 문자열로 변환한다."""
    if value is None:
        return None
    return str(value)


def _optional_int(value: Any) -> int | None:
    """정수 변환 가능하면 int로, 아니면 None을 반환한다(bool 제외)."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
