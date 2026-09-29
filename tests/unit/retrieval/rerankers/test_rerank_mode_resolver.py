"""Mode resolution is pure and never needs provider imports or credentials."""

import pytest

from app.modules.core.retrieval.rerankers.mode import (
    RerankerModeConfigError,
    normalize_mode_value,
    preflight_rerank_mode,
    resolve_rerank_mode,
)


@pytest.mark.parametrize("value, expected", [
    ("legacy", "legacy"), ("jev", "jev"), ("JEV", "jev"), (" jev ", "jev"),
])
def test_explicit_env(value, expected):
    result = resolve_rerank_mode({}, {"RERANK_MODE": value})
    assert (result.effective, result.source) == (expected, "env")


@pytest.mark.parametrize("value", ["", "  "])
@pytest.mark.parametrize("enabled", [True, False])
def test_empty_env_is_always_an_error(value, enabled):
    with pytest.raises(RerankerModeConfigError, match="비어"):
        resolve_rerank_mode({"enabled": enabled}, {"RERANK_MODE": value})


@pytest.mark.parametrize("value", ["on", "shadow", "enforce", "bogus", "legacy_observe"])
@pytest.mark.parametrize("source", ["env", "yaml"])
@pytest.mark.parametrize("enabled", [True, False])
def test_invalid_mode(value, source, enabled):
    rc = {"enabled": enabled, **({"mode": value} if source == "yaml" else {})}
    env = {"RERANK_MODE": value} if source == "env" else {}
    with pytest.raises(RerankerModeConfigError, match="예약" if value == "legacy_observe" else "RERANK_MODE"):
        resolve_rerank_mode(rc, env)


@pytest.mark.parametrize("value", [True, 1, []])
def test_yaml_requires_string(value):
    with pytest.raises(RerankerModeConfigError):
        normalize_mode_value(value)


@pytest.mark.parametrize("value", [None, "", "  "])
def test_unset_yaml(value):
    result = resolve_rerank_mode({"mode": value}, {})
    assert (result.effective, result.source, result.warnings) == ("legacy", "default", ())


def test_env_wins_conflict():
    result = resolve_rerank_mode({"mode": "legacy"}, {"RERANK_MODE": "jev"})
    assert (result.effective, result.source) == ("jev", "env")
    assert "rerank_mode_conflict" in result.warnings[0]


@pytest.mark.parametrize("old", [None, "", "shadow", "off", "bogus"])
@pytest.mark.parametrize("source", ["env", "yaml"])
def test_decision_requires_migration(old, source):
    rc = {"approach": "decision", "typesafe": {"mode": old} if source == "yaml" else {}}
    env = {"TYPESAFE_JEV_MODE": old} if source == "env" and old is not None else {}
    with pytest.raises(RerankerModeConfigError, match="이전 동작: 리랭킹 없이 검색 순서 top_n"):
        resolve_rerank_mode(rc, env)


@pytest.mark.parametrize("typesafe, env", [
    ({}, {"TYPESAFE_JEV_MODE": "enforce"}),
    ({"mode": "enforce"}, {}),
    ({"mode": "shadow"}, {"TYPESAFE_JEV_MODE": "enforce"}),
])
def test_compat_enforce(typesafe, env):
    result = resolve_rerank_mode({"approach": "decision", "typesafe": typesafe}, env)
    assert (result.effective, result.source) == ("jev", "compat_decision_enforce")
    assert len(result.warnings) == 1


def test_old_env_overrides_yaml():
    with pytest.raises(RerankerModeConfigError):
        resolve_rerank_mode({"approach": "decision", "typesafe": {"mode": "enforce"}},
                           {"TYPESAFE_JEV_MODE": "off"})


def test_explicit_legacy_cleans_decision():
    result = resolve_rerank_mode({"approach": "decision"}, {"RERANK_MODE": "legacy"})
    assert (result.legacy_approach, result.legacy_provider) == ("llm", "google")
    assert len(result.warnings) == 1


@pytest.mark.parametrize("mode", ["legacy", "jev"])
def test_explicit_mode_ignores_old_values(mode):
    result = resolve_rerank_mode({"typesafe": {"mode": "bogus"}},
                                {"RERANK_MODE": mode, "TYPESAFE_JEV_MODE": "off"})
    assert result.effective == mode
    assert len(result.warnings) == 1
    assert "무시됨" in result.warnings[0]


def test_default_and_ignored_old_env():
    rc = {"approach": "llm", "provider": "google"}
    assert resolve_rerank_mode(rc, {}).warnings == ()
    assert "무시됨" in resolve_rerank_mode(rc, {"TYPESAFE_JEV_MODE": "enforce"}).warnings[0]


def test_jev_does_not_read_legacy_settings():
    class Config(dict):
        def get(self, key, default=None):
            assert key not in ("approach", "provider")
            return super().get(key, default)

    assert resolve_rerank_mode(Config(), {"RERANK_MODE": "jev"}).effective == "jev"


@pytest.mark.parametrize("key", [None, "", "  "])
@pytest.mark.parametrize("compat", [False, True])
def test_preflight_requires_key(key, compat):
    env = {} if key is None else {"TYPESAFE_API_KEY": key}
    rc = {"approach": "decision", "typesafe": {"mode": "enforce"}} if compat else {"mode": "jev"}
    with pytest.raises(RerankerModeConfigError, match="TYPESAFE_API_KEY"):
        preflight_rerank_mode({"reranking": rc}, env)


def test_disabled_skips_key_and_options():
    result = preflight_rerank_mode({"reranking": {
        "enabled": False, "mode": "jev", "typesafe": {"deadline_seconds": 0},
    }}, {})
    assert (result.effective, result.source) == ("disabled", "disabled")


@pytest.mark.parametrize("options", [
    {"deadline_seconds": 0}, {"min_relevance": 2}, {"concurrency": 0},
    {"min_keep": 0}, {"max_documents": "bad"}, {"timeout": float("nan")},
    {"circuit_failure_threshold": 0}, {"question_type": "bad"}, {"unknown": "test-key"},
])
def test_preflight_validates_options_without_leaking_values(options):
    with pytest.raises(RerankerModeConfigError) as error:
        preflight_rerank_mode({"reranking": {"mode": "jev", "typesafe": options}},
                             {"TYPESAFE_API_KEY": "test-key"})
    assert "test-key" not in str(error.value)


def test_error_is_not_value_error():
    assert not issubclass(RerankerModeConfigError, ValueError)
