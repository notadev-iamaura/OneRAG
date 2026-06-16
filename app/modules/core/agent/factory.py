"""
AgentFactory - 에이전트 팩토리

설정 기반으로 AgentOrchestrator를 생성하는 팩토리 클래스.
기존 RerankerFactory, EmbedderFactory와 동일한 패턴을 따릅니다.

주요 기능:
- YAML 설정 기반 에이전트 컴포넌트 생성
- Planner, Executor, Synthesizer 조립
- MCP 비활성화 시 None 반환
- 기본 설정 제공

사용 예시:
    from app.modules.core.agent import AgentFactory

    # 설정 기반 Orchestrator 생성
    orchestrator = AgentFactory.create(
        config=config,
        llm_client=llm_client,
        mcp_server=mcp_server,
    )

    # 기본 설정 조회
    default = AgentFactory.get_default_config()
"""

from typing import Any

from ....lib.logger import get_logger
from .executor import AgentExecutor
from .interfaces import AgentConfig
from .orchestrator import AgentOrchestrator
from .planner import AgentPlanner
from .reflector import AgentReflector
from .synthesizer import AgentSynthesizer

logger = get_logger(__name__)


# 기본 에이전트 설정 상수
DEFAULT_AGENT_CONFIG = {
    "tool_selection": "llm",
    "selector_model": "google/gemini-2.5-flash-lite",
    "max_iterations": 5,
    "fallback_tool": "search_weaviate",
    "timeout": 60.0,  # deprecated
    "timeout_seconds": 300.0,  # QA-003: 전체 작업 타임아웃 (5분)
    "tool_timeout": 15.0,
    "parallel_execution": True,
    "max_concurrent_tools": 3,
    # Self-Reflection 설정
    "enable_reflection": True,
    "reflection_threshold": 7.0,
    "max_reflection_iterations": 2,
    # 출력 언어 (외주 언어 변경용, 기본값=한국어)
    "output_language": "한국어",
    # 프롬프트 오버라이드 (config 외부화). 기본값 None = 각 컴포넌트의 코드 내장
    # 한국어 기본 프롬프트 사용 → 미설정 시 회귀 0.
    "planner_system_prompt": None,
    "planner_user_prompt": None,
    "synthesizer_system_prompt": None,
    "synthesizer_user_prompt": None,
    "synthesizer_error_message": None,
    "reflector_system_prompt": None,
    "reflector_user_prompt": None,
    "reflector_empty_context": None,
    "orchestrator_error_message": None,
    "orchestrator_empty_context": None,
}


