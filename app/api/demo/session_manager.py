"""
DemoSessionManager — 데모 세션 생명주기 관리

세션별 ChromaDB 컬렉션을 할당하고 TTL 기반으로 자동 정리합니다.
동시접속 50명을 512MB RAM 내에서 안정적으로 지원합니다.

주요 기능:
- 세션 생성/조회/삭제
- TTL 10분 만료 + LRU 퇴거
- asyncio 백그라운드 정리 루프
- 세션별 문서 수/파일 크기 제한
"""

import asyncio
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.lib.logger import get_logger

logger = get_logger(__name__)


# =============================================================================
# 설정 상수
# =============================================================================

# 환경변수로 오버라이드 가능한 기본값
DEFAULT_MAX_SESSIONS = 50
DEFAULT_TTL_SECONDS = 600  # 10분
DEFAULT_CLEANUP_INTERVAL = 30  # 30초
DEFAULT_MAX_DOCS_PER_SESSION = 5
DEFAULT_MAX_FILE_SIZE_MB = 10
DEFAULT_DAILY_API_LIMIT = 500  # 일일 API 호출 상한 (임베딩 + LLM)


# =============================================================================
# 데이터 클래스
# =============================================================================


@dataclass
class DemoSession:
    """개별 데모 세션 정보"""

    session_id: str
    collection_name: str  # ChromaDB 컬렉션명
    created_at: float  # time.time()
    last_accessed: float  # time.time()
    document_count: int = 0
    document_names: list[str] = field(default_factory=list)
    total_chunks: int = 0
    is_sample: bool = False  # 샘플 데이터 세션 여부


@dataclass
class DemoStats:
    """데모 서비스 통계"""

    active_sessions: int
    max_sessions: int
    ttl_seconds: int
    total_sessions_created: int
    total_sessions_expired: int
    total_documents_uploaded: int
    daily_api_calls: int = 0
    daily_api_limit: int = 0


# =============================================================================
# 세션 관리자
# =============================================================================


