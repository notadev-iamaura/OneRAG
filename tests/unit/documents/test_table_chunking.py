"""표(xlsx/csv) 행 단위 청킹 단위 테스트 (#21).

검증 항목:
    1. is_table_document: file_type 메타 기반 표 문서 판별(PDF 제외).
    2. chunk_table_rows: 행 슬라이딩 묶음 + 청크별 헤더 반복.
    3. graceful: 빈 본문/단일행이면 원본 그대로 반환.
    4. DocumentProcessor.split_documents: table_chunking_enabled opt-in 동작 및
       기본 OFF 시 기존 recursive 경로 보존.
"""

from __future__ import annotations

import pytest
from langchain_core.documents import Document

from app.modules.core.documents.document_processing import (
    DocumentProcessor,
    chunk_table_rows,
    is_table_document,
)


def _make_table_text(rows: int) -> str:
    """헤더 1줄 + rows개의 데이터 행으로 구성된 표 텍스트를 만든다."""
    header = "컬럼: 항목, 값"
    lines = [header]
    for i in range(rows):
        lines.append(f"항목: 품목{i} | 값: {i}")
    return "\n".join(lines)


def test_is_table_document_detects_xlsx_csv_excludes_pdf() -> None:
    assert is_table_document(Document(page_content="x", metadata={"file_type": "xlsx"}))
    assert is_table_document(Document(page_content="x", metadata={"file_type": "XLS"}))
    assert is_table_document(Document(page_content="x", metadata={"file_type": "csv"}))
    # PDF는 table_count 기본 0 오분류 위험이 있어 의도적으로 제외한다.
    assert not is_table_document(Document(page_content="x", metadata={"file_type": "pdf"}))
    assert not is_table_document(Document(page_content="x", metadata={}))


def test_chunk_table_rows_repeats_header_each_chunk() -> None:
    doc = Document(page_content=_make_table_text(10), metadata={"file_type": "csv"})
    chunks = chunk_table_rows(
        doc, rows_per_chunk=4, row_overlap=0, include_header_each_chunk=True
    )
    assert len(chunks) >= 2
    # 모든 청크가 헤더 행을 첫 줄에 포함해야 한다(컬럼 의미 보존).
    for chunk in chunks:
        assert chunk.page_content.startswith("컬럼: 항목, 값")
        assert chunk.metadata["table_chunked"] is True
        assert "table_row_start" in chunk.metadata


def test_chunk_table_rows_applies_overlap() -> None:
    doc = Document(page_content=_make_table_text(10), metadata={"file_type": "csv"})
    chunks = chunk_table_rows(
        doc, rows_per_chunk=4, row_overlap=2, include_header_each_chunk=True
    )
    # overlap=2이므로 step=2 → 첫 청크 행0~3, 둘째 청크 행2~5가 겹쳐야 한다.
    assert "품목2" in chunks[0].page_content
    assert "품목2" in chunks[1].page_content


def test_chunk_table_rows_graceful_on_empty_or_single_row() -> None:
    empty = Document(page_content="   ", metadata={"file_type": "csv"})
    assert chunk_table_rows(
        empty, rows_per_chunk=4, row_overlap=0, include_header_each_chunk=True
    ) == [empty]

    single = Document(page_content="컬럼: 항목, 값", metadata={"file_type": "csv"})
    assert chunk_table_rows(
        single, rows_per_chunk=4, row_overlap=0, include_header_each_chunk=True
    ) == [single]


@pytest.mark.asyncio
async def test_split_documents_table_chunking_disabled_by_default() -> None:
    """기본 OFF: 표 문서도 기존 recursive 경로로 처리되어 table_chunked 메타가 없어야 한다."""
    processor = DocumentProcessor.__new__(DocumentProcessor)
    processor.splitter_type = "recursive"
    processor.chunk_size = 1250
    processor.chunk_overlap = 100
    # table_chunking_enabled 미설정 → getattr 폴백으로 기본 OFF여야 한다.

    docs = [Document(page_content=_make_table_text(10), metadata={"file_type": "csv"})]
    result = await processor.split_documents(docs)

    assert result
    assert all(not d.metadata.get("table_chunked") for d in result)


@pytest.mark.asyncio
async def test_split_documents_table_chunking_enabled_produces_row_chunks() -> None:
    """opt-in: enabled=True면 표 문서가 행 단위 청크로 분할되고 splitter_type=table_row."""
    processor = DocumentProcessor.__new__(DocumentProcessor)
    processor.splitter_type = "recursive"
    processor.chunk_size = 1250
    processor.chunk_overlap = 100
    processor.table_chunking_enabled = True
    processor.table_rows_per_chunk = 4
    processor.table_row_overlap = 0
    processor.table_include_header = True

    docs = [Document(page_content=_make_table_text(10), metadata={"file_type": "csv"})]
    result = await processor.split_documents(docs)

    table_chunks = [d for d in result if d.metadata.get("table_chunked")]
    assert len(table_chunks) >= 2
    for chunk in table_chunks:
        assert chunk.page_content.startswith("컬럼: 항목, 값")
        assert chunk.metadata.get("splitter_type") == "table_row"
        assert "chunk_index" in chunk.metadata
        assert chunk.metadata["total_chunks"] == len(result)
