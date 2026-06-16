"""에러 처리 라이브러리.

RAG 시스템의 에러 코드, 메시지, 예외 클래스를 제공합니다.

주요 컴포넌트:
- ErrorCode: 에러 코드 Enum (100+개 에러 코드)
- 예외 클래스: RAGException 및 도메인별 예외 클래스
- 포맷팅 함수: 에러 메시지 및 응답 생성 함수
- 양언어 지원: 한국어(기본) 및 영어 메시지

사용 예시:
    >>> from app.lib.errors import ErrorCode, AuthError, get_error_message
    >>>
    >>> # 예외 생성 및 발생
    >>> raise AuthError(ErrorCode.AUTH_001)
    >>>
    >>> # 에러 메시지 가져오기 (한국어 기본)
    >>> message = get_error_message("DB-001")
    >>> print(message)
    "PostgreSQL 데이터베이스에 연결할 수 없습니다: DATABASE_URL이 설정되지 않았습니다"
    >>>
    >>> # 영어 메시지
    >>> message_en = get_error_message("DB-001", lang="en")
    >>> print(message_en)
    "Cannot connect to PostgreSQL database: DATABASE_URL is not set"
    >>>
    >>> # 에러 응답 생성 (양언어)
    >>> try:
    ...     raise DatabaseError(ErrorCode.DB_001)
    ... except DatabaseError as e:
    ...     response_ko = e.to_dict(lang="ko")
    ...     response_en = e.to_dict(lang="en")
"""

# 에러 코드
from app.lib.errors.codes import ErrorCode

# 예외 클래스
from app.lib.errors.exceptions import (
    AuthError,
    ConfigError,
    DatabaseError,
    DocumentError,
    EmbeddingError,
    GeneralError,
    ImageError,
    LLMError,
    PipelineTimeoutError,
    RAGError,  # 레거시 호환 별칭 (RAGException)
    RAGException,
    RoutingError,
    SearchUnavailableError,
    ServiceError,
    SessionError,
    StorageError,
    UploadError,
    VectorError,
    get_exception_class,
    wrap_exception,
)

# 포맷팅 함수
from app.lib.errors.formatter import (
    format_error_response,
    format_user_facing_error,
    get_all_error_codes,
    get_default_language,
    get_error_codes_by_domain,
    get_error_message,
    get_error_solutions,
)

# 레거시 호환: 이전 코드에서 사용하던 예외 별칭
RetrievalError = VectorError  # 검색 관련은 VectorError 사용
GenerationError = LLMError  # LLM 생성 관련은 LLMError 사용

__all__ = [
    # 에러 코드
    "ErrorCode",
    # 예외 클래스 (신규)
    "RAGException",
    "AuthError",
    "SessionError",
    "ServiceError",
    "DocumentError",
    "UploadError",
    "StorageError",
    "ImageError",
    "LLMError",
    "VectorError",
    "SearchUnavailableError",  # 검색 백엔드 전면 불능 (VectorError 하위)
    "DatabaseError",
    "ConfigError",
    "RoutingError",
    "EmbeddingError",
    "GeneralError",
    "PipelineTimeoutError",
    # 유틸리티 함수
    "get_exception_class",
    "wrap_exception",
    # 포맷팅 함수
    "get_error_message",
    "get_error_solutions",
    "format_error_response",
    "format_user_facing_error",
    "get_default_language",
    "get_all_error_codes",
    "get_error_codes_by_domain",
    # 레거시 호환 별칭
    "RAGError",  # = RAGException
    "RetrievalError",  # = VectorError
    "GenerationError",  # = LLMError
]
