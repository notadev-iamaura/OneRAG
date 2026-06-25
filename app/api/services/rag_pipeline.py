"""
RAG Pipeline 모듈

7개 독립 단계로 분해된 RAG 파이프라인 오케스트레이터.
각 단계는 독립적으로 테스트 및 최적화 가능.

단계:
1. route_query: 쿼리 라우팅 (규칙 기반 + LLM 폴백)
2. prepare_context: 세션 컨텍스트 + 쿼리 확장
3. retrieve_documents: MongoDB Atlas 하이브리드 검색
4. rerank_documents: 리랭킹 (선택적)
5. generate_answer: LLM 답변 생성
6. format_sources: Source 객체 변환
7. build_result: 최종 응답 구성

작성일: 2025-01-27
목적: TASK-H4 구현 - 150줄 블랙박스 함수 → 7개 독립 메서드
"""

from __future__ import annotations

import asyncio
import os
import re
import time
import unicodedata
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any, TypeVar, cast

from ...lib.circuit_breaker import CircuitBreakerOpenError
from ...lib.errors import ErrorCode, GenerationError, PipelineTimeoutError, RetrievalError
from ...lib.langfuse_client import langfuse_context, observe  # Langfuse 트레이싱
from ...lib.logger import get_logger
from ...lib.metrics import CostTracker, PerformanceMetrics
from ...lib.prompt_sanitizer import contains_output_leakage, validate_document
from ...lib.score_normalizer import RRFScoreNormalizer  # RRF 점수 정규화
from ...lib.types import RAGResultDict
from ...modules.core.retrieval.interfaces import IMultiQueryRetriever, SearchResult
from .source_contract import normalize_citation_source_payload, normalize_source_payload

if TYPE_CHECKING:
    from ...modules.core.agent.orchestrator import AgentOrchestrator
    from ...modules.core.generation.generator import GenerationResult
    from ...modules.core.sql_search import SQLSearchResult, SQLSearchService
    from ..schemas.debug import DebugTrace

logger = get_logger(__name__)

# stage 타임아웃 헬퍼(_run_stage_with_timeout)의 반환 타입을 보존하기 위한 TypeVar
_StageT = TypeVar("_StageT")

# Kept as a patchable module attribute for existing tests while avoiding the
# heavy routing module import until route_query actually runs.
RuleBasedRouter: Any | None = None


# 문서 미리보기 추출 실패 시 대체 문구의 코드 기본값(한국어). 함수 기본 인자에서
# 참조하므로 함수 정의보다 먼저 선언한다. rag.yaml generation_fallback로 외부화된다.
DOCUMENT_PREVIEW_UNAVAILABLE_MESSAGE = "문서 내용 요약을 표시할 수 없습니다"


def _resolve_generation_fallback_message(configured: Any, default: str) -> str:
    """generation_fallback 메시지를 config 우선으로 해소한다(미설정/공백이면 기본값).

    Args:
        configured: rag.yaml에서 읽은 원시 값(문자열/None/기타).
        default: 코드 내장 기본 문자열(회귀 0 보장용).

    Returns:
        유효한 문자열(앞뒤 공백만 있는 값은 무효로 보아 default 사용).
    """
    if isinstance(configured, str) and configured.strip():
        return configured
    return default


def _extract_fallback_document_preview(
    document: Any,
    max_chars: int = 300,
    unavailable_message: str = DOCUMENT_PREVIEW_UNAVAILABLE_MESSAGE,
) -> str:
    """Return user-safe document text for LLM outage fallback responses.

    추출 실패 시 반환하는 대체 문구는 unavailable_message로 주입할 수 있다.
    기본값은 코드 내장 한국어 상수로 기존 동작과 동치다(회귀 0).
    """
    for attr in ("page_content", "content", "text"):
        value = getattr(document, attr, None)
        if isinstance(value, str) and value.strip():
            return value.strip()[:max_chars]

    if isinstance(document, dict):
        for key in ("page_content", "content", "text"):
            value = document.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()[:max_chars]

    return unavailable_message


_RERANK_METADATA_KEYS = {"rerank_score", "rerank_method", "original_score"}
_CONTEXT_EXPANSION_MAX_WINDOW = 3

# 환각 방지 게이트(GAP C): 질문 기간과 문서 기간이 완전 불일치할 때 사용하는 보류 메시지.
# 코드 내장 기본값=한국어. 운영자는 rag.yaml hallucination_gate.no_answer_message로
# 코드 포크 없이 오버라이드한다 → 미설정 시 회귀 0(아래 기본 문자열 그대로 사용).
HALLUCINATION_GATE_NO_ANSWER_MESSAGE = (
    "질문하신 기간에 해당하는 내용을 제공된 문서에서 확인하지 못했습니다. "
    "다른 기간의 데이터로 추정하지 않았습니다. 정확한 기간을 확인하시거나 "
    "관련 문서를 추가해 주세요."
)

# 생성 모듈 부재 시 사용자에게 반환되는 답변 폴백 (코드 내장 기본값=한국어).
# 운영자는 rag.yaml generation_fallback.module_missing_message로 오버라이드한다 → 회귀 0.
GENERATION_MODULE_MISSING_MESSAGE = "죄송합니다. 답변을 생성할 수 없습니다."

# LLM 생성 서킷브레이커 폴백 답변 (코드 내장 기본값=한국어).
# 형제 메시지(hallucination_gate/generation_fallback.module_missing_message)와 동일하게
# rag.yaml generation_fallback.* 로 외부화한다 → 미설정 시 회귀 0(아래 기본 문자열 사용).
# (document_preview_unavailable 메시지는 함수 기본 인자 참조를 위해 상단에 선언됨)
# - with_docs: 문서는 찾았으나 LLM 장애로 상세 답변이 어려운 경우. {content} 자리에
#   안전 추출된 문서 미리보기가 치환된다(.replace 사용, 플레이스홀더 보존 필수).
# - no_docs: 문서도 못 찾고 LLM도 장애인 경우.
GENERATION_FALLBACK_WITH_DOCS_MESSAGE = (
    "관련 정보를 찾았습니다:\n\n{content}...\n\n"
    "(현재 AI 서비스 일시 장애로 상세 답변이 어렵습니다. 잠시 후 다시 시도해주세요.)"
)
GENERATION_FALLBACK_NO_DOCS_MESSAGE = (
    "죄송합니다. 관련 정보를 찾을 수 없으며, 현재 AI 서비스도 일시적으로 "
    "이용할 수 없습니다. 다른 방식으로 질문해 주시겠어요?"
)

# 프롬프트 누출(output leakage) 감지 시 답변을 교체하는 보안 메시지 (코드 내장 기본=한국어).
# 통짜 경로와 Self-RAG 경로 두 곳에서 동일하게 사용되던 중복 문자열을 단일 진실원천으로
# 통합한다. 형제 메시지와 동일하게 rag.yaml generation_fallback.prompt_leakage_blocked_message
# 로 외부화한다 → 미설정 시 회귀 0(아래 기본 문자열 사용). 비한국어 운영자는 코드 포크
# 없이 이 값으로 해당 언어의 보안 메시지로 교체할 수 있다.
PROMPT_LEAKAGE_BLOCKED_MESSAGE = (
    "보안 정책에 따라 내부 지시사항은 공개되지 않습니다. "
    "문서 기반 답변이 필요한 내용을 다시 질문해주세요."
)

# 생성 결과 타입 가드 실패(예상치 못한 타입) 시 사용자에게 노출되는 안전 메시지
# (코드 내장 기본=한국어). rag.yaml generation_fallback.type_error_message로 외부화한다
# → 미설정 시 회귀 0. 운영자는 코드 포크 없이 해당 언어로 교체 가능.
GENERATION_TYPE_ERROR_MESSAGE = "답변 생성 중 오류가 발생했습니다."

# Self-RAG 품질 게이트에서 최종 품질 점수가 임계값 미만일 때 답변을 거부하며
# 반환하는 메시지 (코드 내장 기본=한국어). answer(상세)와 text(축약) 2종으로 구성된다.
# self_rag.yaml self_rag.low_quality_reject_message / low_quality_reject_text로 외부화한다
# → 미설정 시 회귀 0(아래 기본 문자열 사용). 비한국어 운영자는 코드 포크 없이 교체 가능.
SELF_RAG_LOW_QUALITY_REJECT_MESSAGE = (
    "죄송합니다. 확실한 정보를 찾지 못했습니다. "
    "질문을 구체적으로 다시 작성해주시겠어요?"
)
SELF_RAG_LOW_QUALITY_REJECT_TEXT = "죄송합니다. 확실한 정보를 찾지 못했습니다."

# ============================================================================
# 정확 식별자(exact-identifier) 검색 보강 패턴 (GAP A) - 언어무관/도메인무관
# ============================================================================
# dense·BM25가 공히 놓치기 쉬운 고유 식별자(모델코드/에러코드 등)의 리콜을 보완한다.
# 원본 구현의 언어 전용 휴리스틱은 제거하고 generic 식별자/라틴 구문만 채택한다.
#
# 식별자: 대문자 시작 + (대문자/숫자) 토큰이 하이픈(각종 대시/장음)으로 연결된 형태.
# 예) GP-1200X, ERR-404, RTX-4090. 좌우 경계로 알파벳·숫자 인접 시 매칭 제외.
_EXACT_IDENTIFIER_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])"
    r"[A-Z][A-Z0-9]{1,}(?:[-‐‑‒–—―ー－][A-Z0-9]{2,})+"
    r"(?![A-Za-z0-9])"
)
# 라틴 다중 단어 구문(예: "error handling"). 너무 짧은 구문은 소비자가 별도로 필터링.
_LATIN_PHRASE_PATTERN = re.compile(r"\b[A-Za-z][A-Za-z0-9]*(?:\s+[A-Za-z][A-Za-z0-9]*)+\b")
# 캘린더 연도(20xx)만 매칭(언어무관). 특정 회계연도 표기 휴리스틱은 채택하지 않는다.
_CALENDAR_YEAR_PATTERN = re.compile(r"(?<!\d)(20\d{2})(?!\d)")

# ============================================================================
# 명시 문서명 기반 컨텍스트 보강(named-document chunk rescue) 패턴 (GAP #1)
# ============================================================================
# 사용자가 질문에서 파일명(확장자) 또는 따옴표 인용구로 특정 문서를 지목하면,
# 벡터 검색이 그 문서를 놓쳐도 list_documents/get_document_chunks로 해당 문서
# 청크를 직접 fetch해 검색 결과 앞에 prepend한다. 원본 구현의 특정 언어 전용 신호어
# ·표/행(row/컬럼) 휴리스틱은 제거하고 범용 패턴만 채택.
#
# 파일명: 따옴표(ASCII/유니코드)로 감싼 `...확장자` 형태. 확장자는 GAP 명세 9종.
_DOCUMENT_FILENAME_PATTERN = re.compile(
    r"""['"“”‘’「」『』]([^'"“”‘’「」『』]+?\.(?:pdf|docx|pptx|xlsx|csv|txt|md|html|json))['"“”‘’「」『』]"""
    r"""|((?:[^\s'"“”‘’「」『』])+?\.(?:pdf|docx|pptx|xlsx|csv|txt|md|html|json))(?![A-Za-z0-9])""",
    re.IGNORECASE,
)
# 따옴표 인용구(3자 이상). 파일명으로 이미 잡힌 것은 소비자가 제외한다.
_QUOTED_TEXT_PATTERN = re.compile(r"""['"“”‘’「」『』]([^'"“”‘’「」『』]{3,})['"“”‘’「」『』]""")
# 본문 라인에서 고가치 신호(연락처/URL/숫자+단위/날짜)를 식별하는 범용 패턴.
# 통화 단위는 특정 언어에 치우치지 않도록 국제 기본셋(원/₩/¥/元/円/$/€/£/usd)을
# 포함한다(한국어 기본 '원'을 유지하면서 타 통화도 동등 인식 — 회귀 0).
_NAMED_DOCUMENT_HIGH_VALUE_PATTERN = re.compile(
    r"(?:https?://|www\.|tel|fax|e-?mail"
    r"|[0-9]+(?:\.[0-9]+)?\s*(?:%|kg|g|mm|cm|km|m|usd|원|₩|¥|元|円|\$|€|£)"
    r"|\b20\d{2}[-/.]?\d{0,2}[-/.]?\d{0,2}\b)",
    re.IGNORECASE,
)
# 매칭용 토큰화 패턴: ASCII 영숫자 런 또는 CJK(한/중/일) 문자 런.
_NAMED_DOCUMENT_TOKEN_PATTERN = re.compile(
    r"[a-z0-9]+|[぀-ヿ㐀-䶿一-鿿가-힣]+"
)
# 문서 목록 조회 시 한 번에 가져올 최대 문서 수(명시 문서 매칭용 풀스캔).
_NAMED_DOCUMENT_LIST_PAGE_SIZE = 10000


def _normalize_named_document_text(value: str | None) -> str:
    """명시 문서 매칭/스코어링용 정규화(GAP #1, 언어무관).

    NFKC 정규화 + lower 후 공백을 제거해, 전각/반각·대소문자·공백 차이에 무관하게
    파일명/본문 토큰을 비교할 수 있게 한다.
    """
    if not value:
        return ""
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", value).lower())


def _requested_document_filenames(message: str) -> list[str]:
    """질문에서 지목된 문서 파일명을 추출한다(GAP #1).

    따옴표로 감싼 파일명과 비따옴표(공백 구분) 파일명을 모두 인식하며,
    등장 순서를 보존한 채 중복을 제거한다.
    """
    filenames: list[str] = []
    for match in _DOCUMENT_FILENAME_PATTERN.finditer(message):
        filename = (match.group(1) or match.group(2) or "").strip()
        if filename:
            filenames.append(filename)
    return list(dict.fromkeys(filenames))


def _quoted_content_hints(message: str) -> list[str]:
    """질문의 따옴표 인용구를 추출한다(GAP #1, 파일명 제외).

    파일명으로 이미 인식된 따옴표 내용은 제외하고, 정규화 키 기준 중복을 제거한다.
    """
    filenames = {_normalize_named_document_text(name) for name in _requested_document_filenames(message)}
    hints: list[str] = []
    for match in _QUOTED_TEXT_PATTERN.finditer(message):
        hint = _normalize_named_document_text(match.group(1).strip())
        if hint and hint not in filenames:
            hints.append(hint)
    return list(dict.fromkeys(hint for hint in hints if hint))


def _named_document_match_terms(query: str) -> set[str]:
    """본문 매칭용 질의 토큰 집합을 만든다(GAP #1, 언어무관).

    ASCII 토큰은 3자 이상만, CJK 토큰은 3~8자 n-gram으로 확장해 부분 일치를 잡는다.
    토큰 폭증을 막기 위해 상한(240)을 둔다.
    """
    normalized_query = _normalize_named_document_text(query)
    terms: set[str] = set()
    for token in _NAMED_DOCUMENT_TOKEN_PATTERN.findall(normalized_query):
        if token.isascii():
            if len(token) >= 3:
                terms.add(token)
            continue
        max_size = min(8, len(token))
        for size in range(3, max_size + 1):
            for start in range(0, len(token) - size + 1):
                terms.add(token[start : start + size])
                if len(terms) >= 240:
                    return terms
    return terms


def _document_matches_requested_filename(filename: str, document: Any) -> bool:
    """문서 메타데이터가 지목 파일명과 일치하는지 판정한다(GAP #1).

    파일명 전체와 확장자 제거 stem을 모두 정규화해 비교하므로, 경로/확장자/표기
    차이에 관대하게 매칭한다.
    """
    requested = _normalize_named_document_text(os.path.basename(filename))
    requested_stem = _normalize_named_document_text(
        os.path.splitext(os.path.basename(filename))[0]
    )
    metadata = _document_metadata(document)
    candidates: list[Any] = [
        metadata.get("source_file"),
        metadata.get("filename"),
        metadata.get("document_name"),
        metadata.get("file_name"),
    ]
    if isinstance(document, dict):
        candidates.extend(
            [
                document.get("filename"),
                document.get("document_name"),
                document.get("source_file"),
            ]
        )
    for candidate in candidates:
        if not isinstance(candidate, str) or not candidate:
            continue
        normalized = _normalize_named_document_text(os.path.basename(candidate))
        normalized_stem = _normalize_named_document_text(
            os.path.splitext(os.path.basename(candidate))[0]
        )
        if normalized == requested or normalized_stem == requested_stem:
            return True
    return False


