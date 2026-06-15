"""Provider-neutral source citation normalization helpers."""

from typing import Any

_DISPLAY_NAME_KEYS = (
    "document_name",
    "source_file",
    "filename",
    "file_name",
    "title",
    "name",
    "source",
    "document",
)
_DOCUMENT_ID_KEYS = ("document_id", "doc_id", "file_id", "id", "_id")
_PAGE_KEYS = ("page", "page_number")
_CHUNK_KEYS = ("chunk", "chunk_index")
_SECTION_KEYS = ("section", "heading", "title")
_SOURCE_URI_KEYS = (
    "source_uri",
    "uri",
    "url",
    "web_url",
    "file_uri",
    "citation",
)
_SOURCE_ID_KEYS = ("source_id", "citation_id", "id", "_id")
_METADATA_EXCLUDE_KEYS = {
    "content",
    "page_content",
    "text",
    "embedding",
    "embeddings",
    "vector",
    "vectors",
    # 서버 내부 경로/스토리지 식별자 차단(정보 노출 방지).
    # GCS 전용 키 대신 storage_backend 일반 키로 일반화해 모든 스토리지 백엔드에 적용한다.
    "file_path",
    "original_file_path",
    "storage_backend",
    "original_storage_backend",
}


def _first_present(data: dict[str, Any], keys: tuple[str, ...]) -> Any | None:
    for key in keys:
        value = data.get(key)
        if value is not None and value != "":
            return value
    return None


def _prefer_explicit(value: Any, fallback: Any | None = None) -> Any | None:
    if value is not None and value != "":
        return value
    return fallback


def _coerce_int(value: Any) -> int | None:
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _public_source_uri(value: Any) -> str | None:
    """공개 가능한 URI만 반환한다(사설 참조는 None).

    차단 대상:
    - file://, gs:// 등 스토리지 스킴 (서버 내부 식별자)
    - 절대/로컬 경로("/"로 시작)
    - 스킴 없이 슬래시를 포함한 상대 경로(예: data/x.pdf)

    보존 대상: http(s):// 등 공개 URL.
    """
    if value is None or value == "":
        return None
    uri = str(value)
    if uri.startswith(("file://", "gs://", "/")):
        return None
    if "://" not in uri and "/" in uri:
        return None
    return uri


def _is_private_source_reference(value: Any) -> bool:
    """문자열이 서버 내부 경로/스토리지 식별자(사설 참조)인지 판정한다."""
    if value is None:
        return False
    text = str(value)
    return ("://" in text or "/" in text) and _public_source_uri(text) is None


def _public_text_value(value: Any | None) -> str | None:
    """텍스트 필드 값이 사설 참조이면 차단하고, 아니면 문자열로 반환한다."""
    if value is None or value == "" or _is_private_source_reference(value):
        return None
    return str(value)


def _normalization_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    """metadata에서 사설 참조 문자열 값을 사전에 제거한다."""
    return {
        key: value
        for key, value in metadata.items()
        if not (isinstance(value, str) and _is_private_source_reference(value))
    }


def _compact_additional_metadata(value: Any) -> Any | None:
    """additional_metadata를 재귀적으로 정제해 사설 참조 노출을 차단한다.

    - 문자열: 경로/URI 형태면 공개 URL만 보존(file://·gs://·로컬경로 → None)
    - dict/list: 내부 항목을 재귀 정제하고, 비면 None 반환
    - 그 외 스칼라: 그대로 보존
    """
    if value is None:
        return None
    if isinstance(value, str):
        if "://" in value or "/" in value:
            return _public_source_uri(value)
        return value
    if isinstance(value, dict):
        compacted: dict[str, Any] = {}
        for key, item in value.items():
            if key in _METADATA_EXCLUDE_KEYS:
                continue
            if (
                key in _SOURCE_URI_KEYS
                and isinstance(item, str)
                and _public_source_uri(item) is None
            ):
                continue
            public_item = _compact_additional_metadata(item)
            if public_item is not None:
                compacted[key] = public_item
        return compacted or None
    if isinstance(value, list):
        compacted_list = [
            public_item
            for item in value
            if (public_item := _compact_additional_metadata(item)) is not None
        ]
        return compacted_list or None
    return value


def _normalize_page(metadata: dict[str, Any], explicit_page: Any | None) -> int | None:
    page = _coerce_int(explicit_page)
    if page is not None:
        return page

    page = _coerce_int(_first_present(metadata, _PAGE_KEYS))
    if page is not None:
        return page

    page_index = _coerce_int(metadata.get("page_index"))
    if page_index is not None:
        return page_index + 1
    return None


def _normalize_chunk(metadata: dict[str, Any], explicit_chunk: Any | None) -> int | None:
    chunk = _coerce_int(explicit_chunk)
    if chunk is not None:
        return chunk
    return _coerce_int(_first_present(metadata, _CHUNK_KEYS))


def _compact_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    compacted: dict[str, Any] = {}
    for key, value in metadata.items():
        if key in _METADATA_EXCLUDE_KEYS or value is None:
            continue
        # 서버 내부 경로/스토리지 식별자(사설 참조)는 키 종류와 무관하게 제외한다.
        if isinstance(value, str) and _is_private_source_reference(value):
            continue
        # source_uri 계열 키는 공개 URL이 아니면(file://·gs://·로컬경로) 제외한다.
        if key in _SOURCE_URI_KEYS and _public_source_uri(value) is None:
            continue
        compacted[key] = value
    return compacted


def _fallback_source_id(
    source_type: str,
    sequence_id: int,
    document_name: str,
    document_id: str | None,
    page: int | None,
    chunk: int | None,
) -> str:
    stable_document = document_id or document_name or f"source-{sequence_id}"
    stable_page = page if page is not None else "na"
    stable_chunk = chunk if chunk is not None else sequence_id
    return f"{source_type}:{stable_document}:{stable_page}:{stable_chunk}"


