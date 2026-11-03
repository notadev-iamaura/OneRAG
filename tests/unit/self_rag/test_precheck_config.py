"""기본 off, YAML 보존 및 실제 DI 배선 검증."""

from pathlib import Path

import pytest
import yaml

from app.core.di_container import AppContainer
from app.modules.core.decision import MockDecisionProvider
from app.modules.core.self_rag.precheck import PrecheckQualityEvaluator, PrecheckSettings
from tests.unit.self_rag.test_orchestrator_options import (
    _FakeComplexityCalculator,
    _RecordingGeneration,
    _RecordingRetrieval,
)
from tests.unit.self_rag.test_precheck_evaluator import _RecordingEvaluator


def _yaml_config():
    path = Path(__file__).resolve().parents[3] / "app/config/features/self_rag.yaml"
    return yaml.safe_load(path.read_text())["self_rag"]


def test_yaml_mode_is_quoted_string_off():
    config = _yaml_config()["precheck"]
    assert config["mode"] == "off"
    assert isinstance(config["mode"], str)
    assert config["api_base"] == "${TYPESAFE_API_BASE:-https://api.typesafe.ai}"
    assert config["systemone_path"] == "${TYPESAFE_SYSTEMONE_PATH:-/v1/systemone}"
    assert config["model"] == "${TYPESAFE_JEV_MODEL:-jev-latest}"
    assert config["api_key"] == "${TYPESAFE_API_KEY:-}"


@pytest.mark.parametrize("mode", [False, None, "off", "shadow", "enforce"])
def test_schema_normalizes_yaml_false(mode):
    expected = "off" if mode is False or mode is None else mode
    assert PrecheckSettings.from_mapping({"mode": mode}).mode == expected


@pytest.mark.parametrize("mode", ["bogus", True, 123, {}, []])
def test_unknown_mode_warns_and_never_raises(mode, caplog):
    assert PrecheckSettings.from_mapping({"mode": mode}).mode == "off"
    assert "self_rag_precheck_unknown_mode" in caplog.text


def test_unknown_provider_disables_precheck(caplog):
    assert PrecheckSettings.from_mapping({"mode": "enforce", "provider": "bogus"}).mode == "off"
    assert "self_rag_precheck_unknown_provider" in caplog.text


def test_config_without_precheck_defaults_to_off():
    config = _yaml_config()
    del config["precheck"]
    settings = PrecheckSettings.from_mapping(config.get("precheck") or {})
    assert settings.mode == "off"
    assert settings.model_dump() == PrecheckSettings().model_dump()


def test_precheck_settings_round_trip_runtime_fields():
    config = _yaml_config()
    config["precheck"] = {
        "mode": "enforce", "provider": "mock", "threshold": 0.45,
        "instructions": "Custom rubric", "timeout_ms": 250, "max_context_chars": 1234,
        "api_base": "https://typesafe.example", "systemone_path": "/proxy/v1/systemone",
        "model": "jev-test", "api_key": "test-only-key",
    }
    settings = PrecheckSettings.from_mapping(config["precheck"])
    assert settings.model_dump() == config["precheck"]
    assert "test-only-key" not in repr(settings)


@pytest.mark.parametrize("mode", [None, "off", "shadow", "enforce"])
def test_di_injects_wrapped_evaluator_and_off_preserves_identity(mode):
    container = AppContainer()
    config = {"enabled": True, "initial_top_k": 5, "retry_top_k": 15, "max_retries": 1}
    if mode is not None:
        config["precheck"] = {"mode": mode, "provider": "mock"}
    container.config.from_dict({"self_rag": config})
    base = _RecordingEvaluator()
    with (
        container.answer_evaluator.override(base),
        container.complexity_calculator.override(_FakeComplexityCalculator()),
        container.retrieval_orchestrator.override(_RecordingRetrieval()),
        container.generation.override(_RecordingGeneration()),
    ):
        evaluator = container.self_rag_evaluator()
        assert container.self_rag().evaluator is evaluator
        assert container.self_rag_evaluator() is evaluator
        if mode in (None, "off"):
            assert evaluator is base
        else:
            assert isinstance(evaluator, PrecheckQualityEvaluator)
            assert evaluator.base_evaluator is base
            assert isinstance(evaluator.provider, MockDecisionProvider)
            assert evaluator.settings.mode == mode
