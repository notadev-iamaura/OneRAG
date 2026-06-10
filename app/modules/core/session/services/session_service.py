"""
Session Service - 세션 CRUD 및 통계 관리
Phase 4.2: enhanced_session.py에서 추출한 검증된 세션 관리 로직
⚠️ 주의: 이 코드는 기존 검증된 로직을 재사용합니다.
"""

import asyncio
import time
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from app.infrastructure.persistence.helpers import timestamps
from app.lib.logger import get_logger

logger = get_logger(__name__)


def _is_valid_uuid4(value: str) -> bool:
    """문자열이 유효한 UUID4 형식인지 검증한다 (세션 ID capability 보안용)."""
    try:
        return UUID(value).version == 4
    except (ValueError, TypeError, AttributeError):
        return False


class SessionService:
    """
    세션 CRUD 및 통계 관리 서비스

    역할:
    - 세션 생성, 조회, 삭제
    - 통계 수집 및 관리
    - TTL 기반 세션 만료 검사
    - PostgreSQL 연동 (선택적)

    기존 코드 기반: enhanced_session.py의 세션 관리 메서드들
    """

    def __init__(self, config: dict[str, Any]):
        """
        Args:
            config: 세션 설정 (ttl_seconds/ttl, max_exchanges, cleanup_interval_seconds/cleanup_interval)
        """
        self.config = config
        session_config = config.get("session", {})

        # 설정값 (신키 우선, 구키 폴백)
        self.ttl = session_config.get("ttl_seconds", session_config.get("ttl", 7200))
        self.max_exchanges = session_config.get("max_exchanges", 10)
        self.cleanup_interval = session_config.get(
            "cleanup_interval_seconds", session_config.get("cleanup_interval", 600)
        )

        # 인메모리 세션 저장소 (enhanced_session.py L34-35)
        self.sessions: dict[str, dict[str, Any]] = {}

        # 🔒 세션 생성 Lock (전역 Lock - session_id 중복 체크 보호)
        # session_id 중복 체크 및 생성은 전역적으로 일어나므로 global lock 사용
        self.create_session_lock = asyncio.Lock()

        # 통계 (enhanced_session.py L37-42)
        self.stats = {
            "total_sessions": 0,
            "active_sessions": 0,
            "total_conversations": 0,
            "cleanup_runs": 0,
        }

        logger.info(
            f"SessionService 초기화: ttl={self.ttl}s, max_exchanges={self.max_exchanges}, "
            f"Session creation lock 활성화 (Race Condition 보호)"
        )

    async def create_session(
        self, metadata: dict[str, Any] | None = None, session_id: str | None = None
    ) -> dict[str, str]:
        """
        새 세션 생성 + Race Condition 보호

        기존 코드: enhanced_session.py의 create_session() (L78-133)
        개선 사항: Global Lock으로 동시 세션 생성 시 session_id 중복 방지

        ⚠️ Race Condition 시나리오:
        - 클라이언트가 같은 session_id로 동시에 두 번 요청
        - 두 요청이 동시에 self.sessions dict를 확인
        - 결과: 둘 다 "session_id 없음"으로 판단하여 중복 생성

        ✅ Lock 전략:
        - Global Lock (session_id 중복 체크는 전역적으로 일어남)
        - Lock은 빠른 작업만 보호 (0.01초 미만)
        - IP 지역 조회(0.1초)는 Lock 밖에서 실행

        Args:
            metadata: 세션 메타데이터 (ip_address, user_agent 등)
            session_id: 세션 ID (None이면 자동 생성)

        Returns:
            {'session_id': str, 'location': dict}
        """
        # IP 지역 정보 조회는 비활성화 상태 (세션 생성 타임아웃 원인이라 제거됨)
        location_data = None

        # 🔒 세션 ID 중복 체크 및 세션 생성 (Lock으로 보호)
        lock_start = time.time()
        async with self.create_session_lock:
            lock_acquired_time = time.time() - lock_start

            # 세션 ID 생성 또는 검증 (L79-86)
            # 🔒 보안(IDOR 방어): 클라이언트가 지정한 session_id는 추측 불가능한
            # UUID4 형식만 허용한다. "admin" 같은 약한 ID를 거부함으로써 session_id
            # 자체가 capability(접근 권한)가 되어 타 세션 무단 조회/삭제를 차단한다.
            uuid_start = time.time()
            if session_id is None:
                session_id = str(uuid4())
            elif not _is_valid_uuid4(session_id):
                logger.warning("유효하지 않은 세션 ID 형식 거부, 서버 UUID 발급")
                session_id = str(uuid4())
            elif session_id in self.sessions:
                logger.warning(f"요청된 세션 ID가 이미 존재함: {session_id}, 새 ID로 대체")
                session_id = str(uuid4())
            uuid_time = time.time() - uuid_start

            # 세션 데이터 생성: datetime 기반 시간 저장 (float 대신)
            data_start = time.time()
            current_time = datetime.now(UTC)
            session_data = {
                "session_id": session_id,
                **timestamps(),  # ✅ created_at, updated_at 자동 추가
                "last_accessed": current_time,  # datetime 객체로 저장
                "metadata": metadata or {},
                "user_name": None,
                "user_info": {},
                "topics": [],
                "facts": {},
                "messages_metadata": [],
                "location": location_data,
            }
            data_time = time.time() - data_start

            # 세션 저장 (L117-120)
            save_start = time.time()
            self.sessions[session_id] = session_data
            self.stats["total_sessions"] += 1
            self.stats["active_sessions"] += 1
            save_time = time.time() - save_start

        # PostgreSQL 저장 (L122-124) - 타임아웃 보호 및 비동기 처리
        db_start = time.time()
        if location_data:
            try:
                # 타임아웃 보호: DB 저장이 2초 이상 걸리면 취소
                await asyncio.wait_for(
                    self._save_session_to_db(session_id, location_data, metadata), timeout=2.0
                )
            except TimeoutError:
                logger.warning(
                    f"세션 DB 저장 타임아웃 (2초 초과): {session_id}, 세션은 계속 작동합니다"
                )
            except Exception as e:
                logger.error(f"세션 DB 저장 실패: {e}, 세션은 계속 작동합니다")
        db_time = time.time() - db_start

        logger.info(
            f"✅ 세션 생성 완료: {session_id}",
            extra={
                "lock_wait": f"{lock_acquired_time*1000:.2f}ms",
                "uuid_gen": f"{uuid_time*1000:.2f}ms",
                "data_create": f"{data_time*1000:.2f}ms",
                "dict_save": f"{save_time*1000:.2f}ms",
                "db_save": f"{db_time*1000:.2f}ms",
                "total_sessions": len(self.sessions),
            },
        )
        logger.debug(f"생성 후 세션 목록: {list(self.sessions.keys())}")
        logger.debug(f"생성 후 전체 세션 수: {len(self.sessions)}")

        return {"session_id": session_id, "location": location_data or {}}

    async def get_session(
        self, session_id: str, context: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """
        세션 조회
        기존 코드: enhanced_session.py의 get_session() (L135-173)

        Args:
            session_id: 세션 ID
            context: 업데이트할 컨텍스트 정보

        Returns:
            {'is_valid': bool, 'session': dict, ...}
        """
        # 세션 존재 여부 확인 (L137-144)
        if session_id not in self.sessions:
            logger.warning(f"세션을 찾을 수 없음: {session_id}")
            logger.debug(f"현재 세션 목록: {list(self.sessions.keys())}")
            logger.debug(f"전체 세션 수: {len(self.sessions)}")
            return {"is_valid": False, "reason": "session_not_found"}

        session = self.sessions[session_id]

        # TTL 검사: datetime 기반 정밀 시간 비교 (타임스탬프 float 연산 취약점 개선)
        current_time = datetime.now(UTC)
        last_accessed = session.get("last_accessed")

        # 하위 호환성: 기존 float 타임스탬프를 datetime으로 변환
        if isinstance(last_accessed, int | float):
            last_accessed = datetime.fromtimestamp(last_accessed, UTC)
        elif last_accessed is None:
            # None인 경우 현재 시간으로 초기화
            last_accessed = current_time

        time_since_access = (current_time - last_accessed).total_seconds()

        if time_since_access > self.ttl:
            logger.debug(
                f"세션 만료: {session_id}, "
                f"경과시간: {time_since_access:.0f}초 (TTL: {self.ttl}초)"
            )
            await self.delete_session(session_id)
            return {
                "is_valid": False,
                "reason": "session_expired",
                "expired_time": time_since_access,
            }

        # 마지막 접근 시간 업데이트 (L160-162)
        session["last_accessed"] = current_time
        logger.debug(
            f"세션 유효하고 업데이트됨: {session_id} "
            f"(남은 시간: {self.ttl - time_since_access:.0f}초)"
        )

        # 컨텍스트 정보 업데이트 (L164-166)
        if context:
            session["metadata"].update(context)

        return {
            "is_valid": True,
            "session": session,
            "renewed_session_id": session_id,
            "remaining_ttl": self.ttl - time_since_access,
        }

    async def delete_session(self, session_id: str):
        """
        세션 삭제
        기존 코드: enhanced_session.py의 delete_session() (L175-182)

        Args:
            session_id: 삭제할 세션 ID
        """
        if session_id in self.sessions:
            del self.sessions[session_id]
            self.stats["active_sessions"] = max(0, self.stats["active_sessions"] - 1)
            logger.debug(f"Enhanced session deleted: {session_id}")

    async def get_stats(self) -> dict[str, Any]:
        """
        통계 반환
        기존 코드: enhanced_session.py의 get_stats() (L352-369)

        Returns:
            통계 딕셔너리
        """
        current_time = datetime.now(UTC)  # ✅ datetime으로 변경

        # 활성 세션 재계산 (L356-361)
        active_count = 0
        for session in self.sessions.values():
            last_accessed = session["last_accessed"]
            # 하위 호환성: float 타임스탬프 처리
            if isinstance(last_accessed, int | float):
                last_accessed = datetime.fromtimestamp(last_accessed, UTC)

            time_since_access = (current_time - last_accessed).total_seconds()
            if time_since_access <= self.ttl:
                active_count += 1

        self.stats["active_sessions"] = active_count

        return {
            **self.stats,
            "total_sessions_in_memory": len(self.sessions),
            "ttl_seconds": self.ttl,
            "max_exchanges": self.max_exchanges,
        }

    async def clear_cache(self):
        """
        캐시 클리어 (만료된 세션 제거)
        기존 코드: enhanced_session.py의 clear_cache() (L371-383)
        """
        expired_sessions = []
        current_time = datetime.now(UTC)  # ✅ datetime으로 변경

        for session_id, session in self.sessions.items():
            last_accessed = session["last_accessed"]
            # 하위 호환성: float 타임스탬프 처리
            if isinstance(last_accessed, int | float):
                last_accessed = datetime.fromtimestamp(last_accessed, UTC)

            time_since_access = (current_time - last_accessed).total_seconds()
            if time_since_access > self.ttl:
                expired_sessions.append(session_id)

        for session_id in expired_sessions:
            await self.delete_session(session_id)

        logger.info(f"Cache cleared: {len(expired_sessions)} expired sessions removed")

    def increment_conversation_count(self):
        """대화 카운트 증가 (MemoryService에서 호출)"""
        self.stats["total_conversations"] += 1

    def increment_cleanup_count(self):
        """정리 작업 카운트 증가 (CleanupService에서 호출)"""
        self.stats["cleanup_runs"] += 1

    async def _save_session_to_db(self, session_id: str, location_data: dict, metadata: dict):
        """
        세션 정보를 PostgreSQL에 저장
        기존 코드: enhanced_session.py의 _save_session_to_db() (L670-704)

        ⚠️ 중요: DB 저장 실패해도 세션 생성은 계속 진행됩니다 (Fail-Safe 설계)

        Args:
            session_id: 세션 ID
            location_data: 위치 정보
            metadata: 메타데이터
        """
        try:
            from app.infrastructure.persistence.connection import db_manager
            from app.infrastructure.persistence.models import ChatSessionModel

            # DB 연결 확인
            if not db_manager._initialized:
                logger.debug(f"DB가 초기화되지 않음, 세션 DB 저장 스킵: {session_id}")
                return

            # DB 세션 획득 (외부에서 타임아웃 적용됨)
            async with db_manager.get_session() as db_session:
                session_model = ChatSessionModel(
                    session_id=session_id,
                    ip_hash=location_data.get("ip_hash"),
                    country=location_data.get("country"),
                    country_code=location_data.get("country_code"),
                    city=location_data.get("city"),
                    region=location_data.get("region"),
                    latitude=location_data.get("latitude"),
                    longitude=location_data.get("longitude"),
                    timezone=location_data.get("timezone"),
                    is_private_ip=location_data.get("is_private", False),
                    user_agent=metadata.get("metadata", {}).get("user_agent"),
                    extra_metadata=metadata.get("metadata", {}),
                )

                db_session.add(session_model)
                await db_session.commit()

                logger.debug(f"✅ 세션 DB 저장 완료: {session_id}")

        except Exception as e:
            # DB 저장 실패해도 세션은 계속 작동 (Fail-Safe)
            logger.error(f"세션 DB 저장 실패 (무시됨): {e}", exc_info=False)
            # ❌ raise 하지 않음 → 세션 생성 중단 없음

    async def update_session_stats_in_db(
        self, session_id: str, tokens: int, processing_time: float
    ):
        """
        PostgreSQL의 세션 통계 업데이트
        기존 코드: enhanced_session.py의 _update_session_stats_in_db() (L706-734)

        Args:
            session_id: 세션 ID
            tokens: 사용된 토큰 수
            processing_time: 처리 시간
        """
        try:
            from sqlalchemy import update
            from sqlalchemy.sql import func

            from app.infrastructure.persistence.connection import db_manager
            from app.infrastructure.persistence.models import ChatSessionModel

            async with db_manager.get_session() as db_session:
                stmt = (
                    update(ChatSessionModel)
                    .where(ChatSessionModel.session_id == session_id)
                    .values(
                        message_count=ChatSessionModel.message_count + 1,
                        total_tokens=ChatSessionModel.total_tokens + tokens,
                        total_processing_time=ChatSessionModel.total_processing_time
                        + processing_time,
                        last_accessed_at=func.now(),
                    )
                )
                await db_session.execute(stmt)
                await db_session.commit()

        except Exception as e:
            logger.error(f"세션 통계 업데이트 실패: {e}")
