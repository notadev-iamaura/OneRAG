"""PostgreSQL 채팅 메시지 영속화 스토어.

채팅 메시지를 PostgreSQL `chat_messages` 테이블에 영구 저장하고 복원합니다.
이는 OneRAG의 **선택적(opt-in) 영속화 백엔드**입니다. 기본 동작은 인메모리이며,
config(`session.chat_persistence.enabled`)로 활성화하고 `DATABASE_URL`이 연결된
환경에서만 실제로 저장/복원합니다.

설계 원칙 (반드시 준수):
- DB 저장/연결 실패가 채팅 응답을 절대 실패시키지 않습니다(graceful). 인메모리는
  그대로 유지되고, 이 스토어는 경고 로그만 남기고 graceful 하게 동작합니다.
- PG 미연결(`DATABASE_URL` 없음, db_manager 미초기화) 환경에서는 save는 no-op,
  get은 빈 리스트를 반환합니다.

범용성:
- `company_id`는 멀티테넌트 확장을 위한 컬럼으로만 유지합니다. 단일테넌트 OSS
  기본 경로에서는 항상 None이며 테넌트 필터를 적용하지 않습니다.

주요 메서드:
- save_message: 단일 메시지 저장 (user/assistant)
- save_exchange: user/assistant 교환을 단일 트랜잭션으로 원자적 저장
- get_session_messages: 세션별 메시지 시간순 복원

의존성:
- DatabaseManager (SQLAlchemy 비동기 세션) - 기존 persistence 계층 재사용
- ChatMessageModel - chat_messages 테이블 매핑
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy import asc, select

from app.infrastructure.persistence.connection import db_manager as default_db_manager
from app.infrastructure.persistence.models import ChatMessageModel
from app.lib.logger import get_logger

if TYPE_CHECKING:
    from app.infrastructure.persistence.connection import DatabaseManager

logger = get_logger(__name__)


class PostgresChatStore:
    """PostgreSQL 기반 채팅 메시지 영속화 스토어.

    기존 `EvaluationDataManager` / `PromptRepository`와 동일하게 모듈 레벨 싱글톤
    `db_manager`(SQLAlchemy 비동기 세션)를 사용합니다. 테이블 생성은 부팅 시
    `Base.metadata.create_all`(`db_manager.create_tables`)로 멱등하게 처리됩니다.
    """

    def __init__(self, db_manager: DatabaseManager | None = None) -> None:
        """
        Args:
            db_manager: 데이터베이스 연결 관리자. 미지정 시 모듈 싱글톤을 사용합니다.
        """
        # DI 주입을 우선하되, 미지정 시 기존 persistence 싱글톤을 재사용합니다.
        self.db_manager: Any = db_manager if db_manager is not None else default_db_manager

    def _is_ready(self) -> bool:
        """DB 세션 생성이 가능한 상태인지 확인 (graceful no-op 판단용).

        `DATABASE_URL`이 없거나 db_manager가 초기화되지 않은 환경에서는
        `async_session_maker`가 None 이므로 저장/조회를 건너뜁니다.
        """
        return getattr(self.db_manager, "async_session_maker", None) is not None

    async def save_message(
        self,
        session_id: str,
        role: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """채팅 메시지 1건을 영구 저장합니다 (graceful).

        DB 연결/저장 실패 시 예외를 전파하지 않고 경고 로그만 남깁니다.
        호출 측(MemoryService)의 인메모리 저장은 영향을 받지 않습니다.

        Args:
            session_id: 세션 ID (FK 없음, 인덱스만)
            role: 'user' 또는 'assistant'
            content: 메시지 본문
            metadata: 추가 메타데이터 (sources, tokens_used 등)
        """
        if not self._is_ready():
            # PG 미연결 환경: 저장 생략 (인메모리만 사용)
            logger.debug("PostgresChatStore: DB 미연결 - 메시지 저장 생략 (graceful)")
            return

        try:
            meta = metadata or {}
            async with self.db_manager.get_session() as session:
                message = ChatMessageModel(
                    session_id=session_id,
                    company_id=_extract_company_id(meta),
                    role=role,
                    content=content,
                    extra_metadata=meta,
                )
                session.add(message)
                # get_session 컨텍스트 매니저가 commit 처리
            logger.debug(f"💾 채팅 메시지 저장 성공: session_id={session_id}, role={role}")
        except Exception as e:  # noqa: BLE001 - 채팅을 절대 실패시키지 않음
            # DB 저장 실패해도 채팅은 계속 작동 (Fail-Safe)
            logger.warning(
                f"PostgresChatStore 메시지 저장 실패 (graceful, 채팅 영향 없음): {e}",
                exc_info=True,
            )

    async def save_exchange(
        self,
        session_id: str,
        user_message: str,
        assistant_response: str,
        user_metadata: dict[str, Any] | None = None,
        assistant_metadata: dict[str, Any] | None = None,
    ) -> None:
        """user/assistant 메시지 2건을 단일 트랜잭션으로 원자적으로 저장합니다 (graceful).

        save_message를 2번 호출하면 user 성공 + assistant 실패 시 짝이 맞지 않는
        불완전 히스토리가 PG에 남습니다. 이 메서드는 하나의 `get_session` 컨텍스트
        (= 단일 트랜잭션) 안에서 두 row를 함께 add/commit 하여 원자성을 보장하고,
        DB 왕복도 1회로 줄입니다.

        DB 연결/저장 실패 시 예외를 전파하지 않고 경고 로그만 남깁니다(둘 다 미저장).

        Args:
            session_id: 세션 ID (FK 없음, 인덱스만)
            user_message: 사용자 메시지 본문
            assistant_response: AI 응답 본문
            user_metadata: 사용자 메시지 메타데이터 (company_id, message_id 등)
            assistant_metadata: 어시스턴트 메시지 메타데이터 (sources, tokens_used 등)
        """
        if not self._is_ready():
            logger.debug("PostgresChatStore: DB 미연결 - 교환 저장 생략 (graceful)")
            return

        # company_id는 전용 컬럼에 저장(멀티테넌트 확장 근거). metadata 안에도 함께
        # 보존하여 기존 복원 로직과의 호환을 유지합니다. 단일테넌트는 None.
        user_meta = user_metadata or {}
        assistant_meta = assistant_metadata or {}
        company_id = _extract_company_id(assistant_meta) or _extract_company_id(user_meta)

        # 복원 시 user→assistant 순서를 보장하기 위해 created_at을 명시적으로 설정합니다.
        # 단일 교환 내 두 row가 동일 타임스탬프를 가지면 정렬 순서가 불안정하므로
        # assistant에 미세 오프셋을 부여합니다(server_default는 값이 None일 때만 동작).
        now = datetime.now(UTC)
        try:
            async with self.db_manager.get_session() as session:
                # 단일 트랜잭션: 두 메시지를 함께 add → 컨텍스트 종료 시 한 번에 commit
                session.add(
                    ChatMessageModel(
                        session_id=session_id,
                        company_id=company_id,
                        role="user",
                        content=user_message,
                        extra_metadata=user_meta,
                        created_at=now,
                    )
                )
                session.add(
                    ChatMessageModel(
                        session_id=session_id,
                        company_id=company_id,
                        role="assistant",
                        content=assistant_response,
                        extra_metadata=assistant_meta,
                        created_at=now + timedelta(microseconds=1),
                    )
                )
            logger.debug(f"💾 채팅 교환 원자 저장 성공: session_id={session_id}")
        except Exception as e:  # noqa: BLE001 - 채팅을 절대 실패시키지 않음
            # 단일 트랜잭션이므로 실패 시 두 메시지 모두 롤백되어 짝이 보존됨
            logger.warning(
                f"PostgresChatStore 교환 저장 실패 (graceful, 둘 다 미저장): {e}",
                exc_info=True,
            )

    async def get_session_messages(
        self, session_id: str, limit: int | None = None, company_id: str | None = None
    ) -> list[dict[str, Any]]:
        """세션의 메시지를 시간순(created_at, id)으로 복원합니다 (graceful).

        DB 연결/조회 실패 시 예외를 전파하지 않고 빈 리스트를 반환합니다.

        [방 격리] company_id가 주어지면 해당 회사 메시지만 복원합니다(멀티테넌트
        확장 대비). company_id=None이면 전체를 반환합니다(단일테넌트 기본 경로).

        Args:
            session_id: 세션 ID
            limit: 최대 조회 개수 (None이면 전체)
            company_id: 회사 범위 필터 (None이면 필터 없음)

        Returns:
            메시지 딕셔너리 리스트. 각 항목은 ChatMessageModel.to_dict() 형식.
        """
        if not self._is_ready():
            logger.debug("PostgresChatStore: DB 미연결 - 메시지 복원 생략 (graceful)")
            return []

        try:
            async with self.db_manager.get_session() as session:
                statement = select(ChatMessageModel).where(
                    ChatMessageModel.session_id == session_id
                )
                if company_id is not None:
                    statement = statement.where(
                        ChatMessageModel.company_id == company_id
                    )
                statement = statement.order_by(
                    asc(ChatMessageModel.created_at), asc(ChatMessageModel.id)
                )
                if limit is not None:
                    statement = statement.limit(limit)

                result = await session.execute(statement)
                rows = result.scalars().all()
            return [row.to_dict() for row in rows]
        except Exception as e:  # noqa: BLE001 - 복원 실패해도 빈 화면이 될 뿐 채팅은 동작
            logger.warning(
                f"PostgresChatStore 메시지 복원 실패 (graceful, 빈 결과 반환): {e}",
                exc_info=True,
            )
            return []


def _extract_company_id(metadata: dict[str, Any]) -> str | None:
    """메타데이터에서 company_id를 문자열로 추출합니다(없으면 None).

    전용 `company_id` 컬럼에 저장할 값을 만듭니다. 빈 문자열/None은 None으로 정규화합니다.
    """
    value = metadata.get("company_id")
    if value is None:
        return None
    text = str(value)
    return text or None
