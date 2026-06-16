"""에러 메시지 포맷팅 유틸리티.

에러 메시지와 해결 방법을 가져오고 포맷팅하는 함수들을 제공합니다.
"""

import os
from typing import Any

from app.lib.errors.messages import (
    ERROR_MESSAGES,
    get_message_template,
    get_solutions_list,
    get_user_facing_error,
)


def get_default_language() -> str:
    """기본 언어 가져오기.

    환경변수 ERROR_LANGUAGE로 기본 언어 설정 가능.
    설정되지 않은 경우 한국어("ko")를 기본값으로 사용.

    Returns:
        언어 코드 ("ko" 또는 "en")
    """
    lang = os.getenv("ERROR_LANGUAGE", "ko")
    return lang if lang in ("ko", "en") else "ko"


def get_error_message(error_code: str, lang: str | None = None, **kwargs: Any) -> str:
    """에러 메시지 가져오기 (포맷팅 포함).

    Args:
        error_code: 에러 코드 (예: "AUTH-001")
        lang: 언어 코드 ("ko" 또는 "en"). None이면 기본 언어 사용
        **kwargs: 메시지 포맷팅에 사용할 키워드 인자

    Returns:
        포맷팅된 에러 메시지

    Example:
        >>> get_error_message("DOC-002", lang="ko", reason="연결 실패")
        "문서 통계 조회 실패: 연결 실패"

        >>> get_error_message("UPLOAD-002", size=15, max_size=10)
        "파일 크기 초과: 15MB (최대 10MB)"
    """
    if lang is None:
        lang = get_default_language()

    template = get_message_template(error_code, lang)

    # 포맷팅 파라미터가 있으면 적용
    if kwargs:
        try:
            return template.format(**kwargs)
        except KeyError as e:
            # 포맷팅 실패 시 원본 템플릿과 함께 경고
            missing_key = str(e).strip("'")
            return f"{template} (포맷팅 오류: {missing_key} 누락)"

    return template


def get_error_solutions(error_code: str, lang: str | None = None) -> list[str]:
    """에러 해결 방법 가져오기.

    Args:
        error_code: 에러 코드 (예: "AUTH-001")
        lang: 언어 코드 ("ko" 또는 "en"). None이면 기본 언어 사용

    Returns:
        에러 해결 방법 리스트

    Example:
        >>> solutions = get_error_solutions("AUTH-001")
        >>> print(solutions[0])
        "프로덕션 환경에서 FASTAPI_AUTH_KEY 환경 변수를 설정하세요"
    """
    if lang is None:
        lang = get_default_language()

    return get_solutions_list(error_code, lang)


def format_error_response(
    error_code: str,
    lang: str | None = None,
    include_solutions: bool = True,
    **context: Any,
) -> dict[str, Any]:
    """에러 응답 JSON 생성.

    Args:
        error_code: 에러 코드 (예: "AUTH-001")
        lang: 언어 코드 ("ko" 또는 "en"). None이면 기본 언어 사용
        include_solutions: 해결 방법 포함 여부
        **context: 메시지 포맷팅에 사용할 키워드 인자

    Returns:
        에러 응답 딕셔너리

    Example:
        >>> response = format_error_response("DB-001", lang="en")
        >>> print(response)
        {
            "error_code": "DB-001",
            "message": "Cannot connect to PostgreSQL database: DATABASE_URL is not set",
            "solutions": [
                "Set DATABASE_URL environment variable",
                "Add database URL to .env file",
                "Verify PostgreSQL server is running (pg_isready)"
            ]
        }
    """
    if lang is None:
        lang = get_default_language()

    response: dict[str, Any] = {
        "error_code": error_code,
        "message": get_error_message(error_code, lang, **context),
    }

    if include_solutions:
        response["solutions"] = get_error_solutions(error_code, lang)

    return response


def format_user_facing_error(
    error_code: str, lang: str | None = None, **preserve: Any
) -> dict[str, Any]:
    """사용자 노출 3-필드 에러 detail 딕셔너리를 양언어로 생성한다.

    chat_router 등 raw 한국어 {error, message, suggestion, ...} detail을 양언어
    카탈로그(USER_FACING_ERRORS) 기반으로 전환하기 위한 헬퍼. 정의된 텍스트
    필드(error/message/suggestion)를 lang에 맞게 채우고, retry_after/session_id
    등 보존 필드를 그대로 병합한다.

    Args:
        error_code: 에러 코드 (예: "SESSION-005")
        lang: 언어 코드 ("ko"|"en"). None이면 기본 언어(ko).
        **preserve: 응답에 그대로 보존할 비텍스트 필드(retry_after, session_id 등)

    Returns:
        {error, message, suggestion, **preserve} 형태의 detail 딕셔너리

    Example:
        >>> format_user_facing_error("SERVICE-001", "en", retry_after=30)
        {'error': 'Service is initializing', 'message': '...', 'suggestion': '...',
         'retry_after': 30}
    """
    if lang is None:
        lang = get_default_language()

    detail: dict[str, Any] = dict(get_user_facing_error(error_code, lang))
    detail.update(preserve)
    return detail


def get_all_error_codes() -> list[str]:
    """모든 에러 코드 목록 가져오기.

    Returns:
        에러 코드 리스트

    Example:
        >>> codes = get_all_error_codes()
        >>> "AUTH-001" in codes
        True
        >>> len(codes)
        81
    """
    return sorted(ERROR_MESSAGES.keys())


def get_error_codes_by_domain(domain: str) -> list[str]:
    """특정 도메인의 에러 코드 목록 가져오기.

    Args:
        domain: 도메인 이름 (예: "AUTH", "DB", "VECTOR")

    Returns:
        해당 도메인의 에러 코드 리스트

    Example:
        >>> auth_codes = get_error_codes_by_domain("AUTH")
        >>> print(auth_codes)
        ['AUTH-001', 'AUTH-002', 'AUTH-003', 'AUTH-004', 'AUTH-005', 'AUTH-006']
    """
    prefix = f"{domain}-"
    return sorted([code for code in ERROR_MESSAGES.keys() if code.startswith(prefix)])