class DemoSessionManager:
    """
    데모 세션 생명주기 관리자

    세션별 ChromaDB 컬렉션을 할당하고 TTL/LRU 기반으로 자동 정리합니다.

    사용 예시:
        manager = DemoSessionManager(chroma_client=client)
        await manager.start_cleanup_loop()

        session = await manager.create_session()
        session = await manager.get_session(session.session_id)
        await manager.delete_session(session.session_id)
    """

    def __init__(
        self,
        chroma_client: Any,
        max_sessions: int = DEFAULT_MAX_SESSIONS,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
        cleanup_interval: int = DEFAULT_CLEANUP_INTERVAL,
        max_docs_per_session: int = DEFAULT_MAX_DOCS_PER_SESSION,
        max_file_size_mb: int = DEFAULT_MAX_FILE_SIZE_MB,
        daily_api_limit: int = DEFAULT_DAILY_API_LIMIT,
        on_session_deleted: Callable[[str], None] | None = None,
    ) -> None:
        """
        세션 관리자 초기화

        Args:
            chroma_client: ChromaDB 클라이언트 인스턴스 (인메모리)
            max_sessions: 최대 동시 세션 수
            ttl_seconds: 세션 TTL (초)
            cleanup_interval: 정리 루프 간격 (초)
            max_docs_per_session: 세션당 최대 문서 수
            max_file_size_mb: 최대 파일 크기 (MB)
            daily_api_limit: 일일 API 호출 상한 (0 = 무제한)
            on_session_deleted: 세션 삭제 시 호출할 콜백 (인메모리 히스토리 정리 등)
        """
        self._chroma_client = chroma_client
        self._max_sessions = max_sessions
        self._ttl_seconds = ttl_seconds
        self._cleanup_interval = cleanup_interval
        self._max_docs_per_session = max_docs_per_session
        self._max_file_size_mb = max_file_size_mb
        self._daily_api_limit = daily_api_limit
        self._on_session_deleted = on_session_deleted

        # 세션 저장소
        self._sessions: dict[str, DemoSession] = {}
        self._lock = asyncio.Lock()

        # 통계
        self._total_created = 0
        self._total_expired = 0
        self._total_documents = 0

        # 일일 API 호출 예산 추적
        self._daily_api_calls = 0
        self._daily_reset_time = time.time()

        # 정리 루프 태스크
        self._cleanup_task: asyncio.Task[None] | None = None

        logger.info(
            f"DemoSessionManager 초기화: max={max_sessions}, "
            f"ttl={ttl_seconds}s, cleanup={cleanup_interval}s, "
            f"daily_api_limit={daily_api_limit}"
        )

    # =========================================================================
    # 세션 CRUD
    # =========================================================================

    async def create_session(self, is_sample: bool = False) -> DemoSession:
        """
        새 데모 세션 생성

        세션 수 제한 초과 시 가장 오래된 세션을 LRU 정리합니다.

        Args:
            is_sample: 샘플 데이터 세션 여부

        Returns:
            생성된 DemoSession
        """
        async with self._lock:
            # 세션 수 제한 — LRU 퇴거
            while len(self._sessions) >= self._max_sessions:
                await self._evict_oldest_session()

            session_id = uuid.uuid4().hex[:16]
            collection_name = f"demo_{session_id[:8]}"
            now = time.time()

            session = DemoSession(
                session_id=session_id,
                collection_name=collection_name,
                created_at=now,
                last_accessed=now,
                is_sample=is_sample,
            )

            self._sessions[session_id] = session
            self._total_created += 1

            logger.info(
                f"세션 생성: {session_id} "
                f"(컬렉션: {collection_name}, 활성: {len(self._sessions)})"
            )

        return session

    async def get_session(self, session_id: str) -> DemoSession | None:
        """
        세션 조회 및 last_accessed 갱신

        Args:
            session_id: 세션 ID

        Returns:
            DemoSession 또는 None (만료/미존재)
        """
        async with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return None

            # TTL 만료 체크
            if self._is_expired(session):
                await self._delete_session_internal(session_id)
                return None

            # last_accessed 갱신
            session.last_accessed = time.time()
            return session

    async def delete_session(self, session_id: str) -> bool:
        """
        세션 수동 삭제

        Args:
            session_id: 세션 ID

        Returns:
            삭제 성공 여부
        """
        async with self._lock:
            return await self._delete_session_internal(session_id)

    async def increment_document_count(
        self, session_id: str, doc_name: str, chunk_count: int = 0
    ) -> bool:
        """
        세션의 문서 카운터 증가

        Args:
            session_id: 세션 ID
            doc_name: 문서 파일명
            chunk_count: 청크 수

        Returns:
            성공 여부 (제한 초과 시 False)
        """
        async with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return False

            if session.document_count >= self._max_docs_per_session:
                return False

            session.document_count += 1
            session.document_names.append(doc_name)
            session.total_chunks += chunk_count
            session.last_accessed = time.time()
            self._total_documents += 1
            return True

    # =========================================================================
    # 세션 정리
    # =========================================================================

    async def start_cleanup_loop(self) -> None:
        """백그라운드 정리 루프 시작"""
        if self._cleanup_task is not None:
            return

        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        logger.info(f"정리 루프 시작 (간격: {self._cleanup_interval}s)")

    async def stop_cleanup_loop(self) -> None:
        """백그라운드 정리 루프 중지"""
        if self._cleanup_task is not None:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            self._cleanup_task = None
            logger.info("정리 루프 중지")

    async def cleanup_expired(self) -> int:
        """
        만료된 세션 정리

        Returns:
            정리된 세션 수
        """
        async with self._lock:
            expired_ids = [
                sid
                for sid, session in self._sessions.items()
                if self._is_expired(session)
            ]

            for sid in expired_ids:
                await self._delete_session_internal(sid)
                self._total_expired += 1

            if expired_ids:
                logger.info(
                    f"만료 세션 {len(expired_ids)}개 정리 "
                    f"(남은 세션: {len(self._sessions)})"
                )

            return len(expired_ids)

    # =========================================================================
    # 통계 및 속성
    # =========================================================================

    async def get_stats(self) -> DemoStats:
        """데모 서비스 통계 반환 (Lock으로 일관성 보장)"""
        async with self._lock:
            self._maybe_reset_daily_counter()
            return DemoStats(
                active_sessions=len(self._sessions),
                max_sessions=self._max_sessions,
                ttl_seconds=self._ttl_seconds,
                total_sessions_created=self._total_created,
                total_sessions_expired=self._total_expired,
                total_documents_uploaded=self._total_documents,
                daily_api_calls=self._daily_api_calls,
                daily_api_limit=self._daily_api_limit,
            )

    @property
    def active_session_count(self) -> int:
        """활성 세션 수"""
        return len(self._sessions)

    @property
    def max_sessions(self) -> int:
        """최대 세션 수"""
        return self._max_sessions

    @property
    def ttl_seconds(self) -> int:
        """세션 TTL (초)"""
        return self._ttl_seconds

    @property
    def max_docs_per_session(self) -> int:
        """세션당 최대 문서 수"""
        return self._max_docs_per_session

    @property
    def max_file_size_mb(self) -> int:
        """최대 파일 크기 (MB)"""
        return self._max_file_size_mb

    async def check_and_increment_api_calls(self, count: int = 1) -> bool:
        """
        일일 API 호출 예산 확인 및 카운터 증가

        Args:
            count: 증가할 호출 수 (임베딩+LLM이면 2)

        Returns:
            True: 예산 내 (호출 허용)
            False: 예산 초과 (호출 거부)
        """
        async with self._lock:
            self._maybe_reset_daily_counter()

            # 0 = 무제한
            if self._daily_api_limit == 0:
                self._daily_api_calls += count
                return True

            if self._daily_api_calls + count > self._daily_api_limit:
                logger.warning(
                    f"일일 API 호출 상한 도달: "
                    f"{self._daily_api_calls}/{self._daily_api_limit}"
                )
                return False

            self._daily_api_calls += count
            return True

    @property
    def daily_api_calls(self) -> int:
        """오늘 사용한 API 호출 수"""
        return self._daily_api_calls

    @property
    def daily_api_limit(self) -> int:
        """일일 API 호출 상한"""
        return self._daily_api_limit

    async def get_session_ttl_remaining(self, session_id: str) -> float | None:
        """
        세션의 남은 TTL (초)

        Args:
            session_id: 세션 ID

        Returns:
            남은 초 또는 None (미존재)
        """
        async with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return None

            elapsed = time.time() - session.last_accessed
            remaining = self._ttl_seconds - elapsed
            return max(0.0, remaining)

    async def get_session_info(self, session_id: str) -> dict[str, Any] | None:
        """
        프론트엔드 호환 세션 정보 반환

        기존 get_session()을 내부 호출하여 TTL 만료 검사를 수행합니다.
        세션이 존재하지 않거나 만료된 경우 None을 반환합니다.

        Args:
            session_id: 조회할 세션 ID

        Returns:
            세션 정보 딕셔너리 또는 None (미존재/만료)
        """
        session = await self.get_session(session_id)
        if session is None:
            return None

        return {
            "session_id": session.session_id,
            "created_at": datetime.fromtimestamp(
                session.created_at, tz=UTC
            ).isoformat(),
            "message_count": 0,
            "last_activity": datetime.fromtimestamp(
                session.last_accessed, tz=UTC
            ).isoformat(),
        }

    # =========================================================================
    # 내부 메서드
    # =========================================================================

    def _maybe_reset_daily_counter(self) -> None:
        """24시간 경과 시 일일 API 호출 카운터 리셋 (lock 없이 호출 — 호출자가 lock 보유)"""
        _SECONDS_PER_DAY = 86400
        if time.time() - self._daily_reset_time >= _SECONDS_PER_DAY:
            prev = self._daily_api_calls
            self._daily_api_calls = 0
            self._daily_reset_time = time.time()
            if prev > 0:
                logger.info(f"일일 API 카운터 리셋 (이전: {prev}건)")

    def _is_expired(self, session: DemoSession) -> bool:
        """세션 TTL 만료 여부 확인"""
        return (time.time() - session.last_accessed) > self._ttl_seconds

    async def _delete_session_internal(self, session_id: str) -> bool:
        """
        세션 내부 삭제 (lock 없이 호출 — 호출자가 lock 보유)

        ChromaDB 컬렉션도 함께 삭제합니다.
        """
        session = self._sessions.pop(session_id, None)
        if session is None:
            return False

        # ChromaDB 컬렉션 삭제
        try:
            self._chroma_client.delete_collection(session.collection_name)
            logger.debug(f"컬렉션 삭제: {session.collection_name}")
        except Exception as e:
            # 컬렉션이 이미 없거나 삭제 실패해도 세션은 제거됨
            logger.warning(f"컬렉션 삭제 실패: {session.collection_name}: {e}")

        logger.info(
            f"세션 삭제: {session_id} "
            f"(문서: {session.document_count}개, 남은 세션: {len(self._sessions)})"
        )

        # 세션 삭제 콜백 호출 (인메모리 히스토리 정리 등)
        if self._on_session_deleted is not None:
            self._on_session_deleted(session_id)

        return True

    async def _evict_oldest_session(self) -> None:
        """가장 오래된 세션 LRU 퇴거 (lock 없이 호출 — 호출자가 lock 보유)"""
        if not self._sessions:
            return

        # 샘플 세션은 퇴거 대상에서 제외 (일반 세션 우선 퇴거)
        non_sample = {
            sid: s
            for sid, s in self._sessions.items()
            if not s.is_sample
        }
        target = non_sample if non_sample else self._sessions

        oldest_id = min(target, key=lambda sid: target[sid].last_accessed)
        await self._delete_session_internal(oldest_id)
        self._total_expired += 1
        logger.info(f"LRU 퇴거: {oldest_id}")

    async def _cleanup_loop(self) -> None:
        """백그라운드 정리 루프 (연속 실패 시 지수 백오프)"""
        consecutive_failures = 0
        max_backoff = 300  # 최대 5분
        while True:
            try:
                await asyncio.sleep(self._cleanup_interval)
                await self.cleanup_expired()
                consecutive_failures = 0  # 성공 시 리셋
            except asyncio.CancelledError:
                break
            except Exception as e:
                consecutive_failures += 1
                backoff = min(
                    self._cleanup_interval * (2 ** consecutive_failures),
                    max_backoff,
                )
                logger.error(
                    f"정리 루프 오류 (연속 {consecutive_failures}회): {e}, "
                    f"다음 시도까지 {backoff}초 대기"
                )
                try:
                    await asyncio.sleep(backoff)
                except asyncio.CancelledError:
                    break
