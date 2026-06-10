"""
Enhanced Session Module - 리팩토링된 Service-Based Architecture

Phase 4: 기존 734줄 God Object를 Service 기반 구조로 분리
- SessionService: CRUD + 통계 + DB 연동
- MemoryService: LangChain 메모리 관리
- AdminService: Admin API 로직
- CleanupService: 자동 정리 작업
- EnhancedSessionModule: Facade (기존 인터페이스 유지)

⚠️ 주의: 기존 검증된 코드를 재구성했습니다. 로직 변경 없음.

## 아키텍처 개선 효과
1. **테스트 가능성**: Service 레이어를 독립적으로 단위 테스트 가능
2. **재사용성**: 각 Service를 다른 모듈에서도 사용 가능
3. **유지보수성**: 관심사 분리로 코드 이해 및 수정 용이
4. **확장성**: 새로운 기능 추가 시 Service만 추가
"""

import asyncio
import time
from typing import Any

from app.lib.logger import get_logger

from .services.admin_service import AdminService
from .services.memory_service import MemoryService
from .services.session_service import SessionService

logger = get_logger(__name__)


class CleanupService:
    """자동 정리 작업 서비스"""

    def __init__(
        self, session_service: SessionService, memory_service: MemoryService, cleanup_interval: int
    ):
        self.session_service = session_service
        self.memory_service = memory_service
        self.cleanup_interval = cleanup_interval
        self.cleanup_task = None

    async def start(self):
        """정리 작업 시작"""
        self.cleanup_task = asyncio.create_task(self._cleanup_loop())
        logger.info(f"CleanupService 시작: interval={self.cleanup_interval}s")

    async def stop(self):
        """정리 작업 중지"""
        if self.cleanup_task:
            self.cleanup_task.cancel()
            try:
                await self.cleanup_task
            except asyncio.CancelledError:
                pass
            logger.info("CleanupService 중지")

    async def _cleanup_loop(self):
        """
        정리 작업 루프
        기존 코드: enhanced_session.py의 _cleanup_loop() (L385-409)
        """
        while True:
            try:
                await asyncio.sleep(self.cleanup_interval)

                from datetime import UTC, datetime

                current_time = datetime.now(UTC)
                expired_sessions = []

                for session_id, session in self.session_service.sessions.items():
                    last_accessed = session["last_accessed"]
                    # datetime 객체 간 차이를 초 단위로 변환
                    if isinstance(last_accessed, datetime):
                        time_diff = (current_time - last_accessed).total_seconds()
                    else:
                        # 하위 호환: float 타임스탬프 지원
                        time_diff = current_time.timestamp() - last_accessed

                    if time_diff > self.session_service.ttl:
                        expired_sessions.append(session_id)

                for session_id in expired_sessions:
                    await self.session_service.delete_session(session_id)
                    self.memory_service.delete_memory(session_id)

                if expired_sessions:
                    logger.debug(f"Cleaned up {len(expired_sessions)} expired sessions")

                self.session_service.increment_cleanup_count()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Session cleanup error: {e}")


