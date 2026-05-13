import pytest

from app.lib.startup_policy import get_retrieval_startup_policy, is_retrieval_required


def _clear_policy_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ["ENVIRONMENT", "NODE_ENV", "WEAVIATE_URL", "RETRIEVAL_STARTUP_POLICY"]:
        monkeypatch.delenv(key, raising=False)


def test_retrieval_policy_defaults_to_degraded_outside_production(monkeypatch) -> None:
    _clear_policy_env(monkeypatch)
    monkeypatch.setenv("ENVIRONMENT", "development")

    assert get_retrieval_startup_policy() == "degraded"
    assert is_retrieval_required() is False


def test_retrieval_policy_defaults_to_required_in_production(monkeypatch) -> None:
    _clear_policy_env(monkeypatch)
    monkeypatch.setenv("ENVIRONMENT", "production")

    assert get_retrieval_startup_policy() == "required"
    assert is_retrieval_required() is True


def test_retrieval_policy_rejects_invalid_value(monkeypatch) -> None:
    _clear_policy_env(monkeypatch)
    monkeypatch.setenv("RETRIEVAL_STARTUP_POLICY", "maybe")

    with pytest.raises(ValueError, match="RETRIEVAL_STARTUP_POLICY"):
        get_retrieval_startup_policy()
