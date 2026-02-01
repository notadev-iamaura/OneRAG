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

import structlog
from structlog.stdlib import LoggerFactory

# 한국 시간대 (KST = UTC+9)
KST = timezone(timedelta(hours=9))


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


class RAGLogger:
    """RAG 챗봇 로깅 시스템"""

    def __init__(self) -> None:
        self.log_level = os.getenv("LOG_LEVEL", "INFO").upper()
        self.is_production = os.getenv("NODE_ENV", "development") == "production"

        if self.is_production:
            self.log_level = os.getenv("LOG_LEVEL", "WARNING").upper()

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
        if not self.is_production:
            handlers.append(logging.FileHandler(self.log_dir / "app.log"))

        logging.basicConfig(level=level, format="%(message)s", handlers=handlers)

        for noisy_logger in ["httpx", "httpcore", "urllib3"]:
            logging.getLogger(noisy_logger).setLevel(logging.WARNING)

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

    def get_logger(self, name: str | None = None) -> structlog.BoundLogger:
        """구조화된 로거 반환"""
        from typing import cast

        return cast(structlog.BoundLogger, structlog.get_logger(name or __name__))


# 글로벌 로거 인스턴스
_rag_logger = RAGLogger()


def get_logger(name: str | None = None) -> structlog.BoundLogger:
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
