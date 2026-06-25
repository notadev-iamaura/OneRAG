"""Server-side admin AI settings storage.

This module keeps provider/model settings out of browser storage and API
responses. Provider keys are write-only. They are persisted only when an
encryption secret is available and `cryptography` can be imported; otherwise
the replacement key is held in process memory and reported as runtime-only.
"""

from __future__ import annotations

import base64
import hashlib
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from threading import RLock
from typing import Any

DEFAULT_AI_SETTINGS_DB_FILE = Path("./uploads/admin_ai_settings.sqlite3")
DEFAULT_PROVIDER = "google"
DEFAULT_MODEL = "gemini-2.0-flash"

PROVIDER_ENV_KEYS = {
    "google": "GOOGLE_API_KEY",
    "gemini": "GOOGLE_API_KEY",
    "openai": "OPENAI_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "ollama": "OLLAMA_BASE_URL",
}

PROVIDER_ALIASES = {
    "gemini": "google",
}

_RUNTIME_PROVIDER_KEYS: dict[str, str] = {}
_STORE: SQLiteAdminAISettingsStore | None = None


def canonical_provider(provider: str) -> str:
    normalized = str(provider or "").strip().lower()
    return PROVIDER_ALIASES.get(normalized, normalized)


def mask_secret(value: str | None) -> str | None:
    if not value:
        return None
    if len(value) <= 8:
        return "****"
    return f"{value[:4]}{'*' * max(len(value) - 8, 4)}{value[-4:]}"


