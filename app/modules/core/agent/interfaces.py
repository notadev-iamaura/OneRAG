"""
Agent 인터페이스 및 데이터 클래스 정의

ReAct 패턴 기반 에이전트 시스템의 핵심 타입 정의.
LLM이 도구 선택 → 실행 → 결과 평가를 반복하는 에이전트 루프에서 사용됩니다.

주요 클래스:
- AgentConfig: 에이전트 설정 (mcp.yaml과 매핑)
- ToolCall: 도구 호출 요청
- ToolResult: 도구 실행 결과
- AgentStep: ReAct 패턴 한 사이클 (Plan → Execute → Observe)
- AgentState: 에이전트 메모리 (히스토리 관리)
- AgentResult: 최종 결과
"""

from dataclasses import dataclass, field
from typing import Any, Literal
from uuid import uuid4


@dataclass
class AgentConfig:
    """
    에이전트 설정

    mcp.yaml의 agent 섹션과 매핑됩니다.
    AgentFactory에서 YAML 설정을 읽어 이 클래스로 변환합니다.

    Attributes:
        tool_selection: 도구 선택 방식 ("llm" | "rule_based" | "hybrid")
        selector_model: 도구 선택에 사용할 LLM 모델
        max_iterations: 최대 반복 횟수 (무한 루프 방지)
        fallback_tool: 도구 선택 실패 시 사용할 기본 도구
        timeout: 전체 에이전트 실행 타임아웃 (초, deprecated)
        timeout_seconds: 전체 작업 타임아웃 (초, QA-003)
        tool_timeout: 개별 도구 실행 타임아웃 (초)
        parallel_execution: 병렬 도구 실행 여부
        enable_reflection: Self-Reflection 활성화 여부 (기본: True)
        reflection_threshold: Reflection 품질 임계값 (기본: 7.0)
        max_reflection_iterations: 최대 Reflection 반복 횟수 (기본: 2)
    """

    # 도구 선택 방식: "llm" | "rule_based" | "hybrid"
    tool_selection: str = "llm"

    # 도구 선택에 사용할 LLM 모델
    selector_model: str = "google/gemini-2.5-flash-lite"

    # 최대 반복 횟수 (무한 루프 방지)
    max_iterations: int = 5

    # 폴백 도구 (도구 선택 실패 시)
    fallback_tool: str = "search_weaviate"

    # 전체 타임아웃 (초)
    timeout: float = 60.0  # 하위 호환성 유지 (deprecated)
    timeout_seconds: float = 300.0  # QA-003: 전체 작업 타임아웃 (초, 기본: 5분)

    # 개별 도구 타임아웃 (초)
    tool_timeout: float = 15.0

    # 병렬 도구 실행 여부
    parallel_execution: bool = True

    # 최대 동시 실행 도구 수 (병렬 실행 시 동시성 제어)
    max_concurrent_tools: int = 3

    # === Self-Reflection 설정 ===

    # Reflection 활성화 여부
    enable_reflection: bool = True

    # Reflection 품질 threshold (이 점수 미만이면 개선 필요)
    reflection_threshold: float = 7.0

    # 최대 Reflection 반복 횟수
    max_reflection_iterations: int = 2


@dataclass
class ToolCall:
    """
    도구 호출 요청

    LLM이 선택한 도구와 인자를 담는 데이터 클래스.
    AgentPlanner에서 생성되어 AgentExecutor로 전달됩니다.

    Attributes:
        tool_name: 도구 이름 (MCP 도구 레지스트리에 등록된 이름)
        arguments: 도구 인자 (딕셔너리)
        call_id: 호출 ID (추적용, 자동 생성)
        reasoning: LLM의 reasoning (왜 이 도구를 선택했는지)
    """

    # 도구 이름 (MCP 도구 레지스트리에 등록된 이름)
    tool_name: str

    # 도구 인자 (딕셔너리)
    arguments: dict[str, Any]

    # 호출 ID (추적용, 자동 생성 - UUID 앞 8자리)
    call_id: str = field(default_factory=lambda: str(uuid4())[:8])

    # LLM의 reasoning (선택적)
    reasoning: str = ""


@dataclass
class ToolResult:
    """
    도구 실행 결과

    MCPServer.execute_tool() 결과를 래핑하는 데이터 클래스.
    AgentExecutor에서 생성되어 AgentSynthesizer로 전달됩니다.

    Attributes:
        call_id: 호출 ID (ToolCall과 매칭)
        tool_name: 도구 이름
        success: 성공 여부
        data: 결과 데이터 (성공 시)
        error: 에러 메시지 (실패 시)
        execution_time: 실행 시간 (초)
    """

    # 호출 ID (ToolCall과 매칭)
    call_id: str

    # 도구 이름
    tool_name: str

    # 성공 여부
    success: bool

    # 결과 데이터 (성공 시)
    data: dict[str, Any] | None = None

    # 에러 메시지 (실패 시)
    error: str | None = None

    # 실행 시간 (초)
    execution_time: float = 0.0


