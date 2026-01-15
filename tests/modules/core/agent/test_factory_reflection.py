"""
AgentFactory Reflector 생성 테스트

AgentFactory가 Reflector를 올바르게 생성하고 Orchestrator에 주입하는지 검증:
- Reflection 활성화 시 Reflector 생성
- Reflection 비활성화 시 Reflector 미생성
- YAML 설정에서 Reflection 옵션 로드
"""
import pytest
from unittest.mock import MagicMock, patch

from app.modules.core.agent.factory import AgentFactory, DEFAULT_AGENT_CONFIG
from app.modules.core.agent.interfaces import AgentConfig


class TestAgentFactoryReflection:
    """AgentFactory Reflection 생성 테스트"""

    @pytest.fixture
    def mock_llm_client(self):
        """Mock LLM 클라이언트"""
        return MagicMock()

    @pytest.fixture
    def mock_mcp_server(self):
        """Mock MCP 서버 (활성화 상태)"""
        server = MagicMock()
        server.is_enabled = True
        server.get_tool_schemas.return_value = []
        return server

    @pytest.fixture
    def config_with_reflection(self):
        """Reflection 활성화 설정"""
        return {
            "mcp": {
                "enabled": True,
                "agent": {
                    "enable_reflection": True,
                    "reflection_threshold": 8.0,
                    "max_reflection_iterations": 3,
                },
            },
        }

    @pytest.fixture
    def config_without_reflection(self):
        """Reflection 비활성화 설정"""
        return {
            "mcp": {
                "enabled": True,
                "agent": {
                    "enable_reflection": False,
                },
            },
        }

    def test_create_config_with_reflection_defaults(self):
        """기본 Reflection 설정 테스트"""
        # Given: 빈 설정
        config: dict = {"mcp": {"agent": {}}}

        # When: AgentConfig 생성
        agent_config = AgentFactory.create_config(config)

        # Then: 기본 Reflection 설정이 적용됨
        assert agent_config.enable_reflection is True  # 기본값
        assert agent_config.reflection_threshold == 7.0  # 기본값
        assert agent_config.max_reflection_iterations == 2  # 기본값

    def test_create_config_with_custom_reflection(self):
        """커스텀 Reflection 설정 테스트"""
        # Given: 커스텀 Reflection 설정
        config = {
            "mcp": {
                "agent": {
                    "enable_reflection": True,
                    "reflection_threshold": 8.5,
                    "max_reflection_iterations": 5,
                },
            },
        }

        # When: AgentConfig 생성
        agent_config = AgentFactory.create_config(config)

        # Then: 커스텀 설정이 적용됨
        assert agent_config.enable_reflection is True
        assert agent_config.reflection_threshold == 8.5
        assert agent_config.max_reflection_iterations == 5

    def test_create_config_with_reflection_disabled(self):
        """Reflection 비활성화 설정 테스트"""
        # Given: Reflection 비활성화 설정
        config = {
            "mcp": {
                "agent": {
                    "enable_reflection": False,
                },
            },
        }

        # When: AgentConfig 생성
        agent_config = AgentFactory.create_config(config)

        # Then: Reflection 비활성화됨
        assert agent_config.enable_reflection is False

    def test_factory_creates_reflector_when_enabled(
        self, mock_llm_client, mock_mcp_server, config_with_reflection
    ):
        """Reflection 활성화 시 Reflector가 생성되어 주입됨"""
        # When: Orchestrator 생성
        orchestrator = AgentFactory.create(
            config=config_with_reflection,
            llm_client=mock_llm_client,
            mcp_server=mock_mcp_server,
        )

        # Then: Orchestrator가 생성되고 Reflector가 주입됨
        assert orchestrator is not None
        assert orchestrator._reflector is not None

    def test_factory_no_reflector_when_disabled(
        self, mock_llm_client, mock_mcp_server, config_without_reflection
    ):
        """Reflection 비활성화 시 Reflector가 생성되지 않음"""
        # When: Orchestrator 생성
        orchestrator = AgentFactory.create(
            config=config_without_reflection,
            llm_client=mock_llm_client,
            mcp_server=mock_mcp_server,
        )

        # Then: Orchestrator가 생성되지만 Reflector는 None
        assert orchestrator is not None
        assert orchestrator._reflector is None

    def test_default_config_includes_reflection_settings(self):
        """기본 설정에 Reflection 관련 설정 포함"""
        # When: 기본 설정 조회
        defaults = AgentFactory.get_default_config()

        # Then: Reflection 설정 포함
        assert "enable_reflection" in defaults
        assert "reflection_threshold" in defaults
        assert "max_reflection_iterations" in defaults

