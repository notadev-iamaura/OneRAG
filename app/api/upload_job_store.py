"""Durable upload job storage adapters."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

TERMINAL_JOB_STATUSES = {"completed", "failed", "cancelled"}
REQUEUE_JOB_STATUSES = {"pending", "queued", "retrying"}
CANCELLATION_JOB_STATUSES = {"cancelling", "cancelled"}


class UploadJobStore(Protocol):
    """Storage contract for upload job state."""

    def load_all(self) -> dict[str, dict[str, Any]]:
        """Return all known upload jobs keyed by job id."""

    def save_all(self, jobs: dict[str, dict[str, Any]]) -> None:
        """Persist the complete in-memory job map."""


class JsonUploadJobStore:
    """Local JSON fallback for development-only upload job state."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def load_all(self) -> dict[str, dict[str, Any]]:
        if not self.path.exists():
            return {}
        with self.path.open(encoding="utf-8") as file:
            loaded_data = json.load(file)
        return dict(loaded_data) if isinstance(loaded_data, dict) else {}

    def save_all(self, jobs: dict[str, dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.path.with_suffix(f"{self.path.suffix}.tmp")
        with temp_path.open("w", encoding="utf-8") as file:
            json.dump(jobs, file, ensure_ascii=False, indent=2, default=str)
        temp_path.replace(self.path)


class PostgresUploadJobStore:
    """PostgreSQL-backed shared upload job store for autoscaled Cloud Run.

    The public contract mirrors ``SQLiteUploadJobStore`` but intentionally avoids
    deleting jobs that are absent from the caller's in-memory map. Autoscaled
    instances only know their own local jobs, so full-map deletion would let one
    instance remove another instance's active uploads.
    """

    def __init__(
        self,
        database_url: str | None = None,
        *,
        min_connections: int | None = None,
        max_connections: int | None = None,
    ) -> None:
        resolved_url = database_url or os.getenv("ONERAG_UPLOAD_JOB_DATABASE_URL")
        resolved_url = resolved_url or os.getenv("DATABASE_URL")
        if not resolved_url:
            raise ValueError("DATABASE_URL is required for PostgresUploadJobStore")
        if resolved_url.startswith("postgres://"):
            resolved_url = resolved_url.replace("postgres://", "postgresql://", 1)
        self.database_url = resolved_url
        self.min_connections = max(1, int(min_connections or _env_int("ONERAG_UPLOAD_JOB_DB_POOL_MIN", 1)))
        self.max_connections = max(
            self.min_connections,
            int(max_connections or _env_int("ONERAG_UPLOAD_JOB_DB_POOL_MAX", 3)),
        )
        self._pool: Any | None = None
        self._pool_lock = threading.Lock()
        self._connection_semaphore = threading.BoundedSemaphore(self.max_connections)
        self.pool_wait_timeout = max(1, _env_int("ONERAG_UPLOAD_JOB_DB_POOL_WAIT_TIMEOUT", 10))
        self._schema_ready = False

    def load_all(self) -> dict[str, dict[str, Any]]:
        with self._connection() as connection:
            self._ensure_schema(connection)
            with connection.cursor() as cursor:
                cursor.execute("SELECT job_id, payload FROM upload_jobs")
                rows = cursor.fetchall()
        jobs: dict[str, dict[str, Any]] = {}
        for job_id, payload in rows:
            decoded = _decode_json_payload(payload)
            if isinstance(decoded, dict):
                jobs[str(job_id)] = decoded
        return jobs

    def cleanup_expired(self, *, retention_seconds: int, now: float | None = None) -> int:
        if retention_seconds <= 0:
            return 0
        now_timestamp = _now_timestamp(now)
        cutoff = datetime.fromtimestamp(now_timestamp - retention_seconds).isoformat()
        with self._connection() as connection:
            self._ensure_schema(connection)
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    DELETE FROM upload_jobs
                    WHERE status IN ('completed', 'failed', 'cancelled')
                    AND updated_at < %s
                    """,
                    (cutoff,),
                )
                deleted_count = cursor.rowcount
            connection.commit()
        return deleted_count

    def save_all(self, jobs: dict[str, dict[str, Any]]) -> None:
        with self._connection() as connection:
            self._ensure_schema(connection)
            with connection.cursor() as cursor:
                for job_id, job in jobs.items():
                    previous_job = self._get_payload(cursor, job_id)
                    self._upsert_job(cursor, job_id, job, previous_job)
            connection.commit()

    def delete(self, job_id: str, company_id: str | None = None) -> bool:
        with self._connection() as connection:
            self._ensure_schema(connection)
            with connection.cursor() as cursor:
                if company_id is None:
                    cursor.execute("DELETE FROM upload_jobs WHERE job_id = %s", (job_id,))
                else:
                    cursor.execute(
                        "DELETE FROM upload_jobs WHERE job_id = %s AND company_id = %s",
                        (job_id, company_id),
                    )
                deleted_count = cursor.rowcount
            connection.commit()
        return deleted_count > 0

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._connection() as connection:
            self._ensure_schema(connection)
            with connection.cursor() as cursor:
                return self._get_payload(cursor, job_id)

    def list_events(self, job_id: str) -> list[dict[str, Any]]:
        with self._connection() as connection:
            self._ensure_schema(connection)
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT event_id, job_id, company_id, event_type, message, progress, metadata, created_at
                    FROM upload_job_events
                    WHERE job_id = %s
                    ORDER BY created_at, event_id
                    """,
                    (job_id,),
                )
                rows = cursor.fetchall()
        events: list[dict[str, Any]] = []
        for row in rows:
            metadata = _decode_json_payload(row[6]) or {}
            events.append(
                {
                    "event_id": row[0],
                    "job_id": row[1],
                    "company_id": row[2],
                    "event_type": row[3],
                    "message": row[4],
                    "progress": row[5],
                    "metadata": metadata,
                    "created_at": row[7].isoformat() if hasattr(row[7], "isoformat") else row[7],
                }
            )
        return events

    def claim_next(
        self,
        *,
        worker_id: str,
        lease_seconds: int = 300,
        now: float | None = None,
    ) -> dict[str, Any] | None:
        now_timestamp = _now_timestamp(now)
        with self._connection() as connection:
            self._ensure_schema(connection)
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT job_id, payload
                    FROM upload_jobs
                    WHERE status IN ('pending', 'queued', 'retrying')
                    ORDER BY updated_at, job_id
                    LIMIT 1
                    FOR UPDATE SKIP LOCKED
                    """
                )
                row = cursor.fetchone()
                if row is None:
                    connection.rollback()
                    return None
                job_id = str(row[0])
                previous_payload = _decode_json_payload(row[1]) or {}
                payload = dict(previous_payload)
                payload["job_id"] = job_id
                payload["status"] = "processing"
                payload["progress"] = max(_optional_float(payload.get("progress")) or 0, 1)
                payload["message"] = "워커가 작업을 확보했습니다"
                payload["claimed_by"] = worker_id
                payload["claimed_at"] = now_timestamp
                payload["heartbeat_at"] = now_timestamp
                payload["lease_expires_at"] = now_timestamp + lease_seconds
                payload["attempt_count"] = int(payload.get("attempt_count") or 0) + 1
                self._upsert_job(cursor, job_id, payload, previous_payload)
                self._record_event(cursor, payload, "claimed", datetime.now().isoformat())
            connection.commit()
        return payload

    def heartbeat(
        self,
        *,
        job_id: str,
        worker_id: str,
        lease_seconds: int = 300,
        now: float | None = None,
        progress: float | None = None,
        message: str | None = None,
    ) -> bool:
        now_timestamp = _now_timestamp(now)
        with self._connection() as connection:
            self._ensure_schema(connection)
            with connection.cursor() as cursor:
                previous_payload = self._get_payload(cursor, job_id, for_update=True)
                if previous_payload is None:
                    connection.rollback()
                    return False
                payload = dict(previous_payload)
                if payload.get("claimed_by") != worker_id:
                    connection.rollback()
                    return False
                if payload.get("status") in {"completed", "failed", "cancelled"}:
                    connection.rollback()
                    return False
                payload["heartbeat_at"] = now_timestamp
                payload["lease_expires_at"] = now_timestamp + lease_seconds
                if progress is not None:
                    payload["progress"] = progress
                if message is not None:
                    payload["message"] = message
                self._upsert_job(cursor, job_id, payload, previous_payload)
            connection.commit()
        return True

    def update_claimed_job(
        self,
        *,
        job_id: str,
        worker_id: str,
        updates: dict[str, Any],
        lease_seconds: int = 300,
        now: float | None = None,
    ) -> dict[str, Any] | None:
        now_timestamp = _now_timestamp(now)
        with self._connection() as connection:
            self._ensure_schema(connection)
            with connection.cursor() as cursor:
                previous_payload = self._get_payload(cursor, job_id, for_update=True)
                if previous_payload is None or previous_payload.get("claimed_by") != worker_id:
                    connection.rollback()
                    return None
                if previous_payload.get("status") in {"completed", "failed", "cancelled"}:
                    connection.rollback()
                    return None
                payload = dict(previous_payload)
                payload.update(updates)
                if payload.get("status") in {"completed", "failed", "cancelled"}:
                    payload["claimed_by"] = None
                    payload["lease_expires_at"] = None
                    payload["heartbeat_at"] = None
                else:
                    payload["claimed_by"] = worker_id
                    payload["heartbeat_at"] = now_timestamp
                    payload["lease_expires_at"] = now_timestamp + lease_seconds
                self._upsert_job(cursor, job_id, payload, previous_payload)
            connection.commit()
        return payload

    def recover_stale(self, *, now: float | None = None) -> int:
        now_timestamp = _now_timestamp(now)
        recovered = 0
        with self._connection() as connection:
            self._ensure_schema(connection)
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT job_id, payload
                    FROM upload_jobs
                    WHERE status IN ('processing', 'parsing', 'chunking', 'embedding', 'indexing')
                    FOR UPDATE SKIP LOCKED
                    """
                )
                rows = cursor.fetchall()
                for job_id, raw_payload in rows:
                    previous_payload = _decode_json_payload(raw_payload) or {}
                    lease_expires_at = _optional_float(previous_payload.get("lease_expires_at"))
                    if lease_expires_at is None or lease_expires_at > now_timestamp:
                        continue
                    payload = dict(previous_payload)
                    payload["status"] = "queued"
                    payload["progress"] = 0
                    payload["message"] = "만료된 워커 lease가 복구되어 재대기 중입니다"
                    payload["claimed_by"] = None
                    payload["lease_expires_at"] = None
                    payload["heartbeat_at"] = None
                    payload["recovered_at"] = now_timestamp
                    self._upsert_job(cursor, str(job_id), payload, previous_payload)
                    self._record_event(
                        cursor,
                        payload,
                        "lease_recovered",
                        datetime.now().isoformat(),
                    )
                    recovered += 1
            connection.commit()
        return recovered

    def retry_job(self, *, job_id: str, company_id: str, now: float | None = None) -> bool:
        return self._requeue_terminal_job(
            job_id=job_id,
            company_id=company_id,
            allowed_statuses={"failed", "cancelled"},
            message="재처리 대기 중...",
            event_type="retried",
            now=now,
            retry=True,
        )

    def resume_job(self, *, job_id: str, company_id: str, now: float | None = None) -> bool:
        now_timestamp = _now_timestamp(now)
        with self._connection() as connection:
            self._ensure_schema(connection)
            with connection.cursor() as cursor:
                previous_payload = self._get_payload(cursor, job_id, company_id, for_update=True)
                if previous_payload is None:
                    connection.rollback()
                    return False
                status = str(previous_payload.get("status") or "")
                payload = dict(previous_payload)
                if status in {"queued", "retrying"}:
                    payload["message"] = "업로드 작업 재개 대기 중..."
                elif status in {"processing", "parsing", "chunking", "embedding", "indexing"}:
                    lease_expires_at = _optional_float(previous_payload.get("lease_expires_at"))
                    if lease_expires_at is not None and lease_expires_at > now_timestamp:
                        connection.rollback()
                        return False
                    payload["status"] = "queued"
                    payload["progress"] = 0
                    payload["message"] = "중단된 업로드 작업이 재개 대기 중입니다"
                    payload["claimed_by"] = None
                    payload["lease_expires_at"] = None
                    payload["heartbeat_at"] = None
                else:
                    connection.rollback()
                    return False
                payload["resume_count"] = int(payload.get("resume_count") or 0) + 1
                payload["resumed_at"] = now_timestamp
                payload["start_time"] = now_timestamp
                self._upsert_job(cursor, job_id, payload, previous_payload)
                self._record_event(cursor, payload, "resumed", datetime.now().isoformat())
            connection.commit()
        return True

    def reprocess_job(self, *, job_id: str, company_id: str, now: float | None = None) -> bool:
        return self._requeue_terminal_job(
            job_id=job_id,
            company_id=company_id,
            allowed_statuses={"completed", "failed", "cancelled"},
            message="문서 재처리 대기 중...",
            event_type="reprocessed",
            now=now,
            retry=False,
            require_original=True,
        )

    def cancel_job(self, *, job_id: str, company_id: str, now: float | None = None) -> bool:
        now_timestamp = _now_timestamp(now)
        with self._connection() as connection:
            self._ensure_schema(connection)
            with connection.cursor() as cursor:
                previous_payload = self._get_payload(cursor, job_id, company_id, for_update=True)
                if previous_payload is None:
                    connection.rollback()
                    return False
                if previous_payload.get("status") in {"completed", "failed", "cancelled"}:
                    connection.rollback()
                    return False
                payload = dict(previous_payload)
                payload["status"] = "cancelled"
                payload["progress"] = 0
                payload["message"] = "업로드 작업이 취소되었습니다"
                payload["claimed_by"] = None
                payload["lease_expires_at"] = None
                payload["heartbeat_at"] = None
                payload["cancelled_from_status"] = previous_payload.get("status")
                payload["cancelled_at"] = now_timestamp
                self._upsert_job(cursor, job_id, payload, previous_payload)
                self._record_event(cursor, payload, "cancelled", datetime.now().isoformat())
            connection.commit()
        return True

    @contextmanager
    def _connection(self) -> Iterator[Any]:
        if not self._connection_semaphore.acquire(timeout=self.pool_wait_timeout):
            raise RuntimeError("Timed out waiting for upload job database connection")
        connection = None
        try:
            pool = self._get_pool()
            connection = pool.getconn()
            yield connection
        except Exception:
            if connection is not None:
                connection.rollback()
            raise
        finally:
            try:
                if connection is not None:
                    connection.rollback()
            except Exception:
                pass
            if connection is not None:
                pool.putconn(connection)
            self._connection_semaphore.release()

    def _get_pool(self) -> Any:
        if self._pool is not None:
            return self._pool
        with self._pool_lock:
            if self._pool is None:
                try:
                    from psycopg2.pool import ThreadedConnectionPool
                except ImportError as error:
                    raise RuntimeError(
                        "psycopg2-binary is required for PostgresUploadJobStore"
                    ) from error
                self._pool = ThreadedConnectionPool(
                    self.min_connections,
                    self.max_connections,
                    dsn=self.database_url,
                    connect_timeout=_env_int("ONERAG_UPLOAD_JOB_DB_CONNECT_TIMEOUT", 10),
                )
        return self._pool

    def _ensure_schema(self, connection: Any) -> None:
        if self._schema_ready:
            return
        with self._pool_lock:
            if self._schema_ready:
                return
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS upload_jobs (
                        job_id TEXT PRIMARY KEY,
                        company_id TEXT,
                        status TEXT,
                        updated_at TIMESTAMPTZ NOT NULL,
                        payload JSONB NOT NULL
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS upload_job_events (
                        event_id TEXT PRIMARY KEY,
                        job_id TEXT NOT NULL REFERENCES upload_jobs(job_id) ON DELETE CASCADE,
                        company_id TEXT,
                        event_type TEXT NOT NULL,
                        message TEXT,
                        progress DOUBLE PRECISION,
                        metadata JSONB,
                        created_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
                cursor.execute(
                    "CREATE INDEX IF NOT EXISTS idx_upload_jobs_company ON upload_jobs(company_id)"
                )
                cursor.execute(
                    "CREATE INDEX IF NOT EXISTS idx_upload_jobs_status_updated ON upload_jobs(status, updated_at)"
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_upload_job_events_job
                    ON upload_job_events(job_id, created_at)
                    """
                )
            connection.commit()
            self._schema_ready = True

    def _get_payload(
        self,
        cursor: Any,
        job_id: str,
        company_id: str | None = None,
        *,
        for_update: bool = False,
    ) -> dict[str, Any] | None:
        query = "SELECT payload FROM upload_jobs WHERE job_id = %s"
        params: tuple[Any, ...] = (job_id,)
        if company_id is not None:
            query += " AND company_id = %s"
            params = (job_id, company_id)
        if for_update:
            query += " FOR UPDATE"
        cursor.execute(query, params)
        row = cursor.fetchone()
        if row is None:
            return None
        payload = _decode_json_payload(row[0])
        return payload if isinstance(payload, dict) else None

    def _upsert_job(
        self,
        cursor: Any,
        job_id: str,
        job: dict[str, Any],
        previous_job: dict[str, Any] | None,
    ) -> None:
        try:
            from psycopg2.extras import Json
        except ImportError as error:
            raise RuntimeError("psycopg2-binary is required for JSONB upload jobs") from error
        now = datetime.now().isoformat()
        payload = dict(job)
        if previous_job is not None and _should_preserve_existing_payload(
            previous_job,
            payload,
        ):
            job.clear()
            job.update(previous_job)
            return
        payload.setdefault("job_id", job_id)
        payload.setdefault("created_at", previous_job.get("created_at") if previous_job else now)
        payload["updated_at"] = now
        job.clear()
        job.update(payload)
        cursor.execute(
            """
            INSERT INTO upload_jobs (job_id, company_id, status, updated_at, payload)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT(job_id) DO UPDATE SET
                company_id = EXCLUDED.company_id,
                status = EXCLUDED.status,
                updated_at = EXCLUDED.updated_at,
                payload = EXCLUDED.payload
            """,
            (
                job_id,
                _optional_str(payload.get("company_id")),
                _optional_str(payload.get("status")),
                now,
                Json(payload),
            ),
        )
        event_type = self._event_type(previous_job, payload)
        if event_type:
            self._record_event(cursor, payload, event_type, now)

    def _event_type(self, previous_job: dict[str, Any] | None, job: dict[str, Any]) -> str | None:
        if previous_job is None:
            return "created"
        if previous_job.get("status") != job.get("status"):
            return "status_changed"
        if previous_job.get("progress") != job.get("progress") or previous_job.get(
            "message"
        ) != job.get("message"):
            return "progress_updated"
        return None

    def _record_event(
        self,
        cursor: Any,
        job: dict[str, Any],
        event_type: str,
        created_at: str,
    ) -> None:
        try:
            from psycopg2.extras import Json
        except ImportError as error:
            raise RuntimeError("psycopg2-binary is required for JSONB upload jobs") from error
        metadata = {
            "chunk_count": job.get("chunk_count"),
            "processing_time": job.get("processing_time"),
            "error_code": job.get("error_code"),
            "retry_count": job.get("retry_count"),
        }
        cursor.execute(
            """
            INSERT INTO upload_job_events (
                event_id, job_id, company_id, event_type, message, progress, metadata, created_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                str(uuid4()),
                str(job["job_id"]),
                _optional_str(job.get("company_id")),
                event_type,
                _optional_str(job.get("message")),
                _optional_float(job.get("progress")),
                Json(metadata),
                created_at,
            ),
        )

    def _requeue_terminal_job(
        self,
        *,
        job_id: str,
        company_id: str,
        allowed_statuses: set[str],
        message: str,
        event_type: str,
        now: float | None,
        retry: bool,
        require_original: bool = False,
    ) -> bool:
        now_timestamp = _now_timestamp(now)
        with self._connection() as connection:
            self._ensure_schema(connection)
            with connection.cursor() as cursor:
                previous_payload = self._get_payload(cursor, job_id, company_id, for_update=True)
                if previous_payload is None:
                    connection.rollback()
                    return False
                if previous_payload.get("status") not in allowed_statuses:
                    connection.rollback()
                    return False
                original_file_path = previous_payload.get("original_file_path")
                if require_original and not original_file_path:
                    connection.rollback()
                    return False
                payload = dict(previous_payload)
                payload["status"] = "retrying"
                payload["progress"] = 0
                payload["message"] = message
                payload["error_message"] = None
                payload["internal_error_message"] = None
                payload["claimed_by"] = None
                payload["lease_expires_at"] = None
                payload["heartbeat_at"] = None
                payload["start_time"] = now_timestamp
                if retry:
                    payload["retry_count"] = int(payload.get("retry_count") or 0) + 1
                    payload["retried_at"] = now_timestamp
                    if original_file_path:
                        payload["temp_file_path"] = original_file_path
                else:
                    payload["chunk_count"] = None
                    payload["processing_time"] = None
                    payload["extraction_summary"] = None
                    payload["temp_file_path"] = original_file_path
                    payload["document_ledger"] = True
                    payload["reprocess_count"] = int(payload.get("reprocess_count") or 0) + 1
                    payload["reprocessed_at"] = now_timestamp
                self._upsert_job(cursor, job_id, payload, previous_payload)
                self._record_event(cursor, payload, event_type, datetime.now().isoformat())
            connection.commit()
        return True


class SQLiteUploadJobStore:
    """SQLite-backed durable upload job store.

    This adapter is intentionally dependency-free. It gives local and single-node
    deployments transactional persistence and append-only job events while keeping
    the storage contract replaceable by a Cloud SQL/PostgreSQL adapter later.
    """

    def __init__(self, path: Path) -> None:
        self.path = path

    def load_all(self) -> dict[str, dict[str, Any]]:
        if not self.path.exists():
            return {}
        with self._connect() as connection:
            self._ensure_schema(connection)
            rows = connection.execute("SELECT job_id, payload FROM upload_jobs").fetchall()
        jobs: dict[str, dict[str, Any]] = {}
        for row in rows:
            payload = json.loads(row["payload"])
            if isinstance(payload, dict):
                jobs[str(row["job_id"])] = payload
        return jobs

    def save_all(self, jobs: dict[str, dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            self._ensure_schema(connection)
            connection.execute("BEGIN IMMEDIATE")
            existing_rows = connection.execute(
                "SELECT job_id, payload FROM upload_jobs"
            ).fetchall()
            existing_jobs = {
                str(row["job_id"]): json.loads(row["payload"]) for row in existing_rows
            }
            incoming_job_ids = set(jobs)
            for stale_job_id in set(existing_jobs) - incoming_job_ids:
                connection.execute(
                    "DELETE FROM upload_jobs WHERE job_id = ?",
                    (stale_job_id,),
                )
            for job_id, job in jobs.items():
                self._upsert_job(connection, job_id, job, existing_jobs.get(job_id))
            connection.commit()

    def delete(self, job_id: str, company_id: str | None = None) -> bool:
        if not self.path.exists():
            return False
        with self._connect() as connection:
            self._ensure_schema(connection)
            if company_id is None:
                cursor = connection.execute("DELETE FROM upload_jobs WHERE job_id = ?", (job_id,))
            else:
                cursor = connection.execute(
                    "DELETE FROM upload_jobs WHERE job_id = ? AND company_id = ?",
                    (job_id, company_id),
                )
            connection.commit()
        return cursor.rowcount > 0

    def get(self, job_id: str) -> dict[str, Any] | None:
        if not self.path.exists():
            return None
        with self._connect() as connection:
            self._ensure_schema(connection)
            row = connection.execute(
                "SELECT payload FROM upload_jobs WHERE job_id = ?",
                (job_id,),
            ).fetchone()
        if row is None:
            return None
        payload = json.loads(row["payload"])
        return payload if isinstance(payload, dict) else None

    def list_events(self, job_id: str) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        with self._connect() as connection:
            self._ensure_schema(connection)
            rows = connection.execute(
                """
                SELECT event_id, job_id, company_id, event_type, message, progress, metadata, created_at
                FROM upload_job_events
                WHERE job_id = ?
                ORDER BY created_at, event_id
                """,
                (job_id,),
            ).fetchall()
        events: list[dict[str, Any]] = []
        for row in rows:
            metadata = json.loads(row["metadata"]) if row["metadata"] else {}
            events.append(
                {
                    "event_id": row["event_id"],
                    "job_id": row["job_id"],
                    "company_id": row["company_id"],
                    "event_type": row["event_type"],
                    "message": row["message"],
                    "progress": row["progress"],
                    "metadata": metadata,
                    "created_at": row["created_at"],
                }
            )
        return events

    def claim_next(
        self,
        *,
        worker_id: str,
        lease_seconds: int = 300,
        now: float | None = None,
    ) -> dict[str, Any] | None:
        """Atomically claim the oldest queued job for a local worker."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        now_timestamp = _now_timestamp(now)
        with self._connect() as connection:
            self._ensure_schema(connection)
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT job_id, payload
                FROM upload_jobs
                WHERE status IN ('pending', 'queued', 'retrying')
                ORDER BY updated_at, job_id
                LIMIT 1
                """
            ).fetchone()
            if row is None:
                connection.rollback()
                return None
            job_id = str(row["job_id"])
            previous_payload = json.loads(row["payload"])
            payload = dict(previous_payload)
            payload["job_id"] = job_id
            payload["status"] = "processing"
            payload["progress"] = max(_optional_float(payload.get("progress")) or 0, 1)
            payload["message"] = "로컬 워커가 작업을 확보했습니다"
            payload["claimed_by"] = worker_id
            payload["claimed_at"] = now_timestamp
            payload["heartbeat_at"] = now_timestamp
            payload["lease_expires_at"] = now_timestamp + lease_seconds
            payload["attempt_count"] = int(payload.get("attempt_count") or 0) + 1
            self._upsert_job(connection, job_id, payload, previous_payload)
            self._record_event(
                connection,
                payload,
                "claimed",
                datetime.now().isoformat(),
            )
            connection.commit()
        return payload

    def heartbeat(
        self,
        *,
        job_id: str,
        worker_id: str,
        lease_seconds: int = 300,
        now: float | None = None,
        progress: float | None = None,
        message: str | None = None,
    ) -> bool:
        """Extend a claimed job lease for the claiming worker."""
        if not self.path.exists():
            return False
        now_timestamp = _now_timestamp(now)
        with self._connect() as connection:
            self._ensure_schema(connection)
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT payload FROM upload_jobs WHERE job_id = ?",
                (job_id,),
            ).fetchone()
            if row is None:
                connection.rollback()
                return False
            previous_payload = json.loads(row["payload"])
            payload = dict(previous_payload)
            if payload.get("claimed_by") != worker_id:
                connection.rollback()
                return False
            if payload.get("status") in {"completed", "failed", "cancelled"}:
                connection.rollback()
                return False
            payload["heartbeat_at"] = now_timestamp
            payload["lease_expires_at"] = now_timestamp + lease_seconds
            if progress is not None:
                payload["progress"] = progress
            if message is not None:
                payload["message"] = message
            self._upsert_job(connection, job_id, payload, previous_payload)
            connection.commit()
        return True

    def update_claimed_job(
        self,
        *,
        job_id: str,
        worker_id: str,
        updates: dict[str, Any],
        lease_seconds: int = 300,
        now: float | None = None,
    ) -> dict[str, Any] | None:
        """Atomically update a job only if the caller still owns its lease."""
        if not self.path.exists():
            return None
        now_timestamp = _now_timestamp(now)
        with self._connect() as connection:
            self._ensure_schema(connection)
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT payload FROM upload_jobs WHERE job_id = ?",
                (job_id,),
            ).fetchone()
            if row is None:
                connection.rollback()
                return None
            previous_payload = json.loads(row["payload"])
            if previous_payload.get("claimed_by") != worker_id:
                connection.rollback()
                return None
            if previous_payload.get("status") in {"completed", "failed", "cancelled"}:
                connection.rollback()
                return None
            payload = dict(previous_payload)
            payload.update(updates)
            if payload.get("status") in {"completed", "failed", "cancelled"}:
                payload["claimed_by"] = None
                payload["lease_expires_at"] = None
                payload["heartbeat_at"] = None
            else:
                payload["claimed_by"] = worker_id
                payload["heartbeat_at"] = now_timestamp
                payload["lease_expires_at"] = now_timestamp + lease_seconds
            self._upsert_job(connection, job_id, payload, previous_payload)
            connection.commit()
        return payload

    def recover_stale(
        self,
        *,
        now: float | None = None,
    ) -> int:
        """Return expired leased jobs to the queued state."""
        if not self.path.exists():
            return 0
        now_timestamp = _now_timestamp(now)
        recovered = 0
        with self._connect() as connection:
            self._ensure_schema(connection)
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                """
                SELECT job_id, payload
                FROM upload_jobs
                WHERE status IN ('processing', 'parsing', 'chunking', 'embedding', 'indexing')
                """
            ).fetchall()
            for row in rows:
                previous_payload = json.loads(row["payload"])
                lease_expires_at = _optional_float(previous_payload.get("lease_expires_at"))
                if lease_expires_at is None or lease_expires_at > now_timestamp:
                    continue
                payload = dict(previous_payload)
                payload["status"] = "queued"
                payload["progress"] = 0
                payload["message"] = "만료된 로컬 워커 lease가 복구되어 재대기 중입니다"
                payload["claimed_by"] = None
                payload["lease_expires_at"] = None
                payload["heartbeat_at"] = None
                payload["recovered_at"] = now_timestamp
                self._upsert_job(connection, str(row["job_id"]), payload, previous_payload)
                self._record_event(
                    connection,
                    payload,
                    "lease_recovered",
                    datetime.now().isoformat(),
                )
                recovered += 1
            connection.commit()
        return recovered

    def retry_job(
        self,
        *,
        job_id: str,
        company_id: str,
        now: float | None = None,
    ) -> bool:
        """Requeue a failed or cancelled job for the same company."""
        if not self.path.exists():
            return False
        now_timestamp = _now_timestamp(now)
        with self._connect() as connection:
            self._ensure_schema(connection)
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT payload FROM upload_jobs WHERE job_id = ? AND company_id = ?",
                (job_id, company_id),
            ).fetchone()
            if row is None:
                connection.rollback()
                return False
            previous_payload = json.loads(row["payload"])
            if previous_payload.get("status") not in {"failed", "cancelled"}:
                connection.rollback()
                return False
            payload = dict(previous_payload)
            payload["status"] = "retrying"
            payload["progress"] = 0
            payload["message"] = "재처리 대기 중..."
            payload["error_message"] = None
            payload["internal_error_message"] = None
            payload["claimed_by"] = None
            payload["lease_expires_at"] = None
            payload["heartbeat_at"] = None
            payload["retry_count"] = int(payload.get("retry_count") or 0) + 1
            payload["retried_at"] = now_timestamp
            payload["start_time"] = now_timestamp
            if payload.get("original_file_path"):
                payload["temp_file_path"] = payload["original_file_path"]
            self._upsert_job(connection, job_id, payload, previous_payload)
            self._record_event(
                connection,
                payload,
                "retried",
                datetime.now().isoformat(),
            )
            connection.commit()
        return True

    def resume_job(
        self,
        *,
        job_id: str,
        company_id: str,
        now: float | None = None,
    ) -> bool:
        """Resume a queued/retrying job or recover an interrupted leased job."""
        if not self.path.exists():
            return False
        now_timestamp = _now_timestamp(now)
        with self._connect() as connection:
            self._ensure_schema(connection)
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT payload FROM upload_jobs WHERE job_id = ? AND company_id = ?",
                (job_id, company_id),
            ).fetchone()
            if row is None:
                connection.rollback()
                return False
            previous_payload = json.loads(row["payload"])
            status = str(previous_payload.get("status") or "")
            payload = dict(previous_payload)
            if status in {"queued", "retrying"}:
                payload["message"] = "업로드 작업 재개 대기 중..."
            elif status in {"processing", "parsing", "chunking", "embedding", "indexing"}:
                lease_expires_at = _optional_float(previous_payload.get("lease_expires_at"))
                if lease_expires_at is not None and lease_expires_at > now_timestamp:
                    connection.rollback()
                    return False
                payload["status"] = "queued"
                payload["progress"] = 0
                payload["message"] = "중단된 업로드 작업이 재개 대기 중입니다"
                payload["claimed_by"] = None
                payload["lease_expires_at"] = None
                payload["heartbeat_at"] = None
            else:
                connection.rollback()
                return False
            payload["resume_count"] = int(payload.get("resume_count") or 0) + 1
            payload["resumed_at"] = now_timestamp
            payload["start_time"] = now_timestamp
            self._upsert_job(connection, job_id, payload, previous_payload)
            self._record_event(
                connection,
                payload,
                "resumed",
                datetime.now().isoformat(),
            )
            connection.commit()
        return True

    def reprocess_job(
        self,
        *,
        job_id: str,
        company_id: str,
        now: float | None = None,
    ) -> bool:
        """Requeue a terminal document job from its retained original file."""
        if not self.path.exists():
            return False
        now_timestamp = _now_timestamp(now)
        with self._connect() as connection:
            self._ensure_schema(connection)
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT payload FROM upload_jobs WHERE job_id = ? AND company_id = ?",
                (job_id, company_id),
            ).fetchone()
            if row is None:
                connection.rollback()
                return False
            previous_payload = json.loads(row["payload"])
            if previous_payload.get("status") not in {"completed", "failed", "cancelled"}:
                connection.rollback()
                return False
            original_file_path = previous_payload.get("original_file_path")
            if not original_file_path:
                connection.rollback()
                return False
            payload = dict(previous_payload)
            payload["status"] = "retrying"
            payload["progress"] = 0
            payload["message"] = "문서 재처리 대기 중..."
            payload["error_message"] = None
            payload["internal_error_message"] = None
            payload["chunk_count"] = None
            payload["processing_time"] = None
            payload["extraction_summary"] = None
            payload["claimed_by"] = None
            payload["lease_expires_at"] = None
            payload["heartbeat_at"] = None
            payload["temp_file_path"] = original_file_path
            payload["document_ledger"] = True
            payload["reprocess_count"] = int(payload.get("reprocess_count") or 0) + 1
            payload["reprocessed_at"] = now_timestamp
            payload["start_time"] = now_timestamp
            self._upsert_job(connection, job_id, payload, previous_payload)
            self._record_event(
                connection,
                payload,
                "reprocessed",
                datetime.now().isoformat(),
            )
            connection.commit()
        return True

    def cancel_job(
        self,
        *,
        job_id: str,
        company_id: str,
        now: float | None = None,
    ) -> bool:
        """Cancel a queued or in-progress job for the same company."""
        if not self.path.exists():
            return False
        now_timestamp = _now_timestamp(now)
        with self._connect() as connection:
            self._ensure_schema(connection)
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT payload FROM upload_jobs WHERE job_id = ? AND company_id = ?",
                (job_id, company_id),
            ).fetchone()
            if row is None:
                connection.rollback()
                return False
            previous_payload = json.loads(row["payload"])
            if previous_payload.get("status") in {"completed", "failed", "cancelled"}:
                connection.rollback()
                return False
            payload = dict(previous_payload)
            payload["status"] = "cancelled"
            payload["progress"] = 0
            payload["message"] = "업로드 작업이 취소되었습니다"
            payload["claimed_by"] = None
            payload["lease_expires_at"] = None
            payload["heartbeat_at"] = None
            payload["cancelled_from_status"] = previous_payload.get("status")
            payload["cancelled_at"] = now_timestamp
            self._upsert_job(connection, job_id, payload, previous_payload)
            self._record_event(
                connection,
                payload,
                "cancelled",
                datetime.now().isoformat(),
            )
            connection.commit()
        return True

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _ensure_schema(self, connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS upload_jobs (
                job_id TEXT PRIMARY KEY,
                company_id TEXT,
                status TEXT,
                updated_at TEXT NOT NULL,
                payload TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS upload_job_events (
                event_id TEXT PRIMARY KEY,
                job_id TEXT NOT NULL,
                company_id TEXT,
                event_type TEXT NOT NULL,
                message TEXT,
                progress REAL,
                metadata TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(job_id) REFERENCES upload_jobs(job_id) ON DELETE CASCADE
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_upload_jobs_company ON upload_jobs(company_id)"
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_upload_job_events_job
            ON upload_job_events(job_id, created_at)
            """
        )

    def _upsert_job(
        self,
        connection: sqlite3.Connection,
        job_id: str,
        job: dict[str, Any],
        previous_job: dict[str, Any] | None,
    ) -> None:
        now = datetime.now().isoformat()
        payload = dict(job)
        payload.setdefault("job_id", job_id)
        payload.setdefault("created_at", previous_job.get("created_at") if previous_job else now)
        payload["updated_at"] = now
        job.clear()
        job.update(payload)
        connection.execute(
            """
            INSERT INTO upload_jobs (job_id, company_id, status, updated_at, payload)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(job_id) DO UPDATE SET
                company_id = excluded.company_id,
                status = excluded.status,
                updated_at = excluded.updated_at,
                payload = excluded.payload
            """,
            (
                job_id,
                _optional_str(payload.get("company_id")),
                _optional_str(payload.get("status")),
                now,
                json.dumps(payload, ensure_ascii=False, default=str),
            ),
        )
        event_type = self._event_type(previous_job, payload)
        if event_type:
            self._record_event(connection, payload, event_type, now)

    def _event_type(
        self, previous_job: dict[str, Any] | None, job: dict[str, Any]
    ) -> str | None:
        if previous_job is None:
            return "created"
        if previous_job.get("status") != job.get("status"):
            return "status_changed"
        if (
            previous_job.get("progress") != job.get("progress")
            or previous_job.get("message") != job.get("message")
        ):
            return "progress_updated"
        return None

    def _record_event(
        self,
        connection: sqlite3.Connection,
        job: dict[str, Any],
        event_type: str,
        created_at: str,
    ) -> None:
        metadata = {
            "chunk_count": job.get("chunk_count"),
            "processing_time": job.get("processing_time"),
            "error_code": job.get("error_code"),
            "retry_count": job.get("retry_count"),
        }
        connection.execute(
            """
            INSERT INTO upload_job_events (
                event_id, job_id, company_id, event_type, message, progress, metadata, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid4()),
                str(job["job_id"]),
                _optional_str(job.get("company_id")),
                event_type,
                _optional_str(job.get("message")),
                _optional_float(job.get("progress")),
                json.dumps(metadata, ensure_ascii=False, default=str),
                created_at,
            ),
        )


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _should_preserve_existing_payload(
    previous_job: dict[str, Any],
    incoming_job: dict[str, Any],
) -> bool:
    previous_status = str(previous_job.get("status") or "")
    incoming_status = str(incoming_job.get("status") or "")
    if previous_status in TERMINAL_JOB_STATUSES and incoming_status != previous_status:
        if incoming_status in REQUEUE_JOB_STATUSES and (
            incoming_job.get("retried_at") or incoming_job.get("reprocessed_at")
        ):
            return False
        return True
    if (
        previous_status in CANCELLATION_JOB_STATUSES
        and incoming_status not in CANCELLATION_JOB_STATUSES
        and incoming_status not in TERMINAL_JOB_STATUSES
    ):
        return True
    if (
        previous_job.get("cancel_requested") is True
        and incoming_job.get("cancel_requested") is not True
        and incoming_status not in TERMINAL_JOB_STATUSES
    ):
        return True
    return False


def _now_timestamp(value: float | None = None) -> float:
    if value is not None:
        return float(value)
    return datetime.now().timestamp()


def _decode_json_payload(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if value is None:
        return None
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    if isinstance(value, str):
        return json.loads(value)
    return value


def _env_int(name: str, default: int) -> int:
    raw_value = os.getenv(name)
    if raw_value in (None, ""):
        return default
    try:
        return int(str(raw_value))
    except ValueError:
        return default
