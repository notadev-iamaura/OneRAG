import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.middleware.rate_limiter import RateLimiter, RateLimitMiddleware


@pytest.mark.asyncio
async def test_check_rate_limit_returns_tuple_when_session_tracking_full() -> None:
    """추적 세션 수가 한도에 도달해도 None이 아닌 (allowed, type, remaining) 튜플을 반환해야 함.

    ip=None이고 새 session_id가 들어올 때 session_requests가 max_tracked_sessions에
    도달하면, if/elif 구조 결함으로 함수가 return 없이 None을 반환했다.
    미들웨어의 `allowed, limit_type, remaining = ...` 언패킹에서 TypeError를 유발한다.
    """
    limiter = RateLimiter(ip_limit=30, session_limit=10, window_seconds=60)
    # 추적 한도를 1로 낮추고 이미 다른 세션이 추적 중인 상태를 만든다
    limiter.max_tracked_sessions = 1
    limiter.session_requests["existing-session"].append((0.0, 1))

    # When: ip 없이 새 세션으로 호출 (추적 한도 도달 상태)
    result = await limiter.check_rate_limit(ip=None, session_id="new-session")

    # Then: None이 아니라 3-튜플을 반환해야 함
    assert result is not None
    allowed, limit_type, remaining = result
    assert isinstance(allowed, bool)
    assert isinstance(limit_type, str)
    assert isinstance(remaining, int)


def test_rate_limit_middleware_replays_post_body_without_session_id() -> None:
    app = FastAPI()
    app.add_middleware(
        RateLimitMiddleware,
        rate_limiter=RateLimiter(ip_limit=10, session_limit=10, window_seconds=60),
        excluded_paths=[],
    )

    @app.post("/ingest")
    async def ingest(request: Request) -> dict[str, str]:
        payload = await request.json()
        return {
            "database_id": payload["database_id"],
            "category_name": payload["category_name"],
        }

    with TestClient(app) as client:
        response = client.post(
            "/ingest",
            json={"database_id": "test-db", "category_name": "test-category"},
        )

    assert response.status_code == 200
    assert response.json() == {
        "database_id": "test-db",
        "category_name": "test-category",
    }


def test_rate_limit_middleware_replays_post_body_with_session_id() -> None:
    app = FastAPI()
    app.add_middleware(
        RateLimitMiddleware,
        rate_limiter=RateLimiter(ip_limit=10, session_limit=10, window_seconds=60),
        excluded_paths=[],
    )

    @app.post("/chat-like")
    async def chat_like(request: Request) -> dict[str, str]:
        payload = await request.json()
        return {
            "session_id": payload["session_id"],
            "message": payload["message"],
        }

    with TestClient(app) as client:
        response = client.post(
            "/chat-like",
            json={"session_id": "session-1", "message": "hello"},
        )

    assert response.status_code == 200
    assert response.json() == {"session_id": "session-1", "message": "hello"}
