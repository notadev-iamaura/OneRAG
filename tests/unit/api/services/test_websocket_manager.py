"""
WebSocketManager 단위 테스트

WebSocket 연결 관리자의 핵심 기능을 검증합니다.
- connect/disconnect: 연결 수락 및 해제
- is_connected: 연결 상태 확인
- send_json: JSON 메시지 전송
- broadcast: 모든 연결에 브로드캐스트
"""

from unittest.mock import AsyncMock, patch

import pytest

from app.api.services.websocket_manager import WebSocketManager


class TestWebSocketManagerConnect:
    """WebSocket 연결 관리 테스트"""

    @pytest.fixture
    def manager(self) -> WebSocketManager:
        """WebSocketManager 인스턴스 생성"""
        return WebSocketManager()

    @pytest.fixture
    def mock_websocket(self) -> AsyncMock:
        """Mock WebSocket 객체 생성"""
        ws = AsyncMock()
        ws.accept = AsyncMock()
        ws.send_json = AsyncMock()
        ws.close = AsyncMock()
        return ws

    @pytest.mark.asyncio
    async def test_connect_새_세션_등록(
        self, manager: WebSocketManager, mock_websocket: AsyncMock
    ) -> None:
        """새 세션을 연결하면 WebSocket이 등록되어야 함"""
        # Given
        session_id = "session-001"

        # When
        await manager.connect(session_id, mock_websocket)

        # Then
        assert manager.is_connected(session_id) is True
        mock_websocket.accept.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_connect_중복_세션_덮어쓰기(
        self, manager: WebSocketManager, mock_websocket: AsyncMock
    ) -> None:
        """동일 세션 ID로 재연결하면 기존 연결이 대체되어야 함"""
        # Given
        session_id = "session-001"
        old_websocket = AsyncMock()
        old_websocket.accept = AsyncMock()
        await manager.connect(session_id, old_websocket)

        # When
        new_websocket = AsyncMock()
        new_websocket.accept = AsyncMock()
        await manager.connect(session_id, new_websocket)

        # Then
        assert manager.is_connected(session_id) is True
        # 새 웹소켓이 accept 호출됨
        new_websocket.accept.assert_awaited_once()


class TestWebSocketManagerDisconnect:
    """WebSocket 연결 해제 테스트"""

    @pytest.fixture
    def manager(self) -> WebSocketManager:
        return WebSocketManager()

    @pytest.fixture
    def mock_websocket(self) -> AsyncMock:
        ws = AsyncMock()
        ws.accept = AsyncMock()
        ws.send_json = AsyncMock()
        ws.close = AsyncMock()
        return ws

    @pytest.mark.asyncio
    async def test_disconnect_연결된_세션_해제(
        self, manager: WebSocketManager, mock_websocket: AsyncMock
    ) -> None:
        """연결된 세션을 해제하면 연결 목록에서 제거되어야 함"""
        # Given
        session_id = "session-001"
        await manager.connect(session_id, mock_websocket)
        assert manager.is_connected(session_id) is True

        # When
        manager.disconnect(session_id)

        # Then
        assert manager.is_connected(session_id) is False

    def test_disconnect_존재하지_않는_세션_무시(
        self, manager: WebSocketManager
    ) -> None:
        """존재하지 않는 세션 해제 시 에러 없이 무시"""
        # Given
        session_id = "nonexistent-session"

        # When & Then (예외 없이 통과)
        manager.disconnect(session_id)
        assert manager.is_connected(session_id) is False

    @pytest.mark.asyncio
    async def test_disconnect_재연결_경합_구연결만_해제(
        self, manager: WebSocketManager
    ) -> None:
        """재연결 시 구 연결의 disconnect가 새 연결을 삭제하면 안 됨.

        같은 session_id로 ws_a → ws_b 재연결 후, ws_a의 finally가
        disconnect(session_id, ws_a)를 호출해도 현재 등록된 ws_b는 유지되어야 한다.
        (session_id 키만 보고 삭제하면 새 연결이 사라져 메시지 전송이 누락됨)
        """
        # Given
        session_id = "session-001"
        ws_a = AsyncMock()
        ws_a.accept = AsyncMock()
        ws_b = AsyncMock()
        ws_b.accept = AsyncMock()

        await manager.connect(session_id, ws_a)
        # 재연결: ws_b가 ws_a를 대체
        await manager.connect(session_id, ws_b)

        # When: 구 연결(ws_a)의 finally가 disconnect 호출
        manager.disconnect(session_id, ws_a)

        # Then: 새 연결(ws_b)은 유지되어야 함
        assert manager.is_connected(session_id) is True

    @pytest.mark.asyncio
    async def test_disconnect_현재_연결_웹소켓_일치_시_해제(
        self, manager: WebSocketManager
    ) -> None:
        """현재 등록된 WebSocket과 동일 객체로 disconnect 시 정상 해제되어야 함."""
        # Given
        session_id = "session-001"
        ws = AsyncMock()
        ws.accept = AsyncMock()
        await manager.connect(session_id, ws)

        # When: 동일 WebSocket으로 disconnect
        manager.disconnect(session_id, ws)

        # Then: 해제됨
        assert manager.is_connected(session_id) is False