def normalize_source_payload(
    *,
    sequence_id: int,
    source_type: str,
    relevance: float,
    content_preview: str,
    metadata: dict[str, Any] | None = None,
    document_name: str | None = None,
    document_id: str | None = None,
    page: Any | None = None,
    chunk: Any | None = None,
    section: str | None = None,
    source_uri: str | None = None,
    additional_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a backward-compatible OneRAG Source payload with normalized fields."""

    # 사설 참조(서버 내부 경로/스토리지 식별자) 문자열을 사전에 정제한다.
    source_metadata = _normalization_metadata(dict(metadata or {}))
    # 명시 인자도 사설 참조이면 차단한다.
    explicit_document_name = _public_text_value(document_name)
    explicit_document_id = _public_text_value(document_id)
    explicit_section = _public_text_value(section)
    public_content_preview = (
        "" if _is_private_source_reference(content_preview) else content_preview
    )
    normalized_document_name = str(
        explicit_document_name
        or _first_present(source_metadata, _DISPLAY_NAME_KEYS)
        or f"Document {sequence_id + 1}"
    )
    normalized_document_id_value = _prefer_explicit(
        explicit_document_id, _first_present(source_metadata, _DOCUMENT_ID_KEYS)
    )
    normalized_document_id = (
        str(normalized_document_id_value)
        if normalized_document_id_value is not None
        else None
    )
    normalized_page = _normalize_page(source_metadata, page)
    normalized_chunk = _normalize_chunk(source_metadata, chunk)
    normalized_section_value = _prefer_explicit(
        explicit_section, _first_present(source_metadata, _SECTION_KEYS)
    )
    normalized_section = (
        str(normalized_section_value)
        if normalized_section_value is not None
        else None
    )
    normalized_source_uri_value = _prefer_explicit(
        source_uri, _first_present(source_metadata, _SOURCE_URI_KEYS)
    )
    # 공개 URL만 보존하고 file://·gs://·로컬경로는 차단한다.
    normalized_source_uri = _public_source_uri(normalized_source_uri_value)
    source_id_value = _first_present(source_metadata, _SOURCE_ID_KEYS)
    source_id = (
        str(source_id_value)
        if source_id_value is not None
        else _fallback_source_id(
            source_type,
            sequence_id,
            normalized_document_name,
            normalized_document_id,
            normalized_page,
            normalized_chunk,
        )
    )

    payload: dict[str, Any] = {
        "id": sequence_id,
        "source_id": source_id,
        "document": normalized_document_name,
        "document_id": normalized_document_id,
        "document_name": normalized_document_name,
        "page": normalized_page,
        "chunk": normalized_chunk,
        "section": normalized_section,
        "relevance": relevance,
        "score": relevance,
        "content_preview": public_content_preview,
        "source_type": source_type,
        "source_uri": normalized_source_uri,
        "metadata": _compact_metadata(source_metadata),
        "additional_metadata": _compact_additional_metadata(additional_metadata) or {},
        "file_type": _public_text_value(source_metadata.get("file_type")),
        # file_path는 서버 내부 절대경로이므로 응답에 노출하지 않는다(항상 None).
        # 프론트엔드 타입(index.ts)에서 file_path는 optional이라 계약 파기 위험 없음.
        "file_path": None,
        "file_size": source_metadata.get("file_size"),
        "total_chunks": source_metadata.get("total_chunks"),
        "file_hash": _public_text_value(source_metadata.get("file_hash")),
        "load_timestamp": source_metadata.get("load_timestamp"),
        "sheet_name": _public_text_value(
            source_metadata.get("sheet_name") or source_metadata.get("sheet")
        ),
        "format": _public_text_value(source_metadata.get("format")),
        "json_type": _public_text_value(source_metadata.get("json_type")),
        "item_index": source_metadata.get("item_index"),
        "rerank_method": _public_text_value(source_metadata.get("rerank_method")),
        "original_score": source_metadata.get("original_score"),
    }
    return payload


def normalize_citation_source_payload(
    sequence_id: int,
    citation: Any,
    *,
    source_type: str = "grok",
) -> dict[str, Any]:
    """Normalize managed-provider citation payloads into OneRAG Source fields."""

    if isinstance(citation, dict):
        metadata = dict(citation)
        preview_value = _first_present(
            metadata,
            ("quote", "snippet", "text", "content", "url", "source_uri", "file_id"),
        )
        if _is_private_source_reference(preview_value):
            preview_value = None
        document_name_value = _first_present(metadata, _DISPLAY_NAME_KEYS + ("file_id",))
        if _is_private_source_reference(document_name_value):
            document_name_value = None
        return normalize_source_payload(
            sequence_id=sequence_id,
            source_type=source_type,
            relevance=1.0,
            content_preview=str(preview_value)[:300] if preview_value else "",
            metadata=metadata,
            document_name=str(document_name_value) if document_name_value else None,
            additional_metadata={"citation": citation},
        )

    citation_text = str(citation)
    # 공개 스킴(http(s)://)만 source_uri로 보존하고 사설 참조는 차단한다.
    source_uri = _public_source_uri(citation_text) if "://" in citation_text else None
    private_reference = _is_private_source_reference(citation_text)
    return normalize_source_payload(
        sequence_id=sequence_id,
        source_type=source_type,
        relevance=1.0,
        content_preview="" if private_reference else citation_text[:300],
        metadata={"citation": citation_text},
        document_name=None if private_reference else citation_text,
        source_uri=source_uri,
        additional_metadata={"citation": citation},
    )
