"""커스텀 예외 클래스 모듈.

RAG 시스템의 모든 커스텀 예외 클래스를 정의합니다.
각 예외는 에러 코드와 컨텍스트 정보를 포함하며,
양언어 에러 응답을 생성할 수 있습니다.
"""

from typing import Any

from app.lib.errors.codes import ErrorCode
from app.lib.errors.formatter import format_error_response


class RAGException(Exception):
    """RAG 시스템 기본 예외 클래스.

    모든 커스텀 예외의 베이스 클래스입니다.
    에러 코드와 컨텍스트 정보를 저장하고,
    양언어 에러 응답을 생성할 수 있습니다.

    Attributes:
        error_code: 에러 코드 (예: "AUTH-001")
        context: 에러 컨텍스트 정보 (메시지 포맷팅에 사용)
    """

    def __init__(self, error_code: str | ErrorCode, **context: Any) -> None:
        """RAGException 초기화.

        Args:
            error_code: 에러 코드 (ErrorCode Enum 또는 문자열)
            **context: 에러 컨텍스트 정보 (메시지 포맷팅에 사용)
        """
        self.error_code = error_code.value if isinstance(error_code, ErrorCode) else error_code
        self.context = context

        # Exception의 메시지는 한국어 기본값으로 설정
        message = format_error_response(self.error_code, lang="ko", include_solutions=False, **context)["message"]
        super().__init__(message)

    def to_dict(self, lang: str = "ko", include_solutions: bool = True) -> dict[str, Any]:
        """에러 응답 딕셔너리로 변환.

        Args:
            lang: 언어 코드 ("ko" 또는 "en")
            include_solutions: 해결 방법 포함 여부

        Returns:
            에러 응답 딕셔너리

        Example:
            >>> exc = AuthError(ErrorCode.AUTH_001)
            >>> response = exc.to_dict(lang="en")
            >>> print(response["error_code"])
            "AUTH-001"
        """
        return format_error_response(
            self.error_code,
            lang=lang,
            include_solutions=include_solutions,
            **self.context,
        )


# 도메인별 예외 클래스


class AuthError(RAGException):
    """인증/인가 관련 예외."""

    pass


class SessionError(RAGException):
    """세션 관리 관련 예외."""

    pass


class ServiceError(RAGException):
    """서비스 초기화 관련 예외."""

    pass


class DocumentError(RAGException):
    """문서 처리 관련 예외."""

    pass


class UploadError(RAGException):
    """파일 업로드 관련 예외."""

    pass


class StorageError(RAGException):
    """원본 파일 보관(스토리지) 관련 예외 (#10)."""

    pass


class ImageError(RAGException):
    """이미지 처리 관련 예외."""

    pass


class LLMError(RAGException):
    """언어 모델 관련 예외."""

    pass


class VectorError(RAGException):
    """벡터 검색 관련 예외."""

    pass


class SearchUnavailableError(VectorError):
    """검색 백엔드 전면 불능 예외 (SEARCH-004).

    모든 검색 쿼리가 예외로 실패해 검색 백엔드가 완전히 동작하지 않는 상태를
    나타낸다. 부분 실패의 degradation(빈 결과 반환)과 달리, 이 예외는 상위
    CircuitBreaker 등이 장애 신호를 받을 수 있도록 반드시 전파되어야 한다.

    VectorError(= RetrievalError 별칭)의 하위 클래스이므로 기존
    `except RetrievalError` 핸들러도 그대로 이 예외를 처리할 수 있다.
    """

    pass


class DatabaseError(RAGException):
    """데이터베이스 관련 예외."""

    pass


class RoutingError(RAGException):
    """라우팅/규칙 관련 예외."""

    pass


class EmbeddingError(RAGException):
    """임베딩 관련 예외."""

    pass


class ConfigError(RAGException):
    """설정 관련 예외."""

    pass


class GeneralError(RAGException):
    """일반 예외."""

    pass


class PipelineTimeoutError(RAGException):
    """파이프라인 타임아웃 관련 예외.

    stage별 deadline 초과(PIPE-001), 총 budget 초과(PIPE-002),
    스트리밍 첫 청크 타임아웃(PIPE-003)에 사용한다.
    무한 대기 대신 "어느 단계에서 얼마만큼 초과했는지"를 명확히 전달한다.
    """

    pass


# 레거시 호환: RAGError 별칭 (기존 코드 지원)
RAGError = RAGException


# 편의 함수: 에러 코드로 적절한 예외 클래스 반환


def get_exception_class(error_code: str | ErrorCode) -> type[RAGException]:
    """에러 코드에 해당하는 예외 클래스 반환.

    Args:
        error_code: 에러 코드 (ErrorCode Enum 또는 문자열)

    Returns:
        해당 도메인의 예외 클래스

    Example:
        >>> exc_class = get_exception_class("AUTH-001")
        >>> exc_class.__name__
        'AuthError'
    """
    code_str = error_code.value if isinstance(error_code, ErrorCode) else error_code
    domain = code_str.split("-")[0]

    domain_map: dict[str, type[RAGException]] = {
        "AUTH": AuthError,
        "SESSION": SessionError,
        "SERVICE": ServiceError,
        "DOC": DocumentError,
        "UPLOAD": UploadError,
        "STORAGE": StorageError,
        "IMAGE": ImageError,
        "LLM": LLMError,
        "VECTOR": VectorError,
        "SEARCH": VectorError,  # SEARCH는 VECTOR와 같은 예외 사용
        "DB": DatabaseError,
        "CONFIG": ConfigError,
        "ROUTING": RoutingError,
        "EMBEDDING": EmbeddingError,
        "GENERAL": GeneralError,
        "API": GeneralError,  # API는 GENERAL과 같은 예외 사용
        "PIPE": PipelineTimeoutError,  # 파이프라인 타임아웃
    }

    return domain_map.get(domain, RAGException)


def wrap_exception(
    error: Exception,
    default_code: str | ErrorCode = "GENERAL-001",
    **context: Any,
) -> RAGException:
    """기존 예외를 RAGException으로 래핑.

    Args:
        error: 원본 예외
        default_code: 기본 에러 코드
        **context: 추가 컨텍스트 정보

    Returns:
        RAGException 또는 적절한 하위 클래스

    Example:
        >>> try:
        ...     raise ValueError("Invalid input")
        ... except Exception as e:
        ...     raise wrap_exception(e, "GENERAL-002", reason=str(e))
    """
    # 이미 RAGException이면 그대로 반환
    if isinstance(error, RAGException):
        return error

    # 에러 코드 문자열 변환
    code_str = default_code.value if isinstance(default_code, ErrorCode) else default_code

    # 컨텍스트에 원본 에러 정보 추가
    context["original_error_type"] = type(error).__name__
    context["original_error_message"] = str(error)

    # 적절한 예외 클래스 선택
    exc_class = get_exception_class(code_str)

    return exc_class(code_str, **context)
