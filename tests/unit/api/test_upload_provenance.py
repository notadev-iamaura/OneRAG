"""업로드 작업상태 처리 프로비넌스 노출 테스트 (GAP #9 차용).

검증 대상:
- JobStatusResponse가 loader_type/splitter_type/storage_locations/extraction_summary
  4개 필드를 노출하는지.
- 백엔드가 '실제 처리된' 값을 산출하는 헬퍼:
  - _upload_loader_type: 파일타입 라벨, PDF는 추출 방식(extraction_method) 반영.
  - _upload_splitter_type: 청크 metadata의 splitter_type(table_row 자동청킹 포함).
  - _upload_storage_locations: Vector DB + (보관 원본 있으면) Original File Storage.
  - _extract_extraction_summary: PDF 스캔/표/경고 요약.
- 일본어/도메인/GCP Document AI OCR 하드코딩 없이 범용 동작.
"""

from types import SimpleNamespace
from typing import Any

from app.api.upload import (
    JobStatusResponse,
    _extract_extraction_summary,
    _upload_loader_type,
    _upload_splitter_type,
    _upload_storage_locations,
)


def _doc(metadata: dict[str, Any]) -> SimpleNamespace:
    return SimpleNamespace(metadata=metadata)


# ============================================================
# JobStatusResponse 필드 노출
# ============================================================


def test_job_status_response_exposes_provenance_fields() -> None:
    """JobStatusResponse가 4개 프로비넌스 필드를 노출하고 기본값은 None이다."""
    response = JobStatusResponse(
        job_id="j1",
        status="completed",
        progress=100.0,
        message="완료",
        filename="a.pdf",
        timestamp="2026-01-01T00:00:00",
    )
    assert response.loader_type is None
    assert response.splitter_type is None
    assert response.storage_locations is None
    assert response.extraction_summary is None

    populated = JobStatusResponse(
        job_id="j2",
        status="completed",
        progress=100.0,
        message="완료",
        filename="b.xlsx",
        timestamp="2026-01-01T00:00:00",
        loader_type="XLSX",
        splitter_type="Recursive",
        storage_locations=["Vector Database"],
        extraction_summary={"page_count": 3},
    )
    assert populated.loader_type == "XLSX"
    assert populated.storage_locations == ["Vector Database"]


# ============================================================
# _upload_loader_type
# ============================================================


def test_loader_type_label_for_known_type() -> None:
    """알려진 파일타입은 사람이 읽기 좋은 라벨로 매핑된다."""
    assert _upload_loader_type("xlsx", []) == "XLSX"
    assert _upload_loader_type("docx", []) == "DOCX"
    assert _upload_loader_type("md", []) == "Markdown"


def test_loader_type_pdf_reflects_extraction_method() -> None:
    """PDF는 실제 추출 방식(extraction_method)을 라벨에 반영한다."""
    docs = [_doc({"extraction_method": "pypdf", "page_number": 1})]
    label = _upload_loader_type("pdf", docs)
    assert "PDF" in label
    assert "pypdf" in label


def test_loader_type_unknown_falls_back_to_upper() -> None:
    """미지의 파일타입은 대문자 폴백."""
    assert _upload_loader_type("xyz", []) == "XYZ"


# ============================================================
# _upload_splitter_type
# ============================================================


def test_splitter_type_from_chunk_metadata() -> None:
    """청크 metadata의 splitter_type을 라벨로 노출한다."""
    chunks = [_doc({"splitter_type": "recursive"}), _doc({"splitter_type": "recursive"})]
    assert _upload_splitter_type(chunks, SimpleNamespace()) == "Recursive"


def test_splitter_type_includes_table_row() -> None:
    """표 자동청킹(table_row)이 섞이면 함께 표기한다."""
    chunks = [
        _doc({"splitter_type": "recursive"}),
        _doc({"splitter_type": "table_row"}),
    ]
    label = _upload_splitter_type(chunks, SimpleNamespace())
    assert label is not None
    assert "Recursive" in label
    assert "Table Row" in label


def test_splitter_type_falls_back_to_processor_config() -> None:
    """청크 metadata가 비면 processor의 설정값으로 폴백한다."""
    processor = SimpleNamespace(splitter_type="semantic")
    assert _upload_splitter_type([_doc({})], processor) == "Semantic"


# ============================================================
# _upload_storage_locations
# ============================================================


def test_storage_locations_vector_only() -> None:
    """보관 원본이 없으면 Vector Database만."""
    assert _upload_storage_locations({}) == ["Vector Database"]


def test_storage_locations_with_original() -> None:
    """원본 보관(local)이 있으면 Original File Storage를 추가한다."""
    job = {"original_storage_backend": "local", "original_file_path": "/tmp/a.pdf"}
    locations = _upload_storage_locations(job)
    assert "Vector Database" in locations
    assert any("Original File Storage" in loc for loc in locations)


# ============================================================
# _extract_extraction_summary
# ============================================================


def test_extraction_summary_aggregates_pdf_pages() -> None:
    """PDF 페이지/스캔/경고 메타를 요약으로 집계한다."""
    docs = [
        _doc(
            {
                "extraction_method": "pypdf",
                "page_number": 1,
                "scanned_page": False,
                "extraction_warnings": [],
            }
        ),
        _doc(
            {
                "extraction_method": "pypdf",
                "page_number": 2,
                "scanned_page": True,
                "extraction_warnings": ["scanned_page"],
            }
        ),
    ]
    summary = _extract_extraction_summary(docs)
    assert summary is not None
    assert summary["page_count"] == 2
    assert summary["scanned_page_count"] == 1
    assert "scanned_page" in summary["extraction_warnings"]


def test_extraction_summary_none_for_non_pdf() -> None:
    """추출 메타가 없는 문서는 요약을 만들지 않는다(None)."""
    docs = [_doc({"sheet": "Sheet1"})]
    assert _extract_extraction_summary(docs) is None
