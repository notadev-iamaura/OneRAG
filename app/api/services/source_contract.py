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

    source_metadata = dict(metadata or {})
    normalized_document_name = str(
        document_name
        or _first_present(source_metadata, _DISPLAY_NAME_KEYS)
        or f"Document {sequence_id + 1}"
    )
    normalized_document_id_value = _prefer_explicit(
        document_id, _first_present(source_metadata, _DOCUMENT_ID_KEYS)
    )
    normalized_document_id = (
        str(normalized_document_id_value)
        if normalized_document_id_value is not None
        else None
    )
    normalized_page = _normalize_page(source_metadata, page)
    normalized_chunk = _normalize_chunk(source_metadata, chunk)
    normalized_section_value = _prefer_explicit(
        section, _first_present(source_metadata, _SECTION_KEYS)
    )
    normalized_section = (
        str(normalized_section_value)
        if normalized_section_value is not None
        else None
    )
    normalized_source_uri_value = _prefer_explicit(
        source_uri, _first_present(source_metadata, _SOURCE_URI_KEYS)
    )
    normalized_source_uri = (
        str(normalized_source_uri_value)
        if normalized_source_uri_value is not None
        else None
    )
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
        "content_preview": content_preview,
        "source_type": source_type,
        "source_uri": normalized_source_uri,
        "metadata": _compact_metadata(source_metadata),
        "additional_metadata": additional_metadata or {},
        "file_type": source_metadata.get("file_type"),
        "file_path": source_metadata.get("file_path"),
        "file_size": source_metadata.get("file_size"),
        "total_chunks": source_metadata.get("total_chunks"),
        "file_hash": source_metadata.get("file_hash"),
        "load_timestamp": source_metadata.get("load_timestamp"),
        "sheet_name": source_metadata.get("sheet_name") or source_metadata.get("sheet"),
        "format": source_metadata.get("format"),
        "json_type": source_metadata.get("json_type"),
        "item_index": source_metadata.get("item_index"),
        "rerank_method": source_metadata.get("rerank_method"),
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
        document_name_value = _first_present(metadata, _DISPLAY_NAME_KEYS + ("file_id",))
        return normalize_source_payload(
            sequence_id=sequence_id,
            source_type=source_type,
            relevance=1.0,
            content_preview=str(preview_value or citation)[:300],
            metadata=metadata,
            document_name=str(document_name_value) if document_name_value else None,
            additional_metadata={"citation": citation},
        )

    citation_text = str(citation)
    source_uri = citation_text if "://" in citation_text else None
    return normalize_source_payload(
        sequence_id=sequence_id,
        source_type=source_type,
        relevance=1.0,
        content_preview=citation_text[:300],
        metadata={"citation": citation_text},
        document_name=citation_text,
        source_uri=source_uri,
        additional_metadata={"citation": citation},
    )
