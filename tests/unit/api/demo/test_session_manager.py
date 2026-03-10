"""
DemoSessionManager 단위 테스트

세션 생성/조회/삭제, TTL 만료, LRU 퇴거, 통계를 검증합니다.
"""

import asyncio
from unittest.mock import MagicMock

import pytest

from app.api.demo.session_manager import (
    DEFAULT_MAX_DOCS_PER_SESSION,
    DEFAULT_MAX_SESSIONS,
    DEFAULT_TTL_SECONDS,
    DemoSession,
    DemoSessionManager,
    DemoStats,
)

# =============================================================================
# 픽스처
# =============================================================================


@pytest.fixture
def mock_chroma_client() -> MagicMock:
    """인메모리 ChromaDB 클라이언트 Mock"""
    client = MagicMock()
    client.delete_collection = MagicMock()
    return client


@pytest.fixture
def manager(mock_chroma_client: MagicMock) -> DemoSessionManager:
    """기본 설정 DemoSessionManager"""
    return DemoSessionManager(
        chroma_client=mock_chroma_client,
        max_sessions=5,
        ttl_seconds=60,
        cleanup_interval=10,
    )


@pytest.fixture
def small_manager(mock_chroma_client: MagicMock) -> DemoSessionManager:
    """세션 제한 3개, TTL 1초인 작은 매니저"""
    return DemoSessionManager(
        chroma_client=mock_chroma_client,
        max_sessions=3,
        ttl_seconds=1,
        cleanup_interval=1,
    )


# =============================================================================
# 초기화 테스트
# =============================================================================


class TestInitialization:
    """초기화 관련 테스트"""

    def test_기본_설정값(self, mock_chroma_client: MagicMock) -> None:
        """기본 설정값이 올바르게 적용되는지 확인"""
        mgr = DemoSessionManager(chroma_client=mock_chroma_client)
        assert mgr.max_sessions == DEFAULT_MAX_SESSIONS
        assert mgr.ttl_seconds == DEFAULT_TTL_SECONDS
        assert mgr.max_docs_per_session == DEFAULT_MAX_DOCS_PER_SESSION
        assert mgr.active_session_count == 0

    def test_커스텀_설정값(self, manager: DemoSessionManager) -> None:
        """커스텀 설정값이 올바르게 적용되는지 확인"""
        assert manager.max_sessions == 5
        assert manager.ttl_seconds == 60


# =============================================================================
# 세션 생성 테스트
# =============================================================================


class TestCreateSession:
    """세션 생성 관련 테스트"""

    @pytest.mark.asyncio
    async def test_세션_생성_성공(self, manager: DemoSessionManager) -> None:
        """세션이 정상적으로 생성되는지 확인"""
        session = await manager.create_session()

        assert isinstance(session, DemoSession)
        assert len(session.session_id) == 16
        assert session.collection_name.startswith("demo_")
        assert session.document_count == 0
        assert session.is_sample is False
        assert manager.active_session_count == 1

    @pytest.mark.asyncio
    async def test_샘플_세션_생성(self, manager: DemoSessionManager) -> None:
        """샘플 데이터 세션이 올바르게 표시되는지 확인"""
        session = await manager.create_session(is_sample=True)
        assert session.is_sample is True

    @pytest.mark.asyncio
    async def test_여러_세션_생성(self, manager: DemoSessionManager) -> None:
        """여러 세션이 독립적으로 생성되는지 확인"""
        sessions = [await manager.create_session() for _ in range(3)]

        assert manager.active_session_count == 3
        ids = {s.session_id for s in sessions}
        assert len(ids) == 3  # 모두 고유 ID

    @pytest.mark.asyncio
    async def test_세션_수_제한_초과시_LRU_퇴거(
        self, small_manager: DemoSessionManager
    ) -> None:
        """최대 세션 수 초과 시 가장 오래된 세션이 퇴거되는지 확인"""
        s1 = await small_manager.create_session()
        s2 = await small_manager.create_session()
        s3 = await small_manager.create_session()
        assert small_manager.active_session_count == 3

        # 4번째 세션 생성 → s1 퇴거
        _s4 = await small_manager.create_session()
        assert small_manager.active_session_count == 3
        assert await small_manager.get_session(s1.session_id) is None
        assert await small_manager.get_session(s2.session_id) is not None
        assert await small_manager.get_session(s3.session_id) is not None