def _is_numeric_score(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _document_metadata(document: Any) -> dict[str, Any]:
    metadata = (
        document.get("metadata")
        if isinstance(document, dict)
        else getattr(document, "metadata", None)
    )
    return metadata if isinstance(metadata, dict) else {}


def _ensure_document_metadata(document: Any) -> dict[str, Any]:
    if isinstance(document, dict):
        metadata = document.get("metadata")
        if not isinstance(metadata, dict):
            metadata = {}
            document["metadata"] = metadata
        return metadata

    metadata = getattr(document, "metadata", None)
    if not isinstance(metadata, dict):
        metadata = {}
        try:
            document.metadata = metadata
        except Exception:
            return {}
    return metadata


def _document_identity(document: Any) -> Any:
    if isinstance(document, dict):
        metadata = _document_metadata(document)
        return (
            document.get("id")
            or document.get("document_id")
            or metadata.get("document_id")
            or metadata.get("source_id")
            or metadata.get("source_file")
            or id(document)
        )

    metadata = _document_metadata(document)
    return (
        getattr(document, "id", None)
        or getattr(document, "document_id", None)
        or metadata.get("document_id")
        or metadata.get("source_id")
        or metadata.get("source_file")
        or id(document)
    )


def _document_score(document: Any) -> float | None:
    score = document.get("score") if isinstance(document, dict) else getattr(document, "score", None)
    if _is_numeric_score(score):
        return float(score)

    metadata = _document_metadata(document)
    for key in ("score", "rerank_score", "retrieval_score"):
        metadata_score = metadata.get(key)
        if _is_numeric_score(metadata_score):
            return float(metadata_score)
    return None


def _snapshot_rerank_inputs(documents: list[Any]) -> list[tuple[Any, float | None]]:
    return [(_document_identity(document), _document_score(document)) for document in documents]


def _has_rerank_metadata(document: Any) -> bool:
    metadata = _document_metadata(document)
    return any(key in metadata for key in _RERANK_METADATA_KEYS)


def _same_score(left: float | None, right: float | None) -> bool:
    if left is None or right is None:
        return left is right
    return abs(left - right) < 1e-12


def _is_noop_rerank(
    original_snapshot: list[tuple[Any, float | None]],
    ranked_results: list[Any],
) -> bool:
    if len(original_snapshot) != len(ranked_results):
        return False
    if any(_has_rerank_metadata(document) for document in ranked_results):
        return False

    ranked_snapshot = _snapshot_rerank_inputs(ranked_results)
    return all(
        original_identity == ranked_identity and _same_score(original_score, ranked_score)
        for (original_identity, original_score), (ranked_identity, ranked_score) in zip(
            original_snapshot, ranked_snapshot, strict=True
        )
    )


def _annotate_rerank_scores(
    original_snapshot: list[tuple[Any, float | None]],
    ranked_results: list[Any],
    *,
    reranked: bool,
) -> None:
    original_scores_by_identity = {
        identity: score
        for identity, score in original_snapshot
        if score is not None
    }
    for document in ranked_results:
        metadata = _ensure_document_metadata(document)
        identity = _document_identity(document)
        retrieval_score = original_scores_by_identity.get(identity)
        if retrieval_score is not None:
            metadata.setdefault("retrieval_score", retrieval_score)
        if reranked:
            rerank_score = _document_score(document)
            if rerank_score is not None:
                metadata.setdefault("rerank_score", rerank_score)


def _coerce_bool(value: Any, *, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
        return default
    return bool(value)


def _coerce_bounded_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    """value를 int로 변환하고 [minimum, maximum] 범위로 clamp한다(#33).

    변환 불가 시 default를 사용한다.
    """
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(parsed, maximum))


def _coerce_optional_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _coerce_positive_int(value: Any, default: int) -> int:
    """value를 양의 int로 변환한다(GAP A). 변환 불가/0 이하면 최소 1 보장."""
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(1, parsed)


def _document_value(document: Any, *keys: str) -> Any:
    if isinstance(document, dict):
        for key in keys:
            value = document.get(key)
            if value not in (None, ""):
                return value

    metadata = _document_metadata(document)
    for key in keys:
        value = metadata.get(key)
        if value not in (None, ""):
            return value

    for key in keys:
        value = getattr(document, key, None)
        if value not in (None, ""):
            return value
    return None


def _document_content(document: Any) -> str:
    value = _document_value(document, "content", "page_content", "text")
    return value if isinstance(value, str) else ""


def _normalize_exact_match_text(value: str | None) -> str:
    """정확 매칭 비교용 정규화(GAP A).

    NFKC 정규화 + casefold 후 하이픈/공백/구분기호를 제거해, 표기 차이(전각/반각,
    하이픈 종류, 공백)에 무관하게 식별자 포함 여부를 비교할 수 있게 한다.
    """
    if not value:
        return ""
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return re.sub(r"[-‐‑‒–—―ー－\s_./:：]+", "", normalized)


def _exact_identifier_terms(query: str) -> list[str]:
    """질문에서 정확 식별자 토큰을 추출한다(GAP A, 언어무관).

    NFKC 정규화 후 _EXACT_IDENTIFIER_PATTERN으로 매칭하며, 정규화 키 기준 중복 제거.
    """
    seen: set[str] = set()
    terms: list[str] = []
    for match in _EXACT_IDENTIFIER_PATTERN.finditer(unicodedata.normalize("NFKC", query)):
        term = match.group(0).strip()
        key = _normalize_exact_match_text(term)
        if key and key not in seen:
            seen.add(key)
            terms.append(term)
    return terms


def _latin_phrase_terms(query: str) -> list[str]:
    """질문에서 라틴 다중 단어 구문을 추출한다(GAP A, 언어무관).

    4자 미만 구문은 신호가 약하므로 제외하고, casefold 기준 중복을 제거한다.
    """
    seen: set[str] = set()
    terms: list[str] = []
    for match in _LATIN_PHRASE_PATTERN.finditer(unicodedata.normalize("NFKC", query)):
        term = re.sub(r"\s+", " ", match.group(0)).strip()
        if len(term) < 4:
            continue
        key = term.casefold()
        if key not in seen:
            seen.add(key)
            terms.append(term)
    return terms


def _document_text_for_exact_signals(document: Any) -> str:
    """정확 신호 매칭에 사용할 문서 텍스트(본문 + 식별 메타) 결합(GAP A)."""
    metadata = _document_metadata(document)
    parts = [
        _document_content(document),
        metadata.get("source_file"),
        metadata.get("source"),
        metadata.get("document_name"),
        metadata.get("title"),
    ]
    return "\n".join(str(part) for part in parts if part)


def _context_document_id(document: Any) -> str | None:
    value = _document_value(document, "document_id", "doc_id")
    return str(value) if value not in (None, "") else None


def _context_chunk_index(document: Any) -> int | None:
    return _coerce_optional_int(_document_value(document, "chunk_index"))


def _context_chunk_identity(document: Any) -> tuple[str, str, int] | tuple[str, str] | tuple[str, int]:
    document_id = _context_document_id(document)
    chunk_index = _context_chunk_index(document)
    if document_id is not None and chunk_index is not None:
        return ("chunk", document_id, chunk_index)

    document_id = _document_value(document, "id")
    if document_id not in (None, ""):
        return ("id", str(document_id))
    return ("object", id(document))


def _chunk_to_search_result(
    chunk: dict[str, Any],
    *,
    source_document: Any,
    source_chunk_index: int,
) -> SearchResult | None:
    content = _document_content(chunk)
    if not content.strip():
        return None

    metadata = dict(_document_metadata(chunk))
    document_id = _context_document_id(chunk) or _context_document_id(source_document)
    chunk_index = _context_chunk_index(chunk)
    source_score = _document_score(source_document)
    chunk_score = _document_score(chunk)
    base_score = source_score if source_score is not None else (chunk_score or 0.0)
    # 이웃 청크는 실제 히트가 아니므로 앵커 점수보다 약간 낮춰 정렬/표기 오염을 방지(#4)
    score = base_score * 0.96 if base_score > 0 else 0.0

    if document_id is not None:
        metadata.setdefault("document_id", document_id)
        metadata["context_expanded_from_document_id"] = document_id
    if chunk_index is not None:
        metadata.setdefault("chunk_index", chunk_index)
    metadata.setdefault("score", score)
    metadata.setdefault("retrieval_score", score)
    metadata["context_expanded"] = True
    metadata["context_expanded_from_chunk_index"] = source_chunk_index

    chunk_id = _document_value(chunk, "id")
    if chunk_id in (None, "") and document_id is not None and chunk_index is not None:
        chunk_id = f"{document_id}:{chunk_index}"

    return SearchResult(
        id=str(chunk_id or id(chunk)),
        content=content,
        score=score,
        metadata=metadata,
    )


@dataclass
class RouteDecision:
    """
    쿼리 라우팅 결정 결과

    Attributes:
        should_continue: RAG 파이프라인 계속 진행 여부
        immediate_response: 즉시 응답 (direct_answer/blocked인 경우)
        metadata: 라우팅 메타데이터 (route, confidence, intent, domain 등)

    Examples:
        # 즉시 응답 (파이프라인 중단)
        RouteDecision(
            should_continue=False,
            immediate_response={"answer": "안녕하세요!", ...},
            metadata={"route": "direct_answer", "confidence": 0.95}
        )

        # RAG 계속 진행
        RouteDecision(
            should_continue=True,
            immediate_response=None,
            metadata={"route": "rag", "domain": "document_query"}
        )
    """

    should_continue: bool
    immediate_response: RAGResultDict | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class PreparedContext:
    """
        세션 컨텍스트 + 쿼리 확장 결과 (Multi-Query RRF 지원)

        Attributes:
            session_context: 세션 컨텍스트 문자열 (최근 5개 대화)
            expanded_query: 확장된 쿼리 (첫 번째 쿼리, 하위 호환성)
            original_query: 원본 쿼리 (참조용)
            expanded_queries: 확장된 쿼리 리스트 (Multi-Query RRF용, 기본 5개)
            query_weights: 쿼리 가중치 리스트 (1.0, 0.8, 0.6, 0.4, 0.2)

        Examples:
            # Multi-Query RRF
            PreparedContext(
                session_context="User: Hello
    Bot: Hello! How can I help you?",
                expanded_query="expanded query with synonyms and related terms",
                original_query="original user query",
                expanded_queries=["query variant A", "query variant B", ...],
                query_weights=[1.0, 0.8, 0.6, 0.4, 0.2]
            )
    """

    session_context: str | None
    expanded_query: str
    original_query: str
    expanded_queries: list[str] = field(default_factory=list)  # Multi-Query RRF용
    query_weights: list[float] = field(default_factory=list)  # 쿼리 가중치
    # 멀티턴 anchor soft boost(GAP B)용 직전 인용 문서. 기본 OFF면 항상 빈 리스트.
    anchor_sources: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class RetrievalResults:
    """
    문서 검색 결과

    Attributes:
        documents: Document 객체 리스트 (langchain_core.documents.Document)
        count: 검색된 문서 수

    Examples:
        RetrievalResults(
            documents=[
                Document(page_content="...", metadata={"source": "doc1.pdf", "score": 0.89}),
                Document(page_content="...", metadata={"source": "doc2.pdf", "score": 0.76})
            ],
            count=2
        )
    """

    documents: list[Any]
    count: int


@dataclass
class RerankResults:
    """
    리랭킹 결과

    Attributes:
        documents: 리랭킹된 Document 객체 리스트
        count: 리랭킹된 문서 수
        reranked: 실제로 리랭킹이 수행되었는지 여부

    Examples:
        # 리랭킹 성공
        RerankResults(documents=[...], count=10, reranked=True)

        # 리랭킹 실패 (원본 반환)
        RerankResults(documents=[...], count=15, reranked=False)
    """

    documents: list[Any]
    count: int
    reranked: bool


# GenerationResult는 generator.py에서 import (L30)


@dataclass
class FormattedSources:
    """
    포맷팅된 소스 리스트

    Attributes:
        sources: Source 객체 리스트 (app.models.prompts.Source)
        count: 소스 개수

    Examples:
        FormattedSources(
            sources=[Source(id=0, document="doc1.pdf", relevance=0.89, ...), ...],
            count=5
        )
    """

    sources: list[Any]
    count: int


class PipelineTracker:
    """
    RAG 파이프라인 단계별 타이밍 추적 클래스

    8개 단계 각각의 실행 시간을 기록하고, 병목 지점을 식별.

    사용법:
        tracker = PipelineTracker()
        tracker.start_pipeline()

        tracker.start_stage("route_query")
        # ... 작업 수행 ...
        tracker.end_stage("route_query")

        tracker.end_pipeline()
        metrics = tracker.get_metrics()

    메트릭 형식:
        {
            'total_duration_ms': 1250.5,
            'stages': {
                'route_query': {'duration_ms': 45.2, 'percentage': 3.6},
                'retrieve_documents': {'duration_ms': 823.1, 'percentage': 65.8},
                ...
            },
            'slowest_stage': 'retrieve_documents'
        }
    """

    def __init__(self):
        """PipelineTracker 초기화"""
        self.stages: dict[str, dict[str, Any]] = {}  # Multi-Query RRF 메타데이터를 위해 Any 허용
        self.start_time: float = 0.0
        self.end_time: float = 0.0

    def start_pipeline(self) -> None:
        """파이프라인 시작 시간 기록"""
        self.start_time = time.time()
        logger.debug("Pipeline tracking 시작")

    def start_stage(self, stage_name: str) -> None:
        """
        단계 시작 시간 기록

        Args:
            stage_name: 단계 이름 (예: "route_query", "retrieve_documents")
        """
        if stage_name not in self.stages:
            self.stages[stage_name] = {}
        self.stages[stage_name]["start"] = time.time()

    def end_stage(self, stage_name: str) -> None:
        """
        단계 종료 시간 기록 및 duration 계산

        Args:
            stage_name: 단계 이름
        """
        if stage_name in self.stages and "start" in self.stages[stage_name]:
            self.stages[stage_name]["end"] = time.time()
            self.stages[stage_name]["duration"] = (
                self.stages[stage_name]["end"] - self.stages[stage_name]["start"]
            )
        else:
            logger.warning(
                "Stage가 시작되지 않았거나 이미 종료됨",
                extra={"stage_name": stage_name}
            )

    def end_pipeline(self) -> None:
        """파이프라인 종료 시간 기록"""
        self.end_time = time.time()
        logger.debug("Pipeline tracking 종료")

    def get_metrics(self) -> dict[str, Any]:
        """
        성능 메트릭 반환

        Returns:
            메트릭 딕셔너리:
            - total_duration_ms: 전체 실행 시간 (밀리초)
            - stages: 각 단계별 실행 시간 및 비율
            - slowest_stage: 가장 느린 단계 이름
        """
        total_duration = self.end_time - self.start_time if self.end_time > 0 else 0
        stage_metrics = {}
        for stage, times in self.stages.items():
            duration = times.get("duration", 0)
            percentage = duration / total_duration * 100 if total_duration > 0 else 0
            stage_metrics[stage] = {
                "duration_ms": round(duration * 1000, 1),
                "percentage": round(percentage, 1),
            }
        slowest_stage = None
        if self.stages:
            slowest_stage = max(self.stages.items(), key=lambda x: x[1].get("duration", 0))[0]
        return {
            "total_duration_ms": round(total_duration * 1000, 1),
            "stages": stage_metrics,
            "slowest_stage": slowest_stage,
        }

    def log_summary(self) -> None:
        """성능 메트릭 요약 로그 출력"""
        metrics = self.get_metrics()
        logger.info("=" * 60)
        logger.info("Pipeline Performance Summary")
        logger.info(
            "총 실행 시간",
            extra={"total_duration_ms": metrics['total_duration_ms']}
        )
        logger.info(
            "가장 느린 단계",
            extra={"slowest_stage": metrics.get('slowest_stage', 'N/A')}
        )
        logger.info("-" * 60)
        for stage, data in metrics["stages"].items():
            logger.info(
                "단계별 성능",
                extra={
                    "stage": stage,
                    "duration_ms": data['duration_ms'],
                    "percentage": data['percentage']
                }
            )
        logger.info("=" * 60)


class RAGPipeline:
    """
    RAG 파이프라인 오케스트레이터

    8개 독립 단계로 분해된 파이프라인:
    1. route_query: 쿼리 라우팅
    2. prepare_context: 컨텍스트 준비
    3. retrieve_documents: 문서 검색
    4. rerank_documents: 리랭킹
    5. generate_answer: 답변 생성
    6. self_rag_verify: Self-RAG 품질 검증 (선택적)
    7. format_sources: 소스 포맷팅
    8. build_result: 결과 구성

    각 단계는 독립적으로 테스트 및 최적화 가능.
    """

    # 기본값 (YAML 설정이 없을 때만 사용)
    FALLBACK_RETRIEVAL_LIMIT = 8
    FALLBACK_MIN_SCORE = 0.05
    FALLBACK_RERANK_TOP_N = 8

    # 정확 식별자 보강용 candidate pool 확장 상수 (GAP A)
    # exact_identifier.enabled=true일 때만 candidate_limit이 확장되며, 기본 OFF면 no-op.
    RETRIEVAL_CANDIDATE_MAX = 40
    RETRIEVAL_CANDIDATE_MIN_EXTRA = 10
    RETRIEVAL_CANDIDATE_MULTIPLIER = 3

    def __init__(
        self,
        config: dict[str, Any],
        query_router: Any | None,
        query_expansion: Any | None,
        retrieval_module: Any,
        generation_module: Any,
        session_module: Any,
        self_rag_module: Any | None,
        extract_topic_func: Callable,
        circuit_breaker_factory: Any,
        cost_tracker: CostTracker,
        performance_metrics: PerformanceMetrics,
        sql_search_service: SQLSearchService | None = None,
        agent_orchestrator: AgentOrchestrator | None = None,
        grok_answer_provider: Any | None = None,
        llm_factory: Any | None = None,
    ):
        """
        RAGPipeline 초기화 (의존성 주입)

        Args:
            config: 설정 딕셔너리
            query_router: 쿼리 라우터 (선택적)
            query_expansion: 쿼리 확장 모듈 (선택적)
            retrieval_module: 검색 모듈 (필수)
            generation_module: 생성 모듈 (필수)
            session_module: 세션 모듈 (필수)
            self_rag_module: Self-RAG 모듈 (선택적)
            extract_topic_func: 토픽 추출 함수
            circuit_breaker_factory: Circuit Breaker Factory (필수)
            cost_tracker: 비용 추적기 (필수)
            performance_metrics: 성능 메트릭 (필수)
            sql_search_service: SQL 검색 서비스 (선택적, Phase 3)
            agent_orchestrator: Agent 오케스트레이터 (선택적, Agentic RAG)
            grok_answer_provider: Grok이 검색과 답변을 모두 맡는 provider (선택적)
        """
        self.config = config
        # SQL Source(_format_sql_row) 라벨: 출력 언어 일관성을 위해 외부화.
        # sql_search.multi_query에서 읽어 service.py의 all_category_label과 단일
        # 진실원천을 공유한다. 미설정 시 한국어 기본값(회귀 0).
        _sql_multi_query = config.get("sql_search", {}).get("multi_query", {})
        self._sql_all_category_label: str = (
            _sql_multi_query.get("all_category_label") or "전체"
        )
        self._sql_entity_name_fallback_template: str = (
            _sql_multi_query.get("entity_name_fallback_template") or "결과 {index}"
        )
        self._sql_preview_fallback: str = (
            _sql_multi_query.get("preview_fallback") or "SQL 쿼리 결과"
        )
        self.query_router = query_router
        self.query_expansion = query_expansion
        self.retrieval_module = retrieval_module
        self.generation_module = generation_module
        self.session_module = session_module
        self.self_rag_module = self_rag_module
        self.extract_topic_func = extract_topic_func
        self.circuit_breaker_factory = circuit_breaker_factory
        self.cost_tracker = cost_tracker
        self.performance_metrics = performance_metrics
        self.sql_search_service = sql_search_service  # SQL 검색 서비스 (Phase 3)
        self.agent_orchestrator = agent_orchestrator  # Agent 오케스트레이터 (Agentic RAG)
        self.grok_answer_provider = grok_answer_provider
        self.llm_factory = llm_factory  # 멀티턴 standalone query rewrite용 LLM Factory

        # YAML 설정에서 retrieval 파라미터 로드
        rag_config = config.get("rag", {})

        # 멀티턴 standalone query rewrite 설정 (기본 OFF)
        # 후속 질문이 대명사/생략/축약으로 자립적이지 않으면 직전 대화 맥락을
        # 반영한 자립적(standalone) 질문으로 재작성해 검색에 투입한다.
        # 게이트 패턴은 언어별로 다르므로 yaml에서 오버라이드 가능하게 일반화한다.
        rewrite_config = rag_config.get("multiturn_rewrite", {})
        self.multiturn_rewrite_enabled = bool(rewrite_config.get("enabled", False))
        self.multiturn_rewrite_provider = rewrite_config.get("provider", "google")
        configured_dependent = rewrite_config.get("followup_dependent_patterns")
        self.multiturn_followup_dependent_patterns: tuple[str, ...] = (
            tuple(str(p) for p in configured_dependent)
            if isinstance(configured_dependent, list) and configured_dependent
            else self._DEFAULT_FOLLOWUP_DEPENDENT_PATTERNS
        )
        configured_start = rewrite_config.get("followup_start_patterns")
        self.multiturn_followup_start_patterns: tuple[str, ...] = (
            tuple(str(p) for p in configured_start)
            if isinstance(configured_start, list) and configured_start
            else self._DEFAULT_FOLLOWUP_START_PATTERNS
        )
        try:
            self.multiturn_short_question_max_words = int(
                rewrite_config.get("short_question_max_words", 5)
            )
        except (TypeError, ValueError):
            self.multiturn_short_question_max_words = 5
        # 재작성 프롬프트 템플릿 (없으면 한국어 기본 템플릿 사용 → 출력 언어 보존)
        configured_prompt = rewrite_config.get("prompt_template")
        self.multiturn_rewrite_prompt_template: str = (
            configured_prompt
            if isinstance(configured_prompt, str) and configured_prompt.strip()
            else self._DEFAULT_MULTITURN_REWRITE_PROMPT
        )

        # 정확 식별자(exact-identifier) 검색 보강 설정 (GAP A, 기본 OFF)
        # dense·BM25가 공히 놓치는 고유 식별자(모델코드/에러코드 등) 리콜을 보완한다.
        # OFF면 쿼리 보강·candidate 확장·rescue·rerank 안정화가 모두 no-op이다.
        exact_config = rag_config.get("exact_identifier", {})
        self.exact_identifier_enabled = bool(
            exact_config.get("enabled", False)
            if isinstance(exact_config, dict)
            else False
        )

        # 환각 방지 게이트 설정 (GAP C, 기본 OFF)
        # 질문에 명시된 연도가 검색 문서 연도집합과 완전 disjoint이면 최종답변을
        # '확인 불가'로 교체한다. OFF면 generation_result를 그대로 반환(no-op).
        hallucination_config = rag_config.get("hallucination_gate", {})
        self.hallucination_gate_enabled = bool(
            hallucination_config.get("enabled", False)
            if isinstance(hallucination_config, dict)
            else False
        )
        self.hallucination_gate_require_period_match = bool(
            hallucination_config.get("require_period_match", True)
            if isinstance(hallucination_config, dict)
            else True
        )
        # 보류 메시지 외부화: config 우선, 미설정/공백이면 코드 내장 한국어 기본값(회귀 0).
        configured_gate_message = (
            hallucination_config.get("no_answer_message")
            if isinstance(hallucination_config, dict)
            else None
        )
        self.hallucination_gate_no_answer_message: str = (
            configured_gate_message
            if isinstance(configured_gate_message, str) and configured_gate_message.strip()
            else HALLUCINATION_GATE_NO_ANSWER_MESSAGE
        )

        # 생성 모듈 부재 시 답변 폴백 메시지 외부화 (config 우선, 미설정 시 코드 기본).
        generation_fallback_config = rag_config.get("generation_fallback", {})
        if not isinstance(generation_fallback_config, dict):
            generation_fallback_config = {}
        configured_missing_message = generation_fallback_config.get(
            "module_missing_message"
        )
        self.generation_module_missing_message: str = (
            configured_missing_message
            if isinstance(configured_missing_message, str)
            and configured_missing_message.strip()
            else GENERATION_MODULE_MISSING_MESSAGE
        )

        # LLM 서킷브레이커 폴백 답변 3종 외부화 (config 우선, 미설정 시 코드 기본 → 회귀 0).
        # _resolve_generation_fallback_message로 null/공백 처리를 일원화한다.
        self.generation_fallback_with_docs_message: str = (
            _resolve_generation_fallback_message(
                generation_fallback_config.get("with_docs_message"),
                GENERATION_FALLBACK_WITH_DOCS_MESSAGE,
            )
        )
        self.generation_fallback_no_docs_message: str = (
            _resolve_generation_fallback_message(
                generation_fallback_config.get("no_docs_message"),
                GENERATION_FALLBACK_NO_DOCS_MESSAGE,
            )
        )
        self.document_preview_unavailable_message: str = (
            _resolve_generation_fallback_message(
                generation_fallback_config.get("document_preview_unavailable"),
                DOCUMENT_PREVIEW_UNAVAILABLE_MESSAGE,
            )
        )
        # 프롬프트 누출 차단 메시지(통짜·Self-RAG 공용, 중복 단일화)와 타입 가드 실패
        # 메시지도 동일하게 generation_fallback로 외부화한다(미설정 시 코드 기본 → 회귀 0).
        self.prompt_leakage_blocked_message: str = (
            _resolve_generation_fallback_message(
                generation_fallback_config.get("prompt_leakage_blocked_message"),
                PROMPT_LEAKAGE_BLOCKED_MESSAGE,
            )
        )
        self.generation_type_error_message: str = (
            _resolve_generation_fallback_message(
                generation_fallback_config.get("type_error_message"),
                GENERATION_TYPE_ERROR_MESSAGE,
            )
        )

        # Self-RAG 저품질 거부 메시지 외부화 (self_rag.yaml self_rag 섹션).
        # min_quality_to_answer와 동일 섹션(self_rag_config)에서 읽어 응집도를 맞춘다.
        # answer(상세)/text(축약) 2종 모두 미설정/공백이면 코드 내장 한국어 기본값 → 회귀 0.
        self_rag_section = self.config.get("self_rag", {})
        if not isinstance(self_rag_section, dict):
            self_rag_section = {}
        self.self_rag_low_quality_reject_message: str = (
            _resolve_generation_fallback_message(
                self_rag_section.get("low_quality_reject_message"),
                SELF_RAG_LOW_QUALITY_REJECT_MESSAGE,
            )
        )
        self.self_rag_low_quality_reject_text: str = (
            _resolve_generation_fallback_message(
                self_rag_section.get("low_quality_reject_text"),
                SELF_RAG_LOW_QUALITY_REJECT_TEXT,
            )
        )

        # 멀티턴 anchor soft boost 설정 (GAP B, 기본 OFF, 보수적)
        # 직전 대화에서 인용된 문서(anchor)를 후속 질문 리랭킹 후처리에서 hard-filter
        # 없이 약하게(boost_multiplier) 우대한다. 강한 우대/하드 필터는 옛 문서 고착
        # (staleness) 위험이 커서 금지한다. 자립(주제전환) 질문이면 anchor를 폐기한다.
        anchor_config = rag_config.get("multiturn_anchor", {})
        if not isinstance(anchor_config, dict):
            anchor_config = {}
        self.multiturn_anchor_enabled = bool(anchor_config.get("enabled", False))
        # 기본 배수 1.05(=+5%). 비정상/범위 밖 값은 1.05로 보정(상한 1.10).
        raw_anchor_multiplier = anchor_config.get("boost_multiplier", 1.05)
        try:
            anchor_multiplier = float(raw_anchor_multiplier)
        except (TypeError, ValueError):
            anchor_multiplier = 1.05
        self.multiturn_anchor_boost_multiplier = (
            anchor_multiplier if 1.0 < anchor_multiplier <= 1.10 else 1.05
        )

        retrieval_config = config.get("retrieval", {})

        self.retrieval_limit = rag_config.get(
            "top_k", retrieval_config.get("top_k", self.FALLBACK_RETRIEVAL_LIMIT)
        )
        self.min_score = retrieval_config.get("min_score", self.FALLBACK_MIN_SCORE)
        self.rerank_top_n = rag_config.get("rerank_top_k", self.FALLBACK_RERANK_TOP_N)

        # 파이프라인 타임아웃 예산(SLA budget) 로드 (opt-in)
        # 각 stage에 개별 deadline을, 전체에 총 budget을 부여해 무한 대기를 막는다.
        # enabled=false면 모든 래핑을 건너뛰어 기존(무제한) 동작을 유지한다.
        # 값이 비정상(0 이하/숫자 아님)이면 해당 stage는 무제한으로 폴백한다.
        timeout_config = rag_config.get("pipeline_timeout", {})
        self.pipeline_timeout_enabled = bool(timeout_config.get("enabled", False))
        self.pipeline_total_budget_seconds = self._coerce_positive_timeout(
            timeout_config.get("total_budget_seconds")
        )
        raw_stage_budgets = timeout_config.get("stages", {}) or {}
        # stage 이름 → deadline(초). None이면 해당 stage 무제한.
        self.pipeline_stage_budgets: dict[str, float | None] = {
            str(stage): self._coerce_positive_timeout(value)
            for stage, value in raw_stage_budgets.items()
        }
        self.pipeline_stream_first_chunk_seconds = self._coerce_positive_timeout(
            timeout_config.get("stream_first_chunk_seconds")
        )
        # 스트리밍 전용 총 예산(초). 스트리밍(SSE/WS)은 프론트 HTTP 타임아웃에
        # 묶이지 않는 장수명 연결이므로, 통짜(total_budget_seconds)보다 넉넉하게
        # 둘 수 있다. 미설정이면 무제한(stage deadline만 적용).
        self.pipeline_stream_total_budget_seconds = self._coerce_positive_timeout(
            timeout_config.get("stream_total_budget_seconds")
        )

        # RRF 점수 정규화 (0~1 범위 변환)
        score_norm_config = rag_config.get("score_normalization", {})
        self.score_normalizer = RRFScoreNormalizer.from_config(score_norm_config)

        # 개인정보 마스킹 (파일명, 답변 텍스트)
        # privacy.yaml 화이트리스트 로드 (오탐 방지: 이모님, 헬퍼님, 담당 등)
        # privacy.enabled: false → 마스킹 완전 비활성화
        privacy_config = config.get("privacy", {})
        privacy_enabled = privacy_config.get("enabled", True)

        if privacy_enabled:
            from ...modules.core.privacy.masker import PrivacyMasker

            whitelist = privacy_config.get("whitelist", [])
            masking_config = privacy_config.get("masking", {})
            char_config = privacy_config.get("characters", {})

            self.privacy_masker = PrivacyMasker(
                mask_phone=masking_config.get("phone", True),
                mask_name=masking_config.get("name", True),
                mask_email=masking_config.get("email", False),
                phone_mask_char=char_config.get("phone", "*"),
                name_mask_char=char_config.get("name", "*"),
                whitelist=whitelist,  # 공용 화이트리스트 (privacy.yaml)
            )
        else:
            self.privacy_masker = None  # PII 마스킹 비활성화
            logger.info(
                "PII 마스킹 비활성화",
                extra={"config_key": "privacy.enabled", "value": False}
            )

        logger.info(
            "RAG 파라미터 설정",
            extra={
                "top_k": self.retrieval_limit,
                "rerank_top_k": self.rerank_top_n,
                "min_score": self.min_score
            }
        )

        from ..schemas.chat_schemas import Source

        self.Source = Source

        # 규칙 기반 라우터를 1회 생성해 재사용한다.
        # 기존에는 route_query()가 매 chat 요청마다 RuleBasedRouter(enabled=True)를
        # 새로 만들어 config.yaml/routing_rules_v2.yaml을 디스크에서 반복 읽었다.
        # DynamicRuleManager(auto_reload=True)가 5분마다 규칙을 자동 리로드하므로
        # 인스턴스를 공유해도 규칙 변경은 그대로 반영된다(동작 보존).
        # 생성 실패 시 None으로 두고 route_query()에서 lazy 생성으로 폴백한다.
        # (생성 로직 자체는 _create_rule_based_router 헬퍼로 단일화)
        self.rule_based_router: Any | None = None
        try:
            self.rule_based_router = self._create_rule_based_router()
        except Exception as e:
            logger.warning(
                "RuleBasedRouter 초기화 실패 (route_query에서 lazy 생성으로 폴백)",
                extra={"error": str(e)},
                exc_info=True,
            )

        logger.info(
            "RAGPipeline 초기화 완료",
            extra={
                "sql_search": "활성화" if sql_search_service else "비활성화",
                "agent": "활성화" if agent_orchestrator else "비활성화",
                "score_normalization": "활성화" if score_norm_config.get('enabled', True) else "비활성화"
            }
        )

    def _create_rule_based_router(self) -> Any:
        """
        RuleBasedRouter 인스턴스를 생성한다 (__init__ eager / route_query lazy 공용).

        모듈 전역 캐시(RuleBasedRouter)를 활용해 임포트는 1회만 수행한다.
        생성 로직을 단일 지점으로 모아 eager/lazy 두 경로가 갈라지지 않게 한다.

        Returns:
            RuleBasedRouter 인스턴스 (enabled=True)

        Raises:
            Exception: 설정 파일 로드 실패 등 생성 실패 시 호출부에서 처리
        """
        global RuleBasedRouter
        if RuleBasedRouter is None:
            from ...modules.core.routing.rule_based_router import (
                RuleBasedRouter as _RuleBasedRouter,
            )

            RuleBasedRouter = _RuleBasedRouter

        return RuleBasedRouter(enabled=True)

    def _create_fallback_response(
        self, message: str, start_time: float, routing_metadata: dict[str, Any]
    ) -> RAGResultDict:
        """라우팅 실패 시 기본 응답 생성"""
        processing_time = time.time() - start_time
        return cast(
            RAGResultDict,
            {
                "answer": "응답을 생성할 수 없습니다.",
                "sources": [],
                "tokens_used": 0,
                "topic": self.extract_topic_func(message),
                "processing_time": processing_time,
                "search_results": 0,
                "ranked_results": 0,
                "model_info": {"provider": "system", "model": "fallback"},
                "routing_metadata": routing_metadata,
            },
        )

    async def _execute_parallel_search(
        self,
        message: str,
        prepared_context: PreparedContext,
        options: dict[str, Any],
    ) -> tuple[RetrievalResults, SQLSearchResult | None]:
        """SQL + RAG 병렬 검색 실행"""
        if self.sql_search_service and self.sql_search_service.is_enabled():
            logger.info("SQL 검색 + RAG 검색 병렬 실행 시작")
            rag_task = self.retrieve_documents(
                prepared_context.expanded_queries,
                prepared_context.query_weights,
                prepared_context.session_context,
                options,
            )
            sql_task = self._execute_sql_search(message)

            rag_result, sql_result = await asyncio.gather(
                rag_task, sql_task, return_exceptions=True
            )

            if isinstance(rag_result, Exception):
                logger.error("RAG 검색 실패", extra={"error": str(rag_result)}, exc_info=True)
                raise rag_result
            retrieval_results = rag_result

            sql_search_result = None
            if isinstance(sql_result, Exception):
                logger.warning(
                    "SQL 검색 실패 (무시)",
                    extra={"error": str(sql_result)},
                    exc_info=True
                )
            else:
                sql_search_result = sql_result
                if sql_search_result and sql_search_result.used:
                    row_count = sql_search_result.query_result.row_count if sql_search_result.query_result else 0
                    logger.info(
                        "SQL 검색 성공",
                        extra={
                            "row_count": row_count,
                            "total_time": sql_search_result.total_time
                        }
                    )

            return retrieval_results, sql_search_result
        else:
            retrieval_results = await self.retrieve_documents(
                prepared_context.expanded_queries,
                prepared_context.query_weights,
                prepared_context.session_context,
                options,
            )
            return retrieval_results, None

    def _track_debug_documents(
        self, enable_debug_trace: bool, debug_trace_data: dict[str, Any], documents: list[Any]
    ) -> None:
        """디버그 추적용 문서 정보 기록"""
        if not enable_debug_trace:
            return

        debug_trace_data["retrieved_documents"] = [
            {
                "id": doc.metadata.get("id", "") if hasattr(doc, "metadata") else "",
                "title": doc.metadata.get("title", "") if hasattr(doc, "metadata") else "",
                "chunk_text": (getattr(doc, "page_content", "")[:200] if hasattr(doc, "page_content") else ""),
                "vector_score": doc.metadata.get("score", 0.0) if hasattr(doc, "metadata") else 0.0,
                "bm25_score": doc.metadata.get("bm25_score") if hasattr(doc, "metadata") else None,
                "rerank_score": None,
                "used_in_answer": False,
            }
            for doc in documents
        ]

    def _update_retrieval_metrics(
        self,
        tracker: PipelineTracker,
        prepared_context: PreparedContext,
        sql_search_result: SQLSearchResult | None,
    ) -> None:
        """검색 메트릭 업데이트"""
        tracker.stages["retrieve_documents"]["multi_query_count"] = len(
            prepared_context.expanded_queries
        )
        tracker.stages["retrieve_documents"]["rrf_enabled"] = (
            len(prepared_context.expanded_queries) > 1
        )
        tracker.stages["retrieve_documents"]["query_weights"] = prepared_context.query_weights
        tracker.stages["retrieve_documents"]["sql_search_used"] = (
            sql_search_result.used if sql_search_result else False
        )

    def _create_debug_trace(
        self,
        enable_debug_trace: bool,
        debug_trace_data: dict[str, Any],
        message: str,
    ) -> DebugTrace | None:
        """DebugTrace 객체 생성"""
        if not enable_debug_trace or not debug_trace_data:
            return None

        try:
            from ..schemas.debug import DebugTrace

            if "query_transformation" not in debug_trace_data:
                debug_trace_data["query_transformation"] = {
                    "original": message,
                    "expanded": None,
                    "final_query": message,
                }
            if "retrieved_documents" not in debug_trace_data:
                debug_trace_data["retrieved_documents"] = []

            debug_trace = DebugTrace(**debug_trace_data)
            logger.debug(
                "DebugTrace 생성 완료",
                extra={"document_count": len(debug_trace.retrieved_documents)}
            )
            return debug_trace
        except Exception as e:
            logger.warning(
                "DebugTrace 생성 실패",
                extra={"error": str(e)},
                exc_info=True
            )
            return None

    def _retrieval_candidate_limit(self, requested_limit: int) -> int:
        """검색 candidate pool 크기를 계산한다(GAP A).

        exact_identifier.enabled=true일 때만 candidate pool을 확장한다(×MULTIPLIER,
        +MIN_EXTRA, 상한 MAX). 정확 식별자가 dense·BM25 상위에서 밀려도 rescue·rerank
        안정화가 더 넓은 후보에서 끌어올릴 수 있게 한다. OFF면 요청 한도 그대로(no-op).

        Args:
            requested_limit: 사용자가 요청한 검색 결과 수

        Returns:
            확장된 candidate 한도(OFF면 requested_limit 그대로).
        """
        if not self.exact_identifier_enabled:
            return requested_limit
        if requested_limit >= self.RETRIEVAL_CANDIDATE_MAX:
            return requested_limit
        expanded_limit = max(
            requested_limit * self.RETRIEVAL_CANDIDATE_MULTIPLIER,
            requested_limit + self.RETRIEVAL_CANDIDATE_MIN_EXTRA,
        )
        return max(requested_limit, min(expanded_limit, self.RETRIEVAL_CANDIDATE_MAX))

    @staticmethod
    def _exact_identifier_terms(query: str) -> list[str]:
        """질문에서 정확 식별자 토큰을 추출한다(GAP A). 모듈 헬퍼 위임."""
        return _exact_identifier_terms(query)

    @staticmethod
    def _latin_phrase_terms(query: str) -> list[str]:
        """질문에서 라틴 다중 단어 구문을 추출한다(GAP A). 모듈 헬퍼 위임."""
        return _latin_phrase_terms(query)

    def _augment_search_queries_with_exact_terms(
        self,
        original_query: str,
        search_queries: list[str],
        query_weights: list[float],
    ) -> tuple[list[str], list[float]]:
        """정확 매칭 프로브 쿼리를 의미 쿼리를 대체하지 않고 추가 주입한다(GAP A).

        식별자(가중치 1.25)와 라틴 구문(1.1)을 별도 검색 쿼리로 추가해, dense/BM25가
        놓치기 쉬운 고유 식별자의 리콜을 보강한다. exact_identifier.enabled=false면
        입력을 그대로 반환(no-op). 정규화 키 기준 중복은 추가하지 않으며 최대 8개로 제한.

        Args:
            original_query: 원본(또는 재작성된) 질문
            search_queries: 기존 검색 쿼리 리스트
            query_weights: 기존 쿼리 가중치 리스트

        Returns:
            (보강된 쿼리 리스트, 보강된 가중치 리스트). OFF면 입력 그대로.
        """
        if not self.exact_identifier_enabled:
            return search_queries, query_weights

        augmented_queries = list(search_queries)
        augmented_weights = list(query_weights)
        existing = {_normalize_exact_match_text(q) for q in augmented_queries}
        candidates: list[tuple[str, float]] = []
        for term in _exact_identifier_terms(original_query):
            candidates.append((term, 1.25))
        for term in _latin_phrase_terms(original_query):
            candidates.append((term, 1.1))

        for term, weight in candidates:
            key = _normalize_exact_match_text(term)
            if not key or key in existing:
                continue
            augmented_queries.append(term)
            augmented_weights.append(weight)
            existing.add(key)
            if len(augmented_queries) >= 8:
                break
        return augmented_queries, augmented_weights

    def _exact_signal_score(self, query: str, document: Any) -> float:
        """문서가 질문의 정확 신호(식별자/라틴 구문/연도)와 얼마나 일치하는지 점수화(GAP A).

        원본 구현의 언어 전용 휴리스틱은 제거하고 언어무관 신호만 채택한다.
        - 식별자 매칭: +12.0 (가장 강한 신호)
        - 라틴 구문 매칭: +5.0
        - 캘린더 연도 일치: +5.0 / 문서에 다른 연도만 존재: -8.0
        """
        text = _document_text_for_exact_signals(document)
        normalized_text = _normalize_exact_match_text(text)
        score = 0.0

        for term in _exact_identifier_terms(query):
            if _normalize_exact_match_text(term) in normalized_text:
                score += 12.0

        for term in _latin_phrase_terms(query):
            if _normalize_exact_match_text(term) in normalized_text:
                score += 5.0

        query_years = {int(y) for y in _CALENDAR_YEAR_PATTERN.findall(query)}
        if query_years:
            doc_years = self._document_calendar_years(document)
            if query_years & doc_years:
                score += 5.0
            elif doc_years:
                score -= 8.0

        return score

    @staticmethod
    def _document_calendar_years(document: Any) -> set[int]:
        """문서의 식별 메타(파일명 등)에서 캘린더 연도(20xx)를 추출한다(GAP A/C).

        OneRAG의 파일명 연도 추출(doc_years 메타)을 우선 사용하고, 없으면 식별 메타
        문자열에서 직접 20xx를 추출한다(언어무관).
        """
        metadata = _document_metadata(document)
        years: set[int] = set()
        raw_doc_years = metadata.get("doc_years")
        if isinstance(raw_doc_years, list | tuple | set):
            for value in raw_doc_years:
                parsed = _coerce_optional_int(value)
                if parsed is not None:
                    years.add(parsed)
        source = str(
            metadata.get("source_file")
            or metadata.get("source")
            or metadata.get("document_name")
            or ""
        )
        for match in _CALENDAR_YEAR_PATTERN.findall(source):
            years.add(int(match))
        return years

    def _stabilize_reranked_results_with_exact_signals(
        self, query: str, ranked_results: list[Any]
    ) -> list[Any]:
        """정확 신호가 강한 문서를 상위로 안정화한다(GAP A).

        exact_identifier.enabled=false면 no-op. 질문에 식별자/연도 등 2차 신호가 없거나
        최고 점수가 임계(2.5) 미만이면 그대로 반환한다. 조건 충족 시 정확 신호 점수
        내림차순(동점은 기존 순서)으로 재정렬해, 리랭커가 정확 식별자 문서를 하위로
        밀어버린 경우를 보정한다.

        Args:
            query: 검색 질문
            ranked_results: 리랭킹된 문서 리스트

        Returns:
            안정화된 문서 리스트(미적용 시 입력 그대로).
        """
        if not self.exact_identifier_enabled:
            return ranked_results
        if len(ranked_results) < 2:
            return ranked_results
        has_secondary_signal = bool(
            _exact_identifier_terms(query)
            or _latin_phrase_terms(query)
            or _CALENDAR_YEAR_PATTERN.search(query)
        )
        if not has_secondary_signal:
            return ranked_results
        scored = [
            (self._exact_signal_score(query, document), index, document)
            for index, document in enumerate(ranked_results)
        ]
        if max(score for score, _, _ in scored) < 2.5:
            return ranked_results
        scored.sort(key=lambda item: (-item[0], item[1]))
        return [document for _, _, document in scored]

    async def _rescue_exact_identifier_candidates(
        self,
        retrieval_module: Any,
        query: str,
        results: list[SearchResult],
        filters: dict[str, Any] | None,
        limit: int,
    ) -> list[SearchResult]:
        """정확 식별자를 직접 타깃 재검색해 매칭 후보를 병합한다(GAP A).

        exact_identifier.enabled=false거나 식별자가 없으면 results를 그대로 반환(no-op).
        식별자별로 직접 검색을 돌려, 식별자가 문서 텍스트에 포함된 후보만 추려 기존
        결과 앞쪽으로 병합한다(_document_identity 기준 중복 제거). 검색 실패는 graceful.

        Args:
            retrieval_module: 검색 모듈(search 메서드 또는 orchestrator.search)
            query: 검색 질문
            results: 기존 검색 결과
            filters: 검색 메타 필터
            limit: 최대 결과 수

        Returns:
            병합된 결과(no-op 시 results 그대로).
        """
        if not self.exact_identifier_enabled:
            return results
        identifiers = _exact_identifier_terms(query)
        if not identifiers:
            return results

        search_func = getattr(retrieval_module, "search", None)
        if search_func is None:
            orchestrator = getattr(retrieval_module, "orchestrator", None)
            search_func = (
                getattr(orchestrator, "search", None) if orchestrator is not None else None
            )
        if search_func is None:
            return results

        rescued: list[SearchResult] = []
        for identifier in identifiers[:3]:
            try:
                candidates = await search_func(
                    identifier, {"limit": limit, "filters": filters}
                )
            except Exception as exc:
                logger.debug(
                    "정확 식별자 보강 검색 실패",
                    extra={"identifier": identifier, "error": str(exc)},
                )
                continue
            identifier_key = _normalize_exact_match_text(identifier)
            for candidate in candidates or []:
                text_key = _normalize_exact_match_text(
                    _document_text_for_exact_signals(candidate)
                )
                if identifier_key and identifier_key in text_key:
                    rescued.append(candidate)

        if not rescued:
            return results

        merged: list[SearchResult] = []
        seen: set[Any] = set()
        for candidate in [*rescued, *results]:
            key = _document_identity(candidate)
            if key in seen:
                continue
            seen.add(key)
            merged.append(candidate)
        logger.info(
            "정확 식별자 후보 보강 완료",
            extra={
                "identifiers": identifiers[:3],
                "rescued_count": len(rescued),
                "merged_count": len(merged),
            },
        )
        return merged[:limit]

    def _hallucination_gate_period_mismatch(
        self, message: str, documents: list[Any]
    ) -> bool:
        """질문에 명시된 연도가 검색 문서들의 연도와 전혀 일치하지 않는지 판정(GAP C).

        다른 기간 데이터로 단정하는 negative 환각을 막기 위한 판정. 캘린더 연도(20xx)만
        매칭하며(언어무관), 특정 회계연도 표기 휴리스틱은 채택하지 않는다. 오탐 방지를
        위해 질문 또는 문서에 연도 정보가 없으면 False(게이트 미적용)를 반환한다.

        Args:
            message: 사용자 질문
            documents: 검색/리랭킹된 컨텍스트 문서

        Returns:
            기간 불일치면 True(보류 대상), 아니면 False.
        """
        query_years = {int(y) for y in _CALENDAR_YEAR_PATTERN.findall(message)}
        if not query_years:
            return False
        doc_years: set[int] = set()
        for document in documents:
            doc_years |= self._document_calendar_years(document)
        if not doc_years:
            return False
        return query_years.isdisjoint(doc_years)

    def _apply_hallucination_gate(
        self,
        message: str,
        generation_result: GenerationResult,
        documents: list[Any],
        options: dict[str, Any] | None,
    ) -> GenerationResult:
        """기간 불일치 환각 게이트(GAP C, 기본 OFF, opt-in).

        hallucination_gate.enabled=true이고 질문 기간이 문서 기간과 전혀 일치하지
        않으면, 답변을 '확인 불가' 메시지로 교체해 환각을 차단한다. 비활성(기본)이면
        generation_result를 그대로 반환해 기존 동작을 유지한다. self_rag_verify 이후에
        호출되어 최종 답변 기준으로 1회만 판정한다.

        Args:
            message: 사용자 질문
            generation_result: 현재 생성 결과
            documents: 컨텍스트 문서
            options: 요청 옵션(예약, 현재 미사용)

        Returns:
            게이트 통과 시 원본, 차단 시 보류 메시지로 교체된 GenerationResult.
        """
        if not self.hallucination_gate_enabled:
            return generation_result
        if not self.hallucination_gate_require_period_match:
            return generation_result
        if not self._hallucination_gate_period_mismatch(message, documents):
            return generation_result
        logger.info("환각 게이트: 질문 기간과 문서 기간 불일치 → '확인 불가' 응답으로 교체")
        return replace(
            generation_result,
            answer=self.hallucination_gate_no_answer_message,
            text=self.hallucination_gate_no_answer_message,
        )

    @staticmethod
    def _conversation_pairs_from_history(
        chat_history: dict[str, Any], max_exchanges: int = 5
    ) -> list[dict[str, str]]:
        """채팅 히스토리(messages)에서 user/assistant 교환 쌍을 추출한다(GAP B).

        Args:
            chat_history: get_chat_history 반환 형태({"messages": [...]})
            max_exchanges: 최근 교환 최대 수

        Returns:
            [{"user": ..., "assistant": ...}, ...] (최근 max_exchanges개)
        """
        messages = chat_history.get("messages", []) if isinstance(chat_history, dict) else []
        conversations: list[dict[str, str]] = []
        i = 0
        while i < len(messages) - 1:
            cur = messages[i]
            nxt = messages[i + 1]
            if (
                isinstance(cur, dict)
                and isinstance(nxt, dict)
                and cur.get("type") == "user"
                and nxt.get("type") == "assistant"
            ):
                conversations.append(
                    {"user": cur.get("content", ""), "assistant": nxt.get("content", "")}
                )
                i += 2
            else:
                i += 1
        return conversations[-max_exchanges:] if conversations else []

    async def _extract_anchor_sources(
        self,
        message: str,
        session_id: str,
        chat_history: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """직전 대화에서 인용된 문서(anchor)를 추출하고 오염 게이트로 유지/폐기 결정(GAP B).

        멀티턴 anchor soft boost의 입력. 직전 assistant 메시지의 sources에서 문서
        식별자(`document`=파일명, `document_id`)를 anchor로 추출한다.

        오염 방지 게이트(고착 방지의 핵심):
        - `_needs_standalone_rewrite`를 재사용한다. True(대명사/생략/축약 → 같은 주제의
          후속 질문)면 anchor 유지, False(충분히 길고 자립적 → 주제 전환 가능성)면 폐기.
        - 기능 비활성(multiturn_anchor_enabled=False)/session_module 부재/직전 sources
          부재 시 빈 리스트를 반환해 기존 동작과 100% 동일(no-op)하게 만든다.

        Args:
            message: 후속 사용자 질문(원본)
            session_id: 세션 ID
            chat_history: 이미 조회된 채팅 히스토리(중복 조회 방지). None이면 직접 조회.

        Returns:
            anchor 리스트(각 {"document", "document_id"}), 폐기/부재 시 빈 리스트.
        """
        if not self.multiturn_anchor_enabled:
            return []
        if self.session_module is None:
            return []

        # 오염 게이트: 자립적(주제 전환) 질문이면 anchor 폐기
        if not self._needs_standalone_rewrite(message):
            logger.debug(
                "anchor 폐기: 자립적 질문(주제 전환 가능성)",
                extra={"message": message[:40]},
            )
            return []

        if chat_history is not None:
            history: dict[str, Any] | None = chat_history
        else:
            get_history = getattr(self.session_module, "get_chat_history", None)
            if get_history is None:
                return []
            try:
                history = await get_history(session_id)
            except Exception as e:
                logger.debug(
                    "anchor 추출 생략: 채팅 히스토리 조회 실패",
                    extra={"error": str(e)},
                )
                return []

        messages = history.get("messages", []) if isinstance(history, dict) else []
        if not messages:
            return []

        # 가장 최근 assistant 메시지를 역순 탐색
        last_sources: list[Any] = []
        for msg in reversed(messages):
            if not isinstance(msg, dict):
                continue
            if msg.get("type") == "assistant":
                raw_sources = msg.get("sources", [])
                if isinstance(raw_sources, list):
                    last_sources = raw_sources
                break

        if not last_sources:
            return []

        anchors: list[dict[str, Any]] = []
        seen: set[str] = set()
        for src in last_sources:
            if not isinstance(src, dict):
                continue
            document = src.get("document") or src.get("source_file")
            document_id = src.get("document_id") or src.get("source_id")
            if not document and not document_id:
                continue
            identity = f"{document_id or ''}|{document or ''}"
            if identity in seen:
                continue
            seen.add(identity)
            anchors.append({"document": document, "document_id": document_id})

        if anchors:
            logger.debug(
                "anchor 유지(후속 질문, soft boost 대상)",
                extra={"anchor_count": len(anchors), "message": message[:40]},
            )
        return anchors

    @staticmethod
    def _document_matches_anchor(
        document: Any, anchor_sources: list[dict[str, Any]]
    ) -> bool:
        """문서가 anchor(직전 인용 문서)와 일치하는지 판정(GAP B).

        document_id 우선, 없으면 source_file(파일명)로 일치 여부를 확인한다.
        """
        metadata = _document_metadata(document)
        doc_id = metadata.get("document_id") or metadata.get("source_id")
        doc_file = metadata.get("source_file") or metadata.get("document")
        for anchor in anchor_sources:
            anchor_id = anchor.get("document_id")
            anchor_file = anchor.get("document")
            if anchor_id and doc_id and str(anchor_id) == str(doc_id):
                return True
            if anchor_file and doc_file and str(anchor_file) == str(doc_file):
                return True
        return False

    def _apply_anchor_soft_boost(
        self, anchor_sources: list[dict[str, Any]], ranked_results: list[Any]
    ) -> list[Any]:
        """리랭킹 결과에 직전 인용 문서(anchor) soft boost를 적용한다(GAP B).

        고착(staleness) 방지를 위해 hard filter(anchor 문서만 남기기)는 절대 쓰지 않고,
        anchor 일치 문서만 boosted 점수만큼 제자리에서 위로 끌어올린다(anchor-only
        stable-insert). 점수 격차가 크면 anchor라도 끌어올리지 못한다.

        불변식(회귀 방지): "anchor 미일치 문서끼리의 상대 순서는 입력과 100% 동일"하게
        보존한다. 직전 fusion(_fuse_reranked_results_with_original_signals)이 의도적으로
        점수 내림차순이 아닌 순서를 만들 수 있으므로 전면 sort를 쓰지 않고 anchor만
        bubble-up 한다.

        no-op 조건(기존 랭킹과 100% 동일):
        - 기능 비활성(multiturn_anchor_enabled=False)
        - anchor 없음 / 결과 2개 미만 / anchor 일치 문서 없음

        Args:
            anchor_sources: anchor 리스트({"document", "document_id"})
            ranked_results: 리랭킹된 문서 리스트(직전 fusion 순서)

        Returns:
            soft boost 후 재정렬된 문서 리스트(no-op 시 입력 그대로).
        """
        if not self.multiturn_anchor_enabled:
            return ranked_results
        if not anchor_sources or len(ranked_results) < 2:
            return ranked_results

        multiplier = self.multiturn_anchor_boost_multiplier
        matches = [
            self._document_matches_anchor(doc, anchor_sources) for doc in ranked_results
        ]
        if not any(matches):
            return ranked_results

        # 비교용 점수: anchor는 base*multiplier, 비-anchor는 base 그대로.
        # _document_score는 None을 반환할 수 있으므로 0.0으로 보정한다.
        effective_scores = [
            (_document_score(doc) or 0.0) * (multiplier if matches[index] else 1.0)
            for index, doc in enumerate(ranked_results)
        ]

        # anchor-only stable-insert: 비-anchor는 항상 맨 뒤 append(상대순서 불변),
        # anchor는 result 뒤쪽부터 위로 스캔하며 자신보다 "엄격히 작은" 문서만 추월.
        result: list[Any] = []
        result_scores: list[float] = []
        for index, document in enumerate(ranked_results):
            if not matches[index]:
                result.append(document)
                result_scores.append(effective_scores[index])
                continue
            boosted = effective_scores[index]
            insert_at = len(result)
            while insert_at > 0 and result_scores[insert_at - 1] < boosted:
                insert_at -= 1
            result.insert(insert_at, document)
            result_scores.insert(insert_at, boosted)

        if [id(d) for d in result] != [id(d) for d in ranked_results]:
            logger.info(
                "anchor soft boost 적용(순서 변경)",
                extra={
                    "boost_multiplier": multiplier,
                    "anchor_match_count": sum(matches),
                },
            )
        return result

    def _build_retrieval_filters(self, options: dict[str, Any]) -> dict[str, Any] | None:
        """요청 옵션에서 검색 메타데이터 필터를 구성한다(#12, GAP G).

        options['filters'](dict)에 더해, 라우팅 결과(data_source)에 대응하는 config
        기반 메타 필터를 병합한다(GAP G). filter_mappings가 비어있으면(기본) 기존
        무필터 동작과 100% 동일하게 동작한다(회귀 방지).
        """
        raw_filters = options.get("filters")
        filters = dict(raw_filters) if isinstance(raw_filters, dict) else {}

        # 라우팅 data_source → config 매핑 필터 병합 (GAP G).
        # 매핑이 비어있으면 추가 필터 없음(no-op) — 운영 회귀 방지 핵심 안전장치.
        data_source_filter = self._resolve_data_source_filter(options.get("data_source"))
        for key, value in data_source_filter.items():
            filters.setdefault(key, value)

        return filters or None

    def _resolve_data_source_filter(self, data_source: str | None) -> dict[str, Any]:
        """라우팅 data_source 값에 대응하는 config 기반 메타 필터를 반환한다(GAP G).

        매핑 설정 위치: ``query_routing.data_source_routing.filter_mappings``
        (app/config/features/routing.yaml). 기본값은 빈 dict이며, 이 경우 어떤
        data_source에 대해서도 추가 필터를 만들지 않는다(no-op, 회귀 0).

        Args:
            data_source: 라우팅 결과 data_source 값(예: "structured"/"general"/"both").
                None이면 빈 필터를 반환한다.

        Returns:
            병합 대상 메타 필터 dict(매핑 미설정/미일치 시 빈 dict).
        """
        if not data_source:
            return {}

        query_routing = self.config.get("query_routing", {})
        if not isinstance(query_routing, dict):
            return {}
        data_source_routing = query_routing.get("data_source_routing", {})
        if not isinstance(data_source_routing, dict):
            return {}

        filter_mappings = data_source_routing.get("filter_mappings") or {}
        if not isinstance(filter_mappings, dict):
            return {}

        mapped = filter_mappings.get(str(data_source))
        if not isinstance(mapped, dict):
            return {}

        # 얕은 복사로 호출자 측 변형을 방지한다.
        return dict(mapped)

    def _resolve_context_expansion(self, options: dict[str, Any]) -> tuple[bool, int]:
        """Resolve adjacent chunk expansion as an explicit opt-in feature."""
        rag_config = self.config.get("rag", {})
        configured = rag_config.get("context_expansion", {})
        context_config = configured if isinstance(configured, dict) else {}

        enabled = _coerce_bool(context_config.get("enabled"), default=False)
        for option_key in ("expand_adjacent_chunks", "context_expansion_enabled"):
            if option_key in options:
                enabled = _coerce_bool(options.get(option_key), default=enabled)
                break

        configured_window = _coerce_optional_int(context_config.get("window"))
        requested_window = _coerce_optional_int(
            options.get("adjacent_chunk_window", options.get("context_expansion_window"))
        )
        # 설정값 0은 "명시적 비활성"이므로 None일 때만 기본값(1)을 사용한다([32]).
        if requested_window is not None:
            window = requested_window
        elif configured_window is not None:
            window = configured_window
        else:
            window = 1

        configured_max_window = _coerce_optional_int(context_config.get("max_window"))
        # max_window=0도 명시적 값으로 취급(아래 max(1, ...) 클램프가 최소 1 보장)([34]).
        max_window = (
            configured_max_window
            if configured_max_window is not None
            else _CONTEXT_EXPANSION_MAX_WINDOW
        )
        max_window = max(1, min(max_window, _CONTEXT_EXPANSION_MAX_WINDOW))
        window = max(0, min(window, max_window))

        return enabled and window > 0, window

    async def expand_context_documents(
        self,
        ranked_results: list[Any],
        options: dict[str, Any],
    ) -> list[Any]:
        """
        Optionally add adjacent chunks around ranked hits before generation.

        Default is off. When enabled, the method uses the existing
        get_document_chunks(document_id) retriever capability and falls back to
        the original ranked results if metadata or retriever support is absent.
        """
        enabled, window = self._resolve_context_expansion(options)
        if not enabled or not ranked_results:
            return ranked_results

        retrieval_module = self.retrieval_module
        if asyncio.iscoroutine(retrieval_module) or isinstance(retrieval_module, asyncio.Future):
            retrieval_module = await retrieval_module

        get_document_chunks = getattr(retrieval_module, "get_document_chunks", None)
        if not callable(get_document_chunks):
            logger.warning("인접 청크 확장 스킵 - get_document_chunks 미지원")
            return ranked_results

        original_by_identity: dict[tuple[Any, ...], Any] = {}
        for document in ranked_results:
            original_by_identity.setdefault(_context_chunk_identity(document), document)

        chunk_cache: dict[str, list[dict[str, Any]]] = {}
        expanded: list[Any] = []
        seen: set[tuple[Any, ...]] = set()

        def append_once(document: Any) -> None:
            identity = _context_chunk_identity(document)
            if identity in seen:
                return
            seen.add(identity)
            expanded.append(document)

        # 인접 청크가 필요한 distinct document_id를 먼저 수집해 동시 조회한다([16]).
        distinct_doc_ids: list[str] = []
        seen_doc_ids: set[str] = set()
        for document in ranked_results:
            doc_id = _context_document_id(document)
            if (
                doc_id is not None
                and _context_chunk_index(document) is not None
                and doc_id not in seen_doc_ids
            ):
                seen_doc_ids.add(doc_id)
                distinct_doc_ids.append(doc_id)

        async def _fetch_chunks(document_id: str) -> tuple[str, list[dict[str, Any]]]:
            try:
                chunks = await get_document_chunks(document_id)
            except NotImplementedError:
                logger.debug(
                    "인접 청크 확장 스킵 - retriever 메서드 미구현",
                    extra={"document_id": document_id},
                )
                chunks = []
            except Exception as exc:
                logger.warning(
                    "인접 청크 조회 실패 - 원본 검색 결과 유지",
                    extra={"document_id": document_id, "error": str(exc)},
                    exc_info=True,
                )
                chunks = []
            return document_id, chunks if isinstance(chunks, list) else []

        if distinct_doc_ids:
            fetched = await asyncio.gather(
                *(_fetch_chunks(doc_id) for doc_id in distinct_doc_ids)
            )
            for doc_id, chunks in fetched:
                chunk_cache[doc_id] = chunks

        for document in ranked_results:
            document_id = _context_document_id(document)
            chunk_index = _context_chunk_index(document)
            if document_id is None or chunk_index is None:
                append_once(document)
                continue

            chunks = chunk_cache.get(document_id, [])
            if not chunks:
                append_once(document)
                continue

            chunks_by_index: dict[int, dict[str, Any]] = {}
            for chunk in chunks:
                index = _context_chunk_index(chunk)
                if index is not None:
                    chunks_by_index.setdefault(index, chunk)

            for index in range(chunk_index - window, chunk_index + window + 1):
                if index < 0:
                    continue
                if index == chunk_index:
                    append_once(document)
                    continue

                identity: tuple[Any, ...] = ("chunk", document_id, index)
                if identity in original_by_identity:
                    append_once(original_by_identity[identity])
                    continue

                chunk = chunks_by_index.get(index)
                if not chunk:
                    continue
                adjacent_document = _chunk_to_search_result(
                    chunk,
                    source_document=document,
                    source_chunk_index=chunk_index,
                )
                if adjacent_document is not None:
                    append_once(adjacent_document)

        if len(expanded) != len(ranked_results):
            logger.info(
                "인접 청크 컨텍스트 확장 완료",
                extra={
                    "before_count": len(ranked_results),
                    "after_count": len(expanded),
                    "window": window,
                }
            )
        return expanded

    # ========================================================================
    # 명시 문서명 기반 컨텍스트 보강 (named-document chunk rescue) - GAP #1
    # ========================================================================
    def _resolve_named_document_rescue(self) -> tuple[bool, int, int]:
        """명시 문서 보강 설정을 해석한다(opt-in, 기본 OFF).

        Returns:
            (enabled, max_chunks, digest_max_lines)
        """
        rag_config = self.config.get("rag", {})
        configured = rag_config.get("named_document_rescue", {})
        rescue_config = configured if isinstance(configured, dict) else {}

        enabled = _coerce_bool(rescue_config.get("enabled"), default=False)
        max_chunks = _coerce_bounded_int(rescue_config.get("max_chunks"), 4, 1, 12)
        digest_max_lines = _coerce_bounded_int(
            rescue_config.get("digest_max_lines"), 40, 20, 120
        )
        return enabled, max_chunks, digest_max_lines

    async def _list_documents_for_named_rescue(self) -> list[dict[str, Any]]:
        """retriever에서 문서 목록을 조회한다(GAP #1, 미지원 시 빈 리스트)."""
        retrieval_module = self.retrieval_module
        if asyncio.iscoroutine(retrieval_module) or isinstance(
            retrieval_module, asyncio.Future
        ):
            retrieval_module = await retrieval_module

        method = getattr(retrieval_module, "list_documents", None)
        if not callable(method):
            orchestrator = getattr(retrieval_module, "orchestrator", None)
            method = getattr(orchestrator, "list_documents", None)
        if not callable(method):
            logger.debug("명시 문서 보강 스킵 - list_documents 미지원")
            return []

        try:
            payload = await method(page=1, page_size=_NAMED_DOCUMENT_LIST_PAGE_SIZE)
        except NotImplementedError:
            logger.debug("명시 문서 보강 스킵 - list_documents 미구현")
            return []
        except Exception as exc:
            logger.warning(
                "명시 문서 목록 조회 실패 - 원본 검색 결과 유지",
                extra={"error": str(exc)},
                exc_info=True,
            )
            return []

        if isinstance(payload, dict) and isinstance(payload.get("documents"), list):
            return [doc for doc in payload["documents"] if isinstance(doc, dict)]
        if isinstance(payload, list):
            return [doc for doc in payload if isinstance(doc, dict)]
        return []

    async def _get_chunks_for_named_rescue(self, document_id: str) -> list[Any]:
        """지목 문서의 전체 청크를 조회한다(GAP #1, 미지원/실패 시 빈 리스트)."""
        retrieval_module = self.retrieval_module
        if asyncio.iscoroutine(retrieval_module) or isinstance(
            retrieval_module, asyncio.Future
        ):
            retrieval_module = await retrieval_module

        method = getattr(retrieval_module, "get_document_chunks", None)
        if not callable(method):
            orchestrator = getattr(retrieval_module, "orchestrator", None)
            method = getattr(orchestrator, "get_document_chunks", None)
        if not callable(method):
            return []

        try:
            chunks = await method(document_id)
        except NotImplementedError:
            return []
        except Exception as exc:
            logger.warning(
                "명시 문서 청크 조회 실패 - 해당 문서 보강 생략",
                extra={"document_id": document_id, "error": str(exc)},
                exc_info=True,
            )
            return []
        return chunks if isinstance(chunks, list) else []

    def _named_document_chunk_result(
        self,
        chunk: Any,
        document_record: dict[str, Any],
        score: float,
    ) -> SearchResult | None:
        """청크를 보강용 SearchResult로 변환한다(GAP #1)."""
        content = _document_content(chunk)
        if not content.strip():
            return None

        metadata = dict(_document_metadata(chunk))
        metadata.pop("content", None)
        metadata.pop("embedding", None)
        metadata["named_document_rescue"] = True
        metadata.setdefault("document_id", document_record.get("id"))
        metadata.setdefault("source_file", document_record.get("filename"))
        metadata.setdefault("file_type", document_record.get("file_type"))

        chunk_id = _document_value(chunk, "id")
        if chunk_id in (None, ""):
            document_id = metadata.get("document_id") or "unknown"
            chunk_index = metadata.get("chunk_index", metadata.get("chunk", "na"))
            chunk_id = f"{document_id}:named:{chunk_index}"
        return SearchResult(
            id=str(chunk_id), content=content, score=score, metadata=metadata
        )

    def _rank_named_document_chunks(
        self,
        message: str,
        chunks: list[Any],
        document_record: dict[str, Any],
        max_chunks: int,
    ) -> list[SearchResult]:
        """지목 문서 청크를 질의 관련성 기준으로 정렬해 상위 N개를 반환한다(GAP #1)."""
        terms = _named_document_match_terms(message)
        quoted_hints = _quoted_content_hints(message)
        scored_chunks: list[tuple[int, int, SearchResult]] = []
        for index, chunk in enumerate(chunks):
            result = self._named_document_chunk_result(chunk, document_record, 1.0)
            if result is None:
                continue
            normalized_content = _normalize_named_document_text(result.content)
            content_score = sum(len(term) for term in terms if term in normalized_content)
            content_score += sum(
                len(hint) * 3 for hint in quoted_hints if hint in normalized_content
            )
            chunk_index = _context_chunk_index(result)
            stable_index = chunk_index if chunk_index is not None else index
            scored_chunks.append((content_score, stable_index, result))

        if not scored_chunks:
            return []

        ranked = sorted(scored_chunks, key=lambda item: (-item[0], item[1]))
        selected = ranked[:max_chunks]
        # 질의와 겹치는 라인이 전혀 없으면(최고점=0) 원래 청크 순서대로 앞부분을 제공한다.
        if selected and selected[0][0] == 0:
            selected = sorted(scored_chunks, key=lambda item: item[1])[:max_chunks]

        results: list[SearchResult] = []
        for offset, (_, _, result) in enumerate(selected):
            # 실제 히트보다 약간 낮은 점수대로 두어 정렬/표기 오염을 방지한다.
            result.score = max(0.95 - (offset * 0.01), 0.5)
            results.append(result)
        return results

    def _named_document_digest_result(
        self,
        message: str,
        chunks: list[Any],
        document_record: dict[str, Any],
        max_lines: int,
    ) -> SearchResult | None:
        """지목 문서 전체에서 질의 관련 라인을 모아 digest 결과를 만든다(GAP #1).

        벡터 검색이 놓친 문서라도 사용자가 명시한 이상, 전체에서 후보 근거를 한 번에
        제공해 답변 누락을 막는다. _generation_only로 표기해 인접 청크 확장/카운트에서
        제외되도록 한다.
        """
        terms = _named_document_match_terms(message)
        quoted_hints = _quoted_content_hints(message)
        scored_lines: list[tuple[int, int, str]] = []
        seen: set[str] = set()

        for chunk_order, chunk in enumerate(chunks):
            chunk_index = _context_chunk_index(chunk)
            stable_chunk_index = chunk_index if chunk_index is not None else chunk_order
            content = _document_content(chunk)
            for line_order, raw_line in enumerate(content.splitlines()):
                line = " ".join(raw_line.split())
                if not line:
                    continue
                if len(line) > 260:
                    line = f"{line[:257]}..."
                normalized_line = _normalize_named_document_text(line)
                if not normalized_line or normalized_line in seen:
                    continue

                score = 0
                if any(hint and hint in normalized_line for hint in quoted_hints):
                    score += 80
                score += sum(min(len(term), 12) for term in terms if term in normalized_line)
                if _NAMED_DOCUMENT_HIGH_VALUE_PATTERN.search(line):
                    score += 10
                if score <= 0:
                    continue

                seen.add(normalized_line)
                scored_lines.append(
                    (
                        score,
                        (stable_chunk_index * 1000) + line_order,
                        f"chunk {stable_chunk_index} line {line_order + 1}: {line}",
                    )
                )

        if not scored_lines:
            return None

        selected = sorted(scored_lines, key=lambda item: (-item[0], item[1]))[:max_lines]
        selected = sorted(selected, key=lambda item: item[1])
        digest_lines = [
            "named_document_digest: 질문에 명시된 문서 전체에서 뽑은 관련 후보 근거입니다.",
            *[line for _, _, line in selected],
        ]

        document_id = str(document_record.get("id") or "named-document")
        filename = str(
            document_record.get("filename") or document_record.get("source_file") or ""
        )
        metadata: dict[str, Any] = {
            "document_id": document_id,
            "source_file": filename,
            "file_type": document_record.get("file_type"),
            "chunk_index": -1,
            "named_document_digest": True,
            "_generation_only": True,
        }
        return SearchResult(
            id=f"{document_id}:named-digest",
            content="\n".join(digest_lines),
            score=0.99,
            metadata=metadata,
        )

    async def prepend_named_document_chunks(
        self,
        message: str,
        ranked_results: list[Any],
        options: dict[str, Any],
    ) -> list[Any]:
        """질문에 명시된 문서의 청크를 검색 결과 앞에 prepend한다(GAP #1, 기본 OFF).

        사용자가 파일명(확장자)이나 따옴표 인용구로 특정 문서를 지목하면, 벡터 검색이
        그 문서를 놓쳐도 list_documents/get_document_chunks로 직접 fetch해 digest +
        ranked chunks를 앞에 붙인다. 인접 청크 확장(expand_context_documents)과는
        독립된 별개 경로이며, 미지원 retriever면 graceful no-op으로 원본을 유지한다.

        Args:
            message: 사용자 질문(원문)
            ranked_results: 리랭킹까지 끝난 검색 결과
            options: 요청 옵션(현재 미사용, 시그니처 호환/확장 여지용)

        Returns:
            보강된 결과(앞: 명시 문서 digest/청크, 뒤: 원본). no-op이면 원본 그대로.
        """
        enabled, max_chunks, digest_max_lines = self._resolve_named_document_rescue()
        if not enabled or not ranked_results:
            return ranked_results

        requested_filenames = _requested_document_filenames(message)
        if not requested_filenames:
            return ranked_results

        document_records = await self._list_documents_for_named_rescue()
        if not document_records:
            return ranked_results

        rescued: list[SearchResult] = []
        for filename in requested_filenames:
            matching_records = [
                document
                for document in document_records
                if _document_matches_requested_filename(filename, document)
            ]
            # 동명 문서가 여럿이어도 첫 매칭 1건만 보강해 컨텍스트 폭증을 막는다.
            for record in matching_records[:1]:
                document_id = record.get("id")
                if document_id in (None, ""):
                    continue
                chunks = await self._get_chunks_for_named_rescue(str(document_id))
                if not chunks:
                    continue
                digest = self._named_document_digest_result(
                    message, chunks, record, digest_max_lines
                )
                if digest is not None:
                    rescued.append(digest)
                rescued.extend(
                    self._rank_named_document_chunks(
                        message, chunks, record, max_chunks
                    )
                )

        if not rescued:
            return ranked_results

        # 명시 문서 보강 결과를 앞에, 원본을 뒤에 두고 청크 동일성 기준 중복을 제거한다.
        expanded: list[Any] = []
        seen: set[tuple[Any, ...]] = set()
        for document in [*rescued, *ranked_results]:
            identity = _context_chunk_identity(document)
            if identity in seen:
                continue
            seen.add(identity)
            expanded.append(document)

        logger.info(
            "명시 문서명 기반 컨텍스트 보강 완료",
            extra={
                "requested_filenames": requested_filenames,
                "rescued_chunks": len(rescued),
                "base_count": len(ranked_results),
                "expanded_count": len(expanded),
            },
        )
        return expanded

    def _resolve_rag_mode(self, options: dict[str, Any]) -> str:
        """Resolve local/grok_search/grok_answer without changing default local flow."""
        explicit_mode = options.get("rag_mode") or options.get("grok_mode")
        if explicit_mode:
            return self._normalize_rag_mode(str(explicit_mode))

        vector_db_config = self.config.get("vector_db", {})
        vector_provider = (
            vector_db_config.get("provider")
            or self.config.get("vector_store", {}).get("provider")
            or os.getenv("VECTOR_DB_PROVIDER", "")
        )
        if str(vector_provider).lower() != "grok":
            return "local"

        grok_config = self.config.get("grok", {})
        return self._normalize_rag_mode(str(grok_config.get("mode", "search")))

    @staticmethod
    def _normalize_rag_mode(mode: str) -> str:
        normalized = mode.strip().lower().replace("-", "_")
        aliases = {
            "local": "local",
            "standard": "local",
            "grok": "grok_search",
            "grok_search": "grok_search",
            "search": "grok_search",
            "grok_answer": "grok_answer",
            "answer": "grok_answer",
        }
        return aliases.get(normalized, "local")

    def _format_grok_citations(self, citations: list[Any]) -> list[Any]:
        """Convert Grok citation payloads into OneRAG Source objects."""
        sources: list[Any] = []
        for idx, citation in enumerate(citations):
            source_data = normalize_citation_source_payload(idx, citation, source_type="grok")
            sources.append(self.Source(**source_data))
        return sources

    async def _execute_grok_answer_mode(
        self,
        message: str,
        start_time: float,
        options: dict[str, Any],
        routing_metadata: dict[str, Any],
    ) -> RAGResultDict:
        """Execute Grok managed RAG answer mode as a narrow fast path."""
        provider = self.grok_answer_provider
        if asyncio.iscoroutine(provider) or isinstance(provider, asyncio.Future):
            provider = await provider

        if provider is None:
            raise RetrievalError(
                ErrorCode.GROK_003,
                reason="Grok answer mode requested but GrokAnswerProvider is not configured",
            )

        result = await provider.answer(
            question=message,
            collection_ids=options.get("collection_ids") or options.get("grok_collection_ids"),
            system_prompt=options.get("system_prompt"),
            top_k=options.get("top_k") or options.get("limit"),
            temperature=float(options.get("temperature", 0.0)),
            include_code_interpreter=bool(options.get("include_code_interpreter", False)),
        )
        sources = self._format_grok_citations(result.citations)
        model_info = {
            "provider": result.provider,
            "model": result.model_used,
            "model_used": result.model_used,
            "mode": "grok_answer",
            "tool_usage": result.tool_usage,
            "citations_count": len(result.citations),
        }
        routing_metadata = {
            **routing_metadata,
            "rag_mode": "grok_answer",
            "source": routing_metadata.get("source", "grok"),
        }
        return self.build_result(
            answer=result.answer,
            sources=sources,
            tokens_used=result.tokens_used,
            topic=self.extract_topic_func(message),
            processing_time=time.time() - start_time,
            search_count=len(result.citations),
            ranked_count=len(result.citations),
            model_info=model_info,
            routing_metadata=routing_metadata,
        )

    # ========================================
    # 멀티턴 standalone query rewrite
    # ========================================

    # 멀티턴 standalone rewrite 게이트용 기본 패턴 (한국어 기본값,
    # yaml의 rag.multiturn_rewrite.followup_*_patterns로 언어별 오버라이드 가능)
    # (1) 후속 질문임을 강하게 시사하는 대명사/지시어/생략 표현
    #     주의: "그리고"/"추가로" 같은 일반 접속사는 자립 질문에도 흔히 등장하므로
    #     여기서 제외하고, 문장 시작 위치에서만 후속 신호로 취급한다.
    _DEFAULT_FOLLOWUP_DEPENDENT_PATTERNS: tuple[str, ...] = (
        "그건", "그게", "그것", "그거", "이건", "이게", "이것", "이거",
        "저건", "저게", "그럼", "그러면", "그때", "거기", "여기",
        "위의", "앞서", "방금", "해당", "그 경우", "이 경우", "그 외",
    )

    # (1-b) 문장 시작 위치에서만 후속 신호로 보는 접속사
    #       (문장 중간의 "A 그리고 B"는 자립 질문이므로 게이트를 통과시키지 않는다)
    _DEFAULT_FOLLOWUP_START_PATTERNS: tuple[str, ...] = (
        "그리고", "추가로", "또", "또한",
    )

    # standalone rewrite 기본 프롬프트 템플릿 (한국어, 출력 언어 보존용)
    # yaml의 rag.multiturn_rewrite.prompt_template로 오버라이드 가능하며,
    # 비한국어 외주는 이 템플릿을 해당 언어로 교체할 수 있다.
    # 플레이스홀더: {session_context}(직전 대화 맥락), {message}(후속 질문)
    _DEFAULT_MULTITURN_REWRITE_PROMPT: str = (
        "당신은 멀티턴 대화의 후속 질문을 검색에 적합한 자립적(standalone) "
        "질문으로 재작성하는 전문가입니다.\n\n"
        "아래 [직전 대화 맥락]을 참고하여, [후속 질문]에서 생략되거나 "
        "대명사/지시어로 표현된 핵심 대상(프로그램명, 제도명, 주체 등)을 "
        "명시적으로 복원해 하나의 완결된 질문으로 다시 쓰세요.\n"
        "- 맥락에 없는 정보를 새로 추가하지 마세요.\n"
        "- 후속 질문의 의도를 바꾸지 마세요.\n"
        "- 설명 없이 재작성된 질문 한 문장만 출력하세요.\n\n"
        "[직전 대화 맥락]\n{session_context}\n\n"
        "[후속 질문]\n{message}\n\n"
        "[재작성된 자립적 질문]"
    )

    def _needs_standalone_rewrite(self, message: str) -> bool:
        """
        멀티턴 standalone rewrite가 필요한지 판정하는 게이트.

        후속 질문이 대명사/지시어/생략 표현에 의존하거나 너무 짧아
        그 자체로는 검색 맥락이 불충분한 경우에만 True를 반환한다.
        이미 자립적(충분히 길고 구체적)인 질문은 False를 반환해 불필요한
        LLM 호출과 지연을 막는다.

        Args:
            message: 후속 사용자 질문(원본)

        Returns:
            True면 재작성 필요(LLM 호출 대상), False면 게이트에서 건너뜀.
        """
        stripped = message.strip()
        if not stripped:
            return False

        # (1) 대명사/지시어/생략 표현 포함 → 자립 불가로 간주
        if any(pattern in stripped for pattern in self.multiturn_followup_dependent_patterns):
            return True

        # (1-b) 문장 시작 위치의 접속사만 후속 신호로 취급
        #       (문장 중간 "A 그리고 B"는 자립 질문이므로 제외)
        if any(stripped.startswith(pattern) for pattern in self.multiturn_followup_start_patterns):
            return True

        # (2) 짧은 후속 질문(맥락 생략형). 어절(공백 분리) 기준으로 판단.
        #     예: "정규직 요건은?" 처럼 핵심 대상(프로그램명 등)이 생략된 형태.
        #     충분히 긴 질문은 자립적으로 보고 건너뛴다.
        word_count = len(stripped.split())
        if word_count <= self.multiturn_short_question_max_words:
            return True

        # (3) 그 외 길고 구체적인 질문은 자립적으로 간주 → 재작성 불필요
        return False

    # 재작성 결과 정제용: 모델이 흔히 붙이는 라벨 접두어
    _REWRITE_LABEL_PATTERN = re.compile(
        r"^\s*(재작성(된)?\s*(질문|쿼리)?|standalone(\s*query)?|질문|rewritten\s*query)\s*[:：]\s*",
        re.IGNORECASE,
    )

    # 재작성 프롬프트 플레이스홀더 치환용: 두 토큰을 단일 패스로 치환해
    # 치환 값 내부 토큰 재치환을 차단한다 (순차 replace는 앞선 치환 결과를
    # 재스캔하므로, 직전 대화에 리터럴 '{message}'가 있으면 컨텍스트 블록에
    # 새 질문이 주입되는 인젝션 벡터가 된다).
    _REWRITE_PLACEHOLDER_PATTERN = re.compile(r"\{session_context\}|\{message\}")

    def _postprocess_rewritten_query(self, content: str | None) -> str:
        """
        LLM 재작성 결과를 검색에 안전하게 투입하도록 경량 정제한다.

        모델이 프롬프트 지시를 어기고 여러 줄/머리말 라벨/따옴표를 붙이는 경우를
        방어한다. 첫 번째 비어있지 않은 줄만 취하고, "재작성: " 같은 라벨과
        앞뒤 따옴표를 제거한다.

        Args:
            content: LLM 원본 응답 텍스트(None 가능)

        Returns:
            정제된 한 줄 질문 문자열(정제 후 비면 빈 문자열).
        """
        if not content:
            return ""

        # 첫 번째 비어있지 않은 줄만 사용 (여러 줄 방어)
        first_line = ""
        for line in content.splitlines():
            if line.strip():
                first_line = line.strip()
                break
        if not first_line:
            return ""

        # 라벨 접두어 제거 (예: "재작성된 질문: ...")
        first_line = self._REWRITE_LABEL_PATTERN.sub("", first_line).strip()

        # 앞뒤 따옴표 제거 (직선/곡선 따옴표 모두)
        first_line = first_line.strip("\"'“”‘’").strip()

        return first_line

    async def _rewrite_standalone_query(
        self, message: str, session_context: str | None
    ) -> str:
        """
        직전 대화 맥락을 반영해 후속 질문을 자립적(standalone) 질문으로 재작성.

        게이트(`_needs_standalone_rewrite`)와 사전 조건(설정 활성화, 세션 맥락,
        llm_factory 존재)을 모두 통과한 경우에만 LLM을 호출한다. 재작성에
        실패하면(예외/빈 결과) 원본 질문으로 graceful 폴백하여 검색을 계속한다.

        Args:
            message: 후속 사용자 질문(원본)
            session_context: 직전 대화 컨텍스트 문자열(없으면 재작성 생략)

        Returns:
            재작성된 standalone 질문, 또는 폴백 시 원본 질문.
        """
        # 사전 조건 확인 (어느 하나라도 불충족이면 원본 반환)
        if not self.multiturn_rewrite_enabled:
            return message
        if not session_context or not session_context.strip():
            return message
        if self.llm_factory is None:
            logger.debug("standalone rewrite 생략: llm_factory 없음")
            return message

        # 게이트: 자립적 질문이면 LLM 호출 없이 건너뜀
        if not self._needs_standalone_rewrite(message):
            logger.debug(
                "standalone rewrite 게이트 통과(자립적 질문), 재작성 생략",
                extra={"message": message[:40]},
            )
            return message

        # LLM 재작성 프롬프트 구성 (설정 템플릿 기반, 기본값=한국어 프롬프트)
        # 템플릿에 {session_context}/{message} 외 중괄호가 있어도 깨지지 않도록
        # 안전 치환한다(format은 임의 중괄호에 취약).
        # 컴파일된 패턴으로 두 토큰을 단일 패스 치환해, 치환 값 내부에
        # 리터럴 토큰이 있어도 재치환되지 않도록 차단한다.
        values = {"{session_context}": session_context, "{message}": message}
        prompt = self._REWRITE_PLACEHOLDER_PATTERN.sub(
            lambda m: values[m.group(0)], self.multiturn_rewrite_prompt_template
        )

        try:
            # 결정적(temperature=0.0) 호출로 재작성의 비결정성을 차단.
            # max_tokens는 thinking(추론) 모델이 추론에 토큰을 소진해 출력이
            # 빈 채 truncate되는 회귀(실가동 관측)를 막기 위해 넉넉히 둔다.
            content, provider = await self.llm_factory.generate_with_fallback(
                prompt=prompt,
                system_prompt=None,
                preferred_provider=self.multiturn_rewrite_provider,
                temperature=0.0,
                max_tokens=2048,
            )
            rewritten = self._postprocess_rewritten_query(content)
            # 빈 결과/비정상적으로 긴 결과는 신뢰하지 않고 폴백
            if not rewritten or len(rewritten) > len(message) + 200:
                logger.warning(
                    "standalone rewrite 결과 비정상, 원본 사용",
                    extra={"original": message[:40]},
                )
                return message

            logger.info(
                "standalone rewrite 성공",
                extra={
                    "provider": provider,
                    "original": message[:40],
                    "rewritten": rewritten[:60],
                },
            )
            return rewritten
        except Exception as e:
            # LLM 실패는 채팅을 깨뜨리지 않고 원본으로 폴백
            logger.warning(
                "standalone rewrite 실패, 원본 사용",
                extra={"error": str(e), "original": message[:40]},
                exc_info=True,
            )
            return message

    @staticmethod
    def _coerce_positive_timeout(value: Any) -> float | None:
        """타임아웃 설정값을 양수 float로 변환한다.

        0 이하/숫자 아님/None이면 None(=무제한)을 반환해 해당 stage·budget의
        wait_for 래핑을 건너뛰게 한다. 잘못된 설정으로 정상 요청이 끊기는
        것을 막기 위한 안전 폴백이다.

        Args:
            value: YAML에서 읽은 타임아웃 값(초)

        Returns:
            양수 float 또는 None(무제한)
        """
        if value is None:
            return None
        try:
            seconds = float(value)
        except (TypeError, ValueError):
            return None
        return seconds if seconds > 0 else None

    async def _run_stage_with_timeout(
        self,
        stage_name: str,
        coro: Awaitable[_StageT],
        *,
        remaining_budget: float | None = None,
    ) -> _StageT:
        """단일 stage 코루틴을 deadline으로 감싸 실행한다.

        - pipeline_timeout.enabled=false거나 stage 예산이 없으면 그대로 await
          한다(기존 동작 유지).
        - stage 예산과 남은 총 budget 중 "더 작은 값"을 실제 deadline으로 쓴다.
          이렇게 하면 stage 자체는 여유가 있어도 총 budget이 임박하면 즉시
          PIPE-002(총 budget 초과)로 끊긴다.
        - deadline 초과 시 무한 대기 대신 PipelineTimeoutError를 던져 "어느
          단계에서 몇 초를 초과했는지"를 명확히 전달한다.

        Args:
            stage_name: stage 이름(에러 메시지·로그용)
            coro: 실행할 stage 코루틴
            remaining_budget: 총 budget에서 남은 시간(초). None이면 미적용.

        Returns:
            stage 코루틴의 반환값

        Raises:
            PipelineTimeoutError: stage deadline(PIPE-001) 또는 총 budget(PIPE-002) 초과
        """
        if not self.pipeline_timeout_enabled:
            return await coro

        stage_budget = self.pipeline_stage_budgets.get(stage_name)

        # 총 budget이 임박하면(남은 시간이 stage 예산보다 작으면) 그 값으로 끊는다.
        effective_timeout = stage_budget
        budget_is_limiting = False
        if remaining_budget is not None:
            if effective_timeout is None or remaining_budget < effective_timeout:
                effective_timeout = remaining_budget
                budget_is_limiting = True

        if effective_timeout is None:
            # stage·총 budget 모두 무제한 → 기존 동작
            return await coro

        try:
            return await asyncio.wait_for(coro, timeout=effective_timeout)
        except TimeoutError as exc:
            if budget_is_limiting:
                logger.warning(
                    "파이프라인 총 budget 초과",
                    extra={
                        "stage": stage_name,
                        "total_budget_seconds": self.pipeline_total_budget_seconds,
                    },
                )
                raise PipelineTimeoutError(
                    ErrorCode.PIPELINE_TOTAL_TIMEOUT,
                    stage=stage_name,
                    timeout=self.pipeline_total_budget_seconds,
                ) from exc
            logger.warning(
                "파이프라인 stage deadline 초과",
                extra={"stage": stage_name, "timeout_seconds": effective_timeout},
            )
            raise PipelineTimeoutError(
                ErrorCode.PIPELINE_STAGE_TIMEOUT,
                stage=stage_name,
                timeout=effective_timeout,
            ) from exc

    def _remaining_total_budget(self, start_time: float) -> float | None:
        """총 budget에서 남은 시간(초)을 계산한다.

        Args:
            start_time: 파이프라인 시작 시각(time.time())

        Returns:
            남은 budget(초). budget 미설정/비활성화면 None.
            이미 초과했으면 0.0(다음 stage가 즉시 PIPE-002로 끊김).
        """
        if not self.pipeline_timeout_enabled or self.pipeline_total_budget_seconds is None:
            return None
        remaining = self.pipeline_total_budget_seconds - (time.time() - start_time)
        return remaining if remaining > 0 else 0.0

    def _remaining_stream_budget(self, start_time: float) -> float | None:
        """스트리밍 총 예산에서 남은 시간(초)을 계산한다.

        스트리밍 경로는 프론트 HTTP 타임아웃에 묶이지 않는 장수명 연결이므로
        통짜 총 budget과 별도의 넉넉한 예산(stream_total_budget_seconds)을 쓴다.

        Args:
            start_time: 스트리밍 시작 시각(time.time())

        Returns:
            남은 예산(초). 미설정/비활성화면 None(무제한, stage deadline만 적용).
            이미 초과했으면 0.0.
        """
        if (
            not self.pipeline_timeout_enabled
            or self.pipeline_stream_total_budget_seconds is None
        ):
            return None
        remaining = self.pipeline_stream_total_budget_seconds - (time.time() - start_time)
        return remaining if remaining > 0 else 0.0

    @observe(name="RAG Pipeline", capture_input=False, capture_output=False)
    async def execute(
        self, message: str, session_id: str, options: dict[str, Any] | None = None
    ) -> RAGResultDict:
        """
        전체 RAG 파이프라인 실행 (7단계 오케스트레이션)

        Args:
            message: 사용자 쿼리
            session_id: 세션 ID
            options: 추가 옵션 (limit, min_score, top_n, enable_debug_trace 등)

        Returns:
            표준 응답 딕셔너리

        Raises:
            RoutingError: 라우팅 실패 시
            RetrievalError: 검색 실패 시
            GenerationError: 답변 생성 실패 시
        """
        start_time = time.time()
        options = options or {}
        logger.info("RAG Pipeline 시작", extra={"query": message[:50]})

        enable_debug_trace = options.get("enable_debug_trace", False)
        debug_trace_data: dict[str, Any] = {} if enable_debug_trace else {}

        use_agent = options.get("use_agent", False)
        if use_agent and self.agent_orchestrator:
            logger.info("Agent 모드 활성화", extra={"orchestrator": "AgentOrchestrator"})
            return await self._execute_agent_mode(message, session_id, start_time)

        tracker = PipelineTracker()
        tracker.start_pipeline()
        tracker.start_stage("route_query")
        route_decision = await self._run_stage_with_timeout(
            "route_query",
            self.route_query(message, session_id, start_time),
            remaining_budget=self._remaining_total_budget(start_time),
        )
        tracker.end_stage("route_query")

        if not route_decision.should_continue:
            logger.info("라우팅 결과: 즉시 응답 반환 (RAG 파이프라인 중단)")
            if route_decision.immediate_response is None:
                logger.error("immediate_response가 None입니다. 완전한 기본 응답 반환")
                return self._create_fallback_response(message, start_time, route_decision.metadata)
            return route_decision.immediate_response

        if enable_debug_trace:
            debug_trace_data["original_query"] = message

        # 라우팅 결과(data_source)를 검색 옵션에 주입한다(GAP G).
        # data_source는 질문 텍스트 기반으로 매 요청 재판단되며, filter_mappings가
        # 비어있으면 _build_retrieval_filters에서 no-op으로 처리된다(회귀 0).
        data_source = route_decision.metadata.get("data_source")
        if data_source is not None:
            options["data_source"] = data_source

        rag_mode = self._resolve_rag_mode(options)
        route_decision.metadata["rag_mode"] = rag_mode
        if rag_mode == "grok_answer":
            logger.info("Grok answer mode 실행")
            return await self._execute_grok_answer_mode(
                message=message,
                start_time=start_time,
                options=options,
                routing_metadata=route_decision.metadata,
            )

        tracker.start_stage("prepare_context")
        prepared_context = await self._run_stage_with_timeout(
            "prepare_context",
            self.prepare_context(message, session_id),
            remaining_budget=self._remaining_total_budget(start_time),
        )
        tracker.end_stage("prepare_context")

        if enable_debug_trace:
            debug_trace_data["query_transformation"] = {
                "original": message,
                "expanded": prepared_context.expanded_query if prepared_context.expanded_query != message else None,
                "final_query": prepared_context.expanded_query,
            }

        tracker.start_stage("retrieve_documents")
        retrieval_results, sql_search_result = await self._run_stage_with_timeout(
            "retrieve_documents",
            self._execute_parallel_search(message, prepared_context, options),
            remaining_budget=self._remaining_total_budget(start_time),
        )
        tracker.end_stage("retrieve_documents")

        self._track_debug_documents(enable_debug_trace, debug_trace_data, retrieval_results.documents)
        self._update_retrieval_metrics(tracker, prepared_context, sql_search_result)

        tracker.start_stage("rerank_documents")
        rerank_results = await self._run_stage_with_timeout(
            "rerank_documents",
            self.rerank_documents(
                prepared_context.expanded_query, retrieval_results.documents, options
            ),
            remaining_budget=self._remaining_total_budget(start_time),
        )
        tracker.end_stage("rerank_documents")

        # 리랭크 fusion guardrail(#33): 리랭커가 실제로 수행됐을 때만 적용한다.
        # 리랭커가 lexical/hybrid 상위 신호를 죽이는 것을 막아 recall@5/MRR을 보존한다.
        # 기본 비활성화(opt-in)이므로 reranking.fusion.enabled가 꺼져 있으면 no-op이다.
        if rerank_results.reranked:
            fused_documents = self._fuse_reranked_results_with_original_signals(
                rerank_results.documents,
                self.config.get("reranking", {}),
                options,
            )
            rerank_results = RerankResults(
                documents=fused_documents,
                count=len(fused_documents),
                reranked=True,
            )

        # 정확 식별자 rerank 안정화(GAP A, 기본 OFF): 리랭커가 정확 식별자 문서를
        # 하위로 밀어버린 경우를 NFKC 정규화 정확매칭 기준으로 상위 보정한다.
        # exact_identifier.enabled=false면 no-op. 리랭킹 미수행 시에도 검색 단계의
        # 정확매칭을 보존하기 위해 항상 적용한다(2차 신호/임계 게이트로 내부 no-op 보호).
        stabilized_documents = self._stabilize_reranked_results_with_exact_signals(
            prepared_context.expanded_query,
            rerank_results.documents,
        )
        if stabilized_documents is not rerank_results.documents:
            rerank_results = RerankResults(
                documents=stabilized_documents,
                count=len(stabilized_documents),
                reranked=rerank_results.reranked,
            )

        # 멀티턴 anchor soft boost(GAP B, 기본 OFF): 직전 인용 문서를 약하게 우대한다.
        # anchor_sources가 있고 같은 주제(후속)일 때만 의미가 있으며, 없으면 no-op.
        # hard filter가 아니므로 고착 위험을 최소화한다(stabilize 이후 최종 후처리).
        if prepared_context.anchor_sources:
            boosted_documents = self._apply_anchor_soft_boost(
                prepared_context.anchor_sources,
                rerank_results.documents,
            )
            if boosted_documents is not rerank_results.documents:
                rerank_results = RerankResults(
                    documents=boosted_documents,
                    count=len(boosted_documents),
                    reranked=rerank_results.reranked,
                )

        if enable_debug_trace and rerank_results.reranked:
            for i, doc in enumerate(rerank_results.documents):
                if i < len(debug_trace_data["retrieved_documents"]):
                    rerank_score = doc.metadata.get("rerank_score", 0.0) if hasattr(doc, "metadata") else 0.0
                    debug_trace_data["retrieved_documents"][i]["rerank_score"] = rerank_score

        tracker.start_stage("expand_context")
        # 명시 문서명 기반 보강(GAP #1, 기본 OFF): 질문에 파일명/인용구로 지목된 문서를
        # 검색이 놓쳤을 때 그 문서 청크를 결과 앞에 prepend한다. 인접 청크 확장과는
        # 별개 경로이며, 보강된 결과를 인접 청크 확장의 입력으로 넘겨 일관 처리한다.
        base_documents = await self.prepend_named_document_chunks(
            message, rerank_results.documents, options
        )
        context_documents = await self.expand_context_documents(base_documents, options)
        tracker.end_stage("expand_context")

        tracker.start_stage("generate_answer")
        generation_options = {**options}
        # 컨텍스트 확장/명시 문서 보강으로 문서가 늘어났을 때만 프롬프트 한도를 상향(20)해
        # 실제 검색 히트가 이웃/보강 청크에 밀려 프롬프트에서 빠지지 않게 한다(#3).
        if len(context_documents) > len(rerank_results.documents):
            generation_options.setdefault("max_context_documents", 20)
        if sql_search_result and sql_search_result.used:
            generation_options["sql_context"] = sql_search_result.formatted_context
            logger.debug(
                "SQL 컨텍스트 전달",
                extra={"context_length": len(sql_search_result.formatted_context)}
            )
        generation_result = await self._run_stage_with_timeout(
            "generate_answer",
            self.generate_answer(
                message, context_documents, prepared_context.session_context, generation_options
            ),
            remaining_budget=self._remaining_total_budget(start_time),
        )
        tracker.end_stage("generate_answer")

        tracker.start_stage("self_rag_verify")
        options_with_debug = {**options}
        if enable_debug_trace:
            options_with_debug["_debug_trace_data"] = debug_trace_data
        generation_result = await self._run_stage_with_timeout(
            "self_rag_verify",
            self.self_rag_verify(
                message, session_id, generation_result, context_documents, options_with_debug
            ),
            remaining_budget=self._remaining_total_budget(start_time),
        )
        # 환각 방지 게이트(GAP C, 기본 OFF): 질문 기간과 문서 기간이 완전 불일치하면
        # 최종 답변을 '확인 불가'로 교체한다. self_rag_verify 이후 최종 답변 기준 1회.
        generation_result = self._apply_hallucination_gate(
            message, generation_result, context_documents, options
        )
        tracker.end_stage("self_rag_verify")

        tracker.start_stage("format_sources")
        formatted_sources = self.format_sources(context_documents, sql_search_result)
        tracker.end_stage("format_sources")

        tracker.start_stage("build_result")
        debug_trace = self._create_debug_trace(enable_debug_trace, debug_trace_data, message)
        result = self.build_result(
            answer=generation_result.answer,
            sources=formatted_sources.sources,
            tokens_used=generation_result.tokens_used,
            topic=self.extract_topic_func(message),
            processing_time=time.time() - start_time,
            search_count=retrieval_results.count,
            # 인접 청크 확장 이웃 청크와 명시 문서 digest(_generation_only)는 실제 히트가
            # 아니므로 카운트에서 제외(#4, GAP #1)
            ranked_count=sum(
                1
                for doc in context_documents
                if not _document_metadata(doc).get("context_expanded")
                and not _document_metadata(doc).get("_generation_only")
            ),
            model_info=generation_result.model_info,
            routing_metadata=route_decision.metadata,
            debug_trace=debug_trace,
            quality_score=getattr(generation_result, "quality_score", None),
            refusal_reason=getattr(generation_result, "refusal_reason", None),
        )
        tracker.end_stage("build_result")
        tracker.end_pipeline()
        performance_metrics = tracker.get_metrics()
        tracker.log_summary()
        result["performance_metrics"] = performance_metrics
        logger.info(
            "RAG Pipeline 완료",
            extra={"processing_time": result['processing_time']}
        )
        return result

    async def route_query(self, message: str, session_id: str, start_time: float) -> RouteDecision:
        """
        1단계: 쿼리 라우팅 (규칙 기반 + LLM 폴백)

        - 규칙 기반 라우터 우선 시도 (YAML 규칙)
        - LLM 라우터 폴백 (규칙 실패 시)
        - direct_answer/blocked 처리

        Args:
            message: 사용자 쿼리
            session_id: 세션 ID
            start_time: 파이프라인 시작 시간

        Returns:
            RouteDecision: 라우팅 결정 (계속 진행 여부 + 즉시 응답)

        Raises:
            RoutingError: 라우팅 실패 시
        """
        logger.debug("[1단계] 쿼리 라우팅 시작")
        routing_metadata = {}
        session_context = None
        if self.session_module:
            try:
                conversation = await self.session_module.get_conversation(
                    session_id, max_exchanges=5
                )
                if conversation and isinstance(conversation, list):
                    session_context = "\n".join(
                        [
                            f"User: {ex.get('user', '')}\nAssistant: {ex.get('assistant', '')}"
                            for ex in conversation
                        ]
                    )
            except Exception as e:
                logger.warning(
                    "세션 컨텍스트 조회 실패",
                    extra={"error": str(e)},
                    exc_info=True
                )
        try:
            # __init__에서 1회 생성한 라우터를 재사용한다.
            # 초기화에 실패했던 경우에만 공용 헬퍼로 lazy 생성 폴백한다.
            # (일시적 실패였다면 여기서 복구되고, 성공 시 캐시되어 재시도 중단)
            rule_router = self.rule_based_router
            if rule_router is None:
                rule_router = self._create_rule_based_router()
                self.rule_based_router = rule_router

            rule_match = await rule_router.check_rules(message)
            if rule_match:
                routing_metadata = {
                    "route": rule_match.route,
                    "intent": rule_match.intent,
                    "domain": rule_match.domain,
                    "confidence": rule_match.confidence,
                    "source": "rule_based",
                    "rule_name": rule_match.rule_name,
                }
                logger.info(
                    "[규칙 기반 라우터] 매칭",
                    extra={
                        "rule_name": rule_match.rule_name,
                        "route": rule_match.route,
                        "domain": rule_match.domain
                    }
                )
                if rule_match.route == "direct_answer" and rule_match.direct_answer:
                    processing_time = time.time() - start_time
                    immediate_response = {
                        "answer": rule_match.direct_answer,
                        "sources": [],
                        "tokens_used": 0,
                        "topic": self.extract_topic_func(message),
                        "processing_time": processing_time,
                        "search_count": 0,
                        "ranked_count": 0,
                        "model_info": {"provider": "rule_based", "model": "N/A"},
                        "routing_metadata": routing_metadata,
                    }

                    logger.info(
                        "[즉시 응답] 규칙 기반 답변 반환",
                        extra={"processing_time": processing_time}
                    )
                    return RouteDecision(
                        should_continue=False,
                        immediate_response=cast(RAGResultDict, immediate_response),
                        metadata=routing_metadata,
                    )
                return RouteDecision(
                    should_continue=True, immediate_response=None, metadata=routing_metadata
                )
        except Exception as rule_error:
            logger.warning(
                "[RuleBasedRouter] 오류",
                extra={"error": str(rule_error)},
                exc_info=True
            )
        if not self.query_router or not self.query_router.enabled:
            logger.info("[LLM 라우터] 비활성화 - RAG 계속 진행")
            return RouteDecision(
                should_continue=True, immediate_response=None, metadata=routing_metadata
            )
        try:
            profile, routing = await self.query_router.analyze_and_route(
                message, session_context=session_context
            )

            # 🆕 dataclass 속성 접근으로 수정 (Oracle 권장사항)
            routing_metadata.update(
                {
                    "llm_route": routing.primary_route,  # ✅ .get() → 속성 접근
                    "llm_intent": profile.intent.value if profile.intent else "unknown",  # ✅
                    "llm_domain": profile.domain,  # ✅
                    "llm_confidence": routing.confidence,  # ✅
                    "llm_reasoning": routing.notes or "",  # ✅
                    "data_source": getattr(profile, "data_source", "general"),  # 🆕 신규 필드
                    "source": routing_metadata.get("source", "llm"),
                    "profile": profile,
                }
            )
            logger.info(
                "[LLM 라우터] 라우팅 완료",
                extra={
                    "route": routing.primary_route,
                    "data_source": routing_metadata['data_source'],
                    "intent": profile.intent.value if profile.intent else 'unknown',
                    "confidence": routing.confidence
                }
            )
            if routing.primary_route == "blocked":
                processing_time = time.time() - start_time
                immediate_response = {
                    "answer": "죄송합니다. 해당 질문은 처리할 수 없습니다.",
                    "sources": [],
                    "tokens_used": 0,
                    "topic": self.extract_topic_func(message),
                    "processing_time": processing_time,
                    "search_count": 0,
                    "ranked_count": 0,
                    "model_info": {"provider": "query_router", "model": "N/A"},
                    "routing_metadata": routing_metadata,
                }
                logger.warning(
                    "[차단] 쿼리가 차단됨",
                    extra={"reason": routing.notes}
                )
                return RouteDecision(
                    should_continue=False,
                    immediate_response=cast(RAGResultDict, immediate_response),
                    metadata=routing_metadata,
                )
        except Exception as llm_error:
            logger.warning(
                "[LLM 라우터] 오류",
                extra={"error": str(llm_error)},
                exc_info=True
            )
            routing_metadata["fallback_reason"] = str(llm_error)
        logger.info("[라우팅 완료] RAG 파이프라인 계속 진행")
        return RouteDecision(
            should_continue=True, immediate_response=None, metadata=routing_metadata
        )

    # NOTE: _get_score_multipliers() 함수 제거됨 (2026-01-02)
    # 스코어 가중치는 ScoringService(rag.yaml의 scoring 섹션)에서 관리됩니다.
    # 마이그레이션 가이드: DOMAIN_CUSTOMIZATION_GUIDE.md 참조

    @observe(name="Query Expansion & Context Preparation", capture_input=False, capture_output=False)
    async def prepare_context(self, message: str, session_id: str) -> PreparedContext:
        """
        2단계: 세션 컨텍스트 조회 + 쿼리 확장

        - 세션 모듈에서 최근 5개 대화 조회
        - 쿼리 확장 모듈로 쿼리 확장 (선택적)

        Args:
            message: 원본 쿼리
            session_id: 세션 ID

        Returns:
            PreparedContext: 세션 컨텍스트 + 확장된 쿼리
        """
        logger.debug("[3단계] 컨텍스트 준비 시작")
        session_context = None
        if self.session_module:
            try:
                context_string = await self.session_module.get_context_string(session_id)
                if context_string:
                    session_context = context_string
                    logger.debug(
                        "세션 컨텍스트 로드 성공",
                        extra={"context_length": len(context_string)}
                    )
                else:
                    logger.debug("세션 컨텍스트 비어있음")
            except Exception as e:
                logger.warning(
                    "세션 컨텍스트 조회 실패",
                    extra={"error": str(e)},
                    exc_info=True
                )

        # 멀티턴 standalone query rewrite (검색 측 맥락 보강, 기본 OFF)
        # 직전 대화가 있고 후속 질문이 자립적이지 않으면(대명사/생략/축약),
        # 직전 맥락을 반영한 standalone 질문으로 재작성해 검색에 투입한다.
        # 원본 질문(message)은 PreparedContext.original_query로 보존된다.
        search_message = await self._rewrite_standalone_query(message, session_context)

        # Multi-Query RRF: 모든 확장 쿼리와 가중치 추출
        expanded_query = search_message
        expanded_queries: list[str] = []
        query_weights: list[float] = []

        if self.query_expansion:
            try:
                logger.debug("쿼리 확장 시도")
                expansion_result = await self.query_expansion.expand_query(
                    query=search_message, context=session_context
                )

                if expansion_result and hasattr(expansion_result, "expansions"):
                    if expansion_result.expansions:
                        # metadata에서 raw_expanded_queries 추출 (weight 정보 포함)
                        raw_queries = expansion_result.metadata.get("raw_expanded_queries", [])

                        if raw_queries:
                            # 원본 데이터에서 쿼리와 가중치 추출
                            for item in raw_queries:
                                if isinstance(item, dict):
                                    query = item.get("query", "")
                                    weight = item.get("weight", 1.0)
                                    if query:
                                        expanded_queries.append(query)
                                        query_weights.append(weight)

                        # raw_queries가 없으면 expansions에서 추출 (가중치는 동일하게)
                        if not expanded_queries:
                            expanded_queries = expansion_result.expansions
                            query_weights = [1.0] * len(expanded_queries)

                        expanded_query = expanded_queries[0]  # 첫 번째 쿼리 (하위 호환성)
                        logger.info(
                            "쿼리 확장 성공",
                            extra={
                                "query_count": len(expanded_queries),
                                "weights": [f'{w:.1f}' for w in query_weights],
                                "original": message[:30],
                                "expanded": expanded_query[:30]
                            }
                        )
                    else:
                        logger.debug("쿼리 확장 결과 없음, 원본 사용")
                        expanded_queries = [search_message]
                        query_weights = [1.0]
                else:
                    logger.debug("쿼리 확장 결과 없음, 원본 사용")
                    expanded_queries = [search_message]
                    query_weights = [1.0]
            except Exception as e:
                logger.warning(
                    "쿼리 확장 실패, 원본 사용",
                    extra={"error": str(e)},
                    exc_info=True
                )
                expanded_queries = [search_message]
                query_weights = [1.0]
        else:
            # query_expansion 모듈 없음
            expanded_queries = [search_message]
            query_weights = [1.0]

        # 정확 식별자 보강(GAP A, 기본 OFF): 재작성된 검색 질문을 시드로 식별자/라틴
        # 구문 프로브 쿼리를 추가 주입한다. exact_identifier.enabled=false면 no-op.
        expanded_queries, query_weights = self._augment_search_queries_with_exact_terms(
            search_message,
            expanded_queries,
            query_weights,
        )
        expanded_query = expanded_queries[0] if expanded_queries else expanded_query

        # 멀티턴 anchor 추출(GAP B, 기본 OFF): 원본 질문(message)으로 오염 게이트를
        # 판정한다. multiturn_anchor.enabled=false면 빈 리스트(no-op).
        anchor_sources = await self._extract_anchor_sources(message, session_id)

        logger.debug(
            "[3단계] 컨텍스트 준비 완료",
            extra={"expanded_query": expanded_query[:50]}
        )
        return PreparedContext(
            session_context=session_context,
            expanded_query=expanded_query,
            original_query=message,
            expanded_queries=expanded_queries,
            query_weights=query_weights,
            anchor_sources=anchor_sources,
        )

    @observe(name="Document Retrieval (Hybrid Search)", capture_input=False, capture_output=False)
    async def retrieve_documents(
        self,
        search_queries: list[str] | str,
        query_weights: list[float] | None,
        context: str | None,
        options: dict[str, Any],
    ) -> RetrievalResults:
        """
        3단계: MongoDB Atlas 하이브리드 검색 (Multi-Query RRF 지원)

        - Multi-Query RRF: 다중 쿼리로 병렬 검색 후 RRF 알고리즘으로 병합
        - Single Query: 기존 방식 (하위 호환성)
        - Circuit Breaker 보호
        - 성능 메트릭 기록

        Args:
            search_queries: 검색 쿼리 (단일 문자열 또는 리스트)
            query_weights: 쿼리 가중치 리스트 (Multi-Query RRF용, 선택적)
            context: 세션 컨텍스트 (선택적)
            options: 검색 옵션 (limit, min_score 등)

        Note:
            스코어 가중치는 ScoringService(rag.yaml의 scoring 섹션)에서 자동 적용됩니다.

        Returns:
            RetrievalResults: 검색된 문서 리스트 (RRF 병합 완료)

        Raises:
            RetrievalError: 검색 실패 시
        """
        # 하위 호환성: 단일 쿼리를 리스트로 변환
        if isinstance(search_queries, str):
            search_queries = [search_queries]
            query_weights = [1.0]

        # query_weights 기본값
        if not query_weights:
            query_weights = [1.0] * len(search_queries)

        logger.debug(
            "[4단계] 문서 검색 시작",
            extra={
                "query_count": len(search_queries),
                "multi_query_rrf": "활성화" if len(search_queries) > 1 else "비활성화"
            }
        )

        # Future 객체 해결 (DI Container에서 Future를 전달할 수 있음)
        retrieval_module = self.retrieval_module
        if asyncio.iscoroutine(retrieval_module) or isinstance(retrieval_module, asyncio.Future):
            retrieval_module = await retrieval_module

        if not retrieval_module:
            logger.error("검색 모듈 없음")
            raise RetrievalError(ErrorCode.RETRIEVAL_SEARCH_FAILED)

        cb = self.circuit_breaker_factory.get("document_retrieval")

        # 정확 식별자 보강(GAP A): candidate pool을 확장해 식별자 문서가 상위에서
        # 밀려도 rescue/안정화가 끌어올릴 여지를 만든다. exact_identifier OFF면
        # candidate_limit == requested_limit이라 기존 동작과 동일(no-op).
        requested_limit = _coerce_positive_int(
            options.get("limit", self.retrieval_limit), self.retrieval_limit
        )
        candidate_limit = self._retrieval_candidate_limit(requested_limit)

        async def _search() -> list[SearchResult]:
            """실제 검색 로직 (Circuit Breaker 내부) - Multi-Query RRF"""
            # ✅ #12 수정: 요청 옵션의 메타데이터 필터를 실제 검색에 연결한다.
            # 필터가 없으면 None을 반환해 기존 무필터 동작과 100% 동일하다(회귀 방지).
            retrieval_filters = self._build_retrieval_filters(options)
            search_options = {
                "limit": candidate_limit,
                "min_score": options.get("min_score", self.min_score),
                "context": context,
                "filters": retrieval_filters,
            }

            # Multi-Query 검색: IMultiQueryRetriever Protocol 체크
            # RetrievalOrchestrator 직접 사용 (프로덕션)
            if isinstance(retrieval_module, IMultiQueryRetriever):
                return await retrieval_module._search_and_merge(
                    queries=search_queries,
                    top_k=search_options["limit"],
                    filters=retrieval_filters,
                    weights=query_weights,
                    use_rrf=True,  # RRF 활성화
                )
            # 하위 호환성: orchestrator를 속성으로 갖는 경우
            elif hasattr(retrieval_module, "orchestrator"):
                orchestrator = retrieval_module.orchestrator
                if isinstance(orchestrator, IMultiQueryRetriever):
                    # orchestrator._search_and_merge 직접 호출 (RRF 병합)
                    return await orchestrator._search_and_merge(
                        queries=search_queries,
                        top_k=search_options["limit"],
                        filters=retrieval_filters,
                        weights=query_weights,
                        use_rrf=True,  # RRF 활성화
                    )

            # Fallback: 단일 쿼리 검색 (기존 방식)
            # orchestrator.search(query, options) 시그니처를 그대로 사용한다.
            # search_options의 filters는 어댑터가 추출해 search_and_rerank에 전달한다(#39).
            return cast(
                list[SearchResult], await retrieval_module.search(search_queries[0], search_options)
            )

        try:
            start_time = time.time()
            search_results = await cb.call(_search, fallback=lambda: [])
            # 정확 식별자 rescue(GAP A): 식별자 직접 재검색으로 매칭 후보를 병합한다.
            # exact_identifier OFF거나 식별자가 없으면 no-op이다.
            search_results = await self._rescue_exact_identifier_candidates(
                retrieval_module,
                " ".join(search_queries),
                search_results,
                self._build_retrieval_filters(options),
                candidate_limit,
            )
            # 리랭킹이 켜져 있으면 확장된 candidate를 그대로 넘겨 리랭커가 더 넓은
            # 풀에서 정렬하게 하고, 그렇지 않으면 요청 한도로 잘라 기존 동작을 유지한다.
            if (
                self.exact_identifier_enabled
                and len(search_results) > requested_limit
                and not self._should_preserve_candidates_for_rerank()
            ):
                search_results = search_results[:requested_limit]
            latency_ms = (time.time() - start_time) * 1000
            self.performance_metrics.record_latency("retrieve_documents", latency_ms)
            logger.info(
                "[4단계] 검색 완료",
                extra={
                    "document_count": len(search_results),
                    "latency_ms": latency_ms,
                    "multi_query_rrf": "활성화" if len(search_queries) > 1 else "비활성화"
                }
            )
            return RetrievalResults(documents=search_results, count=len(search_results))
        except CircuitBreakerOpenError:
            logger.warning("Circuit Breaker OPEN - 검색 서비스 일시 차단")
            return RetrievalResults(documents=[], count=0)
        except Exception as e:
            logger.error(
                "[4단계] 문서 검색 실패",
                extra={"error": str(e)},
                exc_info=True
            )
            raise RetrievalError(
                ErrorCode.RETRIEVAL_SEARCH_FAILED,
                queries=[q[:50] for q in search_queries],
                error=str(e),
            ) from e

    def _should_preserve_candidates_for_rerank(self) -> bool:
        """리랭킹이 활성화되어 확장 candidate를 보존해야 하는지 판단(GAP A).

        리랭킹이 켜져 있으면 확장된 candidate pool을 리랭커에 넘겨 더 넓은 풀에서
        정렬하게 한다. 리랭킹이 꺼져 있으면 요청 한도로 잘라 기존 응답 크기를 유지한다.
        """
        reranking_config = self.config.get("reranking", {})
        retrieval_config = self.config.get("retrieval", {})
        return bool(
            (isinstance(reranking_config, dict) and reranking_config.get("enabled", False))
            or (isinstance(retrieval_config, dict) and retrieval_config.get("enable_reranking", False))
        )

    def _rerank_fusion_enabled(
        self,
        reranking_config: dict[str, Any],
        options: dict[str, Any],
    ) -> bool:
        """리랭크 fusion 활성화 여부 판단(#33).

        provider 무관 opt-in(기본 비활성화)으로 일반화한다. 원본 구현의 vertex
        게이팅(provider=="vertex" or has_vertex_signal)을 제거해 어떤 리랭커
        provider에서도 config/options로 켤 수 있게 한다.

        Args:
            reranking_config: reranking 설정 dict
            options: 요청 옵션(런타임 오버라이드)

        Returns:
            fusion 적용 여부
        """
        fusion_config = reranking_config.get("fusion", {})
        fusion_config = fusion_config if isinstance(fusion_config, dict) else {}
        return _coerce_bool(
            options.get("rerank_fusion_enabled", fusion_config.get("enabled")),
            default=False,
        )

    def _original_signal_score(self, document: Any) -> float | None:
        """문서의 원본 lexical/hybrid 신호 점수를 추출한다(#33).

        original_score → rrf_score → bm25_score → hybrid_score 순으로 탐색한다.
        모두 OneRAG 메타데이터에 존재하는 범용 신호 키다.
        """
        metadata = _document_metadata(document)
        for key in ("original_score", "rrf_score", "bm25_score", "hybrid_score"):
            value = metadata.get(key)
            if value is None:
                continue
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
        return None

    def _fuse_reranked_results_with_original_signals(
        self,
        ranked_results: list[Any],
        reranking_config: dict[str, Any],
        options: dict[str, Any],
    ) -> list[Any]:
        """리랭커 top-k를 보존하면서 원본 신호 상위 후보를 재삽입한다(#33).

        리랭커(특히 semantic)가 BM25/exact-match 신호를 덮어 식별자·모델코드·연도
        문서를 하위로 미는 도메인 무관 문제를 막는다. 리랭커 top1을 그대로 유지해
        recall@1을 보존하면서, original_score 높은 하위 후보를 상위로 승격해
        recall@5/MRR을 개선한다. 기본 비활성화(opt-in)이며 도메인/언어 하드코딩이 없다.

        Args:
            ranked_results: 리랭킹된 문서 리스트
            reranking_config: reranking 설정 dict
            options: 요청 옵션(런타임 오버라이드)

        Returns:
            fusion이 적용된 문서 리스트(미적용 시 원본 그대로)
        """
        if len(ranked_results) < 3:
            return ranked_results
        if not self._rerank_fusion_enabled(reranking_config, options):
            return ranked_results

        fusion_config = reranking_config.get("fusion", {})
        fusion_config = fusion_config if isinstance(fusion_config, dict) else {}
        strategy = str(
            options.get(
                "rerank_fusion_strategy",
                fusion_config.get("strategy", "rerank_top1_original_top3"),
            )
        ).strip()
        if strategy != "rerank_top1_original_top3":
            return ranked_results

        preserve_top_k = _coerce_bounded_int(
            options.get(
                "rerank_fusion_preserve_rerank_top_k",
                fusion_config.get("preserve_rerank_top_k", 1),
            ),
            1,
            1,
            min(5, len(ranked_results)),
        )
        original_top_k = _coerce_bounded_int(
            options.get(
                "rerank_fusion_original_top_k",
                fusion_config.get("original_top_k", 3),
            ),
            3,
            1,
            min(8, len(ranked_results) - preserve_top_k),
        )

        identities = [_document_identity(document) for document in ranked_results]
        preserved_ids = set(identities[:preserve_top_k])
        candidates: list[tuple[float, int, Any]] = []
        for index, document in enumerate(ranked_results[preserve_top_k:], preserve_top_k):
            signal_score = self._original_signal_score(document)
            if signal_score is None:
                continue
            candidates.append((signal_score, index, document))

        if not candidates:
            return ranked_results

        # 원본 신호 점수 내림차순, 동점 시 기존 순위 유지
        candidates.sort(key=lambda item: (-item[0], item[1]))
        promoted: list[Any] = []
        promoted_ids: set[Any] = set()
        for _, _, document in candidates:
            identity = _document_identity(document)
            if identity in preserved_ids or identity in promoted_ids:
                continue
            promoted.append(document)
            promoted_ids.add(identity)
            if len(promoted) >= original_top_k:
                break

        if not promoted:
            return ranked_results

        # 보존(top-k) → 승격(original 상위) → 나머지 순으로 재배치, identity 중복 제거
        fused: list[Any] = []
        seen: set[Any] = set()
        for document in [
            *ranked_results[:preserve_top_k],
            *promoted,
            *ranked_results[preserve_top_k:],
        ]:
            identity = _document_identity(document)
            if identity in seen:
                continue
            seen.add(identity)
            fused.append(document)

        # 순서 변화가 없으면 원본을 그대로 반환(불필요 로그/객체 생성 방지)
        if [_document_identity(document) for document in fused] == identities:
            return ranked_results

        logger.info(
            "리랭크 fusion 적용",
            extra={
                "strategy": strategy,
                "preserve_rerank_top_k": preserve_top_k,
                "original_top_k": original_top_k,
                "before_count": len(ranked_results),
                "after_count": len(fused),
            },
        )
        return fused

    async def rerank_documents(
        self, search_query: str, search_results: list[Any], options: dict[str, Any]
    ) -> RerankResults:
        """
        4단계: 검색 결과 리랭킹 (선택적)

        - 리랭킹 설정 확인 (config.reranking.enabled)
        - Jina/Cohere/LLM 리랭커 호출
        - 실패 시 원본 반환

        Args:
            search_query: 검색 쿼리
            search_results: 검색 결과 (Document 리스트)
            options: 리랭킹 옵션 (top_n 등)

        Returns:
            RerankResults: 리랭킹된 문서 리스트 (reranked=True/False)
        """
        logger.debug("[5단계] 리랭킹 시작")
        if not search_results:
            logger.debug("검색 결과 없음, 리랭킹 스킵")
            return RerankResults(documents=[], count=0, reranked=False)
        reranking_config = self.config.get("reranking", {})
        retrieval_config = self.config.get("retrieval", {})
        reranking_enabled = reranking_config.get("enabled", False) or retrieval_config.get(
            "enable_reranking", False
        )
        if not reranking_enabled:
            logger.debug("리랭킹 비활성화 - 원본 사용")
            return RerankResults(
                documents=search_results, count=len(search_results), reranked=False
            )
        # Future 객체 해결
        retrieval_module = self.retrieval_module
        if asyncio.iscoroutine(retrieval_module) or isinstance(retrieval_module, asyncio.Future):
            retrieval_module = await retrieval_module

        if not retrieval_module or not hasattr(retrieval_module, "rerank"):
            logger.warning("리랭킹 모듈 없음 - 원본 사용")
            return RerankResults(
                documents=search_results, count=len(search_results), reranked=False
            )
        try:
            original_snapshot = _snapshot_rerank_inputs(search_results)
            logger.debug(
                "리랭킹 실행",
                extra={"document_count": len(search_results)}
            )
            ranked_results = await retrieval_module.rerank(
                query=search_query,
                results=search_results,
                top_n=options.get("top_n", self.rerank_top_n),
            )
            if _is_noop_rerank(original_snapshot, ranked_results):
                _annotate_rerank_scores(original_snapshot, ranked_results, reranked=False)
                logger.warning(
                    "[5단계] 리랭커가 원본 결과를 그대로 반환 - 리랭킹 미수행 처리",
                    extra={"document_count": len(ranked_results)}
                )
                return RerankResults(
                    documents=ranked_results,
                    count=len(ranked_results),
                    reranked=False,
                )

            _annotate_rerank_scores(original_snapshot, ranked_results, reranked=True)

            # 리랭킹 후 min_score 필터링
            min_score = reranking_config.get("min_score", 0.05)
            if min_score > 0:
                before_count = len(ranked_results)
                ranked_results = [
                    doc
                    for doc in ranked_results
                    if (hasattr(doc, "score") and doc.score >= min_score)
                    or (hasattr(doc, "metadata") and doc.metadata.get("score", 0) >= min_score)
                ]
                if before_count > len(ranked_results):
                    logger.info(
                        "min_score 필터링",
                        extra={
                            "before_count": before_count,
                            "after_count": len(ranked_results),
                            "threshold": min_score
                        }
                    )
            logger.info(
                "[5단계] 리랭킹 완료",
                extra={"document_count": len(ranked_results)}
            )
            return RerankResults(documents=ranked_results, count=len(ranked_results), reranked=True)
        except Exception as e:
            logger.warning(
                "[5단계] 리랭킹 실패, 원본 사용",
                extra={"error": str(e)},
                exc_info=True
            )
            return RerankResults(
                documents=search_results, count=len(search_results), reranked=False
            )

    @observe(name="Answer Generation (LLM)", capture_input=False, capture_output=False)
    async def generate_answer(
        self, message: str, ranked_results: list[Any], context: str | None, options: dict[str, Any]
    ) -> GenerationResult:
        """
        5단계: LLM 답변 생성

        - LLM 답변 생성 (Gemini/OpenAI/Claude)
        - Circuit Breaker 보호
        - Fallback 답변 처리 (LLM 실패 시)
        - 비용 추적 (CostTracker)

        Args:
            message: 사용자 질문
            ranked_results: 리랭킹된 문서
            context: 세션 컨텍스트
            options: 생성 옵션

        Returns:
            GenerationResult: 답변 + 토큰 수 + 모델 정보

        Raises:
            GenerationError: 답변 생성 실패 시
        """
        from ...modules.core.generation.generator import GenerationResult

        logger.debug("[6단계] 답변 생성 시작")
        if not self.generation_module:
            logger.error("생성 모듈 없음")
            return GenerationResult(
                answer=self.generation_module_missing_message,
                text=self.generation_module_missing_message,
                tokens_used=0,
                model_used="none",
                provider="none",
                generation_time=0.0,
            )
        cb = self.circuit_breaker_factory.get("answer_generation")
        safe_docs = []
        dropped_count = 0
        for doc in ranked_results or []:
            if validate_document(doc):
                safe_docs.append(doc)
            else:
                dropped_count += 1
                logger.warning(
                    "문서 인젝션 패턴 감지 - 차단",
                    extra={"total_dropped": dropped_count}
                )
        if dropped_count > 0:
            logger.info(
                "안전 문서 필터링 완료",
                extra={"safe_count": len(safe_docs), "dropped_count": dropped_count}
            )
        context_documents = safe_docs

        async def _generate() -> GenerationResult:
            """실제 답변 생성 로직 (Circuit Breaker 내부)"""
            # session_context를 options에 포함시켜 전달
            generation_options = {**options, "session_context": context}
            return cast(
                GenerationResult,
                await self.generation_module.generate_answer(
                    query=message, context_documents=context_documents, options=generation_options
                ),
            )

        def _fallback() -> dict[str, Any]:
            """LLM 실패 시 Fallback 답변 (메시지는 rag.yaml generation_fallback 외부화)"""
            if context_documents:
                top_doc = context_documents[0]
                # 문서 미리보기 추출 실패 시 대체 문구도 config 값을 따른다.
                content = _extract_fallback_document_preview(
                    top_doc,
                    unavailable_message=self.document_preview_unavailable_message,
                )
                # {content} 자리에 미리보기를 치환한다. 미리보기 텍스트에 중괄호가
                # 섞여도 안전하도록 .format이 아닌 .replace를 사용한다.
                answer = self.generation_fallback_with_docs_message.replace(
                    "{content}", content
                )
                return {
                    "answer": answer,
                    "tokens_used": 0,
                    "model_info": {"provider": "fallback", "model": "document_summary"},
                }
            else:
                return {
                    "answer": self.generation_fallback_no_docs_message,
                    "tokens_used": 0,
                    "model_info": {"provider": "fallback", "model": "none"},
                }

        try:
            start_time = time.time()
            generation_result: GenerationResult | dict[str, Any] = await cb.call(
                _generate, fallback=_fallback
            )
            latency_ms = (time.time() - start_time) * 1000
            self.performance_metrics.record_latency("generate_integrated_answer", latency_ms)

            # 타입 가드: GenerationResult 또는 dict 처리
            # GenerationResult 객체인지 확인 (hasattr로도 체크하여 더 안전하게)
            if isinstance(generation_result, GenerationResult):
                tokens = generation_result.tokens_used
                provider = generation_result.provider
                answer = generation_result.answer
                model_info = generation_result.model_info
            elif isinstance(generation_result, dict):
                # fallback이 dict를 반환한 경우 (Circuit Breaker 내부 fallback)
                tokens = generation_result.get("tokens_used", 0)
                provider = generation_result.get("model_info", {}).get("provider", "google")
                answer = generation_result.get("answer", "답변을 생성할 수 없습니다.")
                model_info = generation_result.get("model_info", {})
            else:
                # 예상치 못한 타입 (안전 장치)
                logger.error(f"⚠️ 예상치 못한 generation_result 타입: {type(generation_result)}")
                tokens = 0
                provider = "unknown"
                answer = self.generation_type_error_message
                model_info = {"provider": "error", "model": "unknown"}

            if tokens > 0 and provider in ["google", "openai", "anthropic"]:
                self.cost_tracker.track_usage(provider, tokens, is_input=False)

            if contains_output_leakage(answer):
                logger.error(
                    "프롬프트 누출 감지 - 답변 차단",
                    extra={"preview": answer[:100]}
                )
                answer = self.prompt_leakage_blocked_message
                self.performance_metrics.record_error("prompt_leakage_blocked")

            logger.info(
                "[6단계] 답변 생성 완료",
                extra={
                    "answer_length": len(answer),
                    "latency_ms": latency_ms,
                    "tokens": tokens
                }
            )
            return GenerationResult(
                answer=answer,
                text=answer,
                tokens_used=tokens,
                model_used=model_info.get("model", "unknown"),
                provider=model_info.get("provider", "unknown"),
                generation_time=latency_ms / 1000,
            )
        except CircuitBreakerOpenError:
            # Circuit Breaker 에러 → 일시적 장애, Fallback 사용
            logger.warning("🚫 Circuit Breaker OPEN - LLM 서비스 일시 차단, Fallback 사용")
            fallback_result = _fallback()
            return GenerationResult(
                answer=fallback_result["answer"],
                text=fallback_result["answer"],
                tokens_used=fallback_result["tokens_used"],
                model_used=fallback_result["model_info"].get("model", "fallback"),
                provider=fallback_result["model_info"].get("provider", "fallback"),
                generation_time=0.0,
            )
        except TimeoutError as e:
            # 타임아웃 에러 → 클라이언트에게 재시도 유도
            logger.error(
                "[6단계] 답변 생성 타임아웃",
                extra={"error": str(e)},
                exc_info=True
            )
            raise GenerationError(
                ErrorCode.GENERATION_TIMEOUT,
                session_id=options.get("session_id", "unknown"),
                timeout_seconds=30,
            ) from e
        except ValueError as e:
            # 입력 검증 에러 → 클라이언트 에러
            logger.error(
                "[6단계] 잘못된 입력",
                extra={"error": str(e)},
                exc_info=True
            )
            raise GenerationError(
                ErrorCode.GENERATION_INVALID_RESPONSE,
                session_id=options.get("session_id", "unknown"),
                error=str(e),
            ) from e
        except Exception as e:
            # 예상치 못한 에러 → 서버 에러
            logger.error(
                "[6단계] 답변 생성 실패",
                extra={"error": str(e)},
                exc_info=True
            )
            raise GenerationError(
                ErrorCode.GENERATION_REQUEST_FAILED,
                session_id=options.get("session_id", "unknown"),
                error=str(e),
            ) from e

    @observe(name="Self-RAG Quality Verification", capture_input=False, capture_output=False)
    async def self_rag_verify(
        self,
        message: str,
        session_id: str,
        generation_result: GenerationResult,
        documents: list[Any],
        options: dict[str, Any],
    ) -> GenerationResult:
        """
        6단계: Self-RAG 품질 검증 (선택적)

        RAGPipeline이 이미 생성한 답변의 품질을 평가하고, 필요시에만 재생성합니다.
        기존 검색/생성 결과를 재활용하여 중복을 최소화합니다.

        워크플로우:
        1. 복잡도 계산 (낮으면 품질 검증 스킵)
        2. 기존 답변 품질 평가 (재검색/재생성 없이 평가만!)
        3. 품질 >= 0.8 → 기존 답변 그대로 사용 ✅
        4. 품질 < 0.8 → 재검색(15개) + 재생성 + Rollback 판단

        Args:
            message: 사용자 질문
            session_id: 세션 ID
            generation_result: RAGPipeline이 생성한 초기 답변
            documents: RAGPipeline이 검색한 문서 리스트
            options: 추가 옵션

        Returns:
            GenerationResult: 최종 답변 (기존 답변 또는 재생성 답변)
        """
        from ...modules.core.generation.generator import GenerationResult

        logger.debug("[6단계] Self-RAG 품질 검증 시작")

        # ⭐ 디버깅 추적 데이터 추출
        debug_trace_data = options.get("_debug_trace_data")

        # Self-RAG 비활성화 확인
        self_rag_config = self.config.get("self_rag", {})
        if not self_rag_config.get("enabled", False):
            logger.debug("Self-RAG 비활성화 - 기존 답변 사용")
            return generation_result

        # Future 객체 해결
        self_rag_module = self.self_rag_module
        if self_rag_module:
            if asyncio.iscoroutine(self_rag_module) or isinstance(self_rag_module, asyncio.Future):
                self_rag_module = await self_rag_module

        # Self-RAG 모듈 없음
        if not self_rag_module:
            logger.debug("Self-RAG 모듈 없음 - 기존 답변 사용")
            return generation_result

        try:
            logger.info("Self-RAG 품질 검증 시작 (기존 답변 재활용 모드)")

            # ✅ 최적화: verify_existing_answer 메서드 사용 (중복 제거)
            # RAGPipeline이 이미 생성한 답변과 문서를 전달
            # 재생성 시 사용자 옵션(응답 언어/모델/스타일 등)이 소실되지 않도록
            # options를 그대로 전달한다. 단, 파이프라인 내부 전용 키
            # (_debug_trace_data)는 생성 옵션이 아니므로 제외한다.
            verify_options = {
                key: value
                for key, value in options.items()
                if key != "_debug_trace_data"
            }
            self_rag_result = await self_rag_module.verify_existing_answer(
                query=message,
                existing_answer=generation_result.answer,  # ✅ 기존 답변 전달
                existing_docs=documents,  # ✅ 기존 문서 전달
                session_id=session_id,
                options=verify_options,
            )

            # Self-RAG가 적용되었는지 확인
            if self_rag_result.used_self_rag:
                logger.info(
                    "Self-RAG 검증 완료",
                    extra={
                        "complexity": self_rag_result.complexity.score,
                        "regenerated": self_rag_result.regenerated
                    }
                )

                # ⭐ Self-RAG 평가 추적
                if debug_trace_data is not None:
                    debug_trace_data["self_rag_evaluation"] = {
                        "initial_quality": self_rag_result.initial_quality.overall if self_rag_result.initial_quality else 0.0,
                        "regenerated": self_rag_result.regenerated,
                        "final_quality": self_rag_result.final_quality.overall if self_rag_result.final_quality else 0.0,
                        "reason": self_rag_result.initial_quality.reasoning if self_rag_result.initial_quality else None,
                    }

                # ⭐ 품질 게이트 적용
                min_quality = self_rag_config.get("min_quality_to_answer", 0.6)
                final_quality_score = (
                    self_rag_result.final_quality.overall
                    if self_rag_result.final_quality
                    else 0.0
                )

                if final_quality_score < min_quality:
                    logger.warning(
                        "저품질 답변 감지 - 답변 거부",
                        extra={
                            "score": final_quality_score,
                            "threshold": min_quality
                        }
                    )

                    # 거부 메시지 반환
                    return GenerationResult(
                        answer=self.self_rag_low_quality_reject_message,
                        text=self.self_rag_low_quality_reject_text,
                        tokens_used=generation_result.tokens_used,
                        model_used=generation_result.model_used,
                        provider=generation_result.provider,
                        generation_time=generation_result.generation_time,
                        refusal_reason="quality_too_low",  # ⭐ 신규 필드
                        quality_score=final_quality_score,  # ⭐ 신규 필드
                    )

                # 품질 점수 로깅 및 Langfuse Score 기록
                if self_rag_result.initial_quality:
                    initial_q = self_rag_result.initial_quality.overall
                    logger.info("초기 품질", extra={"score": initial_q})

                    # Langfuse Score 기록: 초기 품질
                    try:
                        langfuse_context.score_current_trace(
                            name="self_rag_initial_quality",
                            value=initial_q,
                            comment=f"Self-RAG 초기 답변 품질 (complexity: {self_rag_result.complexity.score:.2f})",
                        )
                    except Exception as e:
                        logger.debug(f"Langfuse Score 기록 실패 (무시): {e}")

                    if self_rag_result.regenerated and self_rag_result.final_quality:
                        final_q = self_rag_result.final_quality.overall
                        improvement = final_q - initial_q
                        logger.info(
                            "품질 비교",
                            extra={
                                "initial": initial_q,
                                "final": final_q,
                                "improvement": improvement
                            }
                        )

                        # Langfuse Score 기록: 최종 품질 및 개선도
                        try:
                            langfuse_context.score_current_trace(
                                name="self_rag_final_quality",
                                value=final_q,
                                comment=f"Self-RAG 재생성 후 품질 (improvement: {improvement:+.2f})",
                            )
                            langfuse_context.score_current_trace(
                                name="self_rag_improvement",
                                value=improvement,
                                comment="Self-RAG 품질 개선도 (final - initial)",
                            )
                        except Exception as e:
                            logger.debug(f"Langfuse Score 기록 실패 (무시): {e}")

                # Self-RAG 답변 출력 누출 검사
                answer = self_rag_result.answer
                if contains_output_leakage(answer):
                    logger.error(
                        "프롬프트 누출 감지 (Self-RAG) - 답변 차단",
                        extra={"preview": answer[:100]}
                    )
                    answer = self.prompt_leakage_blocked_message
                    self.performance_metrics.record_error("prompt_leakage_blocked")

                # Self-RAG 답변으로 교체 (재생성됐든 안 됐든)
                return GenerationResult(
                    answer=answer,
                    text=answer,
                    tokens_used=(
                        self_rag_result.tokens_used
                        if self_rag_result.regenerated
                        else generation_result.tokens_used
                    ),
                    model_used=generation_result.model_used,
                    provider=generation_result.provider,
                    generation_time=generation_result.generation_time,
                    model_config=generation_result.model_config,
                    quality_score=final_quality_score,  # ⭐ 신규 필드
                    _model_info_override={
                        **generation_result.model_info,
                        "self_rag_applied": True,
                        "self_rag_regenerated": self_rag_result.regenerated,
                        "complexity_score": self_rag_result.complexity.score,
                        "initial_quality": (
                            self_rag_result.initial_quality.overall
                            if self_rag_result.initial_quality
                            else None
                        ),
                        "final_quality": (
                            self_rag_result.final_quality.overall
                            if self_rag_result.final_quality
                            else None
                        ),
                    },
                )
            else:
                logger.info(
                    "Self-RAG 미적용 (복잡도 낮음) - 기존 답변 사용",
                    extra={"complexity": self_rag_result.complexity.score}
                )
                # Self-RAG 미적용 시에도 메타데이터 추가 (API 응답 완전성 보장)
                return GenerationResult(
                    answer=generation_result.answer,
                    text=generation_result.text,
                    tokens_used=generation_result.tokens_used,
                    model_used=generation_result.model_used,
                    provider=generation_result.provider,
                    generation_time=generation_result.generation_time,
                    model_config=generation_result.model_config,
                    _model_info_override={
                        **generation_result.model_info,
                        "self_rag_applied": False,
                        "complexity_score": self_rag_result.complexity.score,
                    },
                )

        except Exception as e:
            logger.warning(
                "[6단계] Self-RAG 검증 실패, 기존 답변 사용",
                extra={"error": str(e)},
                exc_info=True
            )
            return generation_result

    def _format_rag_source(self, idx: int, doc: Any) -> dict[str, Any] | None:
        """RAG 검색 결과를 Source 객체로 변환"""
        try:
            metadata = getattr(doc, "metadata", {}) or {}
            source_metadata = dict(metadata)
            document_name = (
                metadata.get("source_file")
                or metadata.get("filename")
                or metadata.get("document_name")
                or metadata.get("source")
                or f"Document {idx + 1}"
            )

            if self.privacy_masker:
                document_name = self.privacy_masker.mask_filename(document_name)
                for key in ("source_file", "filename", "document_name", "file_name"):
                    if source_metadata.get(key):
                        source_metadata[key] = self.privacy_masker.mask_filename(
                            str(source_metadata[key])
                        )

            content_text = getattr(doc, "content", None) or getattr(doc, "page_content", "")
            if content_text and self.privacy_masker:
                content_text = self.privacy_masker.mask_text(content_text)
            content_preview = content_text[:200] if content_text else ""

            raw_score = getattr(doc, "score", 0.0)
            normalized_score = self.score_normalizer.normalize(raw_score)

            # file_path(서버 내부 절대경로)는 출처 응답에 노출하지 않는다.
            # source_contract.normalize_source_payload가 file_path 키를 metadata와
            # 최상위 필드 모두에서 제거하므로, 디렉토리 구조가 새어나가지 않도록
            # 여기서 source_metadata에 file_path를 주입하지 않는다(정보 노출 차단).
            source_metadata.pop("file_path", None)

            return normalize_source_payload(
                sequence_id=idx,
                source_type="rag",
                document_name=document_name,
                relevance=normalized_score,
                content_preview=content_preview,
                metadata=source_metadata,
            )
        except Exception as e:
            logger.warning(
                "소스 포맷팅 실패",
                extra={"source_idx": idx, "error": str(e)},
                exc_info=True
            )
            return None

    def _format_sql_row(
        self,
        row: dict[str, Any],
        row_idx: int,
        source_id: int,
        sql_query: str | None,
        category: str | None = None,
    ) -> dict[str, Any]:
        """SQL 검색 결과의 한 행을 Source 객체로 변환"""
        entity_name = (
            row.get("entity_name")
            or row.get("name")
            or self._sql_entity_name_fallback_template.format(index=row_idx + 1)
        )
        row_preview = ", ".join(f"{k}: {v}" for k, v in row.items() if v is not None)

        if row_preview and self.privacy_masker:
            row_preview = self.privacy_masker.mask_text(row_preview)

        document_name = f"[{category}] {entity_name}" if category else str(entity_name)
        metadata = {
            "category": category,
            "entity_name": entity_name,
            "document_id": (
                row["document_id"]
                if row.get("document_id") is not None and row.get("document_id") != ""
                else row["id"]
                if row.get("id") is not None and row.get("id") != ""
                else row.get("entity_id")
            ),
        }

        source_data = normalize_source_payload(
            sequence_id=source_id,
            source_type="sql",
            document_name=document_name,
            relevance=100.0,
            content_preview=row_preview[:200] if row_preview else self._sql_preview_fallback,
            metadata={key: value for key, value in metadata.items() if value is not None},
            additional_metadata={"row_keys": sorted(str(key) for key in row.keys())},
        )
        source_data.update(
            {
                "sql_query": sql_query,
                "sql_result_summary": row_preview,
            }
        )
        return source_data

    def _add_multi_query_sql_sources(
        self, sources: list[Any], sql_search_result: SQLSearchResult, max_sources: int
    ) -> int:
        """멀티 쿼리 SQL 결과를 sources에 추가"""
        added_count = 0
        for query_result in sql_search_result.query_results:
            if not query_result.success or not query_result.result:
                continue

            sql_result = query_result.result
            sql_query = query_result.query.sql_query
            category = query_result.query.target_category or self._sql_all_category_label

            for row_idx, row in enumerate(sql_result.data):
                if added_count >= max_sources:
                    break

                sql_source_data = self._format_sql_row(
                    row, row_idx, len(sources), sql_query, category
                )
                sources.append(self.Source(**sql_source_data))
                added_count += 1

        logger.info(
            "멀티 SQL 소스 추가",
            extra={
                "row_count": added_count,
                "query_count": len(sql_search_result.query_results)
            }
        )
        return added_count

    def _add_single_query_sql_sources(
        self, sources: list[Any], sql_search_result: SQLSearchResult, max_sources: int
    ) -> int:
        """단일 쿼리 SQL 결과를 sources에 추가"""
        sql_result = sql_search_result.query_result
        sql_gen = sql_search_result.generation_result
        sql_query = sql_gen.sql_query if sql_gen else None
        added_count = 0

        for row_idx, row in enumerate(sql_result.data[:max_sources]):
            sql_source_data = self._format_sql_row(row, row_idx, len(sources), sql_query)
            sources.append(self.Source(**sql_source_data))
            added_count += 1

        logger.info(
            "SQL 소스 추가",
            extra={
                "added_count": added_count,
                "total_rows": sql_result.row_count,
                "query": sql_query[:50] if sql_query else 'N/A'
            }
        )
        return added_count

    def format_sources(
        self,
        ranked_results: list[Any],
        sql_search_result: SQLSearchResult | None = None,
    ) -> FormattedSources:
        """
        6단계: 검색 결과 → Source 객체 변환

        - RAG 문서 → Source 객체 변환 (source_type="rag")
        - SQL 검색 결과 → Source 객체 변환 (source_type="sql")
        - 메타데이터 정규화 (file_type, relevance 등)

        Args:
            ranked_results: 리랭킹된 문서 (RRF 병합 결과)
            sql_search_result: SQL 검색 결과 (선택적)

        Returns:
            FormattedSources: Source 객체 리스트 (RAG + SQL 통합)
        """
        logger.debug("[6단계] 소스 포맷팅 시작")
        sources = []

        try:
            for idx, doc in enumerate(ranked_results):
                # 인접 청크 확장 이웃 청크와 명시 문서 digest(_generation_only)는 실제
                # 검색 히트가 아니므로 사용자 인용 소스에서 제외한다(오염 방지)(#4, GAP #1).
                metadata = _document_metadata(doc)
                if metadata.get("context_expanded") or metadata.get("_generation_only"):
                    continue
                source_data = self._format_rag_source(idx, doc)
                if source_data:
                    sources.append(self.Source(**source_data))

            if sql_search_result and sql_search_result.used:
                try:
                    max_sql_sources = 10
                    if sql_search_result.is_multi_query and sql_search_result.query_results:
                        self._add_multi_query_sql_sources(sources, sql_search_result, max_sql_sources)
                    elif sql_search_result.query_result:
                        self._add_single_query_sql_sources(sources, sql_search_result, max_sql_sources)
                except Exception as sql_err:
                    logger.warning(
                        "SQL 소스 포맷팅 실패 (무시)",
                        extra={"error": str(sql_err)},
                        exc_info=True
                    )

            logger.debug(
                "[6단계] 소스 포맷팅 완료",
                extra={"source_count": len(sources), "type": "RAG + SQL"}
            )
            return FormattedSources(sources=sources, count=len(sources))
        except Exception as e:
            logger.error(
                "[6단계] 소스 리스트 포맷팅 실패",
                extra={"error": str(e)},
                exc_info=True
            )
            return FormattedSources(sources=[], count=0)

    def build_result(
        self,
        answer: str,
        sources: list[Any],
        tokens_used: int,
        topic: str,
        processing_time: float,
        search_count: int,
        ranked_count: int,
        model_info: dict[str, Any],
        routing_metadata: dict[str, Any] | None,
        debug_trace: DebugTrace | None = None,  # ⭐ 신규 파라미터
        quality_score: float | None = None,  # Self-RAG 품질 점수
        refusal_reason: str | None = None,  # 저품질 거부 사유
    ) -> RAGResultDict:
        """
        7단계: 최종 응답 딕셔너리 구성

        - 표준 응답 형식 생성
        - 라우팅 메타데이터 포함 (선택적)
        - 디버깅 추적 정보 포함 (선택적)

        Args:
            answer: 생성된 답변
            sources: Source 객체 리스트
            tokens_used: 사용된 토큰 수
            topic: 추출된 토픽
            processing_time: 총 처리 시간 (초)
            search_count: 검색된 문서 수
            ranked_count: 리랭킹된 문서 수
            model_info: 모델 정보
            routing_metadata: 라우팅 메타데이터
            debug_trace: 디버깅 추적 정보 (enable_debug_trace=True 시)

        Returns:
            표준 응답 딕셔너리

        Note:
            이 메서드는 동기 함수 (async 불필요)
        """
        logger.debug("[8단계] 결과 구성 시작")

        # model_info 표준화 (API 응답 일관성 보장)
        if model_info:
            # 필수 필드 보장 + 하위 호환성
            standardized_model_info = {
                "provider": model_info.get("provider", "unknown"),
                "model": model_info.get("model", "unknown"),
                "model_used": model_info.get("model", model_info.get("model_used", "unknown")),
                "self_rag_applied": model_info.get("self_rag_applied", False),
            }

            # 선택적 필드 (존재하는 경우만 추가)
            optional_fields = [
                "complexity_score",
                "initial_quality",
                "final_quality",
                "self_rag_regenerated",
                "mode",
                "tool_usage",
                "citations_count",
            ]
            for field in optional_fields:
                if field in model_info and model_info[field] is not None:
                    standardized_model_info[field] = model_info[field]
        else:
            # model_info가 없는 경우 안전한 기본값 (방어적 프로그래밍)
            logger.warning("model_info가 None - 기본값 사용")
            standardized_model_info = {
                "provider": "unknown",
                "model": "unknown",
                "model_used": "unknown",
                "self_rag_applied": False,
            }

        # PII 마스킹: 최종 답변에서 개인정보 마스킹 (활성화 시에만)
        masked_answer = answer
        if self.privacy_masker:
            masked_answer = self.privacy_masker.mask_text(answer)

        result = {
            "answer": masked_answer,
            "sources": sources,
            "tokens_used": tokens_used,
            "topic": topic,
            "processing_time": processing_time,
            "search_results": search_count,
            "ranked_results": ranked_count,
            "model_info": standardized_model_info,
        }

        if routing_metadata:
            result["routing_metadata"] = routing_metadata

        # ⭐ Self-RAG 품질 점수/거부 사유 전파
        # (chat_router의 quality 메타데이터 블록이 이 값을 읽는다 — 누락 시 항상 None)
        if quality_score is not None:
            result["quality_score"] = quality_score
        if refusal_reason is not None:
            result["refusal_reason"] = refusal_reason

        # ⭐ 디버깅 추적 정보 추가
        if debug_trace is not None:
            result["debug_trace"] = debug_trace

        logger.debug(
            "[8단계] 결과 구성 완료",
            extra={
                "search_count": search_count,
                "ranked_count": ranked_count
            }
        )
        return cast(RAGResultDict, result)

    async def _execute_sql_search(self, query: str) -> SQLSearchResult | None:
        """
        SQL 검색 실행 (내부 헬퍼 메서드)

        RAG 검색과 병렬로 실행되며, 실패해도 파이프라인은 계속 진행됩니다.
        타임아웃과 에러 핸들링이 적용됩니다.

        Args:
            query: 사용자 질문

        Returns:
            SQLSearchResult | None: SQL 검색 결과 또는 None (실패/비활성화 시)
        """
        if not self.sql_search_service:
            return None

        from ...modules.core.sql_search import SQLSearchResult

        try:
            # SQL 검색 설정에서 타임아웃 조회
            sql_config = self.config.get("sql_search", {}).get("pipeline", {})
            timeout = sql_config.get("timeout", 8)  # 기본 8초

            # 타임아웃 적용
            result = await asyncio.wait_for(self.sql_search_service.search(query), timeout=timeout)

            return result

        except TimeoutError:
            logger.warning(
                "SQL 검색 타임아웃",
                extra={"timeout_seconds": timeout}
            )
            return SQLSearchResult(
                success=False,
                generation_result=None,
                query_result=None,
                formatted_context="",
                total_time=timeout,
                used=False,
                error="SQL 검색 타임아웃",
            )
        except Exception as e:
            logger.warning(
                "SQL 검색 실패",
                extra={"error": str(e)},
                exc_info=True
            )
            return SQLSearchResult(
                success=False,
                generation_result=None,
                query_result=None,
                formatted_context="",
                total_time=0,
                used=False,
                error=str(e),
            )

    async def _execute_agent_mode(
        self, message: str, session_id: str, start_time: float
    ) -> RAGResultDict:
        """
        Agent 모드 실행 (Agentic RAG)

        AgentOrchestrator를 사용하여 ReAct 패턴 기반 에이전트 루프를 실행합니다.
        기존 7단계 파이프라인 대신 LLM이 도구를 선택하고 실행하는 방식입니다.

        Args:
            message: 사용자 쿼리
            session_id: 세션 ID
            start_time: 파이프라인 시작 시간

        Returns:
            RAGResultDict: Agent 모드 응답 (metadata.mode="agent" 포함)

        Raises:
            GenerationError: Agent 실행 중 오류 발생 시
        """
        # 세션 컨텍스트 조회
        session_context = ""
        if self.session_module:
            try:
                context_string = await self.session_module.get_context_string(session_id)
                if context_string:
                    session_context = context_string
                    logger.debug(
                        "세션 컨텍스트 로드 성공",
                        extra={"context_length": len(context_string)}
                    )
            except Exception as e:
                logger.warning(
                    "세션 컨텍스트 조회 실패",
                    extra={"error": str(e)},
                    exc_info=True
                )

        try:
            # AgentOrchestrator 실행
            agent_result = await self.agent_orchestrator.run(
                query=message,
                session_context=session_context,
            )

            # Agent 결과를 RAGResultDict 형식으로 변환
            processing_time = time.time() - start_time

            # Source 객체 변환 (Agent sources는 dict 형태일 수 있음)
            formatted_sources = []
            for idx, source in enumerate(agent_result.sources or []):
                if isinstance(source, dict):
                    formatted_sources.append(
                        self.Source(
                            id=idx,
                            document=source.get("source", source.get("title", f"Source {idx + 1}")),
                            page=source.get("page"),
                            chunk=source.get("chunk"),
                            relevance=source.get("relevance", source.get("score", 0.0)),
                            content_preview=source.get(
                                "content_preview", source.get("content", "")[:200]
                            ),
                            source_type="agent",
                        )
                    )
                else:
                    # 이미 Source 객체인 경우 그대로 사용
                    formatted_sources.append(source)

            result: RAGResultDict = cast(
                RAGResultDict,
                {
                    "answer": agent_result.answer,
                    "sources": formatted_sources,
                    "tokens_used": 0,  # Agent 모드에서는 개별 추적 어려움
                    "topic": self.extract_topic_func(message),
                    "processing_time": processing_time,
                    "search_results": len(agent_result.sources or []),
                    "ranked_results": len(agent_result.sources or []),
                    "model_info": {
                        "provider": "agent",
                        "model": "agent_orchestrator",
                        "model_used": "agent_orchestrator",
                    },
                    "metadata": {
                        "mode": "agent",
                        "steps_taken": agent_result.steps_taken,
                        "tools_used": agent_result.tools_used,
                        "total_time": agent_result.total_time,
                        "success": agent_result.success,
                    },
                },
            )

            logger.info(
                "Agent 모드 완료",
                extra={
                    "steps_taken": agent_result.steps_taken,
                    "processing_time": processing_time,
                    "tools_count": len(agent_result.tools_used)
                }
            )

            return result

        except Exception as e:
            logger.error(
                "Agent 모드 실행 실패",
                extra={"error": str(e)},
                exc_info=True
            )
            raise GenerationError(
                ErrorCode.GENERATION_REQUEST_FAILED,
                session_id=session_id,
                error=str(e),
            ) from e
