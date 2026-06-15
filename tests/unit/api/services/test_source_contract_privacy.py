"""출처(Source) 응답의 사설 참조(서버 내부 경로/스토리지 식별자) 노출 차단 회귀 테스트.

검증 대상(차용 #3):
- 서버 내부 절대경로(/srv/...), file://, gs:// 등 사설 참조가 응답 payload
  최상위·metadata·텍스트 필드 어디에도 노출되지 않는다.
- https:// 등 공개 URL은 source_uri로 보존된다.
- top-level file_path 키는 더 이상 서버 내부 경로를 담지 않는다.
"""

from app.api.services.source_contract import (
    normalize_citation_source_payload,
    normalize_source_payload,
)


def _flatten_strings(value: object) -> list[str]:
    """payload 내 모든 문자열 값을 재귀적으로 수집한다(노출 여부 점검용)."""
    found: list[str] = []
    if isinstance(value, str):
        found.append(value)
    elif isinstance(value, dict):
        for item in value.values():
            found.extend(_flatten_strings(item))
    elif isinstance(value, (list, tuple)):
        for item in value:
            found.extend(_flatten_strings(item))
    return found


def test_server_local_path_not_exposed_anywhere() -> None:
    """metadata의 서버 내부 절대경로가 payload 어디에도 노출되지 않아야 한다."""
    private_path = "/srv/app/data/uploads/customer_secret.pdf"
    payload = normalize_source_payload(
        sequence_id=0,
        source_type="vector",
        relevance=0.9,
        content_preview="문서 미리보기",
        metadata={
            "file_path": private_path,
            "document_name": "고객 안내문",
        },
    )

    all_strings = _flatten_strings(payload)
    assert private_path not in all_strings
    # 최상위 file_path 키는 사설 경로를 담지 않아야 한다(None 또는 제거)
    assert payload.get("file_path") in (None, "")
    # metadata에도 file_path 사설 경로가 새어나가지 않아야 한다
    assert "file_path" not in payload["metadata"]


def test_file_and_gs_scheme_uris_are_filtered() -> None:
    """file://, gs:// 스킴 식별자는 source_uri로 노출되지 않아야 한다."""
    payload = normalize_source_payload(
        sequence_id=1,
        source_type="vector",
        relevance=0.8,
        content_preview="미리보기",
        metadata={"source_uri": "gs://internal-bucket/object/path.pdf"},
    )
    assert payload["source_uri"] is None

    payload_file = normalize_source_payload(
        sequence_id=2,
        source_type="vector",
        relevance=0.8,
        content_preview="미리보기",
        source_uri="file:///var/data/secret.pdf",
    )
    assert payload_file["source_uri"] is None


def test_public_https_uri_is_preserved() -> None:
    """공개 https URL은 source_uri로 보존되어야 한다."""
    public_url = "https://example.com/docs/manual.pdf"
    payload = normalize_source_payload(
        sequence_id=3,
        source_type="web",
        relevance=0.7,
        content_preview="미리보기",
        source_uri=public_url,
    )
    assert payload["source_uri"] == public_url


def test_storage_backend_keys_excluded_from_metadata() -> None:
    """스토리지 백엔드 식별자 일반 키는 metadata에서 제외되어야 한다."""
    payload = normalize_source_payload(
        sequence_id=4,
        source_type="vector",
        relevance=0.6,
        content_preview="미리보기",
        metadata={
            "storage_backend": "gcs",
            "original_storage_backend": "s3",
            "original_file_path": "/mnt/storage/internal.pdf",
            "topic": "안전 공개 값",
        },
    )
    assert "storage_backend" not in payload["metadata"]
    assert "original_storage_backend" not in payload["metadata"]
    assert "original_file_path" not in payload["metadata"]
    # 사설 참조가 아닌 일반 메타데이터는 보존되어야 한다
    assert payload["metadata"].get("topic") == "안전 공개 값"


def test_citation_payload_filters_private_reference() -> None:
    """관리형 인용 payload도 사설 경로를 노출하지 않아야 한다."""
    payload = normalize_citation_source_payload(
        0, "/srv/app/data/private.pdf", source_type="grok"
    )
    all_strings = _flatten_strings(payload)
    assert "/srv/app/data/private.pdf" not in all_strings
