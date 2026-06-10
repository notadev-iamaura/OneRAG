"""
WebSocket 연결 관리자

세션별 WebSocket 연결을 관리하는 매니저 클래스입니다.
- 연결 수락 및 등록 (connect)
- 연결 해제 (disconnect)
- 연결 상태 확인 (is_connected)
- JSON 메시지 전송 (send_json)
- 브로드캐스트 (broadcast)

사용 예시:
    manager = WebSocketManager()
    await manager.connect(session_id, websocket)
    await manager.send_json(session_id, {"type": "message", "content": "Hello"})
    manager.disconnect(session_id, websocket)
"""

from typing import Any

from fastapi import WebSocket

from app.lib.logger import get_logger


class WebSocketManager:
    """
    WebSocket 연결 관리자

    세션 ID를 키로 WebSocket 연결을 관리합니다.
    스레드 안전하지 않으므로 단일 이벤트 루프에서 사용해야 합니다.
    """

    def __init__(self) -> None:
        """WebSocketManager 초기화"""
        self._connections: dict[str, WebSocket] = {}
        self._logger = get_logger(__name__)

    async def connect(self, session_id: str, websocket: WebSocket) -> None:
        """
        WebSocket 연결을 수락하고 등록합니다.

        Args:
            session_id: 세션 식별자
            websocket: FastAPI WebSocket 객체

        Note:
            동일 session_id로 재연결 시 기존 연결이 대체됩니다.
        """
        # 웹소켓 연결 수락
        await websocket.accept()

        # 기존 연결이 있으면 덮어쓰기 (로그만 남김)
        if session_id in self._connections:
            self._logger.info(
                "WebSocket 재연결",
                session_id=session_id,
                action="reconnect",
            )

        # 연결 등록
        self._connections[session_id] = websocket

        self._logger.info(
            "WebSocket 연결됨",
            session_id=session_id,
            total_connections=len(self._connections),
        )

    def disconnect(self, session_id: str, websocket: WebSocket | None = None) -> None:
        """
        WebSocket 연결을 해제합니다.

        Args:
            session_id: 세션 식별자
            websocket: 해제하려는 WebSocket 객체. 지정 시 현재 등록된 연결과
                동일 객체일 때만 삭제합니다(재연결 경합 방지).
                None이면 session_id 기준으로 무조건 삭제합니다(하위 호환).

        Note:
            존재하지 않는 세션 ID에 대해서는 무시합니다.
            재연결 경합 방지: 같은 session_id로 새 연결(ws_b)이 등록된 뒤
            구 연결(ws_a)의 finally가 disconnect를 호출해도, websocket 인자가
            현재 등록된 연결과 다르면 삭제하지 않아 새 연결이 보존됩니다.
        """
        current = self._connections.get(session_id)
        if current is None:
            return

        # websocket이 지정되었는데 현재 등록된 연결과 다르면 삭제하지 않음
        # (재연결로 이미 새 연결이 등록된 상황 → 구 연결 정리 요청은 무시)
        if websocket is not None and current is not websocket:
            self._logger.debug(
                "WebSocket 연결 해제 스킵: 이미 다른 연결로 대체됨",
                session_id=session_id,
                action="stale_disconnect_ignored",
            )
            return

        del self._connections[session_id]
        self._logger.info(
            "WebSocket 연결 해제됨",
            session_id=session_id,
            total_connections=len(self._connections),
        )

    def is_connected(self, session_id: str) -> bool:
        """
        세션의 연결 상태를 확인합니다.

        Args:
            session_id: 세션 식별자

        Returns:
            연결되어 있으면 True, 아니면 False
        """
        return session_id in self._connections

    async def send_json(self, session_id: str, data: dict[str, Any]) -> bool:
        """
        특정 세션에 JSON 메시지를 전송합니다.

        Args:
            session_id: 세션 식별자
            data: 전송할 JSON 데이터

        Returns:
            전송 성공 시 True, 실패 시 False

        Note:
            연결되지 않은 세션에 전송 시 False를 반환합니다.
            전송 중 예외 발생 시 연결을 해제하고 False를 반환합니다.
        """
        if not self.is_connected(session_id):
            self._logger.debug(
                "WebSocket 전송 실패: 연결되지 않은 세션",
                session_id=session_id,
            )
            return False

        websocket = self._connections[session_id]

        try:
            await websocket.send_json(data)
            return True
        except Exception as e:
            self._logger.warning(
                "WebSocket 전송 실패",
                session_id=session_id,
                error=str(e),
            )
            # 연결 해제 (전송 대상 websocket과 동일할 때만 삭제 → 재연결 경합 방지)
            self.disconnect(session_id, websocket)
            return False

    async def broadcast(self, data: dict[str, Any]) -> dict[str, int]:
        """
        모든 연결된 세션에 메시지를 브로드캐스트합니다.

        Args:
            data: 전송할 JSON 데이터

        Returns:
            전송 결과 {"success": 성공 수, "failed": 실패 수}

        Note:
            일부 연결 실패 시에도 나머지 연결에 계속 전송합니다.
            실패한 연결은 자동으로 해제됩니다.
        """
        success_count = 0
        failed_count = 0

        # 연결 목록을 복사하여 순회 중 변경 방지
        session_ids = list(self._connections.keys())

        for session_id in session_ids:
            result = await self.send_json(session_id, data)
            if result:
                success_count += 1
            else:
                failed_count += 1

        self._logger.info(
            "WebSocket 브로드캐스트 완료",
            success=success_count,
            failed=failed_count,
            total_connections=len(self._connections),
        )

        return {"success": success_count, "failed": failed_count}

    @property
    def connection_count(self) -> int:
        """
        현재 연결 수를 반환합니다.

        Returns:
            연결된 세션 수
        """
        return len(self._connections)
