"""Tools 설정 로딩 테스트"""

from pathlib import Path


def test_tools_yaml_exists():
    """tools.yaml 파일 존재 확인"""
    yaml_path = Path("app/config/features/tools.yaml")
    assert yaml_path.exists(), f"Tools 설정 파일이 없습니다: {yaml_path}"


def test_tools_yaml_structure():
    """tools.yaml 구조 확인"""
    import yaml

    with open("app/config/features/tools.yaml") as f:
        config = yaml.safe_load(f)

    assert "tools" in config, "tools 키가 없습니다"
    assert "enabled" in config["tools"], "enabled 키가 없습니다"
    assert "tools" in config["tools"], "tools.tools 키가 없습니다"


def test_tools_have_required_fields():
    """각 도구에 필수 필드가 있는지 확인"""
    import yaml

    with open("app/config/features/tools.yaml") as f:
        config = yaml.safe_load(f)

    tools = config["tools"]["tools"]
    required_fields = ["enabled", "description"]

    for tool_name, tool_config in tools.items():
        for field in required_fields:
            assert field in tool_config, f"{tool_name}에 {field} 필드가 없습니다"


def test_tools_server_name_exists():
    """server_name 필드 존재 확인"""
    import yaml

    with open("app/config/features/tools.yaml") as f:
        config = yaml.safe_load(f)

    assert "server_name" in config["tools"], "server_name 키가 없습니다"
    # 신규 tools.yaml의 서버 이름
    assert config["tools"]["server_name"] == "rag-tools"


def test_tools_has_vector_search_tools():
    """벡터 검색 관련 도구가 있는지 확인"""
    import yaml

    with open("app/config/features/tools.yaml") as f:
        config = yaml.safe_load(f)

    tools = config["tools"]["tools"]

    # search_vector 도구 확인
    assert "search_vector" in tools, "search_vector 도구가 없습니다"
    assert tools["search_vector"]["enabled"] is True


def test_mcp_yaml_backward_compatibility():
    """mcp.yaml 하위 호환성 (존재 시)"""
    yaml_path = Path("app/config/features/mcp.yaml")
    if yaml_path.exists():
        import yaml

        with open(yaml_path) as f:
            config = yaml.safe_load(f)

        assert "mcp" in config, "mcp 키가 없습니다"
        assert "enabled" in config["mcp"], "enabled 키가 없습니다"


