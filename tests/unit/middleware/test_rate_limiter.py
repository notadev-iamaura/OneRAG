from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.middleware.rate_limiter import RateLimiter, RateLimitMiddleware


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