# =============================================================================
# 세션 조회 테스트
# =============================================================================


class TestGetSession:
    """세션 조회 관련 테스트"""

    @pytest.mark.asyncio
    async def test_세션_조회_성공(self, manager: DemoSessionManager) -> None:
        """존재하는 세션을 조회하면 반환되는지 확인"""
        created = await manager.create_session()
        fetched = await manager.get_session(created.session_id)

        assert fetched is not None
        assert fetched.session_id == created.session_id

    @pytest.mark.asyncio
    async def test_존재하지_않는_세션_조회(self, manager: DemoSessionManager) -> None:
        """존재하지 않는 세션 ID로 조회하면 None 반환"""
        result = await manager.get_session("nonexistent_id")
        assert result is None

    @pytest.mark.asyncio
    async def test_조회시_last_accessed_갱신(
        self, manager: DemoSessionManager
    ) -> None:
        """조회 시 last_accessed가 갱신되는지 확인"""
        session = await manager.create_session()
        original_time = session.last_accessed

        await asyncio.sleep(0.01)
        fetched = await manager.get_session(session.session_id)

        assert fetched is not None
        assert fetched.last_accessed > original_time

    @pytest.mark.asyncio
    async def test_만료된_세션_조회시_None(
        self, small_manager: DemoSessionManager
    ) -> None:
        """TTL 만료된 세션 조회 시 None 반환 + 자동 삭제"""
        session = await small_manager.create_session()

        # TTL(1초) 대기
        await asyncio.sleep(1.1)
        result = await small_manager.get_session(session.session_id)

        assert result is None
        assert small_manager.active_session_count == 0


# =============================================================================
# 세션 삭제 테스트
# =============================================================================


class TestDeleteSession:
    """세션 삭제 관련 테스트"""

    @pytest.mark.asyncio
    async def test_세션_삭제_성공(
        self, manager: DemoSessionManager, mock_chroma_client: MagicMock
    ) -> None:
        """세션 삭제 시 ChromaDB 컬렉션도 함께 삭제"""
        session = await manager.create_session()
        result = await manager.delete_session(session.session_id)

        assert result is True
        assert manager.active_session_count == 0
        mock_chroma_client.delete_collection.assert_called_with(
            session.collection_name
        )

    @pytest.mark.asyncio
    async def test_존재하지_않는_세션_삭제(self, manager: DemoSessionManager) -> None:
        """존재하지 않는 세션 삭제 시 False 반환"""
        result = await manager.delete_session("nonexistent_id")
        assert result is False

    @pytest.mark.asyncio
    async def test_컬렉션_삭제_실패해도_세션은_제거(
        self, manager: DemoSessionManager, mock_chroma_client: MagicMock
    ) -> None:
        """ChromaDB 컬렉션 삭제 실패해도 세션은 정상 제거"""
        mock_chroma_client.delete_collection.side_effect = Exception("Chroma 오류")

        session = await manager.create_session()
        result = await manager.delete_session(session.session_id)

        assert result is True
        assert manager.active_session_count == 0


# =============================================================================
# 문서 카운터 테스트
# =============================================================================


