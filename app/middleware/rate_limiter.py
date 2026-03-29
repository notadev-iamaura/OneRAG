"""
Rate Limiting Middleware for FastAPI

IP 기반과 Session 기반 Rate Limiting을 제공합니다.
- IP 기반: 분당 30개 요청
- Session 기반: 분당 10개 요청 (IP를 알 수 없을 때 fallback)
"""

import asyncio
import time
from collections import defaultdict
from collections.abc import Callable
from typing import Any, cast

from fastapi import Request, Response, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.lib.logger import get_logger

logger = get_logger(__name__)


class RateLimiter:
    """
    Rate Limiting 로직을 담당하는 클래스

    시간 윈도우 기반 Rate Limiting 구현:
    - 각 IP/Session에 대해 (timestamp, count) 리스트 유지
    - 현재 시간 기준 60초 이내의 요청만 카운트
    """

    def __init__(
        self,
        ip_limit: int = 30,  # IP 기반: 분당 30개
        session_limit: int = 10,  # Session 기반: 분당 10개
        window_seconds: int = 60,  # 시간 윈도우: 60초
    ):
        self.ip_limit = ip_limit
        self.session_limit = session_limit
        self.window_seconds = window_seconds

        # IP별 요청 기록: {ip: [(timestamp, count), ...]}
        self.ip_requests: dict[str, list] = defaultdict(list)

        # Session별 요청 기록: {session_id: [(timestamp, count), ...]}
        self.session_requests: dict[str, list] = defaultdict(list)

        # 🛡️ 메모리 보호: 최대 추적 IP/Session 제한 (DDoS 방어)
        self.max_tracked_ips = 10000  # 최대 1만 IP 추적
        self.max_tracked_sessions = 50000  # 최대 5만 세션 추적

        # Asyncio Lock (FastAPI는 async 기반이므로 asyncio.Lock 사용)
        self.lock = asyncio.Lock()

        # 🔄 Background Cleanup Task (24시간 주기)
        self._cleanup_task: asyncio.Task | None = None
        self._cleanup_interval = 86400  # 24시간 (초)
        self._grace_period = 60  # 정리 안전 마진 (초)

        logger.info(
            f"RateLimiter 초기화: IP={ip_limit}/min, Session={session_limit}/min, Window={window_seconds}s, "
            f"Cleanup={self._cleanup_interval}s"
        )

    def _clean_old_requests(self, request_list: list, current_time: float) -> None:
        """
        현재 시간 기준으로 window_seconds 이전의 요청 제거

        Args:
            request_list: [(timestamp, count), ...] 형태의 요청 기록 리스트
            current_time: 현재 시간 (Unix timestamp)
        """
        cutoff_time = current_time - self.window_seconds

        # 오래된 요청 제거 (in-place modification)
        while request_list and request_list[0][0] < cutoff_time:
            request_list.pop(0)

    def _get_request_count(self, request_list: list) -> int:
        """
        현재 윈도우 내의 총 요청 수 계산

        Args:
            request_list: [(timestamp, count), ...] 형태의 요청 기록 리스트

        Returns:
            int: 현재 윈도우 내의 총 요청 수
        """
        return sum(count for _, count in request_list)

    async def check_rate_limit(
        self,
        ip: str | None = None,
        session_id: str | None = None,
        override_ip_limit: int | None = None,
        override_session_limit: int | None = None,
    ) -> tuple[bool, str, int]:
        """
        Rate Limit 체크

        우선순위:
        1. IP가 있으면 IP 기반 체크 (30 req/min)
        2. IP가 없으면 Session 기반 체크 (10 req/min)

        Args:
            ip: 클라이언트 IP 주소
            session_id: 세션 ID
            override_ip_limit: 지정 시 해당 값으로 IP 제한 수행
            override_session_limit: 지정 시 해당 값으로 Session 제한 수행

        Returns:
            tuple[bool, str, int]:
                - bool: Rate Limit 통과 여부 (True: 허용, False: 거부)
                - str: 제한 타입 ("ip" or "session")
                - int: 남은 요청 수
        """
        current_time = time.time()
        
        # Override된 Limit 적용 (없으면 기본값)
        active_ip_limit = override_ip_limit if override_ip_limit is not None else self.ip_limit
        active_session_limit = override_session_limit if override_session_limit is not None else self.session_limit

        async with self.lock:
            # 🛡️ 메모리 보호: IP 개수 제한 (LRU 방식 제거)
            if ip and len(self.ip_requests) >= self.max_tracked_ips:
                if ip not in self.ip_requests:
                    # 가장 오래된 IP 제거 (LRU 전략)
                    oldest_ip = min(
                        self.ip_requests.keys(),
                        key=lambda k: (
                            self.ip_requests[k][0][0] if self.ip_requests[k] else float("inf")
                        ),
                    )
                    del self.ip_requests[oldest_ip]
                    logger.info(f"🛡️ 메모리 보호: 오래된 IP 제거 (총 {len(self.ip_requests)}개)")

            # IP 기반 Rate Limiting (우선순위 1)
            if ip:
                request_list = self.ip_requests[ip]
                self._clean_old_requests(request_list, current_time)

                current_count = self._get_request_count(request_list)

                if current_count >= active_ip_limit:
                    remaining = 0
                    logger.warning(
                        f"Rate Limit 초과 (IP): ip={ip}, count={current_count}/{active_ip_limit}"
                    )
                    return False, "ip", remaining

                # 요청 기록 추가
                request_list.append((current_time, 1))
                remaining = active_ip_limit - (current_count + 1)

                return True, "ip", remaining

            # 🛡️ 메모리 보호: Session 개수 제한 (LRU 방식 제거)
            if session_id and len(self.session_requests) >= self.max_tracked_sessions:
                if session_id not in self.session_requests:
                    # 가장 오래된 세션 제거 (LRU 전략)
                    oldest_session = min(
                        self.session_requests.keys(),
                        key=lambda k: (
                            self.session_requests[k][0][0]
                            if self.session_requests[k]
                            else float("inf")
                        ),
                    )
                    del self.session_requests[oldest_session]
                    logger.info(
                        f"🛡️ 메모리 보호: 오래된 세션 제거 (총 {len(self.session_requests)}개)"
                    )

            # Session 기반 Rate Limiting (fallback)
            elif session_id:
                request_list = self.session_requests[session_id]
                self._clean_old_requests(request_list, current_time)

                current_count = self._get_request_count(request_list)

                if current_count >= active_session_limit:
                    remaining = 0
                    logger.warning(
                        f"Rate Limit 초과 (Session): session_id={session_id}, count={current_count}/{active_session_limit}"
                    )
                    return False, "session", remaining

                # 요청 기록 추가
                request_list.append((current_time, 1))
                remaining = self.session_limit - (current_count + 1)

                return True, "session", remaining

            # IP와 Session 모두 없으면 통과 (안전을 위해)
            else:
                logger.warning("Rate Limit 체크 실패: IP와 Session ID 모두 없음")
                return True, "none", -1

    async def get_stats(self) -> dict[str, int]:
        """
        현재 Rate Limiter 상태 통계

        Returns:
            Dict[str, int]: 통계 정보
        """
        async with self.lock:
            return {
                "active_ips": len(self.ip_requests),
                "active_sessions": len(self.session_requests),
                "total_active": len(self.ip_requests) + len(self.session_requests),
            }

    async def periodic_cleanup(self):
        """
        24시간 주기로 오래된 IP/Session 엔트리 제거

        목적: 메모리 누수 방지
        - 트래픽 없는 IP/Session의 dict 엔트리가 무한정 누적되는 것 방지
        - window_seconds + grace_period 이전의 모든 요청 기록 제거

        실행 주기: 24시간 (86400초)
        안전 마진: 60초 추가 (grace_period)
        """
        logger.info(
            f"🔄 Background cleanup task started: interval={self._cleanup_interval}s, "
            f"grace_period={self._grace_period}s"
        )

        while True:
            try:
                # 24시간 대기
                await asyncio.sleep(self._cleanup_interval)

                current_time = time.time()
                cutoff_time = current_time - (self.window_seconds + self._grace_period)

                logger.info("🧹 Starting periodic memory cleanup...")

                async with self.lock:
                    # IP 엔트리 정리 전 통계
                    initial_ip_count = len(self.ip_requests)
                    initial_session_count = len(self.session_requests)

                    # IP 엔트리 정리: 모든 요청이 cutoff_time 이전이면 제거
                    ips_to_remove = [
                        ip
                        for ip, requests in self.ip_requests.items()
                        if all(timestamp < cutoff_time for timestamp, _ in requests)
                    ]

                    for ip in ips_to_remove:
                        del self.ip_requests[ip]

                    # Session 엔트리 정리: 모든 요청이 cutoff_time 이전이면 제거
                    sessions_to_remove = [
                        session_id
                        for session_id, requests in self.session_requests.items()
                        if all(timestamp < cutoff_time for timestamp, _ in requests)
                    ]

                    for session_id in sessions_to_remove:
                        del self.session_requests[session_id]

                    # 정리 후 통계
                    final_ip_count = len(self.ip_requests)
                    final_session_count = len(self.session_requests)

                    removed_ips = initial_ip_count - final_ip_count
                    removed_sessions = initial_session_count - final_session_count

                logger.info(
                    f"✅ Cleanup completed: "
                    f"IPs {initial_ip_count}→{final_ip_count} (-{removed_ips}), "
                    f"Sessions {initial_session_count}→{final_session_count} (-{removed_sessions})"
                )

                if removed_ips > 0 or removed_sessions > 0:
                    logger.debug(
                        f"Removed IPs: {ips_to_remove[:10]}{'...' if len(ips_to_remove) > 10 else ''}, "
                        f"Removed Sessions: {sessions_to_remove[:10]}{'...' if len(sessions_to_remove) > 10 else ''}"
                    )

            except asyncio.CancelledError:
                logger.info("🛑 Cleanup task cancelled")
                break
            except Exception as e:
                logger.error(f"❌ Error during cleanup: {e}", exc_info=True)
                # 에러 발생해도 계속 실행 (서버 다운 방지)
                continue

    def start_cleanup_task(self):
        """
        Background cleanup task 시작

        FastAPI lifespan의 startup 이벤트에서 호출
        """
        if self._cleanup_task is None or self._cleanup_task.done():
            self._cleanup_task = asyncio.create_task(self.periodic_cleanup())
            logger.info("✅ Cleanup task started")
        else:
            logger.warning("⚠️ Cleanup task already running")

    async def stop_cleanup_task(self):
        """
        Background cleanup task 중지

        FastAPI lifespan의 shutdown 이벤트에서 호출
        """
        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                logger.info("✅ Cleanup task stopped")
        else:
            logger.debug("Cleanup task not running or already stopped")


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    FastAPI Rate Limiting Middleware

    특정 경로에 대해 Rate Limiting을 적용합니다.
    """

    def __init__(self, app, rate_limiter: RateLimiter, excluded_paths: list[str] | None = None):
        super().__init__(app)
        self.rate_limiter = rate_limiter

        # Rate Limiting에서 제외할 경로 (Health Check 등)
        self.excluded_paths = excluded_paths or [
            "/health",
            "/api/health",
            "/docs",
            "/redoc",
            "/openapi.json",
        ]

        logger.info(f"RateLimitMiddleware 초기화: excluded_paths={self.excluded_paths}")

    def _get_client_ip(self, request: Request) -> str | None:
        """
        클라이언트 IP 주소 추출

        우선순위:
        1. X-Forwarded-For 헤더 (프록시 환경)
        2. X-Real-IP 헤더
        3. request.client.host (직접 연결)

        Args:
            request: FastAPI Request 객체

        Returns:
            Optional[str]: 클라이언트 IP 주소 (없으면 None)
        """
        # X-Forwarded-For 헤더 체크 (프록시 환경)
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            # 여러 프록시를 거친 경우 첫 번째 IP 사용
            return forwarded_for.split(",")[0].strip()

        # X-Real-IP 헤더 체크
        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip.strip()

        # 직접 연결된 클라이언트 IP
        if request.client:
            return request.client.host

        return None

    async def _get_session_id(self, request: Request) -> str | None:
        """
        Session ID 추출

        우선순위:
        1. Request body의 session_id (POST 요청)
        2. Query parameter의 session_id (GET 요청)
        3. X-Session-ID 헤더

        Args:
            request: FastAPI Request 객체

        Returns:
            Optional[str]: Session ID (없으면 None)
        """
        # 1. 헤더에서 session_id 추출 (가장 빠름)
        session_id = request.headers.get("X-Session-ID")
        if session_id:
            return cast(str | None, session_id)

        # 2. Query parameter에서 session_id 추출
        session_id = request.query_params.get("session_id")
        if session_id:
            return cast(str | None, session_id)

        # 3. POST 요청의 경우 body에서 추출
        if request.method == "POST":
            try:
                # body를 읽기 (한 번만 읽을 수 있으므로 주의)
                body = await request.body()

                # JSON 파싱
                if body:
                    import json

                    try:
                        data = json.loads(body)
                        session_id = data.get("session_id")
                        if session_id:
                            # body를 다시 사용할 수 있도록 복원
                            async def receive():
                                return {"type": "http.request", "body": body}

                            request._receive = receive
                            return cast(str | None, session_id)
                    except json.JSONDecodeError:
                        pass
            except Exception as e:
                logger.debug(f"Failed to extract session_id from body: {e}")

        return None

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """
        요청 인터셉션 및 Rate Limiting 적용

        Args:
            request: FastAPI Request 객체
            call_next: 다음 미들웨어 또는 라우트 핸들러

        Returns:
            Response: FastAPI Response 객체
        """
        # 제외 경로 체크
        if request.url.path in self.excluded_paths:
            return cast(Response, await call_next(request))

        # IP와 Session ID 추출
        client_ip = self._get_client_ip(request)
        session_id = await self._get_session_id(request)

        # Rate Limit 체크 (async 메서드 호출)
        allowed, limit_type, remaining = await self.rate_limiter.check_rate_limit(
            ip=client_ip, session_id=session_id
        )

        if not allowed:
            # Rate Limit 초과
            logger.warning(
                f"Rate Limit 거부: path={request.url.path}, "
                f"ip={client_ip}, session_id={session_id}, type={limit_type}"
            )

            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={
                    "error": "Too Many Requests",
                    "message": "요청 한도를 초과했습니다. 잠시 후 다시 시도해주세요.",
                    "limit_type": limit_type,
                    "retry_after": 60,  # 60초 후 재시도
                },
                headers={
                    "Retry-After": "60",
                    "X-RateLimit-Limit": str(
                        self.rate_limiter.ip_limit
                        if limit_type == "ip"
                        else self.rate_limiter.session_limit
                    ),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(int(time.time()) + 60),
                },
            )

        # Rate Limit 통과
        response = await call_next(request)

        # Rate Limit 정보를 응답 헤더에 추가
        response.headers["X-RateLimit-Limit"] = str(
            self.rate_limiter.ip_limit if limit_type == "ip" else self.rate_limiter.session_limit
        )
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        response.headers["X-RateLimit-Type"] = limit_type

        return cast(Response, response)


class ChatRateLimitMiddleware(BaseHTTPMiddleware):
    """
    Chat API 전용 경량 Rate Limiter

    기존 RateLimitMiddleware와의 차이점:
    - ✅ body를 읽지 않음 → StreamingResponse와 충돌 없음
    - ✅ IP + X-Session-ID 헤더만으로 Rate Limit 판단
    - ✅ Chat API에 특화된 제한 (IP당 분당 20회)

    보안 목적:
    - Chat 요청 1건당 LLM API 1-3회 호출 (비용 발생)
    - 무제한 요청 시 LLM 비용 폭탄 + 서버 스레드 고갈 방지
    - 기존 RateLimitMiddleware는 body 읽기로 인한 StreamingResponse 충돌 때문에
      Chat API를 excluded_paths에 포함시켰으나, 이 미들웨어로 해결
    """

    # Chat API 경로 목록
    CHAT_PATHS = frozenset({
        "/api/chat",
        "/api/chat/stream",
        "/api/chat/session",
        "/v1/chat/completions",
    })

    def __init__(
        self,
        app: Any,
        rate_limiter: RateLimiter,
        ip_limit: int = 20,
        session_limit: int = 10,
    ):
        super().__init__(app)
        self.rate_limiter = rate_limiter
        self.ip_limit = ip_limit
        self.session_limit = session_limit

        logger.info(
            f"ChatRateLimitMiddleware 초기화: "
            f"IP={ip_limit}/min, Session={session_limit}/min, "
            f"paths={list(self.CHAT_PATHS)}"
        )

    def _get_client_ip(self, request: Request) -> str | None:
        """클라이언트 IP 주소 추출 (X-Forwarded-For → X-Real-IP → client.host)"""
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()

        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip.strip()

        if request.client:
            return request.client.host

        return None

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """
        Chat API 요청만 인터셉션하여 Rate Limiting 적용

        핵심: body를 읽지 않고 IP + 헤더만으로 판단
        → StreamingResponse와 충돌 없음
        """
        # Chat API가 아니면 통과
        if request.url.path not in self.CHAT_PATHS:
            return cast(Response, await call_next(request))

        # IP 추출 (body 읽기 없음)
        client_ip = self._get_client_ip(request)

        # X-Session-ID 헤더에서 세션 ID 추출 (body 읽기 없음)
        session_id = request.headers.get("X-Session-ID")

        # Rate Limit 체크
        allowed, limit_type, remaining = await self.rate_limiter.check_rate_limit(
            ip=client_ip,
            session_id=session_id,
            override_ip_limit=self.ip_limit,
            override_session_limit=self.session_limit,
        )

        if not allowed:
            logger.warning(
                f"Chat Rate Limit 거부: path={request.url.path}, "
                f"ip={client_ip}, session_id={session_id}, type={limit_type}"
            )

            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={
                    "error": "Too Many Requests",
                    "message": "채팅 요청 한도를 초과했습니다. 잠시 후 다시 시도해주세요.",
                    "limit_type": limit_type,
                    "retry_after": 60,
                },

                headers={
                    "Retry-After": "60",
                    "X-RateLimit-Limit": str(
                        self.ip_limit if limit_type == "ip" else self.session_limit
                    ),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(int(time.time()) + 60),
                },
            )

        # Rate Limit 통과 → 요청 처리
        response = await call_next(request)

        # Rate Limit 정보를 응답 헤더에 추가
        response.headers["X-RateLimit-Limit"] = str(
            self.ip_limit if limit_type == "ip" else self.session_limit
        )
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        response.headers["X-RateLimit-Type"] = f"chat-{limit_type}"

        return cast(Response, response)
