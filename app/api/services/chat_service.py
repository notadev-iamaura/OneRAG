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

import time
import uuid
from collections.abc import AsyncGenerator
from datetime import datetime
from typing import Any

from ...lib.cost_tracker import CostTracker
from ...lib.errors import ErrorCode, SessionError
from ...lib.logger import get_logger
from ...lib.metrics import PerformanceMetrics
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
        )

        logger.info("ChatService 초기화 완료 (RAGPipeline + Self-RAG + SQL Search 포함)")

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
            logger.error(f"Session handling error - missing key: {e}", exc_info=True)
            raise SessionError(
                message="세션 모듈이 초기화되지 않았습니다. 서버 관리자에게 문의하세요.",
                error_code=ErrorCode.SESSION_MODULE_NOT_AVAILABLE,
                context={"missing_key": str(e)},
                original_error=e,
            ) from e
        except Exception as e:
            # 예상치 못한 세션 처리 에러
            logger.error(f"Session handling error: {e}", exc_info=True)
            raise SessionError(
                message="세션 처리 중 오류가 발생했습니다.",
                error_code=ErrorCode.SESSION_CREATE_FAILED,
                context={"session_id": session_id, "context": context},
                original_error=e,
            ) from e

    def extract_topic(self, message: str) -> str:
        """
        토픽 추출 (간단한 키워드 기반)

        기존 코드: chat.py의 extract_topic() 함수 (L301-329)
        """
        # 안전한 메시지 처리
        if isinstance(message, list):
            message = " ".join(str(item) for item in message)
        elif not isinstance(message, str):
            message = str(message)

        if not message:
            return "general"

        keywords = {
            "search": ["검색", "찾기", "찾아", "검색해"],
            "document": ["문서", "파일", "자료", "데이터"],
            "help": ["도움", "도와", "설명", "알려"],
            "technical": ["기술", "개발", "코드", "프로그래밍"],
            "general": ["일반", "기본", "소개", "개요"],
        }

        try:
            lower_message = message.lower()

            for topic, words in keywords.items():
                if any(word in lower_message for word in words):
                    return topic

            return "general"
        except Exception:
            return "general"

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

            # 4. 리랭킹 (비스트리밍)
            reranked_documents = search_results  # 기본값: 원본 검색 결과
            reranking_applied = False

            if search_results:
                reranking_config = self.config.get("reranking", {})
                retrieval_config = self.config.get("retrieval", {})
                reranking_enabled = reranking_config.get("enabled", False) or retrieval_config.get(
                    "enable_reranking", False
                )

                if reranking_enabled:
                    retrieval_module = self.modules.get("retrieval")
                    if retrieval_module and hasattr(retrieval_module, "rerank"):
                        try:
                            rerank_top_n = options.get("top_n", reranking_config.get("top_n", 8))
                            reranked_documents = await retrieval_module.rerank(
                                query=message,
                                results=search_results,
                                top_n=rerank_top_n,
                            )

                            # min_score 필터링
                            min_score = reranking_config.get("min_score", 0.05)
                            if min_score > 0:
                                reranked_documents = [
                                    doc
                                    for doc in reranked_documents
                                    if (hasattr(doc, "score") and doc.score >= min_score)
                                    or (hasattr(doc, "metadata") and doc.metadata.get("score", 0) >= min_score)
                                ]

                            reranking_applied = True
                            logger.debug(
                                f"스트리밍: 리랭킹 완료 - {len(reranked_documents)}개 문서"
                            )
                        except Exception as e:
                            logger.warning(f"스트리밍: 리랭킹 실패, 원본 사용 - {e}")
                            reranked_documents = search_results
                    else:
                        logger.debug("스트리밍: 리랭킹 모듈 없음, 원본 사용")
                else:
                    logger.debug("스트리밍: 리랭킹 비활성화, 원본 사용")

            # 5. 메타데이터 이벤트 전송
            metadata_event = {
                "event": "metadata",
                "data": {
                    "session_id": final_session_id,
                    "search_results": len(search_results),
                    "ranked_results": len(reranked_documents),
                    "reranking_applied": reranking_applied,
                    "message_id": str(uuid.uuid4()),
                    "timestamp": datetime.now().isoformat(),
                },
            }
            yield metadata_event

            # 6. 스트리밍 답변 생성
            generation_module = self.modules.get("generation")

            if generation_module and hasattr(generation_module, "stream_answer"):
                # 컨텍스트 문서 준비 (리랭킹된 문서 사용)
                context_documents = reranked_documents if reranked_documents else []

                # 생성 옵션 구성
                generation_options = {
                    **options,
                    "session_context": session_context,
                }

                # 스트리밍 호출
                try:
                    async for text_chunk in generation_module.stream_answer(
                        query=message,
                        context_documents=context_documents,
                        options=generation_options,
                    ):
                        chunk_event = {
                            "event": "chunk",
                            "data": text_chunk,
                            "chunk_index": chunk_index,
                        }
                        yield chunk_event
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
                # 생성 모듈이 없거나 스트리밍을 지원하지 않는 경우
                logger.warning("스트리밍: 생성 모듈 없음 또는 스트리밍 미지원")
                yield {
                    "event": "chunk",
                    "data": "답변을 생성할 수 없습니다.",
                    "chunk_index": 0,
                }
                chunk_index = 1

            # 7. 완료 이벤트 전송
            processing_time = time.time() - start_time
            done_event = {
                "event": "done",
                "data": {
                    "session_id": final_session_id,
                    "total_chunks": chunk_index,
                    "processing_time": processing_time,
                    "tokens_used": 0,  # 스트리밍에서는 정확한 토큰 계산 어려움
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