class EnhancedSessionModule:
    """
    향상된 세션 관리 모듈 (Facade Pattern)

    역할:
    - SessionService, MemoryService, AdminService를 하나의 인터페이스로 통합
    - 기존 API 호환성 유지 (main.py 수정 불필요)
    - 자동 정리 작업 관리

    기존 코드 기반: enhanced_session.py의 EnhancedSessionModule 클래스
    """

    def __init__(self, config: dict[str, Any], memory_service: MemoryService):
        """
        Args:
            config: 설정 딕셔너리
            memory_service: MemoryService 인스턴스 (DI)
        """
        self.config = config
        session_config = config.get("session", {})

        # Service 인스턴스 생성/주입
        self.session_service = SessionService(config)
        self.memory_service = memory_service  # DI 주입
        self.admin_service = AdminService(
            ttl=session_config.get("ttl_seconds", session_config.get("ttl", 7200))
        )
        self.cleanup_service = CleanupService(
            session_service=self.session_service,
            memory_service=self.memory_service,
            cleanup_interval=session_config.get(
                "cleanup_interval_seconds", session_config.get("cleanup_interval", 600)
            ),
        )

        # 하위 호환성: 기존 코드에서 직접 접근하는 속성들
        self.ttl = self.session_service.ttl
        self.max_exchanges = self.memory_service.max_exchanges
        self.cleanup_interval = self.cleanup_service.cleanup_interval
        self.sessions = self.session_service.sessions
        self.memories = self.memory_service.memories
        self.stats = self.session_service.stats

        logger.info("EnhancedSessionModule 초기화 (Service-Based Architecture)")

    async def initialize(self):
        """
        모듈 초기화
        기존 코드: enhanced_session.py의 initialize() (L47-58)
        """
        try:
            logger.info("Initializing enhanced session module...")

            # 정리 작업 시작
            await self.cleanup_service.start()

            logger.info("Enhanced session module initialized successfully")

        except Exception as e:
            logger.error(f"Enhanced session module initialization failed: {e}")
            raise

    async def destroy(self):
        """
        모듈 정리
        기존 코드: enhanced_session.py의 destroy() (L61-75)
        """
        try:
            await self.cleanup_service.stop()

            self.session_service.sessions.clear()
            self.memory_service.memories.clear()
            logger.info("Enhanced session module destroyed")

        except Exception as e:
            logger.error(f"Enhanced session module destroy error: {e}")

    # ========================================
    # Public API - SessionService 위임
    # ========================================

    async def create_session(
        self, metadata: dict[str, Any] | None = None, session_id: str | None = None
    ) -> dict[str, str]:
        """세션 생성 (SessionService로 위임)"""
        result = await self.session_service.create_session(metadata, session_id)

        # 메모리도 함께 생성
        self.memory_service.create_memory(result["session_id"])

        return result

    async def get_session(
        self, session_id: str, context: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """세션 조회 (SessionService로 위임)"""
        return await self.session_service.get_session(session_id, context)

    async def delete_session(self, session_id: str):
        """세션 삭제 (SessionService + MemoryService)"""
        await self.session_service.delete_session(session_id)
        self.memory_service.delete_memory(session_id)

    async def get_stats(self) -> dict[str, Any]:
        """통계 반환 (SessionService로 위임)"""
        return await self.session_service.get_stats()

    async def clear_cache(self):
        """캐시 클리어 (SessionService + MemoryService)"""
        await self.session_service.clear_cache()

        # 메모리도 함께 제거
        expired_ids = [
            sid
            for sid in list(self.memory_service.memories.keys())
            if sid not in self.session_service.sessions
        ]
        for session_id in expired_ids:
            self.memory_service.delete_memory(session_id)

    # ========================================
    # Public API - MemoryService 위임
    # ========================================

    async def add_conversation(
        self,
        session_id: str,
        user_message: str,
        assistant_response: str,
        metadata: dict[str, Any] | None = None,
    ):
        """
        대화 추가
        기존 코드: enhanced_session.py의 add_conversation() (L184-242)
        """
        session_result = await self.session_service.get_session(session_id)
        if not session_result["is_valid"]:
            raise ValueError(f"Invalid session: {session_id}")

        session = session_result["session"]

        # 메시지 메타데이터 저장 (L217-228)
        # metadata가 없는 턴이라도 timestamp만 가진 최소 dict를 만들어 messages_metadata가
        # 교환과 항상 1:1로 유지되도록 한다(get_chat_history 정렬 보장)(#8).
        message_metadata: dict[str, Any] = {"timestamp": time.time()}
        if metadata:
            message_metadata.update(
                {
                    "message_id": metadata.get("message_id"),  # ✅ Task 5: 메시지 ID 저장
                    "user_message": user_message,
                    "assistant_response": assistant_response,
                    "tokens_used": metadata.get("tokens_used", 0),
                    "processing_time": metadata.get("processing_time", 0.0),
                    "sources": metadata.get("sources", []),  # 인메모리 경로 sources 노출
                    "model_info": metadata.get("model_info"),
                    "topic": metadata.get("topic"),
                    "debug_trace": metadata.get("debug_trace"),  # ✅ Task 5: 디버깅 추적 저장
                }
            )

        # MemoryService로 위임 (메시지와 metadata를 같은 lock에서 append/trim)
        await self.memory_service.add_conversation(
            session_id, session, user_message, assistant_response, message_metadata
        )

        # 통계 업데이트
        self.session_service.increment_conversation_count()

        if metadata:
            # PostgreSQL 통계 업데이트 (L230-235)
            await self.session_service.update_session_stats_in_db(
                session_id,
                tokens=metadata.get("tokens_used", 0),
                processing_time=metadata.get("processing_time", 0.0),
            )

        # 토픽 추출 (L237-240)
        if metadata and metadata.get("topic"):
            if metadata["topic"] not in session["topics"]:
                session["topics"].append(metadata["topic"])

        logger.debug(f"Conversation added to enhanced session: {session_id}")

    async def get_context_string(self, session_id: str) -> str:
        """컨텍스트 문자열 반환 (MemoryService로 위임)"""
        session_result = await self.session_service.get_session(session_id)
        if not session_result["is_valid"]:
            return ""

        session = session_result["session"]
        return await self.memory_service.get_context_string(session_id, session)

    async def get_chat_history(self, session_id: str) -> dict[str, Any]:
        """채팅 히스토리 반환 (MemoryService로 위임)"""
        session_result = await self.session_service.get_session(session_id)
        if not session_result["is_valid"]:
            return {"messages": [], "message_count": 0}

        session = session_result["session"]
        return await self.memory_service.get_chat_history(session_id, session)

    async def get_conversation(
        self, session_id: str, max_exchanges: int = 5
    ) -> list[dict[str, str]]:
        """
        최근 대화 교환 반환 (RAG 파이프라인용)

        Args:
            session_id: 세션 ID
            max_exchanges: 반환할 최대 교환 수 (기본 5)

        Returns:
            [{"user": "...", "assistant": "..."}, ...]
        """
        chat_history_result = await self.get_chat_history(session_id)
        messages = chat_history_result.get("messages", [])

        # User-Assistant 쌍으로 변환
        conversations = []
        i = 0
        while i < len(messages) - 1:
            if messages[i]["type"] == "user" and messages[i + 1]["type"] == "assistant":
                conversations.append(
                    {"user": messages[i]["content"], "assistant": messages[i + 1]["content"]}
                )
                i += 2
            else:
                i += 1

        # 최근 max_exchanges개만 반환
        return conversations[-max_exchanges:] if conversations else []

    # ========================================
    # Admin API - AdminService 위임
    # ========================================

    async def get_all_sessions(
        self, status: str = "all", limit: int = 50, offset: int = 0
    ) -> dict[str, Any]:
        """모든 세션 목록 조회 (AdminService로 위임)"""
        return await self.admin_service.get_all_sessions(
            self.session_service.sessions, status, limit, offset
        )

    async def get_session_details(self, session_id: str) -> dict[str, Any] | None:
        """세션 상세 정보 조회 (AdminService로 위임)"""
        return await self.admin_service.get_session_details(
            session_id, self.session_service.sessions, self.memory_service.memories
        )

    async def get_recent_chats(self, limit: int = 20) -> list[dict[str, Any]]:
        """최근 채팅 로그 조회 (AdminService로 위임)"""
        return await self.admin_service.get_recent_chats(self.session_service.sessions, limit)

    async def get_debug_trace(
        self, session_id: str, message_id: str
    ) -> dict[str, Any] | None:
        """
        디버깅 추적 정보 조회 (Task 5)

        Args:
            session_id: 세션 ID
            message_id: 메시지 ID

        Returns:
            debug_trace 딕셔너리 또는 None (찾지 못한 경우)
        """
        session_result = await self.session_service.get_session(session_id)
        if not session_result["is_valid"]:
            return None

        session = session_result["session"]
        messages_metadata = session.get("messages_metadata", [])

        # message_id로 메시지 찾기
        for msg in messages_metadata:
            if msg.get("message_id") == message_id:
                return msg.get("debug_trace")

        return None