class TestWebSocketManagerIsConnected:
    """연결 상태 확인 테스트"""

    @pytest.fixture
    def manager(self) -> WebSocketManager:
        return WebSocketManager()

    @pytest.fixture
    def mock_websocket(self) -> AsyncMock:
        ws = AsyncMock()
        ws.accept = AsyncMock()
        return ws

    def test_is_connected_연결되지_않은_세션(
        self, manager: WebSocketManager
    ) -> None:
        """연결되지 않은 세션은 False 반환"""
        assert manager.is_connected("unknown-session") is False

    @pytest.mark.asyncio
    async def test_is_connected_연결된_세션(
        self, manager: WebSocketManager, mock_websocket: AsyncMock
    ) -> None:
        """연결된 세션은 True 반환"""
        # Given
        session_id = "session-001"
        await manager.connect(session_id, mock_websocket)

        # Then
        assert manager.is_connected(session_id) is True


class TestWebSocketManagerSendJson:
    """JSON 메시지 전송 테스트"""

    @pytest.fixture
    def manager(self) -> WebSocketManager:
        return WebSocketManager()

    @pytest.fixture
    def mock_websocket(self) -> AsyncMock:
        ws = AsyncMock()
        ws.accept = AsyncMock()
        ws.send_json = AsyncMock()
        return ws

    @pytest.mark.asyncio
    async def test_send_json_연결된_세션에_전송(
        self, manager: WebSocketManager, mock_websocket: AsyncMock
    ) -> None:
        """연결된 세션에 JSON 메시지를 성공적으로 전송"""
        # Given
        session_id = "session-001"
        await manager.connect(session_id, mock_websocket)
        data = {"type": "message", "content": "Hello, World!"}

        # When
        result = await manager.send_json(session_id, data)

        # Then
        assert result is True
        mock_websocket.send_json.assert_awaited_once_with(data)

    @pytest.mark.asyncio
    async def test_send_json_연결되지_않은_세션_무시(
        self, manager: WebSocketManager
    ) -> None:
        """연결되지 않은 세션에 전송 시 에러 없이 무시하고 False 반환"""
        # Given
        session_id = "nonexistent-session"
        data = {"type": "message", "content": "Hello"}

        # When
        result = await manager.send_json(session_id, data)

        # Then
        assert result is False  # 전송 실패

    @pytest.mark.asyncio
    async def test_send_json_전송_중_예외_발생_시_안전_처리(
        self, manager: WebSocketManager, mock_websocket: AsyncMock
    ) -> None:
        """WebSocket 전송 중 예외 발생 시 연결을 해제하고 False 반환"""
        # Given
        session_id = "session-001"
        await manager.connect(session_id, mock_websocket)
        mock_websocket.send_json.side_effect = Exception("Connection closed")
        data = {"type": "error_test"}

        # When
        result = await manager.send_json(session_id, data)

        # Then
        assert result is False
        # 예외 발생 시 연결 해제
        assert manager.is_connected(session_id) is False


