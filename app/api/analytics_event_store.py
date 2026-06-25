"""Durable application analytics events.

The store intentionally avoids raw questions, answers, IP addresses, and direct
personal identifiers. Visitor/session ids are hashed with a server-side salt.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import RLock
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

DEFAULT_ANALYTICS_DB_FILE = Path("./uploads/analytics_events.sqlite3")
_STORE: SQLiteAnalyticsEventStore | None = None

SAFE_METADATA_KEYS = {
    "channel",
    "locale",
    "origin",
    "embed_id",
    "route",
    "status",
    "source",
}
SENSITIVE_KEY_PARTS = ("key", "secret", "token", "password", "email", "phone", "contact")


class SQLiteAnalyticsEventStore:
    """SQLite-backed analytics event store."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = RLock()

    def record_event(self, event: dict[str, Any]) -> dict[str, Any]:
        payload = _normalize_event(event)
        with self._lock, self._connect() as connection:
            self._ensure_schema(connection)
            connection.execute(
                """
                INSERT OR IGNORE INTO analytics_events (
                    event_id,
                    event_type,
                    occurred_at,
                    visitor_id_hash,
                    session_id_hash,
                    message_id,
                    channel,
                    route,
                    referrer_origin,
                    model_provider,
                    model_name,
                    input_tokens,
                    output_tokens,
                    total_tokens,
                    estimated_cost_usd,
                    latency_ms,
                    success,
                    error_code,
                    langfuse_trace_id,
                    metadata
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload["event_id"],
                    payload["event_type"],
                    payload["occurred_at"],
                    payload["visitor_id_hash"],
                    payload["session_id_hash"],
                    payload["message_id"],
                    payload["channel"],
                    payload["route"],
                    payload["referrer_origin"],
                    payload["model_provider"],
                    payload["model_name"],
                    payload["input_tokens"],
                    payload["output_tokens"],
                    payload["total_tokens"],
                    payload["estimated_cost_usd"],
                    payload["latency_ms"],
                    1 if payload["success"] else 0,
                    payload["error_code"],
                    payload["langfuse_trace_id"],
                    json.dumps(payload["metadata"], ensure_ascii=False, default=str),
                ),
            )
            connection.commit()
        return payload

    def summary(self, *, days: int = 365) -> dict[str, Any]:
        since = _since(days)
        with self._connect() as connection:
            self._ensure_schema(connection)
            row = connection.execute(
                """
                SELECT
                    COUNT(DISTINCT visitor_id_hash) AS visitors,
                    COUNT(DISTINCT session_id_hash) AS sessions,
                    SUM(CASE WHEN event_type = 'question_submitted' THEN 1 ELSE 0 END) AS questions,
                    SUM(CASE WHEN event_type = 'answer_completed' THEN 1 ELSE 0 END) AS answers,
                    COALESCE(SUM(total_tokens), 0) AS total_tokens,
                    COALESCE(SUM(estimated_cost_usd), 0) AS estimated_cost_usd,
                    COALESCE(AVG(CASE WHEN latency_ms > 0 THEN latency_ms END), 0) AS avg_latency_ms
                FROM analytics_events
                WHERE occurred_at >= ?
                """,
                (since,),
            ).fetchone()
        return {
            "periodDays": days,
            "visitors": int(row["visitors"] or 0),
            "sessions": int(row["sessions"] or 0),
            "questions": int(row["questions"] or 0),
            "answers": int(row["answers"] or 0),
            "totalTokens": int(row["total_tokens"] or 0),
            "estimatedCostUsd": float(row["estimated_cost_usd"] or 0.0),
            "avgLatencyMs": float(row["avg_latency_ms"] or 0.0),
        }

    def timeseries(self, *, months: int = 12, grain: str = "month") -> list[dict[str, Any]]:
        since = _since(max(1, min(months, 60)) * 31)
        bucket_expr = "substr(occurred_at, 1, 7)" if grain == "month" else "substr(occurred_at, 1, 10)"
        with self._connect() as connection:
            self._ensure_schema(connection)
            rows = connection.execute(
                f"""
                SELECT
                    {bucket_expr} AS bucket,
                    COUNT(DISTINCT visitor_id_hash) AS visitors,
                    COUNT(DISTINCT session_id_hash) AS sessions,
                    SUM(CASE WHEN event_type = 'question_submitted' THEN 1 ELSE 0 END) AS questions,
                    SUM(CASE WHEN event_type = 'answer_completed' THEN 1 ELSE 0 END) AS answers,
                    COALESCE(SUM(total_tokens), 0) AS total_tokens,
                    COALESCE(SUM(estimated_cost_usd), 0) AS estimated_cost_usd,
                    COALESCE(AVG(CASE WHEN latency_ms > 0 THEN latency_ms END), 0) AS avg_latency_ms
                FROM analytics_events
                WHERE occurred_at >= ?
                GROUP BY bucket
                ORDER BY bucket
                """,
                (since,),
            ).fetchall()
        return [
            {
                "bucket": row["bucket"],
                "visitors": int(row["visitors"] or 0),
                "sessions": int(row["sessions"] or 0),
                "questions": int(row["questions"] or 0),
                "answers": int(row["answers"] or 0),
                "totalTokens": int(row["total_tokens"] or 0),
                "estimatedCostUsd": float(row["estimated_cost_usd"] or 0.0),
                "avgLatencyMs": float(row["avg_latency_ms"] or 0.0),
            }
            for row in rows
        ]

    def model_usage(self, *, days: int = 365) -> list[dict[str, Any]]:
        since = _since(days)
        with self._connect() as connection:
            self._ensure_schema(connection)
            rows = connection.execute(
                """
                SELECT
                    COALESCE(model_provider, 'unknown') AS provider,
                    COALESCE(model_name, 'unknown') AS model,
                    SUM(CASE WHEN event_type = 'answer_completed' THEN 1 ELSE 0 END) AS answers,
                    COALESCE(SUM(total_tokens), 0) AS total_tokens,
                    COALESCE(SUM(estimated_cost_usd), 0) AS estimated_cost_usd,
                    COALESCE(AVG(CASE WHEN latency_ms > 0 THEN latency_ms END), 0) AS avg_latency_ms
                FROM analytics_events
                WHERE occurred_at >= ?
                GROUP BY provider, model
                ORDER BY answers DESC, total_tokens DESC
                LIMIT 50
                """,
                (since,),
            ).fetchall()
        return [
            {
                "provider": row["provider"],
                "model": row["model"],
                "answers": int(row["answers"] or 0),
                "totalTokens": int(row["total_tokens"] or 0),
                "estimatedCostUsd": float(row["estimated_cost_usd"] or 0.0),
                "avgLatencyMs": float(row["avg_latency_ms"] or 0.0),
            }
            for row in rows
        ]

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    def _ensure_schema(self, connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS analytics_events (
                event_id TEXT PRIMARY KEY,
                event_type TEXT NOT NULL,
                occurred_at TEXT NOT NULL,
                visitor_id_hash TEXT,
                session_id_hash TEXT,
                message_id TEXT,
                channel TEXT,
                route TEXT,
                referrer_origin TEXT,
                model_provider TEXT,
                model_name TEXT,
                input_tokens INTEGER NOT NULL DEFAULT 0,
                output_tokens INTEGER NOT NULL DEFAULT 0,
                total_tokens INTEGER NOT NULL DEFAULT 0,
                estimated_cost_usd REAL NOT NULL DEFAULT 0,
                latency_ms REAL NOT NULL DEFAULT 0,
                success INTEGER NOT NULL DEFAULT 1,
                error_code TEXT,
                langfuse_trace_id TEXT,
                metadata TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_analytics_events_occurred
            ON analytics_events(occurred_at)
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_analytics_events_type_occurred
            ON analytics_events(event_type, occurred_at)
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_analytics_events_model_occurred
            ON analytics_events(model_provider, model_name, occurred_at)
            """
        )


