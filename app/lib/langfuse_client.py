"""
Langfuse 클라이언트 래퍼 모듈

Langfuse SDK를 사용한 LLM Observability 및 트레이싱 클라이언트.
에러 발생 시 Graceful Degradation으로 RAG 파이프라인이 정상 동작하도록 보장.

주요 기능:
- RAG 파이프라인 Trace/Span 관리
- Self-RAG 평가 점수 기록
- 에러 처리 및 Fail Silently 모드

작성일: 2025-01-27
참고: https://langfuse.com/docs/sdk/python/decorators
"""

import asyncio
import os
from collections.abc import Generator
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

from .logger import get_logger

logger = get_logger(__name__)

# Langfuse SDK import (선택적)
if TYPE_CHECKING:
    from langfuse import Langfuse

# import 시점 비활성 판정(네트워크/SDK 로드 회피). config 시스템은 아직 로드되기
# 전이므로 환경변수만으로 결정한다 — 이 env 게이트가 활성 트레이싱(@observe/
# langfuse_context, SDK 전역 클라이언트)의 권위 있는 on/off 스위치다(YAML의
# langfuse.enabled는 미사용 LangfuseClient 래퍼 전용이며 이 게이트를 제어하지 않는다).
def _langfuse_disabled_by_env() -> bool:
    """LANGFUSE_ENABLED/ENVIRONMENT 환경변수로 비활성 여부를 판정한다.

    - ENVIRONMENT=test → 항상 비활성(테스트 격리, 외부 통신 차단).
    - LANGFUSE_ENABLED가 false 계열(false/0/no/off, 대소문자 무관) → 비활성.
    - 미설정/그 외(true 등) → 활성(SDK 로드; 단 키 미설정 시 SDK가 자체적으로 inert).
    """
    if os.getenv("ENVIRONMENT") == "test":
        return True
    return os.getenv("LANGFUSE_ENABLED", "").strip().lower() in ("false", "0", "no", "off")


if _langfuse_disabled_by_env():
    LANGFUSE_AVAILABLE = False
    logger.info("Langfuse 비활성(ENVIRONMENT=test 또는 LANGFUSE_ENABLED=false): Dummy 모드로 동작합니다.")
else:
    try:
        from langfuse import Langfuse
        from langfuse.decorators import langfuse_context, observe

        LANGFUSE_AVAILABLE = True
    except ImportError:
        LANGFUSE_AVAILABLE = False
        logger.warning(
            "Langfuse SDK가 설치되지 않음. "
            "트레이싱 기능이 비활성화됩니다. "
            "설치: uv pip install langfuse"
        )

if not LANGFUSE_AVAILABLE:
    # Fallback 데코레이터 (No-op)
    def observe(*args: Any, **kwargs: Any) -> Any:  # type: ignore[no-redef]
        """Langfuse가 없을 때 사용하는 더미 데코레이터"""
        import functools

        def decorator(func: Any) -> Any:
            if asyncio.iscoroutinefunction(func):
                @functools.wraps(func)
                async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                    return await func(*args, **kwargs)
                return async_wrapper
            else:
                @functools.wraps(func)
                def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
                    return func(*args, **kwargs)
                return sync_wrapper

        return decorator

    # Fallback context 객체 (No-op)
    class _DummyLangfuseContext:
        """Langfuse가 없을 때 사용하는 더미 컨텍스트 객체"""

        def update_current_trace(self, *args: Any, **kwargs: Any) -> None:
            """더미 메서드: 아무 것도 하지 않음"""
            pass

        def update_current_observation(self, *args: Any, **kwargs: Any) -> None:
            """더미 메서드: 아무 것도 하지 않음"""
            pass

        def score_current_trace(self, *args: Any, **kwargs: Any) -> None:
            """더미 메서드: 아무 것도 하지 않음"""
            pass

        def score_current_observation(self, *args: Any, **kwargs: Any) -> None:
            """더미 메서드: 아무 것도 하지 않음"""
            pass

        def flush(self, *args: Any, **kwargs: Any) -> None:
            """더미 메서드: 아무 것도 하지 않음"""
            pass

        def __getattr__(self, name: str) -> Any:
            """알 수 없는 메서드 호출 시에도 에러 없이 통과"""
            return lambda *args, **kwargs: None

    langfuse_context = _DummyLangfuseContext()  # type: ignore[assignment]

    # 타입 힌트용 더미 클래스
    Langfuse = Any  # type: ignore[assignment, misc]


