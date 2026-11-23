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


def test_measured_rate_preserves_evidence_but_other_private_references_are_filtered() -> None:
    excerpt = "Payload capacity: 50 kg. Maximum speed: 2 m/s."
    for preview, expected in [(excerpt, excerpt), (excerpt + " See /srv/private.pdf", "")]:
        payload = normalize_source_payload(
            sequence_id=0, source_type="agent", relevance=1.0, content_preview=preview,
            additional_metadata={"cited_sentences": [preview]},
        )
        assert payload["content_preview"] == expected
        assert payload["additional_metadata"].get("cited_sentences", []) == ([expected] if expected else [])


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


def test_public_links_and_measured_rates_do_not_whitelist_embedded_private_references() -> None:
    public = "공개 안내 https://example.org/manual 속도 7 m/s"
    for private in ("file:///private/demo.pdf", "gs://bucket/internal.pdf", "/srv/private/doc", r"C:\uploads\demo"):
        mixed = f"{public} 첨부는 {private}"
        payload = normalize_source_payload(
            sequence_id=0, source_type="agent", relevance=0.8, content_preview=mixed,
            additional_metadata={"cited_sentences": [mixed, public]},
        )
        assert payload["content_preview"] == ""
        assert payload["additional_metadata"] == {"cited_sentences": [public]}


def test_live_stream_and_rest_share_safe_identity_without_inventing_a_file_handle() -> None:
    from app.api.services.chat_service import ChatService
    from app.api.services.source_contract import public_history_message
    from app.modules.core.privacy.masker import PrivacyMasker

    service = ChatService({}, {})
    masker = PrivacyMasker()
    service.rag_pipeline.privacy_masker = masker
    seen = set()
    for value in ("010-1234-6789", "010-5678-6789", r"C:\uploads\example\internal.pdf"):
        metadata = {"source": "안내.pdf", "document_id": value, "chunk_index": 2,
                    "extra": {"file_path": "/internal/path.pdf", "customer": value}}
        [stream] = service._format_stream_sources([{"content": "공개 내용", "metadata": metadata}])
        rest = normalize_source_payload(sequence_id=0, source_type="rag", relevance=0, content_preview="공개 내용",
                                        metadata=metadata, mask_text=masker.mask_text)
        legacy = {"document": "안내.pdf", "document_id": value, "chunk": 2, "id": 0,
                  "source_id": f"rag:{value}:na:2", "metadata": metadata}
        msg = public_history_message({"sources": [legacy], "retrieved_sources": [legacy]}, masker.mask_text)
        for source in (stream, rest, *msg["sources"], *msg["retrieved_sources"]):
            assert source["source_id"] == stream["source_id"]
            assert source.get("document_id") is None
            assert all(value not in text and "/internal/path.pdf" not in text for text in _flatten_strings(source))
        seen.add(stream["source_id"])
    assert len(seen) == 3

    safe = normalize_source_payload(sequence_id=0, source_type="rag", relevance=0, content_preview="",
                                    document_id="public-file", metadata={"source_id": "public-chunk"})
    assert (safe["document_id"], safe["source_id"]) == ("public-file", "public-chunk")
