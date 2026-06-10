"""에이전트 출력 언어 설정 이관 테스트

synthesizer/planner/reflector의 출력 언어 지시를 AgentConfig.output_language로
파라미터화한다.

핵심 요구사항:
1. AgentConfig.output_language 기본값은 "한국어"다(하위 호환).
2. AgentFactory.create_config가 mcp.agent.output_language를 읽는다.
3. 각 컴포넌트의 시스템 프롬프트에 설정된 언어가 반영된다.
"""

from unittest.mock import MagicMock

from app.modules.core.agent.factory import AgentFactory
from app.modules.core.agent.interfaces import AgentConfig
from app.modules.core.agent.planner import AgentPlanner, build_planner_system_prompt
from app.modules.core.agent.reflector import (
    AgentReflector,
    build_reflector_system_prompt,
)
from app.modules.core.agent.synthesizer import (
    AgentSynthesizer,
    build_synthesizer_system_prompt,
)


def test_agent_config_output_language_default_korean() -> None:
    """AgentConfig.output_language 기본값은 한국어다."""
    config = AgentConfig()
    assert config.output_language == "한국어"


def test_factory_create_config_reads_output_language() -> None:
    """create_config가 mcp.agent.output_language를 읽는다."""
    cfg = {"mcp": {"agent": {"output_language": "English"}}}
    agent_config = AgentFactory.create_config(cfg)
    assert agent_config.output_language == "English"


def test_factory_create_config_defaults_korean() -> None:
    """설정이 없으면 create_config는 한국어를 기본값으로 사용한다."""
    agent_config = AgentFactory.create_config({})
    assert agent_config.output_language == "한국어"


def test_synthesizer_system_prompt_default_korean() -> None:
    """synthesizer 시스템 프롬프트 기본값은 한국어 지시를 포함한다."""
    prompt = build_synthesizer_system_prompt("한국어")
    assert "한국어로 자연스럽고 친절하게 답변하세요" in prompt


def test_synthesizer_system_prompt_uses_language() -> None:
    """언어를 바꾸면 synthesizer 시스템 프롬프트에 반영된다."""
    prompt = build_synthesizer_system_prompt("English")
    assert "English" in prompt
    assert "한국어로 자연스럽고 친절하게" not in prompt


def test_planner_system_prompt_uses_language() -> None:
    """planner 시스템 프롬프트의 reasoning 언어가 설정값으로 반영된다."""
    prompt = build_planner_system_prompt("English")
    assert "English" in prompt
    assert "도구 선택 이유 (한국어" not in prompt


def test_reflector_system_prompt_uses_language() -> None:
    """reflector 시스템 프롬프트에 출력 언어가 반영된다."""
    prompt = build_reflector_system_prompt("English")
    assert "English" in prompt


def test_synthesizer_instance_uses_config_language() -> None:
    """AgentSynthesizer 인스턴스가 config.output_language로 프롬프트를 빌드한다."""
    config = AgentConfig(output_language="English")
    synth = AgentSynthesizer(llm_client=MagicMock(), config=config)
    assert "English" in synth._system_prompt
    assert "한국어로 자연스럽고 친절하게" not in synth._system_prompt


def test_planner_instance_uses_config_language() -> None:
    """AgentPlanner 인스턴스가 config.output_language로 프롬프트를 빌드한다."""
    config = AgentConfig(output_language="English")
    planner = AgentPlanner(
        llm_client=MagicMock(),
        mcp_server=MagicMock(),
        config=config,
    )
    assert "English" in planner._system_prompt_template


def test_reflector_instance_uses_config_language() -> None:
    """AgentReflector 인스턴스가 config.output_language로 프롬프트를 빌드한다."""
    config = AgentConfig(output_language="English")
    reflector = AgentReflector(llm_client=MagicMock(), config=config)
    assert "English" in reflector._system_prompt
