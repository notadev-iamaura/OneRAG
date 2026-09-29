"""Actual application startup gates, with infrastructure and dotenv isolated."""

import importlib
import os
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.core.di_container import create_reranker_instance_v2
from app.modules.core.retrieval.rerankers.mode import RerankerModeConfigError


@pytest.fixture
def app_module(monkeypatch):
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "1")
    for key in ("RERANK_MODE", "TYPESAFE_API_KEY", "TYPESAFE_JEV_MODE", "GOOGLE_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    with patch("dotenv.load_dotenv"):
        return importlib.import_module("main")


@pytest.mark.asyncio
@pytest.mark.parametrize("graceful", [False, True])
@pytest.mark.parametrize("rc, env", [
    ({}, {"RERANK_MODE": "jev"}),
    ({"approach": "decision", "typesafe": {"mode": "enforce"}}, {}),
    ({"approach": "decision", "typesafe": {"mode": "shadow"}}, {}),
    ({}, {"RERANK_MODE": ""}),
    ({"typesafe": {"deadline_seconds": 0}}, {"RERANK_MODE": "jev", "TYPESAFE_API_KEY": "test-key"}),
])
async def test_invalid_mode_fails_before_either_initializer(app_module, monkeypatch, graceful, rc, env):
    monkeypatch.setenv("ENABLE_GRACEFUL_DEGRADATION", str(graceful).lower())
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    with patch.object(app_module, "ConfigLoader") as loader, \
         patch.object(app_module, "initialize_async_resources", new_callable=AsyncMock) as standard, \
         patch.object(app_module, "initialize_async_resources_graceful", new_callable=AsyncMock) as degraded, \
         patch.object(app_module.health, "set_startup_state") as health:
        loader.return_value.load_config.return_value = {"reranking": rc}
        app = app_module.RAGChatbotApp()
        with pytest.raises(RerankerModeConfigError):
            await app.initialize_modules()
    standard.assert_not_awaited()
    degraded.assert_not_awaited()
    assert health.call_args.args[:2] == (False, "failed")


@pytest.mark.asyncio
@pytest.mark.parametrize("graceful", [False, True])
async def test_legacy_missing_key_starts(app_module, monkeypatch, graceful):
    monkeypatch.setenv("RERANK_MODE", "legacy")
    monkeypatch.setenv("ENABLE_GRACEFUL_DEGRADATION", str(graceful).lower())
    config = {"reranking": {"approach": "llm", "provider": "google"}}

    async def initialize(container):
        assert await create_reranker_instance_v2(container.config()) is None

    with patch.object(app_module, "ConfigLoader") as loader, \
         patch.object(app_module, "validate_provider_env", return_value=SimpleNamespace(is_valid=True, warnings=[])), \
         patch.object(app_module, "initialize_async_resources", new=AsyncMock(side_effect=initialize)) as standard, \
         patch.object(app_module, "initialize_async_resources_graceful", new=AsyncMock(side_effect=initialize)) as degraded, \
         patch("app.core.di_container.logger") as logger:
        loader.return_value.load_config.return_value = config
        await app_module.RAGChatbotApp().initialize_modules()
    assert standard.await_count == (0 if graceful else 1)
    assert degraded.await_count == (1 if graceful else 0)
    assert logger.warning.call_args.kwargs["extra"]["effective_reranker"] == "none"


@pytest.mark.parametrize("rc, env, exit_code, output", [
    ({}, {"RERANK_MODE": "legacy"}, 0, "effective=legacy"),
    ({}, {"RERANK_MODE": "jev", "TYPESAFE_API_KEY": "test-key"}, 0, "typesafe_key=present"),
    ({"approach": "decision"}, {}, 1, "RERANK_MODE 를 명시"),
    ({}, {"RERANK_MODE": ""}, 1, "비어"),
])
def test_check_cli_without_secrets_or_provider_imports(rc, env, exit_code, output):
    # run_module exercises the same __main__ path as python -m, with an isolated config.
    code = f"""
import runpy, sys
from unittest.mock import patch
sys.argv = ['mode', '--check']
with patch('app.lib.config_loader.load_config', return_value={{'reranking': {rc!r}}}):
    try:
        runpy.run_module('app.modules.core.retrieval.rerankers.mode', run_name='__main__')
    finally:
        assert all('app.modules.core.retrieval.rerankers.' + name not in sys.modules
                   for name in ['jev_client', 'jev_decision_reranker', 'gemini_reranker'])
"""
    clean_env = {key: value for key, value in os.environ.items()
                 if key not in ("RERANK_MODE", "TYPESAFE_JEV_MODE", "TYPESAFE_API_KEY")}
    result = subprocess.run([sys.executable, "-c", code],
        env={**clean_env, **env, "PYTHON_DOTENV_DISABLED": "1"}, capture_output=True, text=True, timeout=30)
    assert result.returncode == exit_code, result.stderr
    assert output in result.stdout
    assert "test-key" not in result.stdout + result.stderr


@pytest.mark.parametrize("mode, exit_code", [("legacy", 0), ("jev", 0), ("", 1)])
def test_real_module_cli_with_repository_yaml(mode, exit_code):
    result = subprocess.run(
        [sys.executable, "-m", "app.modules.core.retrieval.rerankers.mode", "--check"],
        env={"PATH": os.environ["PATH"], "PYTHON_DOTENV_DISABLED": "1", "ENVIRONMENT": "test",
             "RERANK_MODE": mode, "TYPESAFE_API_KEY": "test-key"},
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == exit_code, result.stderr
    assert "test-key" not in result.stdout + result.stderr


@pytest.mark.asyncio
async def test_startup_does_not_log_constructor_cause(app_module, monkeypatch):
    monkeypatch.setenv("RERANK_MODE", "jev")
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key")

    async def initialize(container):
        await create_reranker_instance_v2(container.config())

    with patch.object(app_module, "ConfigLoader") as loader, \
         patch.object(app_module, "validate_provider_env", return_value=SimpleNamespace(is_valid=True, warnings=[])), \
         patch.object(app_module, "initialize_async_resources", new=AsyncMock(side_effect=initialize)), \
         patch("app.modules.core.retrieval.rerankers.factory.RerankerFactoryV2.create", side_effect=RuntimeError("test-key")), \
         patch.object(app_module, "logger") as logger:
        loader.return_value.load_config.return_value = {}
        with pytest.raises(RerankerModeConfigError):
            await app_module.RAGChatbotApp().initialize_modules()
    assert "test-key" not in str(logger.mock_calls)
    assert not logger.error.call_args.kwargs.get("exc_info")
