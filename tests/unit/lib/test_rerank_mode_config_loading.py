"""Real YAML loading, strict schema validation, and resolver parity."""

import os
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from pydantic import ValidationError

from app.config.schemas.reranking import RerankingConfigV2
from app.lib.config_loader import ConfigLoader
from app.lib.errors import ConfigError
from app.modules.core.retrieval.rerankers.factory import RerankerFactoryV2
from app.modules.core.retrieval.rerankers.mode import (
    RerankerModeConfigError,
    normalize_mode_value,
    preflight_rerank_mode,
    resolve_rerank_mode,
)


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch):
    monkeypatch.setattr("app.lib.config_loader.load_dotenv", lambda *args, **kwargs: None)
    with patch.dict(os.environ, {"ENVIRONMENT": "test", "PYTHON_DOTENV_DISABLED": "1"},
                    clear=True):
        yield


@pytest.fixture
def loader(tmp_path):
    """Import the shipped reranking YAML; isolate unrelated config/env validation."""
    source = Path(__file__).resolve().parents[3] / "app/config/features/reranking.yaml"
    (tmp_path / "base.yaml").write_text(yaml.safe_dump({"imports": [str(source)]}))
    (tmp_path / "environments").mkdir()
    instance = ConfigLoader()
    instance.base_path = tmp_path
    return instance


def override(loader, **reranking):
    (loader.base_path / "environments/test.yaml").write_text(
        yaml.safe_dump({"reranking": reranking})
    )


def test_substitution_preserves_empty_vs_unset_via_env_snapshot(monkeypatch):
    monkeypatch.setattr("app.lib.config_loader.load_dotenv", lambda *args, **kwargs: None)
    loader = ConfigLoader()
    monkeypatch.delenv("RERANK_MODE", raising=False)
    unset = loader._substitute_env_vars({"mode": "${RERANK_MODE:-}"})
    monkeypatch.setenv("RERANK_MODE", "")
    empty = loader._substitute_env_vars({"mode": "${RERANK_MODE:-}"})
    assert unset == empty == {"mode": ""}
    assert resolve_rerank_mode(unset, {}).source == "default"
    with pytest.raises(RerankerModeConfigError, match="비어"):
        resolve_rerank_mode(empty, {"RERANK_MODE": ""})


def test_old_env_survives_removal_of_yaml_substitution(loader, monkeypatch):
    monkeypatch.setenv("TYPESAFE_JEV_MODE", "enforce")
    override(loader, approach="decision", provider="typesafe")
    raw = loader.load_config(validate=False)
    assert "mode" not in raw["reranking"]["typesafe"]
    assert "shadow_background" not in raw["reranking"]["typesafe"]
    result = resolve_rerank_mode(raw["reranking"], os.environ)
    assert (result.effective, result.source) == ("jev", "compat_decision_enforce")


@pytest.mark.parametrize("modular", [False, True])
@pytest.mark.parametrize("strict", [False, True])
@pytest.mark.parametrize("raw", ["JEV", " jev ", "legacy", "bogus", "legacy_observe"])
def test_strict_nonstrict_and_raw_agree(loader, monkeypatch, modular, strict, raw):
    monkeypatch.setenv("RERANK_MODE", raw)
    unvalidated = loader.load_config(validate=False)
    try:
        expected = normalize_mode_value(raw)
    except RerankerModeConfigError as exc:
        message = str(exc)
        with pytest.raises(RerankerModeConfigError, match=message):
            resolve_rerank_mode(unvalidated["reranking"], os.environ)
        if strict:
            with pytest.raises(ConfigError) as error:
                loader.load_config(use_modular_schema=modular, raise_on_validation_error=True)
            # ConfigLoader wraps schema errors with a generic public ConfigError.
            assert message in str(error.value.__cause__)
        else:
            loaded = loader.load_config(use_modular_schema=modular)
            with pytest.raises(RerankerModeConfigError, match=message):
                resolve_rerank_mode(loaded["reranking"], os.environ)
    else:
        loaded = loader.load_config(use_modular_schema=modular, raise_on_validation_error=strict)
        assert loaded["reranking"]["mode"] == expected
        assert resolve_rerank_mode(loaded["reranking"], os.environ).effective == expected
        assert resolve_rerank_mode(unvalidated["reranking"], os.environ).effective == expected