class TestDocumentCounter:
    """문서 카운터 관련 테스트"""

    @pytest.mark.asyncio
    async def test_문서_카운트_증가(self, manager: DemoSessionManager) -> None:
        """문서 카운트가 정상적으로 증가하는지 확인"""
        session = await manager.create_session()
        result = await manager.increment_document_count(
            session.session_id, "test.pdf", 10
        )

        assert result is True
        updated = await manager.get_session(session.session_id)
        assert updated is not None
        assert updated.document_count == 1
        assert updated.total_chunks == 10
        assert "test.pdf" in updated.document_names

    @pytest.mark.asyncio
    async def test_문서_수_제한_초과(self, manager: DemoSessionManager) -> None:
        """세션당 최대 문서 수 초과 시 False 반환"""
        session = await manager.create_session()

        for i in range(manager.max_docs_per_session):
            result = await manager.increment_document_count(
                session.session_id, f"doc_{i}.pdf"
            )
            assert result is True

        # 제한 초과
        result = await manager.increment_document_count(
            session.session_id, "extra.pdf"
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_존재하지_않는_세션에_문서_추가(
        self, manager: DemoSessionManager
    ) -> None:
        """존재하지 않는 세션에 문서 추가 시 False 반환"""
        result = await manager.increment_document_count(
            "nonexistent", "test.pdf"
        )
        assert result is False


# =============================================================================
# TTL 만료 및 정리 테스트
# =============================================================================


class TestCleanup:
    """세션 정리 관련 테스트"""

    @pytest.mark.asyncio
    async def test_만료_세션_정리(self, small_manager: DemoSessionManager) -> None:
        """cleanup_expired()가 만료된 세션만 정리하는지 확인"""
        _s1 = await small_manager.create_session()
        await asyncio.sleep(1.1)  # TTL(1초) 대기

        # 새 세션은 만료되지 않음
        s2 = await small_manager.create_session()

        cleaned = await small_manager.cleanup_expired()
        assert cleaned == 1
        assert small_manager.active_session_count == 1
        assert await small_manager.get_session(s2.session_id) is not None

    @pytest.mark.asyncio
    async def test_만료_세션_없을때_정리(self, manager: DemoSessionManager) -> None:
        """만료된 세션이 없으면 0 반환"""
        await manager.create_session()
        cleaned = await manager.cleanup_expired()
        assert cleaned == 0

    @pytest.mark.asyncio
    async def test_LRU_퇴거시_샘플_세션_보호(
        self, small_manager: DemoSessionManager
    ) -> None:
        """LRU 퇴거 시 샘플 세션은 일반 세션보다 우선 보호"""
        sample = await small_manager.create_session(is_sample=True)
        s2 = await small_manager.create_session()
        _s3 = await small_manager.create_session()

        # 4번째 세션 → 일반 세션 중 가장 오래된 s2 퇴거 (sample 보호)
        _s4 = await small_manager.create_session()

        assert await small_manager.get_session(sample.session_id) is not None
        assert await small_manager.get_session(s2.session_id) is None


# =============================================================================
# 정리 루프 테스트
# =============================================================================


class TestCleanupLoop:
    """정리 루프 관련 테스트"""

    @pytest.mark.asyncio
    async def test_정리_루프_시작_중지(self, manager: DemoSessionManager) -> None:
        """정리 루프가 정상적으로 시작/중지되는지 확인"""
        await manager.start_cleanup_loop()
        assert manager._cleanup_task is not None

        await manager.stop_cleanup_loop()
        assert manager._cleanup_task is None

    @pytest.mark.asyncio
    async def test_중복_시작_방지(self, manager: DemoSessionManager) -> None:
        """이미 시작된 정리 루프를 다시 시작해도 중복 생성 안 됨"""
        await manager.start_cleanup_loop()
        first_task = manager._cleanup_task

        await manager.start_cleanup_loop()
        assert manager._cleanup_task is first_task

        await manager.stop_cleanup_loop()


# =============================================================================
# 통계 테스트
# =============================================================================


class TestStats:
    """통계 관련 테스트"""

    @pytest.mark.asyncio
    async def test_통계_반환(self, manager: DemoSessionManager) -> None:
        """get_stats()가 올바른 통계를 반환하는지 확인"""
        await manager.create_session()
        await manager.create_session()

        stats = await manager.get_stats()
        assert isinstance(stats, DemoStats)
        assert stats.active_sessions == 2
        assert stats.max_sessions == 5
        assert stats.ttl_seconds == 60
        assert stats.total_sessions_created == 2
        assert stats.total_sessions_expired == 0
        assert stats.daily_api_calls == 0
        assert stats.daily_api_limit == 500

    @pytest.mark.asyncio
    async def test_일일_API_호출_예산(self, manager: DemoSessionManager) -> None:
        """일일 API 호출 예산이 올바르게 작동하는지 확인"""
        # 기본 상한: 500 (DEFAULT_DAILY_API_LIMIT)
        assert manager.daily_api_limit == 500

        # 호출 허용
        assert await manager.check_and_increment_api_calls(count=1) is True
        assert manager.daily_api_calls == 1

        # 여러 건 증가
        assert await manager.check_and_increment_api_calls(count=2) is True
        assert manager.daily_api_calls == 3

    @pytest.mark.asyncio
    async def test_일일_API_호출_상한_초과(
        self, mock_chroma_client: MagicMock
    ) -> None:
        """일일 API 호출 상한 초과 시 False 반환"""
        mgr = DemoSessionManager(
            chroma_client=mock_chroma_client,
            daily_api_limit=5,
        )

        # 4건 사용 → 남은 1건
        assert await mgr.check_and_increment_api_calls(count=4) is True
        # 2건 요청 → 상한 초과
        assert await mgr.check_and_increment_api_calls(count=2) is False
        # 1건 요청 → 정확히 상한
        assert await mgr.check_and_increment_api_calls(count=1) is True
        # 추가 요청 → 초과
        assert await mgr.check_and_increment_api_calls(count=1) is False

    @pytest.mark.asyncio
    async def test_일일_API_무제한(
        self, mock_chroma_client: MagicMock
    ) -> None:
        """daily_api_limit=0이면 무제한"""
        mgr = DemoSessionManager(
            chroma_client=mock_chroma_client,
            daily_api_limit=0,
        )
        assert await mgr.check_and_increment_api_calls(count=10000) is True

    @pytest.mark.asyncio
    async def test_세션_TTL_남은시간(self, manager: DemoSessionManager) -> None:
        """get_session_ttl_remaining()이 올바른 남은 시간을 반환하는지 확인"""
        session = await manager.create_session()

        remaining = await manager.get_session_ttl_remaining(session.session_id)
        assert remaining is not None
        assert 59.0 <= remaining <= 60.0

    @pytest.mark.asyncio
    async def test_존재하지_않는_세션_TTL(self, manager: DemoSessionManager) -> None:
        """존재하지 않는 세션의 TTL은 None"""
        assert await manager.get_session_ttl_remaining("nonexistent") is None


# =============================================================================
# 세션 정보 조회 테스트
# =============================================================================


class TestGetSessionInfo:
    """get_session_info() 관련 테스트"""

    @pytest.mark.asyncio
    async def test_get_session_info_returns_info(
        self, manager: DemoSessionManager
    ) -> None:
        """정상 세션의 정보가 올바른 형식으로 반환되는지 확인"""
        session = await manager.create_session()
        info = await manager.get_session_info(session.session_id)

        assert info is not None
        assert info["session_id"] == session.session_id
        assert isinstance(info["created_at"], str)
        assert isinstance(info["last_activity"], str)
        assert info["message_count"] == 0

        # ISO 형식 검증 (파싱 가능해야 함)
        from datetime import datetime

        datetime.fromisoformat(info["created_at"])
        datetime.fromisoformat(info["last_activity"])

    @pytest.mark.asyncio
    async def test_get_session_info_nonexistent(
        self, manager: DemoSessionManager
    ) -> None:
        """미존재 세션에서 None 반환"""
        info = await manager.get_session_info("nonexistent_session_id")
        assert info is None

    @pytest.mark.asyncio
    async def test_get_session_info_expired(
        self, small_manager: DemoSessionManager
    ) -> None:
        """TTL 만료된 세션에서 None 반환"""
        session = await small_manager.create_session()

        # TTL(1초) 대기
        await asyncio.sleep(1.1)
        info = await small_manager.get_session_info(session.session_id)

        assert info is None