class TestWebSocketManagerBroadcast:
    """브로드캐스트 테스트"""

    @pytest.fixture
    def manager(self) -> WebSocketManager:
        return WebSocketManager()

    def create_mock_websocket(self) -> AsyncMock:
        """Mock WebSocket 생성 헬퍼"""
        ws = AsyncMock()
        ws.accept = AsyncMock()
        ws.send_json = AsyncMock()
        return ws

    @pytest.mark.asyncio
    async def test_broadcast_모든_연결에_전송(
        self, manager: WebSocketManager
    ) -> None:
        """모든 연결된 세션에 메시지 브로드캐스트"""
        # Given
        ws1 = self.create_mock_websocket()
        ws2 = self.create_mock_websocket()
        ws3 = self.create_mock_websocket()

        await manager.connect("session-1", ws1)
        await manager.connect("session-2", ws2)
        await manager.connect("session-3", ws3)

        data = {"type": "broadcast", "content": "Hello, everyone!"}

        # When
        results = await manager.broadcast(data)

        # Then
        assert results["success"] == 3
        assert results["failed"] == 0
        ws1.send_json.assert_awaited_once_with(data)
        ws2.send_json.assert_awaited_once_with(data)
        ws3.send_json.assert_awaited_once_with(data)

    @pytest.mark.asyncio
    async def test_broadcast_일부_실패_처리(
        self, manager: WebSocketManager
    ) -> None:
        """일부 연결 실패 시에도 나머지 연결에 계속 전송"""
        # Given
        ws1 = self.create_mock_websocket()
        ws2 = self.create_mock_websocket()
        ws2.send_json.side_effect = Exception("Connection lost")
        ws3 = self.create_mock_websocket()

        await manager.connect("session-1", ws1)
        await manager.connect("session-2", ws2)
        await manager.connect("session-3", ws3)

        data = {"type": "broadcast", "content": "Test message"}

        # When
        results = await manager.broadcast(data)

        # Then
        assert results["success"] == 2
        assert results["failed"] == 1
        # 실패한 연결은 제거됨
        assert manager.is_connected("session-2") is False

    @pytest.mark.asyncio
    async def test_broadcast_연결_없을_때(
        self, manager: WebSocketManager
    ) -> None:
        """연결이 없을 때 브로드캐스트는 빈 결과 반환"""
        # Given
        data = {"type": "broadcast", "content": "No one to receive"}

        # When
        results = await manager.broadcast(data)

        # Then
        assert results["success"] == 0
        assert results["failed"] == 0


class TestWebSocketManagerConnectionCount:
    """연결 수 확인 테스트"""

    @pytest.fixture
    def manager(self) -> WebSocketManager:
        return WebSocketManager()

    def create_mock_websocket(self) -> AsyncMock:
        ws = AsyncMock()
        ws.accept = AsyncMock()
        return ws

    def test_connection_count_초기값(self, manager: WebSocketManager) -> None:
        """초기 연결 수는 0"""
        assert manager.connection_count == 0

    @pytest.mark.asyncio
    async def test_connection_count_연결_추가(
        self, manager: WebSocketManager
    ) -> None:
        """연결 추가 시 카운트 증가"""
        ws1 = self.create_mock_websocket()
        ws2 = self.create_mock_websocket()

        await manager.connect("session-1", ws1)
        assert manager.connection_count == 1

        await manager.connect("session-2", ws2)
        assert manager.connection_count == 2

    @pytest.mark.asyncio
    async def test_connection_count_연결_해제(
        self, manager: WebSocketManager
    ) -> None:
        """연결 해제 시 카운트 감소"""
        ws1 = self.create_mock_websocket()
        await manager.connect("session-1", ws1)
        assert manager.connection_count == 1

        manager.disconnect("session-1")
        assert manager.connection_count == 0


class TestWebSocketManagerLogging:
    """로깅 테스트"""

    @pytest.fixture
    def manager(self) -> WebSocketManager:
        return WebSocketManager()

    @pytest.fixture
    def mock_websocket(self) -> AsyncMock:
        ws = AsyncMock()
        ws.accept = AsyncMock()
        ws.send_json = AsyncMock()
        return ws

    @pytest.mark.asyncio
    async def test_connect_로깅_호출(
        self, manager: WebSocketManager, mock_websocket: AsyncMock
    ) -> None:
        """연결 시 로그가 기록되어야 함"""
        session_id = "session-001"

        with patch.object(manager, "_logger") as mock_logger:
            await manager.connect(session_id, mock_websocket)
            # info 레벨 로그 호출 확인
            mock_logger.info.assert_called()

    @pytest.mark.asyncio
    async def test_disconnect_로깅_호출(
        self, manager: WebSocketManager, mock_websocket: AsyncMock
    ) -> None:
        """연결 해제 시 로그가 기록되어야 함"""
        session_id = "session-001"
        await manager.connect(session_id, mock_websocket)

        with patch.object(manager, "_logger") as mock_logger:
            manager.disconnect(session_id)
            mock_logger.info.assert_called()
