"""
API Routers - FastAPI 라우팅 레이어

Phase 3.3: chat.py에서 추출한 검증된 라우터 모듈
"""

# WebSocket 라우터 (Task 3)
from . import websocket_router
from .admin_router import router as admin_eval_router
from .admin_router import set_config as set_admin_config
from .admin_router import set_session_module  # ✅ Task 5: 세션 모듈 주입
from .chat_router import router as chat_router
from .chat_router import set_chat_service
from .websocket_router import router as websocket_chat_router
from .websocket_router import set_chat_service as set_ws_chat_service
from .websocket_router import ws_manager

__all__ = [
    "chat_router",
    "set_chat_service",
    "admin_eval_router",
    "set_admin_config",
    "set_session_module",  # ✅ Task 5
    # WebSocket (Task 3)
    "websocket_router",
    "websocket_chat_router",
    "set_ws_chat_service",
    "ws_manager",
]
