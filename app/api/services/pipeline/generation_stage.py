"""5단계 답변 생성: LLM 생성, Grok 답변 모드, 에이전트 모드.

rag_pipeline.py 의 RAGPipeline 에서 분리한 단계 믹스인. 동작은 분리 전과 동일하다.
"""
from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any, cast

from ....lib.circuit_breaker import CircuitBreakerOpenError
from ....lib.errors import ErrorCode, GenerationError, RetrievalError
from ....lib.langfuse_client import observe  # Langfuse 트레이싱
from ....lib.logger import get_logger
from ....lib.prompt_sanitizer import contains_output_leakage, validate_document
from ....lib.request_cost import bind_request_cost_ledger
from ....lib.types import RAGResultDict
from ..source_contract import normalize_citation_source_payload
from .document_utils import (
    _extract_fallback_document_preview,
)

if TYPE_CHECKING:
    from ...modules.core.generation.generator import GenerationResult

from .base import PipelineStateBase

logger = get_logger(__name__)


class GenerationStageMixin(PipelineStateBase):
    """5단계 답변 생성: LLM 생성, Grok 답변 모드, 에이전트 모드."""


    def _format_grok_citations(self, citations: list[Any]) -> list[Any]:
        """Convert Grok citation payloads into OneRAG Source objects."""
        sources: list[Any] = []
        for idx, citation in enumerate(citations):
            source_data = normalize_citation_source_payload(idx, citation, source_type="grok")
            sources.append(self.Source(**source_data))
        return sources


    async def _execute_grok_answer_mode(
        self,
        message: str,
        start_time: float,
        options: dict[str, Any],
        routing_metadata: dict[str, Any],
    ) -> RAGResultDict:
        """Execute Grok managed RAG answer mode as a narrow fast path."""
        provider = self.grok_answer_provider
        if asyncio.iscoroutine(provider) or isinstance(provider, asyncio.Future):
            provider = await provider

        if provider is None:
            raise RetrievalError(
                ErrorCode.GROK_003,
                reason="Grok answer mode requested but GrokAnswerProvider is not configured",
            )

        result = await provider.answer(
            question=message,
            collection_ids=options.get("collection_ids") or options.get("grok_collection_ids"),
            system_prompt=options.get("system_prompt"),
            top_k=options.get("top_k") or options.get("limit"),
            temperature=float(options.get("temperature", 0.0)),
            include_code_interpreter=bool(options.get("include_code_interpreter", False)),
        )
        sources = self._format_grok_citations(result.citations)
        model_info = {
            "provider": result.provider,
            "model": result.model_used,
            "model_used": result.model_used,
            "mode": "grok_answer",
            "tool_usage": result.tool_usage,
            "citations_count": len(result.citations),
        }
        routing_metadata = {
            **routing_metadata,
            "rag_mode": "grok_answer",
            "source": routing_metadata.get("source", "grok"),
        }
        return cast(
            RAGResultDict,
            self.build_result(
            answer=result.answer,
            sources=sources,
            tokens_used=result.tokens_used,
            topic=self.extract_topic_func(message),
            processing_time=time.time() - start_time,
            search_count=len(result.citations),
            ranked_count=len(result.citations),
            model_info=model_info,
            routing_metadata=routing_metadata,
            ),
        )


    @observe(name="Answer Generation (LLM)", capture_input=False, capture_output=False)
    async def generate_answer(
        self, message: str, ranked_results: list[Any], context: str | None, options: dict[str, Any]
    ) -> GenerationResult:
        """
        5단계: LLM 답변 생성

        - LLM 답변 생성 (Gemini/OpenAI/Claude)
        - Circuit Breaker 보호
        - Fallback 답변 처리 (LLM 실패 시)
        - 비용 추적 (CostTracker)

        Args:
            message: 사용자 질문
            ranked_results: 리랭킹된 문서
            context: 세션 컨텍스트
            options: 생성 옵션

        Returns:
            GenerationResult: 답변 + 토큰 수 + 모델 정보

        Raises:
            GenerationError: 답변 생성 실패 시
        """
        from ....modules.core.generation.generator import GenerationResult

        logger.debug("[6단계] 답변 생성 시작")
        if not self.generation_module:
            logger.error("생성 모듈 없음")
            return GenerationResult(
                answer=self.generation_module_missing_message,
                text=self.generation_module_missing_message,
                tokens_used=0,
                model_used="none",
                provider="none",
                generation_time=0.0,
            )
        cb = self.circuit_breaker_factory.get("answer_generation")
        safe_docs = []
        dropped_count = 0
        for doc in ranked_results or []:
            if validate_document(doc):
                safe_docs.append(doc)
            else:
                dropped_count += 1
                logger.warning(
                    "문서 인젝션 패턴 감지 - 차단",
                    extra={"total_dropped": dropped_count}
                )
        if dropped_count > 0:
            logger.info(
                "안전 문서 필터링 완료",
                extra={"safe_count": len(safe_docs), "dropped_count": dropped_count}
            )
        context_documents = safe_docs

        async def _generate() -> GenerationResult:
            """실제 답변 생성 로직 (Circuit Breaker 내부)"""
            # session_context를 options에 포함시켜 전달
            generation_options = {**options, "session_context": context}
            return cast(
                GenerationResult,
                await self.generation_module.generate_answer(
                    query=message, context_documents=context_documents, options=generation_options
                ),
            )

        def _fallback() -> dict[str, Any]:
            """LLM 실패 시 Fallback 답변 (메시지는 rag.yaml generation_fallback 외부화)"""
            if context_documents:
                top_doc = context_documents[0]
                # 문서 미리보기 추출 실패 시 대체 문구도 config 값을 따른다.
                content = _extract_fallback_document_preview(
                    top_doc,
                    unavailable_message=self.document_preview_unavailable_message,
                )
                # {content} 자리에 미리보기를 치환한다. 미리보기 텍스트에 중괄호가
                # 섞여도 안전하도록 .format이 아닌 .replace를 사용한다.
                answer = self.generation_fallback_with_docs_message.replace(
                    "{content}", content
                )
                return {
                    "answer": answer,
                    "tokens_used": 0,
                    "model_info": {"provider": "fallback", "model": "document_summary"},
                }
            else:
                return {
                    "answer": self.generation_fallback_no_docs_message,
                    "tokens_used": 0,
                    "model_info": {"provider": "fallback", "model": "none"},
                }

        try:
            start_time = time.time()
            generation_result: GenerationResult | dict[str, Any] = await cb.call(
                _generate, fallback=_fallback
            )
            latency_ms = (time.time() - start_time) * 1000
            self.performance_metrics.record_latency("generate_integrated_answer", latency_ms)

            # 타입 가드: GenerationResult 또는 dict 처리
            # GenerationResult 객체인지 확인 (hasattr로도 체크하여 더 안전하게)
            if isinstance(generation_result, GenerationResult):
                tokens = generation_result.tokens_used
                provider = generation_result.provider
                answer = generation_result.answer
                model_info = generation_result.model_info
            elif isinstance(generation_result, dict):
                # fallback이 dict를 반환한 경우 (Circuit Breaker 내부 fallback)
                tokens = generation_result.get("tokens_used", 0)
                provider = generation_result.get("model_info", {}).get("provider", "google")
                answer = generation_result.get("answer", "답변을 생성할 수 없습니다.")
                model_info = generation_result.get("model_info", {})
            else:
                # 예상치 못한 타입 (안전 장치)
                logger.error(f"⚠️ 예상치 못한 generation_result 타입: {type(generation_result)}")
                tokens = 0
                provider = "unknown"
                answer = self.generation_type_error_message
                model_info = {"provider": "error", "model": "unknown"}

            if tokens > 0 and provider in ["google", "openai", "anthropic"]:
                self.cost_tracker.track_usage(provider, tokens, is_input=False)

            if contains_output_leakage(answer):
                logger.error(
                    "프롬프트 누출 감지 - 답변 차단",
                    extra={"preview": answer[:100]}
                )
                answer = self.prompt_leakage_blocked_message
                self.performance_metrics.record_error("prompt_leakage_blocked")

            logger.info(
                "[6단계] 답변 생성 완료",
                extra={
                    "answer_length": len(answer),
                    "latency_ms": latency_ms,
                    "tokens": tokens
                }
            )
            return GenerationResult(
                answer=answer,
                text=answer,
                tokens_used=tokens,
                model_used=model_info.get("model", "unknown"),
                provider=model_info.get("provider", "unknown"),
                generation_time=latency_ms / 1000,
            )
        except CircuitBreakerOpenError:
            # Circuit Breaker 에러 → 일시적 장애, Fallback 사용
            logger.warning("🚫 Circuit Breaker OPEN - LLM 서비스 일시 차단, Fallback 사용")
            fallback_result = _fallback()
            return GenerationResult(
                answer=fallback_result["answer"],
                text=fallback_result["answer"],
                tokens_used=fallback_result["tokens_used"],
                model_used=fallback_result["model_info"].get("model", "fallback"),
                provider=fallback_result["model_info"].get("provider", "fallback"),
                generation_time=0.0,
            )
        except TimeoutError as e:
            # 타임아웃 에러 → 클라이언트에게 재시도 유도
            logger.error(
                "[6단계] 답변 생성 타임아웃",
                extra={"error": str(e)},
                exc_info=True
            )
            raise GenerationError(
                ErrorCode.GENERATION_TIMEOUT,
                session_id=options.get("session_id", "unknown"),
                timeout_seconds=30,
            ) from e
        except ValueError as e:
            # 입력 검증 에러 → 클라이언트 에러
            logger.error(
                "[6단계] 잘못된 입력",
                extra={"error": str(e)},
                exc_info=True
            )
            # ErrorCode.GENERATION_INVALID_RESPONSE 는 존재하지 않는 멤버였다(이 경로에서
            # AttributeError 가 났다). 생성 요청 실패 코드로 정규화한다.
            raise GenerationError(
                ErrorCode.GENERATION_REQUEST_FAILED,
                session_id=options.get("session_id", "unknown"),
                error=str(e),
            ) from e
        except Exception as e:
            # 예상치 못한 에러 → 서버 에러
            logger.error(
                "[6단계] 답변 생성 실패",
                extra={"error": str(e)},
                exc_info=True
            )
            raise GenerationError(
                ErrorCode.GENERATION_REQUEST_FAILED,
                session_id=options.get("session_id", "unknown"),
                error=str(e),
            ) from e


    async def _execute_agent_mode(
        self, message: str, session_id: str, start_time: float
    ) -> RAGResultDict:
        """
        Agent 모드 실행 (Agentic RAG)

        AgentOrchestrator를 사용하여 ReAct 패턴 기반 에이전트 루프를 실행합니다.
        기존 7단계 파이프라인 대신 LLM이 도구를 선택하고 실행하는 방식입니다.

        Args:
            message: 사용자 쿼리
            session_id: 세션 ID
            start_time: 파이프라인 시작 시간

        Returns:
            RAGResultDict: Agent 모드 응답 (metadata.mode="agent" 포함)

        Raises:
            GenerationError: Agent 실행 중 오류 발생 시
        """
        # 세션 컨텍스트 조회
        session_context = ""
        if self.session_module:
            try:
                context_string = await self.session_module.get_context_string(session_id)
                if context_string:
                    session_context = context_string
                    logger.debug(
                        "세션 컨텍스트 로드 성공",
                        extra={"context_length": len(context_string)}
                    )
            except Exception as e:
                logger.warning(
                    "세션 컨텍스트 조회 실패",
                    extra={"error": str(e)},
                    exc_info=True
                )

        try:
            # AgentOrchestrator 실행
            with bind_request_cost_ledger() as request_ledger:
                agent_result = await self.agent_orchestrator.run(
                    query=message,
                    session_context=session_context,
                )

            # Agent 결과를 RAGResultDict 형식으로 변환
            processing_time = time.time() - start_time

            # Source 객체 변환 (Agent sources는 dict 형태일 수 있음)
            formatted_sources = []
            for idx, source in enumerate(agent_result.sources or []):
                if isinstance(source, dict):
                    formatted_sources.append(
                        self.Source(
                            id=idx,
                            document=source.get("source", source.get("title", f"Source {idx + 1}")),
                            page=source.get("page"),
                            chunk=source.get("chunk"),
                            relevance=source.get("relevance", source.get("score", 0.0)),
                            content_preview=source.get(
                                "content_preview", source.get("content", "")[:200]
                            ),
                            source_type="agent",
                        )
                    )
                else:
                    # 이미 Source 객체인 경우 그대로 사용
                    formatted_sources.append(source)

            result: RAGResultDict = cast(
                RAGResultDict,
                {
                    "answer": agent_result.answer,
                    "sources": formatted_sources,
                    "tokens_used": request_ledger.total_tokens,
                    "topic": self.extract_topic_func(message),
                    "processing_time": processing_time,
                    "search_results": len(agent_result.sources or []),
                    "ranked_results": len(agent_result.sources or []),
                    "model_info": {
                        "provider": "agent",
                        "model": "agent_orchestrator",
                        "model_used": "agent_orchestrator",
                    },
                    "metadata": {
                        "mode": "agent",
                        "steps_taken": agent_result.steps_taken,
                        "tools_used": agent_result.tools_used,
                        "total_time": agent_result.total_time,
                        "success": agent_result.success,
                    },
                },
            )

            logger.info(
                "Agent 모드 완료",
                extra={
                    "steps_taken": agent_result.steps_taken,
                    "processing_time": processing_time,
                    "tools_count": len(agent_result.tools_used)
                }
            )

            return result

        except Exception as e:
            logger.error(
                "Agent 모드 실행 실패",
                extra={"error": str(e)},
                exc_info=True
            )
            raise GenerationError(
                ErrorCode.GENERATION_REQUEST_FAILED,
                session_id=session_id,
                error=str(e),
            ) from e


    @staticmethod
    def _conversation_pairs_from_history(
        chat_history: dict[str, Any], max_exchanges: int = 5
    ) -> list[dict[str, str]]:
        """채팅 히스토리(messages)에서 user/assistant 교환 쌍을 추출한다(GAP B).

        Args:
            chat_history: get_chat_history 반환 형태({"messages": [...]})
            max_exchanges: 최근 교환 최대 수

        Returns:
            [{"user": ..., "assistant": ...}, ...] (최근 max_exchanges개)
        """
        messages = chat_history.get("messages", []) if isinstance(chat_history, dict) else []
        conversations: list[dict[str, str]] = []
        i = 0
        while i < len(messages) - 1:
            cur = messages[i]
            nxt = messages[i + 1]
            if (
                isinstance(cur, dict)
                and isinstance(nxt, dict)
                and cur.get("type") == "user"
                and nxt.get("type") == "assistant"
            ):
                conversations.append(
                    {"user": cur.get("content", ""), "assistant": nxt.get("content", "")}
                )
                i += 2
            else:
                i += 1
        return conversations[-max_exchanges:] if conversations else []

