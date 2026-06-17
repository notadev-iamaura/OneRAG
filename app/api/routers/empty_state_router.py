"""빈 화면(Empty State) 설정 API 라우터.

챗봇 시작 화면의 메인/보조 메시지와 추천 질문을 로케일별로 서버에서 관리합니다.
기존 프론트엔드는 localStorage(관리자 브라우저에만 반영)를 사용했으나, 서버 저장으로
이관하여 관리자가 저장하면 모든 사용자에게 반영됩니다(다중 사용자 결함 수정).

엔드포인트:
- GET    /api/chat-empty-state               (공개) — 전 로케일 설정(저장값 없으면 기본값)
- PUT    /api/admin/chat-empty-state/{locale} (관리자, X-API-Key) — 로케일 설정 저장
- DELETE /api/admin/chat-empty-state/{locale} (관리자, X-API-Key) — 기본값으로 리셋

인증:
- 관리자 쓰기 엔드포인트는 OneRAG 표준 관리자 인증(`get_api_key`, FASTAPI_AUTH_KEY)을
  사용합니다. 클라이언트 노출용 EMPTY_STATE_API_KEY는 공개 OSS 배포 시
  누구나 문구를 수정할 수 있는 위험이 있어 제거했습니다.

범용성:
- 지원 로케일과 로케일별 기본 텍스트는 config(`empty_state` 섹션)에서 외부화하며,
  미설정 시 도메인 중립적인 코드 기본값(ko/en)으로 폴백합니다.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Path, Request
from pydantic import BaseModel, Field, field_validator

from app.api.routers._empty_state_defaults import (
    get_default_empty_state,
    get_supported_locales,
)
from app.infrastructure.storage.chat.empty_state_settings_store import (
    ChatEmptyStateSettingsStore,
)
from app.lib.auth import get_api_key
from app.lib.errors import ErrorCode, get_error_message
from app.lib.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(tags=["EmptyState"])


def _resolve_request_language(request: Request) -> str:
    """Accept-Language 헤더로 사용자 노출 언어 결정 (ko 기본).

    en이 ko보다 먼저 명시되면 영어, 그 외에는 한국어를 반환합니다.
    """
    accept_language = (request.headers.get("accept-language") or "").lower()
    en_idx = accept_language.find("en")
    ko_idx = accept_language.find("ko")
    if en_idx != -1 and (ko_idx == -1 or en_idx < ko_idx):
        return "en"
    return "ko"

# 검증 한도 (프론트엔드 chatSettingsService.validateSettings와 동일)
_MAIN_MAX = 100
_SUB_MAX = 200
_SUGGESTION_MAX = 200
_SUGGESTIONS_MIN = 1
_SUGGESTIONS_MAX = 10


# ── 의존성 주입 (main.py lifespan에서 set_store 호출) ──
_store: ChatEmptyStateSettingsStore | None = None


def set_store(store: ChatEmptyStateSettingsStore) -> None:
    """빈 화면 설정 스토어 주입."""
    global _store
    _store = store
    logger.info("EmptyStateSettingsStore 주입 완료")


def _get_store() -> ChatEmptyStateSettingsStore:
    """주입된 스토어를 반환. 미주입 시 기본 db_manager로 지연 생성."""
    global _store
    if _store is None:
        _store = ChatEmptyStateSettingsStore()
    return _store


# ── 요청/응답 모델 ──
class EmptyStateSettingsBody(BaseModel):
    """빈 화면 설정 저장 요청 본문."""

    mainMessage: str = Field(..., description="메인 환영 메시지")
    subMessage: str = Field(..., description="보조 메시지")
    suggestions: list[str] = Field(..., description="추천 질문 목록")

    @field_validator("mainMessage")
    @classmethod
    def _validate_main(cls, v: str) -> str:
        text = (v or "").strip()
        if not text:
            raise ValueError("mainMessage는 비어 있을 수 없습니다")
        if len(v) > _MAIN_MAX:
            raise ValueError(f"mainMessage는 {_MAIN_MAX}자를 초과할 수 없습니다")
        return v

    @field_validator("subMessage")
    @classmethod
    def _validate_sub(cls, v: str) -> str:
        text = (v or "").strip()
        if not text:
            raise ValueError("subMessage는 비어 있을 수 없습니다")
        if len(v) > _SUB_MAX:
            raise ValueError(f"subMessage는 {_SUB_MAX}자를 초과할 수 없습니다")
        return v

    @field_validator("suggestions")
    @classmethod
    def _validate_suggestions(cls, v: list[str]) -> list[str]:
        if not isinstance(v, list):
            raise ValueError("suggestions는 배열이어야 합니다")
        if len(v) < _SUGGESTIONS_MIN:
            raise ValueError("추천 질문은 최소 1개 필요합니다")
        if len(v) > _SUGGESTIONS_MAX:
            raise ValueError(f"추천 질문은 최대 {_SUGGESTIONS_MAX}개까지 가능합니다")
        for i, s in enumerate(v):
            if not isinstance(s, str):
                raise ValueError(f"추천 질문{i + 1}은 문자열이어야 합니다")
            if not s.strip():
                raise ValueError(f"추천 질문{i + 1}은 비어 있을 수 없습니다")
            if len(s) > _SUGGESTION_MAX:
                raise ValueError(
                    f"추천 질문{i + 1}은 {_SUGGESTION_MAX}자를 초과할 수 없습니다"
                )
        if len({s.strip() for s in v}) != len(v):
            raise ValueError("중복된 추천 질문이 있습니다")
        return v


def _public_view(data: dict[str, Any]) -> dict[str, Any]:
    """공개 응답 형태(mainMessage/subMessage/suggestions)만 추출."""
    return {
        "mainMessage": data["mainMessage"],
        "subMessage": data["subMessage"],
        "suggestions": list(data.get("suggestions", [])),
    }


def _validate_locale(locale: str, lang: str = "ko") -> str:
    supported = get_supported_locales()
    if locale not in supported:
        raise HTTPException(
            status_code=400,
            detail=get_error_message(
                ErrorCode.EMPTY_001.value,
                lang,
                locale=locale,
                supported=", ".join(supported),
            ),
        )
    return locale


# ── 엔드포인트 ──
@router.get("/chat-empty-state")
async def get_empty_state_settings() -> dict[str, dict[str, Any]]:
    """전 로케일 빈 화면 설정 반환 (공개). 저장값이 없는 로케일은 기본값으로 폴백."""
    stored = await _get_store().get_all()
    result: dict[str, dict[str, Any]] = {}
    for locale in get_supported_locales():
        if locale in stored:
            result[locale] = _public_view(stored[locale])
        else:
            result[locale] = _public_view(get_default_empty_state(locale))
    return result


@router.put(
    "/admin/chat-empty-state/{locale}",
    dependencies=[Depends(get_api_key)],
)
async def put_empty_state_settings(
    request: Request,
    body: EmptyStateSettingsBody,
    locale: str = Path(..., description="로케일 코드 (예: ko|en)"),
) -> dict[str, Any]:
    """로케일 빈 화면 설정 저장 (관리자, X-API-Key)."""
    lang = _resolve_request_language(request)
    _validate_locale(locale, lang)
    saved = await _get_store().upsert(
        locale=locale,
        main_message=body.mainMessage,
        sub_message=body.subMessage,
        suggestions=body.suggestions,
    )
    if saved is None:
        raise HTTPException(
            status_code=503,
            detail=get_error_message(ErrorCode.EMPTY_002.value, lang),
        )
    logger.info(f"빈 화면 설정 저장(API): locale={locale}")
    return _public_view(saved)


@router.delete(
    "/admin/chat-empty-state/{locale}",
    dependencies=[Depends(get_api_key)],
)
async def reset_empty_state_settings(
    request: Request,
    locale: str = Path(..., description="로케일 코드 (예: ko|en)"),
) -> dict[str, Any]:
    """로케일 빈 화면 설정을 기본값으로 리셋 (관리자, X-API-Key)."""
    lang = _resolve_request_language(request)
    _validate_locale(locale, lang)
    ok = await _get_store().delete(locale)
    if not ok:
        raise HTTPException(
            status_code=503,
            detail=get_error_message(ErrorCode.EMPTY_003.value, lang),
        )
    logger.info(f"빈 화면 설정 리셋(API): locale={locale}")
    return _public_view(get_default_empty_state(locale))
