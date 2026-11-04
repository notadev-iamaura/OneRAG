"""RAG 파이프라인 공용 헬퍼/상수 (rag_pipeline.py에서 분리).

문서 메타데이터 접근, 점수/리랭크 판정, 정확 식별자·문서명 추출, 사용자 노출 메시지 상수 등
단계 믹스인과 RAGPipeline이 함께 쓰는 순수 함수들이다. 상태를 갖지 않는다.
"""
from __future__ import annotations

import os
import re
import unicodedata
from typing import Any

from ....lib.logger import get_logger
from ....modules.core.retrieval.interfaces import SearchResult

logger = get_logger(__name__)

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
    if score is not None and _is_numeric_score(score):
        return float(score)

    metadata = _document_metadata(document)
    for key in ("score", "rerank_score", "retrieval_score"):
        metadata_score = metadata.get(key)
        if metadata_score is not None and _is_numeric_score(metadata_score):
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
