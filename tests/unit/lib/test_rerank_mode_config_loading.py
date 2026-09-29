"""Resolver behavior across env substitution, before the YAML/schema migration."""

import pytest

from app.lib.config_loader import ConfigLoader
from app.modules.core.retrieval.rerankers.mode import RerankerModeConfigError, resolve_rerank_mode


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


def test_old_env_survives_removal_of_yaml_substitution():
    result = resolve_rerank_mode({"approach": "decision", "typesafe": {}},
                                {"TYPESAFE_JEV_MODE": "enforce"})
    assert (result.effective, result.source) == ("jev", "compat_decision_enforce")