def get_analytics_event_store() -> SQLiteAnalyticsEventStore:
    global _STORE
    if _STORE is None:
        db_path = Path(os.getenv("ONERAG_ANALYTICS_DB", str(DEFAULT_ANALYTICS_DB_FILE)))
        _STORE = SQLiteAnalyticsEventStore(db_path)
    return _STORE


def _normalize_event(event: dict[str, Any]) -> dict[str, Any]:
    now = datetime.now(UTC).replace(tzinfo=None).isoformat()
    total_tokens = _int(event.get("total_tokens") or event.get("totalTokens"))
    input_tokens = _int(event.get("input_tokens") or event.get("inputTokens"))
    output_tokens = _int(event.get("output_tokens") or event.get("outputTokens"))
    if total_tokens == 0:
        total_tokens = input_tokens + output_tokens

    return {
        "event_id": str(event.get("event_id") or event.get("eventId") or uuid4()),
        "event_type": _event_type(event.get("event_type") or event.get("eventType")),
        "occurred_at": str(event.get("occurred_at") or event.get("occurredAt") or now),
        "visitor_id_hash": _hash_identifier(event.get("visitor_id") or event.get("visitorId")),
        "session_id_hash": _hash_identifier(event.get("session_id") or event.get("sessionId")),
        "message_id": _clean_optional(event.get("message_id") or event.get("messageId")),
        "channel": _clean_optional(event.get("channel")) or "web",
        "route": _clean_optional(event.get("route")),
        "referrer_origin": _clean_origin(event.get("referrer_origin") or event.get("referrerOrigin")),
        "model_provider": _clean_optional(event.get("model_provider") or event.get("modelProvider")),
        "model_name": _clean_optional(event.get("model_name") or event.get("modelName")),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "estimated_cost_usd": _float(
            event.get("estimated_cost_usd") or event.get("estimatedCostUsd")
        ),
        "latency_ms": _float(event.get("latency_ms") or event.get("latencyMs")),
        "success": bool(event.get("success", True)),
        "error_code": _clean_optional(event.get("error_code") or event.get("errorCode")),
        "langfuse_trace_id": _clean_optional(
            event.get("langfuse_trace_id") or event.get("langfuseTraceId")
        ),
        "metadata": _safe_metadata(event.get("metadata")),
    }


