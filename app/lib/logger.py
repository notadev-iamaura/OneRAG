"""
Structured logging for OneRAG
구조화된 로깅 시스템
"""

import logging
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from time import time
from typing import Any


# 로그 타임스탬프 타임존: LOG_TZ_OFFSET_HOURS env로 오버라이드 가능, 미설정 시 KST(UTC+9) 기본.
# 비한국 지역 배포 시 자국 타임존 오프셋을 지정할 수 있다(미설정 시 기존 KST 동작 유지=회귀 0).
def _resolve_log_timezone() -> timezone:
    """LOG_TZ_OFFSET_HOURS env로 로그 타임스탬프 오프셋(시간)을 지정. 미설정/오류 시 KST(+9)로 폴백."""
    try:
        return timezone(timedelta(hours=float(os.getenv("LOG_TZ_OFFSET_HOURS", "9"))))
    except (TypeError, ValueError):
        # 잘못된 값이면 기본 KST로 폴백(graceful degradation)
        return timezone(timedelta(hours=9))


KST = _resolve_log_timezone()


class LogThrottler:
    """로그 쓰로틀링 클래스"""

    def __init__(self, max_logs_per_second: int = 50):
        self.max_logs_per_second = max_logs_per_second
        self.log_counts: dict[str, list[float]] = defaultdict(list)
        self.last_cleanup = time()

    def should_log(self, log_key: str) -> bool:
        current_time = time()

        if current_time - self.last_cleanup > 60:
            self._cleanup_old_entries()
            self.last_cleanup = current_time

        if log_key not in self.log_counts:
            self.log_counts[log_key] = []

        self.log_counts[log_key] = [t for t in self.log_counts[log_key] if current_time - t < 1.0]

        if len(self.log_counts[log_key]) < self.max_logs_per_second:
            self.log_counts[log_key].append(current_time)
            return True
        return False

    def _cleanup_old_entries(self) -> None:
        current_time = time()
        keys_to_remove = []
        for key, timestamps in self.log_counts.items():
            self.log_counts[key] = [t for t in timestamps if current_time - t < 5.0]
            if not self.log_counts[key]:
                keys_to_remove.append(key)
        for key in keys_to_remove:
            del self.log_counts[key]


