"""
Chat Service - 비즈니스 로직 레이어

Phase 3.2: chat.py에서 추출한 검증된 비즈니스 로직
기존 코드 기반: app/api/chat.py의 핵심 함수들

⚠️ 주의: 이 코드는 기존 검증된 로직을 재사용합니다.

## Service Layer의 역할
- 비즈니스 로직만 담당 (HTTP 요청/응답과 분리)
- 모듈 의존성 주입을 통한 테스트 가능성 확보
- RAG 파이프라인, 세션 처리, 통계 관리 등 핵심 기능 제공
"""

import asyncio
import time
import uuid
from collections.abc import AsyncGenerator
from datetime import datetime
from typing import Any

from ...lib.errors import ErrorCode, SessionError
from ...lib.logger import get_logger
from ...lib.metrics import CostTracker, PerformanceMetrics
from ...lib.topic_extractor import extract_topic
from ...lib.types import RAGResultDict, SessionInfoDict, SessionResult, StatsDict
from .rag_pipeline import RAGPipeline

# LangSmith 트레이싱 import
try:
    from langsmith import traceable

    LANGSMITH_AVAILABLE = True
except ImportError:
    LANGSMITH_AVAILABLE = False

    def traceable(*args, **kwargs):  # type: ignore[no-redef]
        def decorator(func):
            return func

        return decorator


logger = get_logger(__name__)