@dataclass
class AgentStep:
    """
    에이전트 한 스텝 (Plan → Execute → Observe)

    ReAct 패턴의 한 사이클을 나타내는 데이터 클래스.
    AgentOrchestrator에서 생성되어 AgentState에 저장됩니다.

    Attributes:
        step_number: 스텝 번호 (1-based)
        reasoning: LLM의 reasoning (왜 이 도구를 선택했는지)
        tool_calls: 이번 스텝에서 호출한 도구들
        tool_results: 도구 실행 결과들
        should_continue: 이 스텝 완료 후 LLM의 판단 (계속/종료)
        duration: 스텝 완료 시간 (초)
    """

    # 스텝 번호 (1-based)
    step_number: int

    # LLM의 reasoning (왜 이 도구를 선택했는지)
    reasoning: str

    # 이번 스텝에서 호출한 도구들
    tool_calls: list[ToolCall]

    # 도구 실행 결과들
    tool_results: list[ToolResult]

    # 이 스텝 완료 후 LLM의 판단 (계속/종료)
    should_continue: bool = True

    # 스텝 완료 시간 (초)
    duration: float = 0.0


@dataclass
class AgentState:
    """
    에이전트 전체 상태 (AgentMemory)

    대화 진행 상태와 히스토리를 관리하는 데이터 클래스.
    AgentOrchestrator에서 생성되어 전체 에이전트 루프 동안 유지됩니다.

    Attributes:
        original_query: 원본 사용자 쿼리
        status: 현재 상태
        steps: 실행된 스텝들 (히스토리)
        final_answer: 최종 답변 (완료 시)
        sources: 소스 정보 (검색 결과에서 추출)
        error: 에러 정보 (실패 시)
    """

    # 원본 쿼리
    original_query: str

    # 현재 상태: "pending" | "running" | "completed" | "failed" | "max_iterations"
    status: Literal[
        "pending", "running", "completed", "failed", "max_iterations"
    ] = "pending"

    # 실행된 스텝들 (히스토리)
    steps: list[AgentStep] = field(default_factory=list)

    # 최종 답변 (완료 시)
    final_answer: str | None = None

    # 소스 정보 (검색 결과에서 추출)
    sources: list[dict[str, Any]] = field(default_factory=list)

    # 에러 정보 (실패 시)
    error: str | None = None

    @property
    def current_iteration(self) -> int:
        """
        현재 반복 횟수

        Returns:
            실행된 스텝 수
        """
        return len(self.steps)

    @property
    def all_tool_results(self) -> list[ToolResult]:
        """
        모든 스텝의 도구 결과 (평탄화)

        여러 스텝에 걸쳐 분산된 도구 결과들을 하나의 리스트로 모읍니다.
        AgentSynthesizer에서 최종 답변 생성 시 사용됩니다.

        Returns:
            모든 도구 결과 리스트
        """
        results = []
        for step in self.steps:
            results.extend(step.tool_results)
        return results

    def get_context_for_llm(self) -> str:
        """
        LLM에 전달할 컨텍스트 문자열 생성

        이전 스텝들의 요약을 반환합니다.
        AgentPlanner에서 다음 도구 선택 시 참조합니다.

        Returns:
            이전 스텝들의 요약 문자열 (없으면 빈 문자열)
        """
        if not self.steps:
            return ""

        context_parts = []
        for step in self.steps:
            step_summary = f"Step {step.step_number}: {step.reasoning}"
            for result in step.tool_results:
                if result.success:
                    step_summary += f"\n  - {result.tool_name}: 성공"
                else:
                    step_summary += f"\n  - {result.tool_name}: 실패 ({result.error})"
            context_parts.append(step_summary)

        return "\n".join(context_parts)


@dataclass
class AgentResult:
    """
    에이전트 최종 결과

    AgentOrchestrator.run() 반환값으로 사용되는 데이터 클래스.
    RAGPipeline에서 사용자에게 반환됩니다.

    Attributes:
        success: 성공 여부
        answer: 최종 답변
        sources: 참조 소스 (검색 결과에서 추출)
        steps_taken: 실행된 스텝 수
        total_time: 총 실행 시간 (초)
        tools_used: 사용된 도구들
        error: 에러 정보 (실패 시)
        debug_info: 디버그 정보 (선택적)
    """

    # 성공 여부
    success: bool

    # 최종 답변
    answer: str

    # 참조 소스 (검색 결과에서 추출)
    sources: list[dict[str, Any]] = field(default_factory=list)

    # 실행된 스텝 수
    steps_taken: int = 0

    # 총 실행 시간 (초)
    total_time: float = 0.0

    # 사용된 도구들
    tools_used: list[str] = field(default_factory=list)

    # 에러 정보 (실패 시)
    error: str | None = None

    # 디버그 정보 (선택적)
    debug_info: dict[str, Any] = field(default_factory=dict)


@dataclass
class ReflectionResult:
    """
    Self-Reflection 결과

    AgentReflector가 답변 품질을 평가한 결과를 담는 데이터 클래스.
    점수가 threshold 미만이면 needs_improvement=True로 설정됩니다.

    Attributes:
        score: 품질 점수 (0-10, 높을수록 좋음)
        issues: 발견된 문제점 리스트
        suggestions: 개선 제안 리스트
        needs_improvement: 추가 개선 필요 여부
        reasoning: 평가 근거
    """

    # 품질 점수 (0-10)
    score: float

    # 추가 개선 필요 여부
    needs_improvement: bool

    # 발견된 문제점
    issues: list[str] = field(default_factory=list)

    # 개선 제안
    suggestions: list[str] = field(default_factory=list)

    # 평가 근거
    reasoning: str = ""
