"""
PostgreSQL 데이터베이스 연결 관리 모듈

Railway PostgreSQL과의 비동기 연결을 관리하고
SQLAlchemy 세션을 제공합니다.
"""

import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy import MetaData
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import declarative_base

from app.lib.errors import DatabaseError, ErrorCode
from app.lib.logger import get_logger

logger = get_logger(__name__)

# SQLAlchemy Base 클래스
convention = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

metadata = MetaData(naming_convention=convention)
Base = declarative_base(metadata=metadata)


class DatabaseManager:
    """데이터베이스 연결 관리자"""

    def __init__(self) -> None:
        self.engine: AsyncEngine | None = None
        self.async_session_maker: async_sessionmaker[AsyncSession] | None = None
        self._initialized = False

    async def initialize(self, database_url: str | None = None) -> None:
        """
        데이터베이스 연결 초기화

        Args:
            database_url: 데이터베이스 URL (없으면 환경변수에서 읽음)
        """
        if self._initialized:
            logger.warning("데이터베이스가 이미 초기화되었습니다")
            return

        try:
            # Railway에서 제공하는 DATABASE_URL 사용
            if not database_url:
                # 1순위: Railway가 자동으로 설정하는 DATABASE_URL 사용
                database_url = os.getenv("DATABASE_URL")

                # 2순위: TCP Proxy를 통한 Public URL (외부 접근용)
                if not database_url:
                    tcp_domain = os.getenv("RAILWAY_TCP_PROXY_DOMAIN")
                    tcp_port = os.getenv("RAILWAY_TCP_PROXY_PORT")
                    pguser = os.getenv("PGUSER") or os.getenv("POSTGRES_USER")
                    pgpassword = os.getenv("POSTGRES_PASSWORD")
                    pgdatabase = os.getenv("PGDATABASE") or os.getenv("POSTGRES_DB")

                    if all([tcp_domain, tcp_port, pguser, pgpassword, pgdatabase]):
                        database_url = f"postgresql://{pguser}:{pgpassword}@{tcp_domain}:{tcp_port}/{pgdatabase}"
                        logger.info(
                            f"TCP Proxy로 DATABASE_URL 구성: {pguser}@{tcp_domain}:{tcp_port}/{pgdatabase}"
                        )

                # 3순위: 개별 환경변수로 구성 (Private Domain 사용 - IPv6 문제 있을 수 있음)
                if not database_url:
                    pguser = os.getenv("PGUSER") or os.getenv("POSTGRES_USER")
                    pgpassword = os.getenv("POSTGRES_PASSWORD")
                    pghost = os.getenv("RAILWAY_PRIVATE_DOMAIN")
                    pgport = os.getenv("PGPORT", "5432")
                    pgdatabase = os.getenv("PGDATABASE") or os.getenv("POSTGRES_DB")

                    if all([pguser, pgpassword, pghost, pgdatabase]):
                        database_url = (
                            f"postgresql://{pguser}:{pgpassword}@{pghost}:{pgport}/{pgdatabase}"
                        )
                        logger.info(
                            f"Private Domain으로 DATABASE_URL 구성: {pguser}@{pghost}:{pgport}/{pgdatabase}"
                        )

            if not database_url:
                raise DatabaseError(ErrorCode.DB_001)

            # 비밀번호 마스킹: postgresql://user:password@host -> postgresql://user:***@host
            masked_url = database_url
            if "://" in masked_url and "@" in masked_url:
                # protocol://user:password@host 형식 파싱
                protocol_part, rest = masked_url.split("://", 1)
                if "@" in rest:
                    credentials, host_part = rest.split("@", 1)
                    if ":" in credentials:
                        user, _ = credentials.split(":", 1)
                        masked_url = f"{protocol_part}://{user}:***@{host_part}"
                    else:
                        # 비밀번호 없는 경우
                        masked_url = f"{protocol_part}://{credentials}@{host_part}"

            logger.info(f"사용할 DATABASE_URL: {masked_url}")

            # PostgreSQL용 비동기 드라이버 URL로 변경
            if database_url.startswith("postgresql://"):
                database_url = database_url.replace("postgresql://", "postgresql+asyncpg://", 1)

            # 엔진 생성
            self.engine = create_async_engine(
                database_url,
                echo=False,
                pool_pre_ping=True,
                pool_size=5,
                max_overflow=10,
            )

            # AsyncSession 생성기
            self.async_session_maker = async_sessionmaker(
                self.engine, class_=AsyncSession, expire_on_commit=False
            )

            # 연결 테스트
            try:
                async with self.engine.begin() as conn:
                    await conn.run_sync(lambda _: None)
            except Exception as conn_error:
                raise DatabaseError(ErrorCode.DB_002, reason=masked_url) from conn_error

            self._initialized = True
            logger.info("데이터베이스 연결 성공")

        except DatabaseError:
            # DatabaseError는 그대로 전파
            raise
        except Exception as e:
            # 기타 예외는 DatabaseError로 변환 (마이그레이션 관련)
            raise DatabaseError(ErrorCode.DB_003, reason=str(e)) from e

    async def create_tables(self) -> None:
        """모든 테이블 생성"""
        if not self.engine:
            raise DatabaseError(ErrorCode.DB_004)

        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("데이터베이스 테이블 생성 완료")

    async def drop_tables(self) -> None:
        """모든 테이블 삭제 (주의: 개발용)"""
        if not self.engine:
            raise DatabaseError(ErrorCode.DB_005)

        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        logger.info("데이터베이스 테이블 삭제 완료")

    async def close(self) -> None:
        """데이터베이스 연결 종료"""
        if self.engine:
            await self.engine.dispose()
            self._initialized = False
            logger.info("데이터베이스 연결 종료")

    @asynccontextmanager
    async def get_session(self) -> AsyncGenerator[AsyncSession, None]:
        """
        비동기 세션 생성

        사용 예:
            async with db_manager.get_session() as session:
                # 데이터베이스 작업
                pass
        """
        if not self.async_session_maker:
            raise DatabaseError(ErrorCode.DB_006)

        async with self.async_session_maker() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise
            finally:
                await session.close()

    async def get_db_session(self) -> AsyncGenerator[AsyncSession, None]:
        """FastAPI 의존성 주입용 세션 생성기"""
        async with self.get_session() as session:
            yield session


# 싱글톤 인스턴스
db_manager = DatabaseManager()


# FastAPI 의존성 주입용
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI 의존성 주입용 데이터베이스 세션

    사용 예:
        @router.get("/items")
        async def get_items(db: AsyncSession = Depends(get_db)):
            # 데이터베이스 작업
            pass
    """
    async with db_manager.get_session() as session:
        yield session