class AgentFactory:
    """
    에이전트 팩토리

    YAML 설정 기반으로 에이전트 컴포넌트들을 생성하고 조립합니다.
    DI Container에서 사용하는 표준 팩토리 패턴을 따릅니다.

    패턴:
    - create(): 전체 Orchestrator 생성
    - create_config(): AgentConfig 객체 생성
    - get_default_config(): 기본 설정 딕셔너리 반환
    """

    @staticmethod
    def create(
        config: dict[str, Any],
        llm_client: Any,
        mcp_server: Any,
    ) -> AgentOrchestrator | None:
        """
        AgentOrchestrator 생성

        설정, LLM 클라이언트, MCP 서버를 받아
        완전한 AgentOrchestrator 인스턴스를 생성합니다.

        Args:
            config: 전체 설정 딕셔너리 (mcp 섹션 포함)
            llm_client: LLM 클라이언트 (generate_text 메서드 필요)
            mcp_server: MCP 서버 (도구 스키마 제공)

        Returns:
            AgentOrchestrator 인스턴스 또는 None (비활성화 시)

        Note:
            - mcp.enabled=false인 경우 None 반환
            - mcp_server가 None이거나 is_enabled=False인 경우 None 반환
        """
        mcp_config = config.get("mcp", {})

        # MCP 비활성화 시 None 반환
        if not mcp_config.get("enabled", False):
            logger.info("ℹ️  Agent 비활성화 (mcp.enabled=false)")
            return None

        # MCP 서버 확인
        if mcp_server is None:
            logger.warning("⚠️  MCP 서버가 None - Agent를 생성할 수 없습니다")
            return None

        if not getattr(mcp_server, "is_enabled", False):
            logger.warning("⚠️  MCP 서버가 비활성화 - Agent를 생성할 수 없습니다")
            return None

        # 에이전트 설정 로드
        agent_config = AgentFactory.create_config(config)

        # 컴포넌트 생성
        planner = AgentPlanner(
            llm_client=llm_client,
            mcp_server=mcp_server,
            config=agent_config,
        )

        executor = AgentExecutor(
            mcp_server=mcp_server,
            config=agent_config,
        )

        synthesizer = AgentSynthesizer(
            llm_client=llm_client,
            config=agent_config,
        )

        # Reflector 생성 (Reflection 활성화 시에만)
        reflector: AgentReflector | None = None
        if agent_config.enable_reflection:
            reflector = AgentReflector(
                llm_client=llm_client,
                config=agent_config,
            )
            logger.debug("🔍 AgentReflector 생성 완료")

        # Orchestrator 생성
        orchestrator = AgentOrchestrator(
            planner=planner,
            executor=executor,
            synthesizer=synthesizer,
            config=agent_config,
            reflector=reflector,
        )

        logger.info(
            f"🤖 AgentFactory: Orchestrator 생성 완료 "
            f"(max_iterations={agent_config.max_iterations}, "
            f"fallback={agent_config.fallback_tool}, "
            f"reflection={'enabled' if reflector else 'disabled'})"
        )

        return orchestrator

    @staticmethod
    def create_config(config: dict[str, Any]) -> AgentConfig:
        """
        AgentConfig 객체 생성

        딕셔너리 설정을 AgentConfig 데이터 클래스로 변환합니다.
        누락된 설정은 기본값으로 채워집니다.

        Args:
            config: 전체 설정 딕셔너리 (mcp.agent 섹션 참조)

        Returns:
            AgentConfig: 에이전트 설정 객체
        """
        agent_yaml = config.get("mcp", {}).get("agent", {})
        defaults = DEFAULT_AGENT_CONFIG

        # 프롬프트 오버라이드는 mcp.agent.prompts 하위에서 읽는다.
        # 섹션/키가 없으면 빈 dict → .get()이 None 기본값을 반환 →
        # 각 컴포넌트가 코드 내장 한국어 기본 프롬프트를 사용한다 (회귀 0).
        prompts_yaml = agent_yaml.get("prompts", {}) or {}

        return AgentConfig(
            tool_selection=agent_yaml.get(
                "tool_selection",
                defaults["tool_selection"],
            ),
            selector_model=agent_yaml.get(
                "selector_model",
                defaults["selector_model"],
            ),
            # max_tool_calls (YAML) -> max_iterations (AgentConfig)
            max_iterations=int(
                agent_yaml.get(
                    "max_tool_calls",
                    defaults["max_iterations"],
                )
            ),
            fallback_tool=agent_yaml.get(
                "fallback_tool",
                defaults["fallback_tool"],
            ),
            timeout=float(
                agent_yaml.get(
                    "timeout",
                    defaults["timeout"],
                )
            ),
            # QA-003: 전체 작업 타임아웃 (환경변수 또는 YAML에서 로드)
            timeout_seconds=float(
                agent_yaml.get(
                    "timeout_seconds",
                    defaults["timeout_seconds"],
                )
            ),
            tool_timeout=float(
                agent_yaml.get(
                    "tool_timeout",
                    defaults["tool_timeout"],
                )
            ),
            parallel_execution=agent_yaml.get(
                "parallel_execution",
                defaults["parallel_execution"],
            ),
            max_concurrent_tools=int(
                agent_yaml.get(
                    "max_concurrent_tools",
                    defaults["max_concurrent_tools"],
                )
            ),
            # Self-Reflection 설정
            enable_reflection=agent_yaml.get(
                "enable_reflection",
                defaults["enable_reflection"],
            ),
            reflection_threshold=float(
                agent_yaml.get(
                    "reflection_threshold",
                    defaults["reflection_threshold"],
                )
            ),
            max_reflection_iterations=int(
                agent_yaml.get(
                    "max_reflection_iterations",
                    defaults["max_reflection_iterations"],
                )
            ),
            # 출력 언어 (없으면 한국어 기본값 → 기존 동작 보존)
            output_language=agent_yaml.get(
                "output_language",
                defaults["output_language"],
            ),
            # 프롬프트 오버라이드 (없으면 None → 코드 내장 한국어 기본 프롬프트)
            planner_system_prompt=prompts_yaml.get(
                "planner_system",
                defaults["planner_system_prompt"],
            ),
            planner_user_prompt=prompts_yaml.get(
                "planner_user",
                defaults["planner_user_prompt"],
            ),
            synthesizer_system_prompt=prompts_yaml.get(
                "synthesizer_system",
                defaults["synthesizer_system_prompt"],
            ),
            synthesizer_user_prompt=prompts_yaml.get(
                "synthesizer_user",
                defaults["synthesizer_user_prompt"],
            ),
            synthesizer_error_message=prompts_yaml.get(
                "synthesizer_error_message",
                defaults["synthesizer_error_message"],
            ),
            reflector_system_prompt=prompts_yaml.get(
                "reflector_system",
                defaults["reflector_system_prompt"],
            ),
            reflector_user_prompt=prompts_yaml.get(
                "reflector_user",
                defaults["reflector_user_prompt"],
            ),
            reflector_empty_context=prompts_yaml.get(
                "reflector_empty_context",
                defaults["reflector_empty_context"],
            ),
            orchestrator_error_message=prompts_yaml.get(
                "orchestrator_error_message",
                defaults["orchestrator_error_message"],
            ),
            orchestrator_empty_context=prompts_yaml.get(
                "orchestrator_empty_context",
                defaults["orchestrator_empty_context"],
            ),
        )

    @staticmethod
    def get_default_config() -> dict[str, Any]:
        """
        기본 에이전트 설정 반환

        새로운 프로젝트에서 사용할 수 있는 기본 설정을 제공합니다.

        Returns:
            기본 에이전트 설정 딕셔너리

        Note:
            반환되는 딕셔너리의 키들:
            - tool_selection: "llm" | "rule_based" | "hybrid"
            - selector_model: 도구 선택에 사용할 LLM 모델
            - max_iterations: 최대 반복 횟수
            - fallback_tool: 폴백 도구 이름
            - timeout: 전체 타임아웃 (초)
            - parallel_execution: 병렬 실행 여부
        """
        return DEFAULT_AGENT_CONFIG.copy()

    @staticmethod
    def get_supported_features() -> dict[str, Any]:
        """
        지원하는 에이전트 기능 정보 반환

        Returns:
            지원 기능 정보 딕셔너리
        """
        return {
            "tool_selection_modes": ["llm", "rule_based", "hybrid"],
            "execution_modes": ["sequential", "parallel"],
            "fallback_enabled": True,
            "max_iterations_range": (1, 20),
        }