class LangfuseClient:
    """
    Langfuse 클라이언트 래퍼

    설정 기반 초기화 및 에러 처리를 담당.
    Langfuse 서버 연결 실패 시에도 애플리케이션 정상 동작 보장.

    Attributes:
        enabled: Langfuse 트레이싱 활성화 여부
        client: Langfuse SDK 클라이언트 인스턴스
        fail_silently: 에러 발생 시 조용히 실패 (기본: True)

    Examples:
        >>> # 설정 파일 기반 초기화
        >>> langfuse_config = config["langfuse"]
        >>> client = LangfuseClient(langfuse_config)
        >>>
        >>> # Trace 생성 (컨텍스트 매니저)
        >>> with client.trace(name="RAG Pipeline", user_id="user123") as trace:
        ...     # 파이프라인 실행
        ...     result = await rag_pipeline.execute(message, session_id)
    """

    def __init__(self, config: dict[str, Any]):
        """
        Langfuse 클라이언트 초기화

        Args:
            config: Langfuse 설정 딕셔너리 (langfuse.yaml의 langfuse 섹션)
                - enabled: 활성화 여부
                - host: Langfuse 서버 URL
                - public_key: Public Key
                - secret_key: Secret Key
                - error_handling.fail_silently: 에러 시 조용히 실패 여부
        """
        self.enabled = config.get("enabled", True)
        self.fail_silently = config.get("error_handling", {}).get("fail_silently", True)
        self.client: Any = None  # Langfuse | None (타입 힌트는 TYPE_CHECKING에서 처리)

        # 테스트 환경 또는 명시적 비활성화 감지
        if os.getenv("ENVIRONMENT") == "test" or os.getenv("LANGFUSE_ENABLED") == "False":
            logger.info("테스트 환경 또는 설정에 의해 Langfuse 트레이싱이 비활성화되었습니다")
            self.enabled = False
            return

        if not self.enabled:
            logger.info("Langfuse 트레이싱이 비활성화되어 있습니다 (enabled: false)")
            return

        if not LANGFUSE_AVAILABLE:
            logger.warning("Langfuse SDK를 사용할 수 없어 트레이싱이 비활성화됩니다")
            self.enabled = False
            return

        try:
            # 환경변수 또는 설정 파일에서 연결 정보 가져오기
            host = config.get("host") or os.getenv("LANGFUSE_HOST")
            public_key = config.get("public_key") or os.getenv("LANGFUSE_PUBLIC_KEY")
            secret_key = config.get("secret_key") or os.getenv("LANGFUSE_SECRET_KEY")

            if not all([host, public_key, secret_key]):
                logger.warning(
                    "Langfuse 연결 정보가 불완전합니다. "
                    "트레이싱이 비활성화됩니다. "
                    "필요 환경변수: LANGFUSE_HOST, LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY"
                )
                self.enabled = False
                return

            # Langfuse 클라이언트 초기화
            self.client = Langfuse(
                public_key=public_key,
                secret_key=secret_key,
                host=host,
                debug=config.get("debug", {}).get("verbose", False),
            )

            logger.info(
                f"Langfuse 클라이언트 초기화 완료 (host: {host}, "
                f"fail_silently: {self.fail_silently})"
            )

        except Exception as e:
            error_msg = f"Langfuse 클라이언트 초기화 실패: {e}"

            if self.fail_silently:
                logger.warning(f"{error_msg} - 트레이싱 없이 계속 진행합니다")
                self.enabled = False
            else:
                logger.error(error_msg)
                raise

    @contextmanager
    def trace(
        self,
        name: str,
        user_id: str | None = None,
        session_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        tags: list[str] | None = None,
    ) -> Generator[Any, None, None]:
        """
        Langfuse Trace 컨텍스트 매니저

        RAG 파이프라인 전체 실행을 하나의 Trace로 기록.

        Args:
            name: Trace 이름 (예: "RAG Pipeline")
            user_id: 사용자 ID (선택적)
            session_id: 세션 ID (선택적)
            metadata: 추가 메타데이터 (선택적)
            tags: 태그 리스트 (선택적)

        Yields:
            Langfuse Trace 객체 (비활성화 시 None)

        Examples:
            >>> with client.trace("RAG Pipeline", user_id="user123") as trace:
            ...     result = await pipeline.execute(message)
            ...     # Trace는 자동으로 종료됨
        """
        if not self.enabled or not self.client:
            # 비활성화 상태: No-op 컨텍스트 반환
            yield None
            return

        try:
            # Trace 생성
            trace = self.client.trace(
                name=name, user_id=user_id, session_id=session_id, metadata=metadata, tags=tags
            )

            yield trace

            # Trace 완료 (자동)
            # Langfuse SDK가 컨텍스트 종료 시 자동으로 flush함

        except Exception as e:
            error_msg = f"Langfuse Trace 생성/종료 중 오류: {e}"

            if self.fail_silently:
                logger.warning(f"{error_msg} - 계속 진행합니다")
                yield None
            else:
                logger.error(error_msg)
                raise

    def score(
        self, trace_id: str | None, name: str, value: float, comment: str | None = None
    ) -> None:
        """
        Langfuse Score 기록 (Self-RAG 평가 점수 등)

        Args:
            trace_id: Trace ID (None이면 현재 활성 Trace 사용)
            name: 평가 메트릭 이름 (예: "relevance", "groundedness")
            value: 평가 점수 (0.0 ~ 1.0)
            comment: 추가 설명 (선택적)

        Examples:
            >>> # Self-RAG 점수 기록
            >>> client.score(
            ...     trace_id=trace.id,
            ...     name="relevance",
            ...     value=0.92,
            ...     comment="High relevance to user query"
            ... )
        """
        if not self.enabled or not self.client:
            return

        try:
            self.client.score(trace_id=trace_id, name=name, value=value, comment=comment)

            logger.debug(f"Langfuse Score 기록 완료: {name}={value:.2f}")

        except Exception as e:
            error_msg = f"Langfuse Score 기록 실패: {e}"

            if self.fail_silently:
                logger.warning(f"{error_msg} - 계속 진행합니다")
            else:
                logger.error(error_msg)
                raise

    def flush(self) -> None:
        """
        대기 중인 모든 이벤트를 Langfuse 서버로 전송

        애플리케이션 종료 시 호출하여 누락 방지.

        Examples:
            >>> # 애플리케이션 종료 전
            >>> langfuse_client.flush()
        """
        if not self.enabled or not self.client:
            return

        try:
            self.client.flush()
            logger.info("Langfuse 이벤트 flush 완료")

        except Exception as e:
            logger.warning(f"Langfuse flush 실패: {e}")


# 전역 observe 데코레이터 export (편의성)
# 사용 예: @observe(name="Query Expansion")
__all__ = ["LangfuseClient", "observe", "langfuse_context", "LANGFUSE_AVAILABLE"]
