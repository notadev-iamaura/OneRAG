"""Tool 팩토리 테스트 (MCP 하위 호환성)"""


def test_supported_tools_registry_exists():
    """SUPPORTED_TOOLS 레지스트리 존재 확인"""
    from app.modules.core.tools.factory import SUPPORTED_TOOLS

    assert isinstance(SUPPORTED_TOOLS, dict)
    assert len(SUPPORTED_TOOLS) > 0


def test_factory_get_supported_tools():
    """get_supported_tools() 메서드 테스트"""
    from app.modules.core.tools import ToolFactory

    tools = ToolFactory.get_supported_tools()

    assert isinstance(tools, list)
    assert "search_weaviate" in tools


def test_factory_get_tool_info():
    """get_tool_info() 메서드 테스트"""
    from app.modules.core.tools import ToolFactory

    info = ToolFactory.get_tool_info("search_weaviate")

    assert info is not None
    assert "description" in info
    assert "category" in info


def test_factory_get_tool_info_unknown():
    """알 수 없는 도구 조회 시 None 반환"""
    from app.modules.core.tools import ToolFactory

    info = ToolFactory.get_tool_info("unknown_tool")

    assert info is None


def test_factory_list_tools_by_category():
    """카테고리별 도구 목록 조회 (vector 카테고리)"""
    from app.modules.core.tools import ToolFactory

    # 'weaviate' 카테고리가 'vector'로 변경됨
    vector_tools = ToolFactory.list_tools_by_category("vector")

    assert isinstance(vector_tools, list)
    assert "search_weaviate" in vector_tools


def test_factory_list_tools_by_category_sql():
    """SQL 카테고리 도구 목록 조회"""
    from app.modules.core.tools import ToolFactory

    sql_tools = ToolFactory.list_tools_by_category("sql")

    assert isinstance(sql_tools, list)
    assert "query_sql" in sql_tools


def test_supported_tools_have_required_fields():
    """SUPPORTED_TOOLS 각 항목에 필수 필드가 있는지 확인"""
    from app.modules.core.tools.factory import SUPPORTED_TOOLS

    required_fields = ["category", "description", "module", "function"]

    for tool_name, tool_info in SUPPORTED_TOOLS.items():
        for field in required_fields:
            assert field in tool_info, f"{tool_name}에 {field} 필드가 없습니다"


def test_factory_register_tool():
    """동적 도구 등록 테스트"""
    from app.modules.core.tools import ToolFactory
    from app.modules.core.tools.factory import SUPPORTED_TOOLS

    # 초기 개수 저장
    len(SUPPORTED_TOOLS)

    # 새 도구 등록
    ToolFactory.register_tool(
        tool_name="test_dynamic_tool",
        category="test",
        description="동적 테스트 도구",
        module="app.modules.core.tools.test",
        function="test_func",
    )

    # 등록 확인
    assert "test_dynamic_tool" in SUPPORTED_TOOLS
    assert SUPPORTED_TOOLS["test_dynamic_tool"]["category"] == "test"

    # 정리 (다른 테스트에 영향 없도록)
    del SUPPORTED_TOOLS["test_dynamic_tool"]


def test_mcp_alias_compatibility():
    """MCPToolFactory 하위 호환성 alias 테스트"""
    from app.modules.core.tools import MCPToolFactory, ToolFactory

    # MCPToolFactory는 ToolFactory의 alias
    assert MCPToolFactory is ToolFactory


