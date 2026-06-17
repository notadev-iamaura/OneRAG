"""
AgentOrchestrator - 메인 에이전트 루프

ReAct 패턴 기반 에이전트 루프를 조율하는 핵심 컴포넌트입니다.
Plan -> Execute -> Observe -> Synthesize -> Reflect 사이클을 반복하며
최종 답변을 생성합니다.

주요 기능:
- AgentPlanner를 통한 도구 선택 (Plan)
- AgentExecutor를 통한 도구 실행 (Execute)
- 결과 관찰 및 다음 행동 결정 (Observe)
- AgentSynthesizer를 통한 최종 답변 생성 (Synthesize)
- AgentReflector를 통한 답변 품질 평가 및 개선 (Reflect)
- max_iterations로 무한 루프 방지
- AgentResult 생성 및 반환

사용 예시:
    orchestrator = AgentOrchestrator(
        planner=planner,
        executor=executor,
        synthesizer=synthesizer,
        config=config,
        reflector=reflector,  # 선택적
    )
    result = await orchestrator.run("사용자 질문")

아키텍처:
    ┌──────────────────────────────────────────────────────────────────────────┐
    │                           AgentOrchestrator                               │
    │                                                                           │
    │  ┌─────────┐   ┌─────────┐   ┌─────────┐   ┌──────────┐   ┌─────────┐  │
    │  │  Plan   │──▶│ Execute │──▶│ Observe │──▶│Synthesize│──▶│ Reflect │  │
    │  │(Planner)│   │(Executor)│   │ (State) │   │ (Synth)  │   │(Reflector)│ │
    │  └─────────┘   └─────────┘   └─────────┘   └──────────┘   └─────────┘  │
    │       │                            │              │             │        │
    │       └────────── 반복 ────────────┘              └─── 개선 ────┘        │
    │              (until done or max)                (until pass or max)      │
    └──────────────────────────────────────────────────────────────────────────┘
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from app.lib.logger import get_logger
from app.modules.core.agent.executor import AgentExecutor
from app.modules.core.agent.interfaces import (
    AgentConfig,
    AgentResult,
    AgentState,
    AgentStep,
)
from app.modules.core.agent.planner import AgentPlanner
from app.modules.core.agent.synthesizer import AgentSynthesizer

if TYPE_CHECKING:
    from app.modules.core.agent.reflector import AgentReflector

logger = get_logger(__name__)


# 최상위 예외 시 사용자에게 노출되는 폴백 답변 (코드 내장 기본값=한국어).
# 운영자는 config.orchestrator_error_message(tools.yaml mcp.agent.prompts.
# orchestrator_error_message)로 코드 포크 없이 오버라이드한다 → 미설정 시 회귀 0.
ORCHESTRATOR_ERROR_MESSAGE = "죄송합니다. 처리 중 오류가 발생했습니다."

# Reflection 컨텍스트 추출 시 수집된 도구 결과가 없을 때의 대체 문자열
# (사용자 직접 노출이 아니라 LLM 프롬프트 내부 신호). 코드 내장 기본값=한국어.
# config.orchestrator_empty_context로 오버라이드 가능 → 미설정 시 회귀 0.
ORCHESTRATOR_EMPTY_CONTEXT = "검색 결과 없음"


class AgentOrchestrator:
    """
    에이전트 오케스트레이터

    ReAct 패턴 기반 에이전트 루프를 실행하는 핵심 컴포넌트입니다.
    Plan -> Execute -> Observe -> Synthesize 사이클을 반복하며
    최종 답변을 생성합니다.

    Attributes:
        _planner: 도구 선택기 (AgentPlanner)
        _executor: 도구 실행기 (AgentExecutor)
        _synthesizer: 결과 합성기 (AgentSynthesizer)
        _config: 에이전트 설정 (AgentConfig)
        _reflector: 답변 품질 평가기 (AgentReflector, 선택적)

    흐름:
        1. Planner: 다음 행동 결정 (도구 선택)
        2. Executor: 도구 실행
        3. Observe: 결과 확인 -> 계속/종료 결정
        4. Synthesizer: 최종 답변 생성
        5. Reflector: 답변 품질 평가 및 개선 (선택적)
    """

    def __init__(
        self,
        planner: AgentPlanner,
        executor: AgentExecutor,
        synthesizer: AgentSynthesizer,
        config: AgentConfig,
        reflector: AgentReflector | None = None,
    ) -> None:
        """
        AgentOrchestrator 초기화

        Args:
            planner: 도구 선택기 (LLM 기반)
            executor: 도구 실행기 (MCPServer 래핑)
            synthesizer: 결과 합성기 (최종 답변 생성)
            config: 에이전트 설정 (max_iterations, timeout 등)
            reflector: 답변 품질 평가기 (선택적, None이면 Reflection 건너뜀)

        Raises:
            ValueError: 필수 의존성 누락 시
        """
        if planner is None:
            raise ValueError("planner는 필수입니다")
        if executor is None:
            raise ValueError("executor는 필수입니다")
        if synthesizer is None:
            raise ValueError("synthesizer는 필수입니다")
        if config is None:
            raise ValueError("config는 필수입니다")

        self._planner = planner
        self._executor = executor
        self._synthesizer = synthesizer
        self._config = config
        self._reflector = reflector
        # 사용자 노출 폴백 메시지/내부 컨텍스트 대체어를 config 우선으로 해소.
        # 미설정(None)이면 코드 내장 한국어 기본값을 사용한다 → 회귀 0.
        self._error_message = (
            getattr(config, "orchestrator_error_message", None)
            or ORCHESTRATOR_ERROR_MESSAGE
        )
        self._empty_context = (
            getattr(config, "orchestrator_empty_context", None)
            or ORCHESTRATOR_EMPTY_CONTEXT
        )

        logger.info(
            f"AgentOrchestrator 초기화: "
            f"max_iterations={config.max_iterations}, "
            f"timeout={config.timeout}s, "
            f"reflection={'enabled' if reflector and config.enable_reflection else 'disabled'}"
        )

    async def run(
        self,
        query: str,
        session_context: str = "",
    ) -> AgentResult:
        """
        에이전트 루프 실행

        사용자 쿼리를 받아 ReAct 루프를 실행하고
        최종 결과를 AgentResult로 반환합니다.

        Args:
            query: 사용자 질문
            session_context: 세션 컨텍스트 (이전 대화 내용, 선택적)

        Returns:
            AgentResult: 최종 결과 (성공 여부, 답변, 소스 등)

        Note:
            - max_iterations에 도달하면 현재까지의 결과로 답변 생성
            - 예외 발생 시 실패 결과 반환
        """
        start_time = time.time()

        # 상태 초기화
        state = AgentState(original_query=query)
        state.status = "running"

        # 세션 컨텍스트가 있으면 로깅 (향후 AgentState 확장 시 활용)
        if session_context:
            logger.debug(f"세션 컨텍스트: {session_context[:100]}...")

        logger.info(f"Agent 시작: {query[:50]}...")

        try:
            # 메인 ReAct 루프
            while state.current_iteration < self._config.max_iterations:
                step_start = time.time()
                iteration = state.current_iteration + 1

                logger.info(
                    f"Step {iteration}/{self._config.max_iterations}"
                )

                # 1. Plan: 다음 행동 결정 (도구 선택)
                tool_calls, reasoning, should_continue = await self._planner.plan(
                    state
                )

                # 2. Execute: 도구 실행
                tool_results = []
                if tool_calls:
                    tool_results = await self._executor.execute(tool_calls)

                # 3. Observe: 스텝 기록
                step = AgentStep(
                    step_number=iteration,
                    reasoning=reasoning,
                    tool_calls=tool_calls,
                    tool_results=tool_results,
                    should_continue=should_continue,
                    duration=time.time() - step_start,
                )
                state.steps.append(step)

                logger.debug(
                    f"Step {iteration} 완료: "
                    f"도구={len(tool_calls)}개, "
                    f"should_continue={should_continue}"
                )

                # 4. 종료 조건 확인
                if not should_continue:
                    logger.info(
                        f"Agent 종료 (should_continue=False, step={iteration})"
                    )
                    break

            # 최대 반복 도달 확인
            if state.current_iteration >= self._config.max_iterations:
                logger.warning(
                    f"최대 반복 횟수 도달 ({self._config.max_iterations})"
                )
                state.status = "max_iterations"

            # 5. Synthesize: 최종 답변 생성
            answer, sources = await self._synthesizer.synthesize(state)

            # 6. Reflect: 답변 품질 평가 및 개선 (선택적)
            if self._should_reflect():
                answer, sources = await self._reflection_loop(state, answer, sources)

            # 상태 업데이트
            state.final_answer = answer
            state.sources = sources
            state.status = "completed"

            # 결과 생성
            total_time = time.time() - start_time
            tools_used = self._collect_tools_used(state)

            logger.info(
                f"Agent 완료: {state.current_iteration}스텝, "
                f"{total_time:.2f}초, {len(tools_used)}개 도구 사용"
            )

            return AgentResult(
                success=True,
                answer=answer,
                sources=sources,
                steps_taken=state.current_iteration,
                total_time=total_time,
                tools_used=tools_used,
            )

        except Exception as e:
            # 에러 처리
            logger.error(f"Agent 에러: {e}", exc_info=True)

            state.status = "failed"
            state.error = str(e)

            return AgentResult(
                success=False,
                answer=self._error_message,
                error=str(e),
                steps_taken=state.current_iteration,
                total_time=time.time() - start_time,
            )

    def _collect_tools_used(self, state: AgentState) -> list[str]:
        """
        사용된 도구 목록 수집

        모든 스텝에서 사용된 도구 이름을 중복 제거하여 반환합니다.

        Args:
            state: 에이전트 상태

        Returns:
            사용된 도구 이름 리스트 (중복 제거)
        """
        tools_used: set[str] = set()

        for step in state.steps:
            for tool_call in step.tool_calls:
                tools_used.add(tool_call.tool_name)

        return list(tools_used)

    def _should_reflect(self) -> bool:
        """
        Reflection 실행 여부 판단

        설정에서 reflection이 활성화되어 있고,
        reflector가 주입된 경우에만 True를 반환합니다.

        Returns:
            bool: Reflection을 실행해야 하면 True
        """
        return (
            self._reflector is not None
            and self._config.enable_reflection
        )

    async def _reflection_loop(
        self,
        state: AgentState,
        answer: str,
        sources: list[dict],
    ) -> tuple[str, list[dict]]:
        """
        Self-Reflection 루프

        생성된 답변의 품질을 평가하고, threshold 미달 시
        재생성을 통해 개선합니다.

        Args:
            state: 현재 에이전트 상태
            answer: 초기 생성된 답변
            sources: 초기 소스 목록

        Returns:
            tuple[str, list[dict]]: 최종 답변과 소스 목록
        """
        if self._reflector is None:
            return answer, sources

        # 컨텍스트 추출 (검색 결과 요약)
        context = self._extract_context_for_reflection(state)

        current_answer = answer
        current_sources = sources

        for iteration in range(self._config.max_reflection_iterations):
            logger.info(
                f"Reflection 평가 {iteration + 1}/"
                f"{self._config.max_reflection_iterations}"
            )

            # Reflection 수행
            reflection_result = await self._reflector.reflect(
                query=state.original_query,
                answer=current_answer,
                context=context,
            )

            logger.debug(
                f"Reflection 결과: score={reflection_result.score}, "
                f"needs_improvement={reflection_result.needs_improvement}"
            )

            # 품질 충분하면 종료
            if not reflection_result.needs_improvement:
                logger.info(
                    f"Reflection 통과: score={reflection_result.score} "
                    f"(threshold={self._config.reflection_threshold})"
                )
                break

            # 마지막 iteration이면 더 이상 개선하지 않음
            if iteration == self._config.max_reflection_iterations - 1:
                logger.warning(
                    f"Reflection 최대 반복 도달: "
                    f"score={reflection_result.score}"
                )
                break

            # 재생성 시도
            logger.info(
                f"답변 재생성 시도: "
                f"issues={reflection_result.issues}"
            )
            current_answer, current_sources = await self._synthesizer.synthesize(
                state
            )

        return current_answer, current_sources

    def _extract_context_for_reflection(self, state: AgentState) -> str:
        """
        Reflection을 위한 컨텍스트 추출

        에이전트가 수집한 도구 결과들을 요약하여
        Reflection 평가에 사용할 컨텍스트를 생성합니다.

        Args:
            state: 에이전트 상태

        Returns:
            str: 검색 결과 요약 문자열
        """
        context_parts: list[str] = []

        for step in state.steps:
            for result in step.tool_results:
                if result.success and result.data:
                    # 결과가 너무 길면 truncate
                    result_text = str(result.data)[:500]
                    context_parts.append(
                        f"[{result.tool_name}]: {result_text}"
                    )

        if not context_parts:
            return self._empty_context

        return "\n".join(context_parts)