class SQLiteAdminAISettingsStore:
    """SQLite-backed admin AI settings store."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = RLock()

    def get_settings(self) -> dict[str, Any]:
        with self._connect() as connection:
            self._ensure_schema(connection)
            row = connection.execute(
                """
                SELECT provider, model, updated_at, restart_required
                FROM ai_runtime_settings
                WHERE id = 'active'
                """
            ).fetchone()

        if row is None:
            return {
                "provider": DEFAULT_PROVIDER,
                "model": DEFAULT_MODEL,
                "updatedAt": None,
                "restartRequired": False,
                "configured": False,
            }
        return {
            "provider": row["provider"],
            "model": row["model"],
            "updatedAt": row["updated_at"],
            "restartRequired": bool(row["restart_required"]),
            "configured": True,
        }

    def update_settings(self, provider: str, model: str) -> dict[str, Any]:
        resolved_provider = canonical_provider(provider)
        resolved_model = str(model or "").strip()
        if not resolved_provider or not resolved_model:
            raise ValueError("provider and model are required")

        now = datetime.now().isoformat()
        with self._lock, self._connect() as connection:
            self._ensure_schema(connection)
            connection.execute(
                """
                INSERT INTO ai_runtime_settings (
                    id, provider, model, updated_at, restart_required
                )
                VALUES ('active', ?, ?, ?, 1)
                ON CONFLICT(id) DO UPDATE SET
                    provider = excluded.provider,
                    model = excluded.model,
                    updated_at = excluded.updated_at,
                    restart_required = 1
                """,
                (resolved_provider, resolved_model, now),
            )
            connection.commit()
        return self.get_settings()

    def set_restart_required(self, required: bool) -> None:
        current = self.get_settings()
        if not current.get("configured"):
            return
        with self._lock, self._connect() as connection:
            self._ensure_schema(connection)
            connection.execute(
                """
                INSERT INTO ai_runtime_settings (
                    id, provider, model, updated_at, restart_required
                )
                VALUES ('active', ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    restart_required = excluded.restart_required,
                    updated_at = excluded.updated_at
                """,
                (
                    current["provider"],
                    current["model"],
                    datetime.now().isoformat(),
                    1 if required else 0,
                ),
            )
            connection.commit()

    def replace_provider_key(self, provider: str, api_key: str) -> dict[str, Any]:
        resolved_provider = canonical_provider(provider)
        normalized_key = str(api_key or "").strip()
        if not resolved_provider or not normalized_key:
            raise ValueError("provider and api_key are required")

        encrypted_key = _encrypt_secret(normalized_key)
        storage = "encrypted" if encrypted_key is not None else "runtime"
        if encrypted_key is None:
            _RUNTIME_PROVIDER_KEYS[resolved_provider] = normalized_key

        now = datetime.now().isoformat()
        with self._lock, self._connect() as connection:
            self._ensure_schema(connection)
            connection.execute(
                """
                INSERT INTO ai_provider_keys (
                    provider, encrypted_key, key_last4, storage, updated_at
                )
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(provider) DO UPDATE SET
                    encrypted_key = excluded.encrypted_key,
                    key_last4 = excluded.key_last4,
                    storage = excluded.storage,
                    updated_at = excluded.updated_at
                """,
                (resolved_provider, encrypted_key, normalized_key[-4:], storage, now),
            )
            connection.commit()
        self.set_restart_required(True)
        return self.get_key_metadata(resolved_provider)

    def get_provider_key(self, provider: str) -> str | None:
        resolved_provider = canonical_provider(provider)
        if resolved_provider in _RUNTIME_PROVIDER_KEYS:
            return _RUNTIME_PROVIDER_KEYS[resolved_provider]

        row = self._get_key_row(resolved_provider)
        if row is not None and row["encrypted_key"]:
            decrypted = _decrypt_secret(row["encrypted_key"])
            if decrypted:
                return decrypted

        env_name = PROVIDER_ENV_KEYS.get(resolved_provider)
        if env_name:
            return os.getenv(env_name)
        return None

    def get_key_metadata(self, provider: str) -> dict[str, Any]:
        resolved_provider = canonical_provider(provider)
        row = self._get_key_row(resolved_provider)
        env_name = PROVIDER_ENV_KEYS.get(resolved_provider)
        env_value = os.getenv(env_name) if env_name else None
        runtime_value = _RUNTIME_PROVIDER_KEYS.get(resolved_provider)

        storage = "none"
        updated_at = None
        last4 = None
        configured = False

        if row is not None and row["storage"] == "encrypted" and row["encrypted_key"]:
            storage = "encrypted"
            updated_at = row["updated_at"]
            last4 = row["key_last4"]
            configured = True
        elif runtime_value:
            storage = "runtime"
            last4 = runtime_value[-4:]
            configured = True
        elif env_value:
            storage = "env"
            last4 = env_value[-4:]
            configured = True
        elif row is not None:
            storage = row["storage"]
            updated_at = row["updated_at"]
            last4 = row["key_last4"]

        return {
            "provider": resolved_provider,
            "configured": configured,
            "masked": f"****{last4}" if last4 else None,
            "last4": last4,
            "storage": storage,
            "envName": env_name,
            "updatedAt": updated_at,
            "persisted": storage == "encrypted",
        }

    def list_key_metadata(self, providers: list[str]) -> dict[str, dict[str, Any]]:
        return {
            canonical_provider(provider): self.get_key_metadata(provider)
            for provider in providers
        }

    def _get_key_row(self, provider: str) -> sqlite3.Row | None:
        with self._connect() as connection:
            self._ensure_schema(connection)
            return connection.execute(
                """
                SELECT provider, encrypted_key, key_last4, storage, updated_at
                FROM ai_provider_keys
                WHERE provider = ?
                """,
                (canonical_provider(provider),),
            ).fetchone()

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    def _ensure_schema(self, connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS ai_runtime_settings (
                id TEXT PRIMARY KEY,
                provider TEXT NOT NULL,
                model TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                restart_required INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS ai_provider_keys (
                provider TEXT PRIMARY KEY,
                encrypted_key TEXT,
                key_last4 TEXT,
                storage TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )


def get_admin_ai_settings_store() -> SQLiteAdminAISettingsStore:
    global _STORE
    if _STORE is None:
        db_path = Path(os.getenv("ONERAG_ADMIN_AI_SETTINGS_DB", str(DEFAULT_AI_SETTINGS_DB_FILE)))
        _STORE = SQLiteAdminAISettingsStore(db_path)
    return _STORE


def can_persist_provider_keys() -> bool:
    """Return whether GUI-submitted provider keys can survive a restart."""
    return _get_fernet() is not None


def get_active_generation_override() -> dict[str, Any]:
    """Return active generation defaults for request-time model injection."""
    settings = get_admin_ai_settings_store().get_settings()
    return settings if settings.get("configured") else {}


def _encrypt_secret(value: str) -> str | None:
    fernet = _get_fernet()
    if fernet is None:
        return None
    return fernet.encrypt(value.encode("utf-8")).decode("utf-8")


def _decrypt_secret(value: str) -> str | None:
    fernet = _get_fernet()
    if fernet is None:
        return None
    try:
        return fernet.decrypt(value.encode("utf-8")).decode("utf-8")
    except Exception:
        return None


def _get_fernet() -> Any | None:
    secret = os.getenv("ONERAG_SETTINGS_SECRET") or os.getenv("FASTAPI_AUTH_KEY")
    if not secret:
        return None
    try:
        from cryptography.fernet import Fernet
    except Exception:
        return None
    key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode("utf-8")).digest())
    return Fernet(key)
