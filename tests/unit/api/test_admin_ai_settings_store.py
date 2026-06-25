from app.api.admin_ai_settings_store import (
    SQLiteAdminAISettingsStore,
    get_active_generation_override,
)


def test_ai_settings_store_returns_masked_key_metadata_without_raw_secret(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("ONERAG_SETTINGS_SECRET", "test-secret")
    store = SQLiteAdminAISettingsStore(tmp_path / "ai-settings.sqlite3")

    metadata = store.replace_provider_key("openai", "sk-test-secret-value")

    assert metadata["configured"] is True
    assert metadata["last4"] == "alue"
    assert metadata["storage"] == "encrypted"
    assert "sk-test-secret-value" not in str(metadata)
    assert store.get_settings()["restartRequired"] is False


def test_ai_settings_store_persists_provider_and_model(tmp_path) -> None:
    store = SQLiteAdminAISettingsStore(tmp_path / "ai-settings.sqlite3")

    settings = store.update_settings("google", "gemini-2.5-pro")

    assert settings["provider"] == "google"
    assert settings["model"] == "gemini-2.5-pro"
    assert settings["restartRequired"] is True
    assert settings["configured"] is True


def test_ai_settings_store_does_not_map_claude_to_openrouter(tmp_path) -> None:
    store = SQLiteAdminAISettingsStore(tmp_path / "ai-settings.sqlite3")

    settings = store.update_settings("claude", "claude-sonnet-4")

    assert settings["provider"] == "claude"


def test_active_generation_override_is_empty_until_admin_setting_saved(
    monkeypatch, tmp_path
) -> None:
    store = SQLiteAdminAISettingsStore(tmp_path / "ai-settings.sqlite3")
    monkeypatch.setattr(
        "app.api.admin_ai_settings_store.get_admin_ai_settings_store",
        lambda: store,
    )

    assert store.get_settings()["configured"] is False
    assert get_active_generation_override() == {}