class ChatService:
    """
    채팅 비즈니스 로직 서비스

    역할:
    - RAG 파이프라인 실행
    - 세션 관리
    - 통계 수집
    - 컨텍스트 처리

    기존 코드 기반: app/api/chat.py의 함수들을 클래스로 재구성
    """

    def __init__(self, modules: dict[str, Any], config: dict[str, Any]):
        """
        Args:
            modules: 애플리케이션 모듈 딕셔너리 (DI)
            config: 설정 딕셔너리
        """
        self.modules = modules
        self.config = config

        # 통계 정보
        self.stats = {
            "total_chats": 0,
            "total_tokens": 0,
            "average_latency": 0.0,
            "error_rate": 0.0,
            "errors": 0,
        }

        # RAGPipeline 인스턴스 생성 (의존성 주입)
        self.rag_pipeline = RAGPipeline(
            config=config,
            query_router=modules.get("query_router"),
            query_expansion=modules.get("query_expansion"),
            retrieval_module=modules.get("retrieval"),
            generation_module=modules.get("generation"),
            session_module=modules.get("session"),
            self_rag_module=modules.get("self_rag"),  # ✅ Self-RAG 모듈 주입
            extract_topic_func=self.extract_topic,
            circuit_breaker_factory=modules.get(
                "circuit_breaker_factory"
            ),  # ✅ Circuit Breaker Factory 주입
            cost_tracker=modules.get("cost_tracker") or CostTracker(),  # ✅ 비용 추적기 주입
            performance_metrics=modules.get("performance_metrics")
            or PerformanceMetrics(),  # ✅ 성능 메트릭 주입
            sql_search_service=modules.get(
                "sql_search_service"
            ),  # ✅ SQL Search Service 주입 (Phase 3)
            llm_factory=modules.get("llm_factory"),  # ✅ standalone rewrite용 LLM Factory
            # Phase 2.6: Grok answer 모드 / Agentic RAG 의존성 전달
            # (미전달 시 grok answer는 GROK_003 에러, use_agent는 일반 RAG로 강등)
            grok_answer_provider=modules.get("grok_answer_provider"),
            agent_orchestrator=modules.get("agent_orchestrator"),
        )

        # GAP #5: 서버사이드 SSE 청크 페이싱 설정.
        # 연속 LLM chunk burst가 SSE에 한꺼번에 flush되면 프론트 타이프라이터
        # 애니메이션의 평활도가 깨진다. 최소 간격(초)을 두어 소스 레벨에서 토큰
        # 방출을 평탄화한다. 기본 0.0=무동작(opt-in, 회귀 0).
        streaming_config = config.get("rag", {}).get("streaming", {})
        self.stream_chunk_min_interval_seconds = self._coerce_non_negative_float(
            streaming_config.get("chunk_min_interval_seconds"),
            default=0.0,
        )

        logger.info("ChatService 초기화 완료 (RAGPipeline + Self-RAG + SQL Search 포함)")

    @staticmethod
    def _coerce_non_negative_float(value: Any, *, default: float) -> float:
        """설정값을 0 이상 float로 정규화한다(음수/비정상 값은 default).

        Args:
            value: YAML에서 읽은 원본 설정값(숫자/문자열/None 가능)
            default: 변환 실패 또는 None일 때 사용할 기본값

        Returns:
            0.0 이상으로 보정된 float
        """
        try:
            if value is None:
                return default
            coerced = float(value)
        except (TypeError, ValueError):
            return default
        return max(0.0, coerced)

    async def _sleep_for_stream_pacing(self, delay_seconds: float) -> None:
        """스트리밍 청크 페이싱 전용 sleep 훅(테스트에서 교체 가능).

        Args:
            delay_seconds: 대기할 시간(초)
        """
        await asyncio.sleep(delay_seconds)

    async def _pace_stream_chunk(self, last_sent_at: float | None) -> float:
        """연속 chunk burst가 SSE에 한 번에 flush되지 않도록 최소 간격을 둔다(GAP #5).

        간격(chunk_min_interval_seconds)이 0 이하이거나 첫 청크(last_sent_at=None)면
        sleep 없이 현재 시각만 반환한다(무동작). 그 외에는 직전 전송 이후 경과
        시간을 빼고 남은 만큼만 sleep 해, 이미 느린 청크는 추가 지연 없이 통과시킨다.

        Args:
            last_sent_at: 직전 청크 전송 시각(time.monotonic 기준, 첫 청크는 None)

        Returns:
            이번 청크 전송 직후의 time.monotonic 값(다음 호출의 기준점)
        """
        interval = self.stream_chunk_min_interval_seconds
        if interval <= 0 or last_sent_at is None:
            return time.monotonic()

        elapsed = time.monotonic() - last_sent_at
        delay = interval - elapsed
        if delay > 0:
            await self._sleep_for_stream_pacing(delay)
        return time.monotonic()

    async def handle_session(
        self, session_id: str | None, context: dict[str, Any]
    ) -> SessionResult:
        """
        세션 처리 - 기존 세션 검증 또는 새 세션 생성

        기존 코드: chat.py의 handle_session() 함수 (L235-298)

        Args:
            session_id: 요청된 세션 ID (None이면 새로 생성)
            context: 요청 컨텍스트 (IP, User-Agent 등)

        Returns:
            세션 처리 결과 딕셔너리
        """
        try:
            session_module = self.modules.get("session")
            if not session_module:
                return {"success": False, "message": "Session module not available"}

            logger.debug(f"🔍 세션 요청 - 요청받은 session_id: {session_id}")

            if session_id:
                # 기존 세션 조회
                logger.debug(f"기존 세션 조회 시도: {session_id}")
                session_result = await session_module.get_session(session_id, context)

                if session_result.get("is_valid"):
                    logger.debug(f"✅ 세션 유효함 - session_id: {session_id}")
                    return {
                        "success": True,
                        "session_id": session_id,
                        "is_new": False,
                        "validation_result": session_result,
                    }
                else:
                    logger.warning(
                        f"세션 만료/없음: {session_id}, "
                        f"이유: {session_result.get('reason', 'unknown')}"
                    )

            # 새 세션 생성
            logger.debug(f"새 세션 생성 중... (기존 세션: {session_id})")
            new_session = await session_module.create_session(
                {"metadata": context}, session_id=session_id
            )
            new_session_id = new_session["session_id"]

            logger.debug(f"✅ 새 세션 생성 완료 - session_id: {new_session_id}")

            return {
                "success": True,
                "session_id": new_session_id,
                "is_new": True,
                "message": "새 대화 세션이 시작되었습니다.",
            }

        except KeyError as e:
            # 세션 모듈 초기화 안 됨 또는 필수 키 누락
            # RAGException 시그니처는 (error_code, **context)이므로 message=/
            # original_error= 키워드는 데드 인자(context dict에 흡수, 렌더 안 됨)였다.
            # 사용자 노출 메시지는 양언어 카탈로그(SESSION-002)가 렌더하고,
            # 디버깅 정보는 context로 전달한다(데드 한국어 문자열 제거).
            logger.error(f"Session handling error - missing key: {e}", exc_info=True)
            raise SessionError(
                ErrorCode.SESSION_MODULE_NOT_AVAILABLE,
                missing_key=str(e),
            ) from e
        except Exception as e:
            # 예상치 못한 세션 처리 에러
            # 위와 동일: 데드 message=/original_error= 제거, context는 키워드로 전달.
            logger.error(f"Session handling error: {e}", exc_info=True)
            raise SessionError(
                ErrorCode.SESSION_CREATE_FAILED,
                session_id=session_id,
                context=context,
            ) from e

    def extract_topic(self, message: str) -> str:
        """토픽 추출 (키워드 기반).

        lib의 단일 소스 함수(topic_extractor.extract_topic)에 위임한다(DRY).
        토픽 키워드는 config(routing.topic_keywords)로 외부화되며, 미설정 시
        코드 내장 한국어 기본 맵을 사용한다(회귀 0). 토픽은 세션 메타(cosmetic)
        라벨이라 검색/라우팅 동작에는 영향을 주지 않는다.
        """
        topic_keywords = self.config.get("routing", {}).get("topic_keywords")
        return extract_topic(message, topic_keywords)

    @traceable(
        name="RAGPipeline",
        tags=["chat", "rag", "pipeline"],
        metadata={"module": "chat_service", "version": "3.0.0"},
    )
    async def execute_rag_pipeline(
        self, message: str, session_id: str, options: dict[str, Any] | None = None
    ) -> RAGResultDict:
        """
        RAG 파이프라인 실행

        Phase 2 개선: 150줄 블랙박스 → RAGPipeline.execute() 단일 호출
        - 8개 독립 단계로 분해된 파이프라인 사용
        - 단계별 성능 추적 (PipelineTracker)
        - Circuit Breaker, Graceful Degradation 패턴 적용

        Args:
            message: 사용자 메시지
            session_id: 세션 ID
            options: 추가 옵션 (limit, min_score, top_n 등)

        Returns:
            RAG 파이프라인 실행 결과:
            {
                "answer": str,
                "sources": List[Source],
                "tokens_used": int,
                "topic": str,
                "processing_time": float,
                "search_results": int,
                "ranked_results": int,
                "model_info": Dict[str, Any],
                "routing_metadata": Optional[Dict[str, Any]],
                "performance_metrics": Dict[str, Any]  # NEW: PipelineTracker 메트릭
            }
        """
        logger.debug(
            "RAG Pipeline Starting (Phase 2 Refactored)",
            message_preview=message[:50],
            session_id=session_id,
        )

        # RAGPipeline.execute() 단일 호출 (8단계 오케스트레이션)
        return await self.rag_pipeline.execute(
            message=message, session_id=session_id, options=options
        )

    async def add_conversation_to_session(
        self, session_id: str, user_message: str, assistant_answer: str, metadata: dict[str, Any]
    ) -> None:
        """
        세션에 대화 기록 추가

        Args:
            session_id: 세션 ID
            user_message: 사용자 메시지
            assistant_answer: 어시스턴트 응답
            metadata: 추가 메타데이터
        """
        session_module = self.modules.get("session")
        if session_module:
            logger.debug(f"대화 추가: session_id={session_id}")
            await session_module.add_conversation(
                session_id, user_message, assistant_answer, metadata
            )

    def update_stats(self, data: dict[str, Any]) -> None:
        """
        통계 업데이트

        기존 코드: chat.py의 update_stats() 함수 (L161-179)
        """
        self.stats["total_chats"] += 1

        if data.get("success"):
            if data.get("tokens_used"):
                self.stats["total_tokens"] += data["tokens_used"]

            if data.get("latency"):
                current_avg = self.stats["average_latency"]
                chat_count = self.stats["total_chats"]
                self.stats["average_latency"] = (
                    current_avg * (chat_count - 1) + data["latency"]
                ) / chat_count
        else:
            self.stats["errors"] += 1
            self.stats["error_rate"] = (self.stats["errors"] / self.stats["total_chats"]) * 100

    def get_stats(self) -> StatsDict:
        """현재 통계 반환"""
        return self.stats.copy()  # type: ignore[return-value]

    async def get_session_info(self, session_id: str) -> SessionInfoDict:
        """
        세션 상세 정보 조회

        Returns:
            세션 정보 딕셔너리 (message_count, tokens_used, processing_time 등)
        """
        session_module = self.modules.get("session")
        if not session_module:
            raise Exception("Session module not available")

        # 세션 존재 확인
        session_result = await session_module.get_session(session_id, {})
        if not session_result.get("is_valid"):
            raise Exception("Session not found")

        # 채팅 히스토리에서 통계 추출
        history = await session_module.get_chat_history(session_id)
        messages = history.get("messages", [])

        # 통계 계산
        message_count = len(messages)
        total_tokens = 0
        total_processing_time = 0
        latest_model_info = None

        for message in messages:
            if message.get("type") == "assistant":
                if "tokens_used" in message:
                    total_tokens += message["tokens_used"]
                if "processing_time" in message:
                    total_processing_time += message["processing_time"]
                if "model_info" in message:
                    latest_model_info = message["model_info"]

        return {
            "session_id": session_id,
            "message_count": message_count,
            "tokens_used": total_tokens,
            "processing_time": total_processing_time,
            "model_info": latest_model_info,
            "timestamp": datetime.now().isoformat(),
        }

    def _format_stream_sources(self, documents: list[Any]) -> list[dict[str, Any]]:
        """Normalize retrieved documents for stream metadata and done events."""
        sources: list[dict[str, Any]] = []
        for index, document in enumerate(documents):
            metadata = getattr(document, "metadata", None)
            if not isinstance(metadata, dict) and isinstance(document, dict):
                metadata = document.get("metadata", {})
            if not isinstance(metadata, dict):
                metadata = {}

            # 인접 청크 확장으로 추가된 이웃 청크는 실제 검색 히트가 아니므로
            # 사용자 인용 소스에서 제외한다(비스트리밍 format_sources와 정합)(#4).
            if metadata.get("context_expanded"):
                continue

            content = (
                getattr(document, "page_content", None)
                or getattr(document, "content", None)
                or (document.get("content") if isinstance(document, dict) else "")
                or ""
            )
            # 점수 추출: 0.0도 유효한 값이므로 `or` 대신 명시적 None 검사를 사용한다(#14).
            score_candidates = (
                getattr(document, "score", None),
                metadata.get("score"),
                metadata.get("relevance"),
            )
            score = next(
                (candidate for candidate in score_candidates if candidate is not None),
                0.0,
            )
            source_name = (
                metadata.get("source")
                or metadata.get("source_file")
                or metadata.get("file_name")
                or metadata.get("filename")
                or f"document-{index + 1}"
            )

            sources.append(
                {
                    "id": index,
                    "document": str(source_name),
                    "content_preview": str(content)[:200],
                    "relevance": float(score) if isinstance(score, (int, float)) else 0.0,
                }
            )
        return sources

    def _get_stream_model_info(self, generation_module: Any | None) -> dict[str, Any]:
        """Return best-effort model metadata for streaming completion events."""
        if generation_module is None:
            return {"provider": "none", "model": "none", "streaming": True}
        return {
            "provider": getattr(generation_module, "provider", "unknown"),
            "model": getattr(generation_module, "default_model", "unknown"),
            "streaming": True,
        }

    def _get_first_token_timeout(self, options: dict[str, Any]) -> float:
        """Resolve the first-token watchdog timeout in seconds."""
        timeout = options.get("first_token_timeout", options.get("stream_first_token_timeout"))
        if timeout is None:
            timeout = self.config.get("streaming", {}).get("first_token_timeout", 25.0)
        try:
            return max(float(timeout), 0.0)
        except (TypeError, ValueError):
            return 25.0

    @staticmethod
    def _estimate_stream_tokens(answer: str, chunk_count: int) -> int:
        """Estimate token usage when providers do not expose streaming usage."""
        if not answer:
            return 0
        return max(chunk_count * 5, len(answer) // 4)

    @staticmethod
    def _split_fallback_answer_into_chunks(text: str, target: int = 60) -> list[str]:
        """Split a non-streaming fallback answer into SSE-sized chunks."""
        if not text:
            return []

        sentence_boundaries = "。．.!?！？"
        chunks: list[str] = []
        current: list[str] = []
        current_len = 0
        for char in text:
            current.append(char)
            current_len += 1
            is_boundary = char in sentence_boundaries or char == "\n"
            if (current_len >= target and is_boundary) or current_len >= target * 2:
                chunks.append("".join(current))
                current = []
                current_len = 0

        if current:
            chunks.append("".join(current))
        return chunks

    async def stream_rag_pipeline(
        self, message: str, session_id: str | None, options: dict[str, Any] | None = None
    ) -> AsyncGenerator[dict[str, Any], None]:
        """
        스트리밍 RAG 파이프라인 실행

        세션 처리, 컨텍스트 준비, 문서 검색, 리랭킹은 비스트리밍으로 처리하고,
        답변 생성 단계에서만 스트리밍으로 청크를 yield합니다.

        이벤트 타입:
        - metadata: 검색 결과 메타데이터 (세션 ID, 문서 수, 소스 등)
        - chunk: LLM 응답 텍스트 청크 (data, chunk_index)
        - done: 스트리밍 완료 이벤트 (session_id, total_chunks)
        - error: 에러 이벤트 (error_code, message)

        Args:
            message: 사용자 메시지
            session_id: 세션 ID (None이면 새로 생성)
            options: 추가 옵션 (temperature, max_tokens, model 등)

        Yields:
            dict: 스트리밍 이벤트 딕셔너리

        Example:
            async for event in chat_service.stream_rag_pipeline(message, session_id):
                if event["event"] == "chunk":
                    print(event["data"], end="", flush=True)
        """
        options = options or {}
        start_time = time.time()
        chunk_index = 0
        final_session_id = session_id
        message_id = str(uuid.uuid4())
        answer_chunks: list[str] = []
        # GAP #5: 직전 청크 전송 시각(time.monotonic). 첫 청크는 None이라 페이싱
        # 무동작이며, chunk_min_interval_seconds=0이면 전체 구간에서 무동작이다.
        last_chunk_sent_at: float | None = None

        try:
            # 1. 세션 처리 (비스트리밍)
            session_module = self.modules.get("session")

            if session_module:
                if session_id:
                    # 기존 세션 검증
                    session_result = await session_module.get_session(session_id, {})
                    if not session_result.get("is_valid"):
                        # 세션이 유효하지 않으면 새로 생성
                        new_session = await session_module.create_session(
                            {"metadata": {}}, session_id=session_id
                        )
                        final_session_id = new_session["session_id"]
                        logger.debug(f"스트리밍: 새 세션 생성 - {final_session_id}")
                else:
                    # 세션 ID 없으면 새로 생성
                    new_session = await session_module.create_session({"metadata": {}})
                    final_session_id = new_session["session_id"]
                    logger.debug(f"스트리밍: 새 세션 생성 - {final_session_id}")

                # 2. 세션 컨텍스트 조회 (비스트리밍)
                session_context = await session_module.get_context_string(final_session_id)
            else:
                session_context = ""
                if not final_session_id:
                    final_session_id = str(uuid.uuid4())

            # 3. 문서 검색 (비스트리밍)
            retrieval_module = self.modules.get("retrieval")
            # 일부 DI 구성에서 retrieval 모듈이 코루틴/Future로 지연 제공되므로 해소한다
            # ('_asyncio.Future' object has no attribute 'search' 방지).
            if asyncio.iscoroutine(retrieval_module) or isinstance(
                retrieval_module, asyncio.Future
            ):
                retrieval_module = await retrieval_module
            search_results = []

            if retrieval_module:
                try:
                    search_results = await retrieval_module.search(message, {
                        "limit": options.get("limit", 8),
                        "min_score": options.get("min_score", 0.05),
                    })
                    logger.debug(f"스트리밍: 검색 완료 - {len(search_results)}개 문서")
                except Exception as e:
                    logger.warning(f"스트리밍: 검색 실패 - {e}")

            # 4. 리랭킹 (비스트리밍) — 통짜 rerank_documents 재사용.
            #    no-op 리랭커 감지(_is_noop_rerank), min_score 필터, 점수 주석은
            #    모두 RAGPipeline.rerank_documents 내부에서 통짜(execute)와 동일하게
            #    처리된다. 스트리밍이 인라인으로 중복 구현하면 no-op 폴백 리랭커가
            #    전체 문서를 잘못 필터링해 검색 0건처럼 보이는 회귀가 발생한다(#2).
            reranked_documents = search_results  # 기본값: 원본 검색 결과
            reranking_applied = False

            if search_results:
                try:
                    rerank_results = await self.rag_pipeline.rerank_documents(
                        message,
                        search_results,
                        options,
                    )
                    reranked_documents = rerank_results.documents
                    reranking_applied = rerank_results.reranked
                    logger.debug(
                        f"스트리밍: 리랭킹 단계 완료 - {len(reranked_documents)}개 문서 "
                        f"(reranked={reranking_applied})"
                    )
                except Exception as e:
                    # rerank_documents는 내부에서 대부분의 실패를 흡수하지만,
                    # 방어적으로 원본 검색 결과로 graceful 진행한다.
                    logger.warning(f"스트리밍: 리랭킹 실패, 원본 사용 - {e}")
                    reranked_documents = search_results
                    reranking_applied = False

            # 4-1. 인접 청크 컨텍스트 확장 (opt-in) — 통짜(execute)와 동일하게
            #     expand_context_documents를 호출해 SSE에서도 동일하게 동작시킨다.
            #     기본값 off: config(rag.context_expansion.enabled) 또는 옵션
            #     (expand_adjacent_chunks/context_expansion_enabled)이 켜졌을 때만
            #     인접 청크를 추가한다. 미지원/메타데이터 부재 시 원본을 반환한다(#9).
            context_expanded_grew = False
            if reranked_documents:
                pre_expand_count = len(reranked_documents)
                try:
                    reranked_documents = await self.rag_pipeline.expand_context_documents(
                        reranked_documents, options
                    )
                    context_expanded_grew = len(reranked_documents) > pre_expand_count
                except Exception as e:
                    # 확장 실패는 비치명적 — 리랭킹 결과 그대로 진행.
                    logger.warning(f"스트리밍: 컨텍스트 확장 실패, 원본 사용 - {e}")

            # 5. 메타데이터 이벤트 전송
            stream_sources = self._format_stream_sources(reranked_documents)
            metadata_event = {
                "event": "metadata",
                "data": {
                    "session_id": final_session_id,
                    "search_results": len(search_results),
                    "ranked_results": len(reranked_documents),
                    "reranking_applied": reranking_applied,
                    "message_id": message_id,
                    "sources": stream_sources,
                    "timestamp": datetime.now().isoformat(),
                },
            }
            yield metadata_event

            # 6. 스트리밍 답변 생성
            generation_module = self.modules.get("generation")
            model_info = self._get_stream_model_info(generation_module)
            stream_tokens_used = 0
            # 안내성(문서 없음) 응답은 실제 답변이 아니므로 저장/성공 집계에서 제외한다(#7/[28]).
            canned_no_answer = False

            if not reranked_documents:
                canned_no_answer = True
                no_context_answer = (
                    "관련 문서를 찾을 수 없습니다. 문서를 업로드했는지 확인하거나 "
                    "질문을 바꿔 다시 시도해주세요."
                )
                # answer_chunks에 추가하지 않아 answer_text를 비워둔다 → tokens_used=0,
                # 영속화/성공 집계 스킵(안내 UX는 chunk+done으로 유지).
                yield {
                    "event": "chunk",
                    "data": no_context_answer,
                    "chunk_index": chunk_index,
                }
                chunk_index += 1
            elif generation_module and hasattr(generation_module, "stream_answer"):
                # 컨텍스트 문서 준비 (리랭킹된 문서 사용)
                context_documents = reranked_documents

                # 생성 옵션 구성
                generation_options = {
                    **options,
                    "session_context": session_context,
                }
                # 인접 청크 확장으로 문서가 늘었을 때만 프롬프트 한도를 상향(20)해
                # 실제 히트가 이웃 청크에 밀려나지 않게 한다(비스트리밍 execute와 정합)(#3).
                if context_expanded_grew:
                    generation_options.setdefault("max_context_documents", 20)

                # 스트리밍 호출
                # 첫 청크(first-chunk) 타임아웃 + 청크 간(inter-chunk) 타임아웃.
                #  - 첫 토큰이 너무 늦으면 에러 대신 검증된 비스트리밍 답변으로
                #    폴백한다(답변 보장).
                #  - 이후 청크도 generate_answer stage 예산만큼만 대기해, 생성
                #    중간에 무한정 멈추는 상황을 막는다(pipeline_timeout opt-in).
                try:
                    first_chunk_timeout = self._get_first_token_timeout(options)
                    inter_chunk_timeout = (
                        self.rag_pipeline.pipeline_stage_budgets.get("generate_answer")
                        if getattr(self.rag_pipeline, "pipeline_timeout_enabled", False)
                        else None
                    )
                    stream_gen = generation_module.stream_answer(
                        query=message,
                        context_documents=context_documents,
                        options=generation_options,
                    )
                    stream_iter = stream_gen.__aiter__()
                    # 폴백 결정 상태:
                    #  - chunk_emitted: chunk 이벤트를 1개라도 yield했는지. True면
                    #    중복 답변 방지를 위해 폴백하지 않고 기존 에러 처리를 유지.
                    #  - fallback_reason: 첫 청크 단계에서 실패해 폴백할 사유.
                    #    None이면 폴백하지 않는다(정상 종료 또는 중간 실패).
                    chunk_emitted = False
                    fallback_reason: str | None = None
                    try:
                        is_first_chunk = True
                        while True:
                            chunk_timeout = (
                                first_chunk_timeout if is_first_chunk else inter_chunk_timeout
                            )
                            try:
                                if chunk_timeout is not None and chunk_timeout > 0:
                                    text_chunk = await asyncio.wait_for(
                                        anext(stream_iter), timeout=chunk_timeout
                                    )
                                else:
                                    text_chunk = await anext(stream_iter)
                            except StopAsyncIteration:
                                break
                            except TimeoutError:
                                # 무한 대기 대신 명확한 timeout. 정리는 아래 finally의
                                # aclose로 결정적으로 수행한다.
                                if not chunk_emitted:
                                    # 첫 청크가 끝내 오지 않은 경우: 검증된 비스트리밍
                                    # 답변으로 폴백한다. 실제 폴백 호출은 stream_gen
                                    # 정리(finally) 후 수행한다.
                                    logger.warning(
                                        "스트리밍 첫 청크 타임아웃, 비스트리밍 fallback 진입",
                                        extra={
                                            "timeout": first_chunk_timeout,
                                            "session_id": final_session_id,
                                        },
                                    )
                                    fallback_reason = (
                                        f"first_token_timeout:{first_chunk_timeout}"
                                    )
                                    break
                                # 이미 청크를 보낸 뒤 중간 timeout: 폴백 시 중복 답변이
                                # 되므로 stage timeout 에러로 종료한다.
                                logger.warning(
                                    "스트리밍 청크 간 타임아웃",
                                    extra={"timeout_seconds": inter_chunk_timeout},
                                )
                                yield {
                                    "event": "error",
                                    "error_code": ErrorCode.PIPELINE_STAGE_TIMEOUT.value,
                                    "message": "답변 생성이 지연되어 중단되었습니다. 잠시 후 다시 시도해주세요.",
                                }
                                return

                            answer_chunks.append(str(text_chunk))
                            # GAP #5: burst flush 방지를 위한 서버사이드 페이싱.
                            last_chunk_sent_at = await self._pace_stream_chunk(
                                last_chunk_sent_at
                            )
                            yield {
                                "event": "chunk",
                                "data": text_chunk,
                                "chunk_index": chunk_index,
                            }
                            chunk_index += 1
                            chunk_emitted = True
                            is_first_chunk = False
                    except Exception as stream_error:
                        # 첫 청크 전(아직 chunk 미전송) 예외는 폴백 대상.
                        # 이미 청크를 보낸 뒤라면 중복 답변 방지를 위해 기존 에러 처리.
                        if not chunk_emitted:
                            logger.warning(
                                "스트리밍 첫 청크 전 예외, 비스트리밍 fallback 진입: %s",
                                stream_error,
                            )
                            fallback_reason = f"stream_error:{stream_error}"
                        else:
                            raise
                    finally:
                        # 생성 제너레이터를 닫아 하위 브리지(_async_bridge) 정리를
                        # 즉시 트리거한다. 정상 소진 시에는 이미 닫혀 no-op이다.
                        # aclose 실패는 정리 단계이므로 치명적이지 않다(로깅 후 흡수).
                        aclose = getattr(stream_gen, "aclose", None)
                        if callable(aclose):
                            try:
                                await aclose()
                            except Exception as close_exc:  # noqa: BLE001 - 정리 단계
                                logger.debug(
                                    "스트리밍 생성 제너레이터 aclose 실패(무시)",
                                    extra={"error": str(close_exc)},
                                )

                    if fallback_reason is not None:
                        try:
                            fallback_result = await generation_module.generate_answer(
                                query=message,
                                context_documents=context_documents,
                                options=generation_options,
                            )
                        except Exception as fallback_error:
                            logger.error(
                                f"스트리밍 비스트리밍 fallback 실패: {fallback_error}",
                                exc_info=True,
                            )
                            yield {
                                "event": "error",
                                "error_code": ErrorCode.GENERATION_REQUEST_FAILED.value,
                                "message": "답변 생성 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요.",
                            }
                            return

                        fallback_answer = str(getattr(fallback_result, "answer", "") or "")
                        stream_tokens_used = int(getattr(fallback_result, "tokens_used", 0) or 0)
                        fallback_model_info = getattr(fallback_result, "model_info", None)
                        if isinstance(fallback_model_info, dict):
                            model_info = fallback_model_info

                        for piece in self._split_fallback_answer_into_chunks(fallback_answer):
                            answer_chunks.append(piece)
                            # GAP #5: 폴백 분할 청크도 동일하게 페이싱한다.
                            last_chunk_sent_at = await self._pace_stream_chunk(
                                last_chunk_sent_at
                            )
                            yield {
                                "event": "chunk",
                                "data": piece,
                                "chunk_index": chunk_index,
                            }
                            chunk_index += 1

                except Exception as e:
                    logger.error(f"스트리밍 답변 생성 실패: {e}", exc_info=True)
                    yield {
                        "event": "error",
                        "error_code": ErrorCode.GENERATION_REQUEST_FAILED.value,
                        "message": "답변 생성 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요.",
                    }
                    return
            else:
                # 생성 모듈이 없거나 스트리밍을 미지원하면 실제 실패이므로 안내 청크를
                # 답변으로 저장/성공 집계하지 않고 error 이벤트로 종료한다(#7).
                logger.warning("스트리밍: 생성 모듈 없음 또는 스트리밍 미지원")
                self.update_stats(
                    {
                        "tokens_used": 0,
                        "latency": time.time() - start_time,
                        "success": False,
                    }
                )
                yield {
                    "event": "error",
                    "error_code": ErrorCode.GENERATION_REQUEST_FAILED.value,
                    "message": "답변을 생성할 수 없습니다. 잠시 후 다시 시도해주세요.",
                }
                return

            # 7. 완료 이벤트 전송
            processing_time = time.time() - start_time
            answer_text = "".join(answer_chunks)
            # 생성기가 컨텍스트 부재 시 반환하는 안내문구도 실제 답변이 아니므로
            # 저장/성공 집계에서 제외한다(reranked_documents가 있으나 본문이 비는 경우).
            from app.modules.core.generation.generator import NO_DOCUMENTS_MESSAGE

            if answer_text.strip() == NO_DOCUMENTS_MESSAGE.strip():
                canned_no_answer = True
            # 안내성 응답(canned_no_answer)이거나 답변이 비면 토큰을 0으로 보고한다([28]).
            if canned_no_answer or not answer_text:
                tokens_used = 0
            else:
                tokens_used = stream_tokens_used or self._estimate_stream_tokens(
                    answer_text, chunk_index
                )

            # 실제 답변이 있을 때만 저장하고 성공으로 집계한다(#7).
            persisted_real_answer = bool(
                final_session_id and answer_text and not canned_no_answer
            )
            if persisted_real_answer:
                try:
                    await self.add_conversation_to_session(
                        final_session_id,
                        message,
                        answer_text,
                        {
                            "tokens_used": tokens_used,
                            "processing_time": processing_time,
                            "sources": stream_sources,
                            "topic": self.extract_topic(message),
                            "model_info": model_info,
                            "message_id": message_id,
                            "can_evaluate": True,
                        },
                    )
                except Exception as persist_error:
                    logger.warning(
                        "스트리밍 대화 저장 실패",
                        extra={
                            "session_id": final_session_id,
                            "error": str(persist_error),
                        },
                        exc_info=True,
                    )

            self.update_stats(
                {
                    "tokens_used": tokens_used,
                    "latency": processing_time,
                    "success": persisted_real_answer,
                }
            )

            done_event = {
                "event": "done",
                "data": {
                    "session_id": final_session_id,
                    "message_id": message_id,
                    "total_chunks": chunk_index,
                    "processing_time": processing_time,
                    "tokens_used": tokens_used,
                    "sources": stream_sources,
                    "model_info": model_info,
                    "token_estimation": "estimated_from_stream",
                },
            }
            yield done_event

            logger.info(
                f"스트리밍 완료: session_id={final_session_id}, "
                f"chunks={chunk_index}, time={processing_time:.2f}s"
            )

        except Exception as e:
            # 에러 이벤트 전송
            logger.error(f"스트리밍 파이프라인 에러: {e}", exc_info=True)
            yield {
                "event": "error",
                "error_code": ErrorCode.GENERAL_004.value,
                "message": "스트리밍 처리 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요.",
            }
