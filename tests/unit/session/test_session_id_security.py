"""
세션 ID capability 보안 테스트 (Phase 1.2 — IDOR 방어)

목적:
    클라이언트가 추측 가능한 약한 session_id("admin", "user1" 등)를 지정해
    세션을 만들지 못하도록 강제한다. session_id가 항상 추측 불가능한 UUID4가
    되면, session_id를 아는 것 자체가 capability(접근 권한)가 되어 IDOR
    (다른 사용자 세션 무단 조회/삭제)을 실질적으로 차단한다.
"""

from __future__ import annotations

from uuid import UUID

import pytest

from app.modules.core.session.services.session_service import SessionService


def _is_uuid4(value: str) -> bool:
    try:
        return UUID(value).version == 4
    except (ValueError, TypeError, AttributeError):
        return False


@pytest.fixture
def service() -> SessionService:
    # 최소 설정으로 생성 (TTL 등 기본값 사용)
    return SessionService(config={"session": {}})


@pytest.mark.asyncio
async def test_weak_client_session_id_is_rejected(service: SessionService) -> None:
    """추측 가능한 약한 session_id는 거부되고 서버 UUID4로 대체돼야 한다."""
    result = await service.create_session(session_id="admin")
    issued = result["session_id"]
    assert issued != "admin", "약한 클라이언트 지정 ID가 그대로 수용됨 (IDOR 위험)"
    assert _is_uuid4(issued), f"발급된 세션 ID가 UUID4가 아님: {issued}"


@pytest.mark.asyncio
async def test_none_session_id_gets_server_uuid(service: SessionService) -> None:
    """session_id 미지정 시 서버가 UUID4를 발급해야 한다."""
    result = await service.create_session(session_id=None)
    assert _is_uuid4(result["session_id"])


@pytest.mark.asyncio
async def test_valid_uuid_client_id_is_accepted(service: SessionService) -> None:
    """유효한 UUID4 형식의 클라이언트 ID는 그대로 수용된다 (세션 복원)."""
    valid = "550e8400-e29b-41d4-a716-446655440000"
    result = await service.create_session(session_id=valid)
    assert result["session_id"] == valid