def _event_type(value: Any) -> str:
    candidate = str(value or "").strip().lower().replace("-", "_")
    allowed = {
        "page_view",
        "chat_open",
        "question_submitted",
        "answer_completed",
        "answer_failed",
        "session_created",
        "feedback_submitted",
        "error",
    }
    if candidate not in allowed:
        return "custom"
    return candidate


def _safe_metadata(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    safe: dict[str, str] = {}
    for key, raw in value.items():
        key_text = str(key).strip().lower()
        if key_text not in SAFE_METADATA_KEYS:
            continue
        if any(part in key_text for part in SENSITIVE_KEY_PARTS):
            continue
        safe[key_text] = str(raw)[:120]
        if len(safe) >= 10:
            break
    return safe


def _hash_identifier(value: Any) -> str | None:
    text = _clean_optional(value)
    if not text:
        return None
    salt = (
        os.getenv("ONERAG_ANALYTICS_SALT")
        or os.getenv("FASTAPI_AUTH_KEY")
        or "onerag-analytics-development-salt"
    )
    return hashlib.sha256(f"{salt}:{text}".encode()).hexdigest()


def _clean_origin(value: Any) -> str | None:
    text = _clean_optional(value)
    if not text:
        return None
    parsed = urlparse(text)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}"[:200]
    return None


def _clean_optional(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text[:256]


def _int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _float(value: Any) -> float:
    try:
        return max(0.0, float(value or 0.0))
    except (TypeError, ValueError):
        return 0.0


def _since(days: int) -> str:
    return (datetime.now(UTC).replace(tzinfo=None) - timedelta(days=max(1, days))).isoformat()