@pytest.mark.parametrize("modular", [False, True])
def test_strict_jev_ignores_stale_legacy_selection(loader, monkeypatch, modular):
    monkeypatch.setenv("RERANK_MODE", "jev")
    for approach in ("llm", "stale-approach"):
        override(loader, approach=approach, provider="stale-provider")
        loaded = loader.load_config(use_modular_schema=modular, raise_on_validation_error=True)
        assert resolve_rerank_mode(loaded["reranking"], os.environ).effective == "jev"


@pytest.mark.parametrize("modular", [False, True])
@pytest.mark.parametrize("old_mode", [None, "shadow", "off", "enforce"])
def test_strict_leaves_decision_migration_to_resolver(loader, modular, old_mode):
    override(loader, approach="decision", provider="stale-provider", typesafe={"mode": old_mode})
    loaded = loader.load_config(use_modular_schema=modular, raise_on_validation_error=True)
    if old_mode == "enforce":
        assert resolve_rerank_mode(loaded["reranking"], {}).effective == "jev"
    else:
        with pytest.raises(RerankerModeConfigError, match="더 이상 지원하지"):
            resolve_rerank_mode(loaded["reranking"], {})
    assert resolve_rerank_mode(loaded["reranking"], {"RERANK_MODE": "legacy"}).legacy_provider == "google"


@pytest.mark.parametrize("raw", [True, 1, [], "bogus", "legacy_observe"])
def test_schema_and_resolver_reject_same_invalid_yaml_values(raw):
    with pytest.raises(RerankerModeConfigError) as error:
        normalize_mode_value(raw)
    with pytest.raises(ValidationError, match=str(error.value)):
        RerankingConfigV2(mode=raw)


@pytest.mark.parametrize("raw", [None, ""])
def test_schema_empty_yaml_mode_is_unspecified(raw):
    config = RerankingConfigV2(mode=raw).model_dump()
    assert config["mode"] is None
    assert resolve_rerank_mode(config, {}).source == "default"


@pytest.mark.parametrize("modular", [False, True])
def test_schema_dump_does_not_forward_deprecated_defaults(loader, monkeypatch, modular):
    monkeypatch.setenv("RERANK_MODE", "jev")
    loaded = loader.load_config(use_modular_schema=modular, raise_on_validation_error=True)
    assert loaded["reranking"]["typesafe"]["mode"] is None
    assert loaded["reranking"]["typesafe"]["shadow_background"] is None
    env = {"RERANK_MODE": "jev", "TYPESAFE_API_KEY": "test-key"}
    assert preflight_rerank_mode(loaded, env).effective == "jev"
    with patch("app.modules.core.retrieval.rerankers.jev_decision_reranker.JevDecisionReranker") as ctor:
        RerankerFactoryV2.create(loaded, env=env)
        ctor.assert_called_once()
        assert ctor.call_args.kwargs["mode"] == "enforce"
        assert "shadow_background" not in ctor.call_args.kwargs


def test_shipped_yaml_unset_vs_explicit_empty_after_strict_loading(loader, monkeypatch):
    loaded = loader.load_config(raise_on_validation_error=True)
    assert resolve_rerank_mode(loaded["reranking"], os.environ).source == "default"
    monkeypatch.setenv("RERANK_MODE", "")
    loaded = loader.load_config(raise_on_validation_error=True)
    with pytest.raises(RerankerModeConfigError, match="비어"):
        resolve_rerank_mode(loaded["reranking"], os.environ)
