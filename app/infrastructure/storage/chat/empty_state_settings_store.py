"""빈 화면(Empty State) 설정 영속화 스토어 (PostgreSQL).

챗봇 시작 화면의 메인/보조 메시지와 추천 질문을 로케일별로
`chat_empty_state_settings` 테이블에 저장/조회합니다.

설계 원칙:
- 공개 조회(get_all/get)는 graceful: DB 미연결/실패 시 빈 결과를 반환하여
  라우터가 코드 기본값으로 폴백하도록 합니다(빈 화면이 절대 깨지지 않음).
- 관리자 저장(upsert)/삭제(delete)는 DB 미연결이면 None/False를 반환합니다
  (라우터가 503 처리). 실제 DB 오류는 예외를 전파하여 관리자가 실패를 인지하도록
  합니다(공개 조회와 달리 은폐하지 않음).

의존성:
- DatabaseManager (SQLAlchemy 비동기 세션) - 기존 persistence 계층 재사용
- ChatEmptyStateSettingsModel - chat_empty_state_settings 테이블 매핑
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import delete as sa_delete
from sqlalchemy import select

from app.infrastructure.persistence.connection import db_manager as default_db_manager
from app.infrastructure.persistence.models import ChatEmptyStateSettingsModel
from app.lib.logger import get_logger

if TYPE_CHECKING:
    from app.infrastructure.persistence.connection import DatabaseManager

logger = get_logger(__name__)


class ChatEmptyStateSettingsStore:
    """PostgreSQL 기반 빈 화면 설정 스토어 (로케일별 1행)."""

    def __init__(self, db_manager: DatabaseManager | None = None) -> None:
        """
        Args:
            db_manager: 데이터베이스 연결 관리자. 미지정 시 모듈 싱글톤을 사용합니다.
        """
        self.db_manager: Any = db_manager if db_manager is not None else default_db_manager

    def _is_ready(self) -> bool:
        """DB 세션 생성이 가능한 상태인지 확인."""
        return getattr(self.db_manager, "async_session_maker", None) is not None

    async def get_all(self) -> dict[str, dict[str, Any]]:
        """저장된 모든 로케일 설정을 반환합니다 (graceful).

        Returns:
            {locale: {"mainMessage", "subMessage", "suggestions", "updatedAt"}} 형식.
            DB 미연결/실패 시 빈 dict.
        """
        if not self._is_ready():
            logger.debug("EmptyStateStore: DB 미연결 - 빈 설정 반환 (graceful)")
            return {}

        try:
            async with self.db_manager.get_session() as session:
                result = await session.execute(select(ChatEmptyStateSettingsModel))
                rows = result.scalars().all()
            return {row.locale: row.to_dict() for row in rows}
        except Exception as e:  # noqa: BLE001 - 조회 실패해도 기본값으로 폴백
            logger.warning(
                f"EmptyStateStore 조회 실패 (graceful, 기본값 폴백): {e}", exc_info=True
            )
            return {}

    async def get(self, locale: str) -> dict[str, Any] | None:
        """단일 로케일 설정을 반환합니다 (graceful). 없으면 None."""
        if not self._is_ready():
            return None
        try:
            async with self.db_manager.get_session() as session:
                result = await session.execute(
                    select(ChatEmptyStateSettingsModel).where(
                        ChatEmptyStateSettingsModel.locale == locale
                    )
                )
                row = result.scalars().first()
            return row.to_dict() if row else None
        except Exception as e:  # noqa: BLE001
            logger.warning(
                f"EmptyStateStore 단일 조회 실패 (graceful): {e}", exc_info=True
            )
            return None

    async def upsert(
        self,
        locale: str,
        main_message: str,
        sub_message: str,
        suggestions: list[str],
    ) -> dict[str, Any] | None:
        """로케일 설정을 저장(없으면 생성, 있으면 갱신)합니다.

        DB 미연결이면 None을 반환하고(라우터가 503), 실제 DB 오류는 예외를
        전파합니다(관리자가 실패를 인지해야 하므로, 공개 조회와 달리 은폐하지 않음).

        Returns:
            저장된 설정 dict. DB 미연결 시 None.
        """
        if not self._is_ready():
            logger.warning("EmptyStateStore: DB 미연결 - 설정 저장 불가")
            return None

        async with self.db_manager.get_session() as session:
            result = await session.execute(
                select(ChatEmptyStateSettingsModel).where(
                    ChatEmptyStateSettingsModel.locale == locale
                )
            )
            row = result.scalars().first()
            if row is None:
                row = ChatEmptyStateSettingsModel(
                    locale=locale,
                    main_message=main_message,
                    sub_message=sub_message,
                    suggestions=suggestions,
                )
                session.add(row)
            else:
                row.main_message = main_message
                row.sub_message = sub_message
                row.suggestions = suggestions
            # get_session 컨텍스트가 commit 처리
        logger.info(f"빈 화면 설정 저장 완료: locale={locale}")
        # 저장값을 그대로 dict로 구성해 반환 (재조회 없이)
        return {
            "mainMessage": main_message,
            "subMessage": sub_message,
            "suggestions": list(suggestions),
        }

    async def delete(self, locale: str) -> bool:
        """로케일 설정을 삭제(기본값으로 리셋)합니다.

        DB 미연결이면 False를 반환(라우터가 503)하고, 실제 DB 오류는 예외를
        전파합니다.

        Returns:
            DB 연결되어 삭제를 시도했으면 True(행이 없어도 True), 미연결이면 False.
        """
        if not self._is_ready():
            logger.warning("EmptyStateStore: DB 미연결 - 설정 삭제 불가")
            return False

        async with self.db_manager.get_session() as session:
            await session.execute(
                sa_delete(ChatEmptyStateSettingsModel).where(
                    ChatEmptyStateSettingsModel.locale == locale
                )
            )
        logger.info(f"빈 화면 설정 삭제(기본값 리셋) 완료: locale={locale}")
        return True
