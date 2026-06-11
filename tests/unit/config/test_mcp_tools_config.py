"""
mcp/agent 데드 컨피그 회귀 테스트 (P2)

차단하는 결함:
    tools.yaml이 base.yaml imports에 없어 로드 자체가 안 됐고, 키 구조도
    코드가 읽는 경로(config["mcp"]["agent"])와 불일치해 운영자가
    output_language 등을 바꿔도 무효였던 결함.

검증 원칙:
    합성 dict가 아니라 실제 load_config() 결과를 끝까지 사용한다.
    (과거 합성 dict 기반 테스트가 이 결함을 가렸던 전철을 방지)

정본(canonical) 구조:
    - mcp.enabled        → di_container.create_mcp_server_instance 활성화 게이트 (기본 false)
    - mcp.agent.*        → AgentFactory.create_config
    - mcp.tools.<도구명> → 도구 구현(vector_search 등) 파라미터 조회
    - ToolFactory도 mcp 섹션을 정본으로 우선 조회한다 (tools는 레거시 폴백).
    - tools 섹션은 mcp의 YAML 별칭 — 레거시 외부 소비자 호환을 위해
      출하 설정에서는 두 섹션 내용이 동일해야 한다.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest

from app.lib.config_loader import ConfigLoader, load_config
from app.modules.core.agent.factory import AgentFactory
from app.modules.core.tools.factory import ToolFactory


@pytest.fixture(scope="module")
def loaded_config() -> dict[str, Any]:
    """실제 설정 파일을 로드한다 (원시 병합 결과 확인)."""
    return load_config(validate=False)


def test_mcp_section_present_with_required_subsections(
    loaded_config: dict[str, Any],
) -> None:
    """출하 설정 로드만으로 mcp 섹션과 핵심 하위 구조가 존재해야 한다."""
    mcp = loaded_config.get("mcp")
    assert mcp is not None, (
        "load_config() 결과에 'mcp' 섹션이 없습니다. "
        "app/config/features/tools.yaml이 base.yaml imports에 포함됐는지, "
        "tools.yaml에 정본 mcp: 섹션이 있는지 확인하십시오."
    )
    # 기능 기본 비활성 — 단, 키가 존재해야 설정만으로 켤 수 있다
    assert mcp.get("enabled") is False, (
        "mcp.enabled 기본값은 false여야 합니다 (기본 비활성, 설정으로만 활성화)"
    )
    assert isinstance(mcp.get("agent"), dict), "mcp.agent 하위 섹션 누락"
    assert isinstance(mcp.get("tools"), dict), "mcp.tools 하위 섹션 누락"


def test_mcp_section_survives_default_validation_path() -> None:
    """기본 load_config()(Pydantic 검증 경로)에서도 mcp 섹션이 보존돼야 한다."""
    config = load_config()
    assert config.get("mcp") is not None, (
        "Pydantic 검증/model_dump 과정에서 mcp 섹션이 유실됐습니다 "
        "(루트 스키마의 extra 허용 여부 확인)"
    )


def test_agent_output_language_flows_from_yaml_to_factory(
    loaded_config: dict[str, Any],
) -> None:
    """yaml의 output_language 값이 AgentFactory.create_config까지 전달돼야 한다."""
    agent_yaml = loaded_config["mcp"]["agent"]
    yaml_value = agent_yaml.get("output_language")
    assert isinstance(yaml_value, str) and yaml_value, (
        "mcp.agent.output_language가 출하 설정에 존재해야 합니다"
    )
    agent_config = AgentFactory.create_config(loaded_config)
    assert agent_config.output_language == yaml_value


def test_agent_output_language_change_is_effective(
    loaded_config: dict[str, Any],
) -> None:
    """운영자가 output_language를 바꾸면 AgentConfig에 실제로 반영돼야 한다.

    실로드된 설정의 해당 키만 변경해, '기본값과 우연히 일치해서 통과'하는
    가짜 검증을 배제한다.
    """
    for changed_value in ("English", "日本語"):
        config = copy.deepcopy(loaded_config)
        config["mcp"]["agent"]["output_language"] = changed_value
        agent_config = AgentFactory.create_config(config)
        assert agent_config.output_language == changed_value


def test_tools_alias_is_synchronized_with_mcp(
    loaded_config: dict[str, Any],
) -> None:
    """레거시 tools 섹션은 mcp 섹션과 내용이 동일해야 한다.

    ToolFactory는 mcp 섹션을 정본으로 읽지만, tools 섹션을 직접 읽는
    레거시 외부 소비자와의 계약을 위해 출하 설정에서는 두 섹션 내용을
    동일하게 유지한다.
    """
    assert loaded_config.get("tools") == loaded_config.get("mcp"), (
        "tools 섹션과 mcp 섹션 내용이 다릅니다. "
        "tools.yaml에서 tools는 mcp의 YAML 별칭(*alias)으로 유지하십시오."
    )


def test_mcp_only_env_override_activates_tool_factory(
    loaded_config: dict[str, Any],
) -> None:
    """환경별 yaml이 mcp 섹션만 오버라이드해도 활성화가 일관돼야 한다.

    차단하는 결함(split-brain):
        tools 섹션은 mcp의 YAML 별칭이라 파일 로드 시점에만 동기화된다.
        운영자가 environments/*.yaml에 `mcp: {enabled: true}`만 추가하면
        병합 후 mcp는 새 dict, tools는 stale 별칭이 된다. 과거 ToolFactory가
        tools 섹션을 우선 읽어 활성화가 조용히 실패했다(di_container의
        mcp.enabled 게이트와 판단 분열). ToolFactory는 mcp를 정본으로
        읽어야 하며, 이 테스트는 그 회귀를 차단한다.
    """
    # 환경별 오버라이드와 동일한 방식으로 합성 병합 (_merge_configs 사용)
    base = copy.deepcopy(loaded_config)
    merged = ConfigLoader()._merge_configs(base, {"mcp": {"enabled": True}})

    # di_container.create_mcp_server_instance의 게이트 (mcp.enabled)
    assert merged["mcp"]["enabled"] is True, "mcp.enabled 오버라이드가 병합에 반영돼야 합니다"
    # stale 별칭 상태 재현 확인: tools는 여전히 비활성 (분열 상황 그 자체)
    assert merged["tools"]["enabled"] is False, (
        "전제 불성립: 병합 후 tools 별칭이 stale 상태여야 split-brain 재현이 됩니다"
    )

    # ToolFactory도 동일하게 '활성화'로 읽어야 한다 (비활성으로 읽으면 ValueError)
    server = ToolFactory.create(merged)
    assert server.is_enabled is True, (
        "ToolFactory가 mcp.enabled=true 오버라이드를 활성화로 읽지 못했습니다 "
        "(stale tools 별칭을 우선 조회하는 split-brain 회귀)"
    )


def test_registry_tools_have_explicit_yaml_entries(
    loaded_config: dict[str, Any],
) -> None:
    """SUPPORTED_TOOLS 레지스트리의 모든 도구가 yaml에 명시돼야 한다.

    yaml 항목이 없는 도구는 ToolFactory에서 기본 enabled=True로 조용히
    활성화되므로, 레지스트리에 도구를 추가하면 yaml에도 명시해 운영자가
    스위치를 볼 수 있게 강제한다.
    """
    yaml_tools = loaded_config["mcp"]["tools"]
    missing = [name for name in ToolFactory.get_supported_tools() if name not in yaml_tools]
    assert not missing, f"레지스트리 도구가 tools.yaml의 mcp.tools에 명시되지 않았습니다: {missing}"