def add_kst_timestamp(logger: Any, method_name: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    """KST(한국 시간) 타임스탬프 추가"""
    event_dict["timestamp"] = datetime.now(KST).isoformat()
    return event_dict


class LightweightBoundLogger:
    """Small structlog-compatible wrapper used in test/import-sensitive paths."""

    def __init__(self, name: str | None = None) -> None:
        self._logger = logging.getLogger(name or __name__)

    def bind(self, **kwargs: Any) -> "LightweightBoundLogger":
        return self

    def unbind(self, *args: str) -> "LightweightBoundLogger":
        return self

    def _log(self, level: int, event: str, *args: Any, **kwargs: Any) -> None:
        exc_info = kwargs.pop("exc_info", None)
        extra = kwargs.pop("extra", None) or {}
        if kwargs:
            extra = {**extra, **kwargs}
        self._logger.log(level, event, *args, extra={"structured": extra}, exc_info=exc_info)

    def debug(self, event: str, *args: Any, **kwargs: Any) -> None:
        self._log(logging.DEBUG, event, *args, **kwargs)

    def info(self, event: str, *args: Any, **kwargs: Any) -> None:
        self._log(logging.INFO, event, *args, **kwargs)

    def warning(self, event: str, *args: Any, **kwargs: Any) -> None:
        self._log(logging.WARNING, event, *args, **kwargs)

    warn = warning

    def error(self, event: str, *args: Any, **kwargs: Any) -> None:
        self._log(logging.ERROR, event, *args, **kwargs)

    def critical(self, event: str, *args: Any, **kwargs: Any) -> None:
        self._log(logging.CRITICAL, event, *args, **kwargs)

    def exception(self, event: str, *args: Any, **kwargs: Any) -> None:
        kwargs["exc_info"] = True
        self._log(logging.ERROR, event, *args, **kwargs)


class RAGLogger:
    """RAG 챗봇 로깅 시스템"""

    def __init__(self) -> None:
        self.log_level = os.getenv("LOG_LEVEL", "INFO").upper()
        self.is_production = os.getenv("NODE_ENV", "development") == "production"
        self.use_lightweight_logger = (
            os.getenv("ENVIRONMENT") == "test"
            or os.getenv("ONERAG_LIGHTWEIGHT_LOGGER") == "1"
            or "pytest" in sys.modules
        )

        if self.is_production:
            self.log_level = os.getenv("LOG_LEVEL", "WARNING").upper()

        self.log_dir: Path | None = None
        if not self.use_lightweight_logger:
            if os.path.exists("/app"):
                self.log_dir = Path("/app/logs")
            else:
                self.log_dir = Path("./logs")
            self.log_dir.mkdir(exist_ok=True, parents=True)

        self.throttler = LogThrottler(max_logs_per_second=50)

        self._setup_logging()

    def _setup_logging(self) -> None:
        """로깅 설정"""
        level = getattr(logging, self.log_level, logging.INFO)

        handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
        if not self.is_production and self.log_dir is not None:
            handlers.append(logging.FileHandler(self.log_dir / "app.log"))

        logging.basicConfig(level=level, format="%(message)s", handlers=handlers)

        if self.use_lightweight_logger:
            return

        for noisy_logger in ["httpx", "httpcore", "urllib3"]:
            logging.getLogger(noisy_logger).setLevel(logging.WARNING)

        import structlog
        from structlog.stdlib import LoggerFactory

        # Structlog 설정 (KST 타임스탬프 사용)
        use_json = self._should_use_json()
        processors: list[Any] = [
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            add_kst_timestamp,  # type: ignore[list-item]  # KST 타임스탬프 (UTC+9)
            structlog.processors.StackInfoRenderer(),
        ]
        # ConsoleRenderer는 예외 정보를 자체 포맷팅하므로 format_exc_info 불필요
        # JSONRenderer 사용 시에만 명시적 변환 필요
        if use_json:
            processors.append(structlog.processors.format_exc_info)
        processors.extend([
            structlog.processors.UnicodeDecoder(),
            self._add_context,  # type: ignore[list-item]
            (
                structlog.processors.JSONRenderer()
                if use_json
                else structlog.dev.ConsoleRenderer()
            ),
        ])
        structlog.configure(
            processors=processors,
            context_class=dict,
            logger_factory=LoggerFactory(),
            wrapper_class=structlog.stdlib.BoundLogger,
            cache_logger_on_first_use=True,
        )

    def _should_use_json(self) -> bool:
        """JSON 형식 사용 여부 결정"""
        return os.getenv("LOG_FORMAT", "console").lower() == "json"

    def _add_context(
        self, logger: Any, method_name: str, event_dict: dict[str, Any]
    ) -> dict[str, Any]:
        """컨텍스트 정보 추가"""
        event_dict["service"] = "rag-chatbot"
        event_dict["environment"] = os.getenv("NODE_ENV", "development")
        event_dict["pid"] = os.getpid()
        return event_dict

    def get_logger(self, name: str | None = None) -> Any:
        """구조화된 로거 반환"""
        if self.use_lightweight_logger:
            return LightweightBoundLogger(name)

        from typing import cast

        import structlog

        return cast(structlog.BoundLogger, structlog.get_logger(name or __name__))


# 글로벌 로거 인스턴스
_rag_logger = RAGLogger()


def get_logger(name: str | None = None) -> Any:
    """로거 인스턴스 반환"""
    return _rag_logger.get_logger(name)


class ChatLoggingMiddleware:
    """채팅 요청 로깅 미들웨어"""

    def __init__(self) -> None:
        self.logger = get_logger("chat_middleware")

    async def log_chat_request(
        self,
        request_data: dict[str, Any],
        response_data: dict[str, Any],
        processing_time: float,
        session_id: str | None = None,
    ) -> None:
        """채팅 요청/응답 로깅"""
        log_data = {
            "event": "chat_request",
            "session_id": session_id,
            "message_length": len(request_data.get("message", "")),
            "response_length": len(response_data.get("answer", "")),
            "processing_time": processing_time,
            "tokens_used": response_data.get("tokens_used", 0),
            "sources_count": len(response_data.get("sources", [])),
            "success": "error" not in response_data,
        }

        if response_data.get("error"):
            self.logger.error("Chat request failed", **log_data, error=response_data["error"])
        else:
            self.logger.info("Chat request completed", **log_data)


def create_chat_logging_middleware() -> ChatLoggingMiddleware:
    """채팅 로깅 미들웨어 팩토리"""
    return ChatLoggingMiddleware()
