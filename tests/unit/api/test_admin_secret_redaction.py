from datetime import UTC, datetime, timedelta

import pytest

from app.api import admin


def test_mask_sensitive_data_recursively_masks_keys() -> None:
    payload = {
        "generation": {
            "google": {"api_key": "secret-google-key", "model": "gemini"},
            "nested": [{"secret_token": "tok-123456789"}],
        },
        "llm": {"openai": {"password": "super-secret"}},
    }

    masked = admin.mask_sensitive_data(payload)

    assert "secret-google-key" not in str(masked)
    assert "tok-123456789" not in str(masked)
    assert "super-secret" not in str(masked)
    assert masked["generation"]["google"]["api_key"] == "****-key"


@pytest.mark.asyncio
async def test_get_config_info_masks_all_top_level_sections(monkeypatch) -> None:
    monkeypatch.setattr(
        admin,
        "config",
        {
            "generation": {"openai": {"api_key": "sk-openai-raw"}},
            "embeddings": {"google": {"secret": "embed-secret"}},
            "environment": "test",
        },
    )

    result = await admin.get_config_info()

    assert "sk-openai-raw" not in str(result)
    assert "embed-secret" not in str(result)
    assert result["config"]["generation"]["openai"]["api_key"] == "****-raw"


@pytest.mark.asyncio
async def test_get_module_info_masks_config_and_stats(monkeypatch) -> None:
    class DummyModule:
        config = {"llm": {"api_key": "module-secret-key"}}

        async def get_stats(self):
            return {"token": "stats-secret-token", "count": 1}

    monkeypatch.setattr(admin, "modules", {"generation": DummyModule()})

    result = await admin.get_module_info()

    assert "module-secret-key" not in str(result[0].dict())
    assert "stats-secret-token" not in str(result[0].dict())
    assert result[0].stats["count"] == 1


@pytest.mark.asyncio
async def test_update_ai_settings_preserves_key_restart_requirement(monkeypatch, tmp_path) -> None:
    class DummyGenerationModule:
        provider = "google"
        default_model = "gemini-2.0-flash"

    from app.api.admin_ai_settings_store import SQLiteAdminAISettingsStore

    monkeypatch.setenv("ONERAG_SETTINGS_SECRET", "test-secret")
    store = SQLiteAdminAISettingsStore(tmp_path / "ai-settings.sqlite3")
    store.update_settings("google", "gemini-2.0-flash")
    store.set_restart_required(False)
    store.replace_provider_key("google", "AIza-test-secret-value")
    monkeypatch.setattr(admin, "modules", {"generation": DummyGenerationModule()})
    monkeypatch.setattr(admin, "get_admin_ai_settings_store", lambda: store)

    result = await admin.update_ai_settings(
        admin.AISettingsUpdate(provider="google", model="gemini-2.5-pro")
    )

    assert result["restartRequired"] is True
    assert store.get_settings()["restartRequired"] is True


@pytest.mark.asyncio
async def test_update_ai_settings_rejects_unknown_model() -> None:
    with pytest.raises(admin.HTTPException) as exc_info:
        await admin.update_ai_settings(
            admin.AISettingsUpdate(provider="google", model="not-a-real-model")
        )

    assert exc_info.value.status_code == 400


def test_langfuse_trace_sanitizer_omits_question_and_answer_previews() -> None:
    sanitized = admin._sanitize_langfuse_trace(
        {
            "id": "trace-1",
            "name": "RAG Pipeline",
            "input": "confidential question",
            "output": "confidential answer",
            "latency": 1.25,
            "usage": {"total": 42},
            "metadata": {"model": "gemini-2.0-flash"},
        }
    )

    assert sanitized["traceId"] == "trace-1"
    assert sanitized["totalTokens"] == 42
    assert sanitized["latencyMs"] == 1250
    assert "inputPreview" not in sanitized
    assert "outputPreview" not in sanitized
    assert "confidential question" not in str(sanitized)
    assert "confidential answer" not in str(sanitized)


def test_langfuse_trace_retention_filter_is_seven_days() -> None:
    recent = {"timestamp": datetime.now(UTC).isoformat()}
    old = {"timestamp": (datetime.now(UTC) - timedelta(days=8)).isoformat()}
    missing = {}

    assert admin._is_trace_within_retention(recent, days=7) is True
    assert admin._is_trace_within_retention(old, days=7) is False
    assert admin._is_trace_within_retention(missing, days=7) is False
