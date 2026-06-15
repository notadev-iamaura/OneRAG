"""빈 화면(Empty State) 기본값 및 지원 로케일 로더.

지원 로케일과 로케일별 기본 텍스트(메인/보조 메시지, 추천 질문)를 config의
`empty_state` 섹션에서 외부화합니다. 도메인/언어 하드코딩을 피하기 위해
config 미설정 시 도메인 중립적인 코드 기본값(ko/en)으로 폴백합니다.

config 예시 (features/session.yaml의 empty_state 섹션):
    empty_state:
      supported_locales: ["ko", "en"]
      defaults:
        ko:
          mainMessage: "무엇을 도와드릴까요?"
          subMessage: "..."
          suggestions: ["...", "..."]
        en:
          mainMessage: "How can I help you?"
          ...
"""

from __future__ import annotations

from typing import Any

from app.lib.logger import get_logger

logger = get_logger(__name__)

# config 미설정 시 폴백 — 도메인 중립적 기본값(ko/en).
# 특정 서비스/언어(예: ja)에 종속되지 않도록 일반적인 안내 문구만 사용합니다.
_CODE_DEFAULT_LOCALES: tuple[str, ...] = ("ko", "en")
_CODE_DEFAULTS: dict[str, dict[str, Any]] = {
    "ko": {
        "mainMessage": "무엇을 도와드릴까요?",
        "subMessage": "AI가 참고 문서를 분석하여 정확한 답변을 제공합니다",
        "suggestions": [
            "이 문서에서 핵심 내용을 요약해주세요",
            "예시 질문 1",
            "예시 질문 2",
            "예시 질문 3",
        ],
    },
    "en": {
        "mainMessage": "How can I help you?",
        "subMessage": "AI analyzes reference documents to provide accurate answers",
        "suggestions": [
            "Summarize the key points of this document",
            "Sample question 1",
            "Sample question 2",
            "Sample question 3",
        ],
    },
}


def _load_empty_state_config() -> dict[str, Any]:
    """config의 empty_state 섹션을 안전하게 로드합니다 (실패 시 빈 dict)."""
    try:
        from app.lib.config_loader import load_config

        config = load_config()
        section = config.get("empty_state")
        return section if isinstance(section, dict) else {}
    except Exception as e:  # noqa: BLE001 - config 로드 실패해도 코드 기본값으로 폴백
        logger.debug(f"empty_state config 로드 실패, 코드 기본값 사용: {e}")
        return {}


def get_supported_locales() -> tuple[str, ...]:
    """지원 로케일 목록을 반환합니다 (config 우선, 미설정 시 코드 기본값)."""
    section = _load_empty_state_config()
    locales = section.get("supported_locales")
    if isinstance(locales, list) and locales:
        # 문자열만 정규화하여 채택
        normalized = tuple(str(loc) for loc in locales if isinstance(loc, str) and loc.strip())
        if normalized:
            return normalized
    return _CODE_DEFAULT_LOCALES


def get_default_empty_state(locale: str) -> dict[str, Any]:
    """로케일별 기본 빈 화면 설정을 반환합니다 (config 우선, 미설정 시 코드 기본값).

    config/코드 어디에도 해당 로케일 기본값이 없으면, 첫 코드 기본 로케일(ko)을
    최종 폴백으로 사용해 절대 빈 화면이 깨지지 않도록 합니다.
    """
    section = _load_empty_state_config()
    defaults = section.get("defaults")
    if isinstance(defaults, dict):
        entry = defaults.get(locale)
        if isinstance(entry, dict) and _is_valid_entry(entry):
            return entry

    if locale in _CODE_DEFAULTS:
        return _CODE_DEFAULTS[locale]

    # 최종 폴백: 첫 코드 기본 로케일
    return _CODE_DEFAULTS[_CODE_DEFAULT_LOCALES[0]]


def _is_valid_entry(entry: dict[str, Any]) -> bool:
    """기본값 항목이 필수 키(mainMessage/subMessage/suggestions)를 갖췄는지 확인."""
    return (
        isinstance(entry.get("mainMessage"), str)
        and isinstance(entry.get("subMessage"), str)
        and isinstance(entry.get("suggestions"), list)
    )
