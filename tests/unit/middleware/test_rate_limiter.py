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


@pytest.mark.asyncio
async def test_session_remaining_respects_override_limit() -> None:
    """override_session_limit 적용 시 remaining도 override 기준으로 계산되어야 함.

    limit 초과 판정은 active_session_limit(override 반영)을 쓰면서
    remaining 계산만 기본 session_limit을 쓰면, override가 기본값과 다를 때
    X-RateLimit-Remaining 헤더에 음수/오류 값이 노출된다.
    """
    limiter = RateLimiter(ip_limit=30, session_limit=10, window_seconds=60)

    # 첫 요청: override=3 기준 remaining = 3 - 1 = 2 (버그 시 10 - 1 = 9)
    allowed, limit_type, remaining = await limiter.check_rate_limit(
        ip=None, session_id="override-session", override_session_limit=3
    )
    assert allowed is True
    assert limit_type == "session"
    assert remaining == 2

    # 두 번째 요청: remaining = 3 - 2 = 1
    allowed, _, remaining = await limiter.check_rate_limit(
        ip=None, session_id="override-session", override_session_limit=3
    )
    assert allowed is True
    assert remaining == 1

    # 세 번째 요청: 한도 도달 직전 마지막 허용, remaining = 0 (버그 시 7 등 오값)
    allowed, _, remaining = await limiter.check_rate_limit(
        ip=None, session_id="override-session", override_session_limit=3
    )
    assert allowed is True
    assert remaining == 0

    # 네 번째 요청: override 한도(3) 초과로 거부
    allowed, _, remaining = await limiter.check_rate_limit(
        ip=None, session_id="override-session", override_session_limit=3
    )
    assert allowed is False
    assert remaining == 0


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


# ---------------------------------------------------------------------------
# 신뢰 프록시 정책: X-Forwarded-For 스푸핑으로 IP 레이트리밋을 우회할 수 없어야 한다
# ---------------------------------------------------------------------------


def _build_limited_app(ip_limit: int, trusted_proxy_policy):
    """IP 한도가 작은 앱을 만들어 몇 번의 요청으로 429를 재현한다."""
    from app.lib.client_ip import TrustedProxyPolicy  # noqa: F401 (타입 참고용)

    limiter = RateLimiter(ip_limit=ip_limit, session_limit=100, window_seconds=60)
    app = FastAPI()
    app.add_middleware(
        RateLimitMiddleware,
        rate_limiter=limiter,
        excluded_paths=[],
        trusted_proxy_policy=trusted_proxy_policy,
    )

    @app.get("/ping")
    async def ping() -> dict[str, str]:
        return {"ok": "pong"}

    return app


def test_forwarded_for_spoofing_cannot_bypass_ip_limit() -> None:
    """peer(testclient)가 신뢰 프록시가 아니면 매 요청 다른 XFF를 보내도 한 IP로 집계된다."""
    from app.lib.client_ip import TrustedProxyPolicy

    app = _build_limited_app(ip_limit=2, trusted_proxy_policy=TrustedProxyPolicy.none())
    client = TestClient(app)

    statuses = [
        client.get("/ping", headers={"X-Forwarded-For": f"203.0.113.{i}"}).status_code
        for i in range(1, 5)
    ]
    # 2건 허용 후 3번째부터 429 — 헤더 변경이 새 IP로 인정되지 않는다
    assert statuses == [200, 200, 429, 429]


def test_trusted_proxy_forwarded_for_separates_clients() -> None:
    """peer가 신뢰 프록시면 XFF의 클라이언트 주소별로 따로 집계된다."""
    from app.lib.client_ip import TrustedProxyPolicy

    app = _build_limited_app(ip_limit=1, trusted_proxy_policy=TrustedProxyPolicy.all())
    client = TestClient(app)

    first = client.get("/ping", headers={"X-Forwarded-For": "198.51.100.1"}).status_code
    second = client.get("/ping", headers={"X-Forwarded-For": "198.51.100.2"}).status_code
    repeat = client.get("/ping", headers={"X-Forwarded-For": "198.51.100.1"}).status_code
    assert (first, second, repeat) == (200, 200, 429)


def test_chat_rate_limit_middleware_ignores_spoofed_headers() -> None:
    """ChatRateLimitMiddleware도 같은 신뢰 프록시 규칙을 따른다."""
    from app.lib.client_ip import TrustedProxyPolicy
    from app.middleware.rate_limiter import ChatRateLimitMiddleware

    limiter = RateLimiter(ip_limit=100, session_limit=100, window_seconds=60)
    app = FastAPI()
    app.add_middleware(
        ChatRateLimitMiddleware,
        rate_limiter=limiter,
        ip_limit=1,
        session_limit=100,
        trusted_proxy_policy=TrustedProxyPolicy.none(),
    )

    @app.post("/api/chat")
    async def chat() -> dict[str, str]:
        return {"ok": "chat"}

    client = TestClient(app)
    first = client.post("/api/chat", headers={"X-Forwarded-For": "1.1.1.1"}).status_code
    second = client.post("/api/chat", headers={"X-Forwarded-For": "2.2.2.2"}).status_code
    assert (first, second) == (200, 429)
