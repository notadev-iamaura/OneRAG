from unittest.mock import MagicMock
from zipfile import ZipFile

import pandas as pd
import pytest
from langchain_core.documents import Document

from app.modules.core.documents.document_processing import DocumentProcessor
from app.modules.core.documents.loaders.factory import LoaderFactory
from app.modules.core.documents.loaders.pptx_loader import PPTXLoader
from app.modules.core.documents.loaders.xlsx_loader import XLSXLoader


def _write_minimal_pptx(path) -> None:
    with ZipFile(path, "w") as archive:
        archive.writestr(
            "[Content_Types].xml",
            """<?xml version="1.0" encoding="UTF-8"?>
            <Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
              <Default Extension="xml" ContentType="application/xml"/>
            </Types>""",
        )
        archive.writestr(
            "ppt/slides/slide2.xml",
            """<?xml version="1.0" encoding="UTF-8"?>
            <p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"
                   xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">
              <p:cSld><p:spTree><p:sp><p:txBody><a:p><a:r><a:t>두 번째 슬라이드</a:t></a:r></a:p></p:txBody></p:sp></p:spTree></p:cSld>
            </p:sld>""",
        )
        archive.writestr(
            "ppt/slides/slide1.xml",
            """<?xml version="1.0" encoding="UTF-8"?>
            <p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"
                   xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">
              <p:cSld><p:spTree><p:sp><p:txBody><a:p><a:r><a:t>첫 번째 제목</a:t></a:r><a:r><a:t>본문 텍스트</a:t></a:r></a:p></p:txBody></p:sp></p:spTree></p:cSld>
            </p:sld>""",
        )


@pytest.mark.asyncio
async def test_embed_chunks_emits_canonical_embedding_and_legacy_alias() -> None:
    processor = DocumentProcessor.__new__(DocumentProcessor)
    processor.embedder = MagicMock()
    processor.embedder.embed_documents = MagicMock(return_value=[[0.1, 0.2, 0.3]])
    processor.sparse_embedder = None

    chunks = [
        Document(
            page_content="테스트 문서",
            metadata={"document_id": "doc-1", "source_file": "sample.txt"},
        )
    ]

    embedded = await processor.embed_chunks(chunks)

    assert embedded == [
        {
            "content": "테스트 문서",
            "embedding": [0.1, 0.2, 0.3],
            "dense_embedding": [0.1, 0.2, 0.3],
            "metadata": {"document_id": "doc-1", "source_file": "sample.txt"},
        }
    ]


@pytest.mark.asyncio
async def test_xlsx_loader_accepts_date_headers(tmp_path) -> None:
    path = tmp_path / "date-header.xlsx"
    header = pd.Timestamp("2026-01-01")
    pd.DataFrame([{header: "값", "name": "홍길동"}]).to_excel(path, index=False)

    documents = await XLSXLoader().load(path)

    assert documents
    assert "2026-01-01" in documents[0].page_content
    assert "값" in documents[0].page_content


@pytest.mark.asyncio
async def test_legacy_xlsx_loader_accepts_date_headers(tmp_path) -> None:
    path = tmp_path / "legacy-date-header.xlsx"
    header = pd.Timestamp("2026-01-01")
    pd.DataFrame([{header: "값"}]).to_excel(path, index=False)

    processor = DocumentProcessor.__new__(DocumentProcessor)
    documents = await processor._load_xlsx(path)

    assert documents
    assert "2026-01-01" in documents[0].page_content


def test_doc_extension_is_not_mapped_to_docx_loader() -> None:
    assert LoaderFactory.get_loader("legacy.doc") is None


def test_pptx_extension_is_mapped_to_pptx_loader() -> None:
    assert isinstance(LoaderFactory.get_loader("deck.pptx"), PPTXLoader)


@pytest.mark.asyncio
async def test_pptx_loader_extracts_slide_text_in_slide_order(tmp_path) -> None:
    path = tmp_path / "deck.pptx"
    _write_minimal_pptx(path)

    documents = await PPTXLoader().load(path)

    assert [doc.metadata["slide_number"] for doc in documents] == [1, 2]
    assert "첫 번째 제목" in documents[0].page_content
    assert "본문 텍스트" in documents[0].page_content
    assert "두 번째 슬라이드" in documents[1].page_content


@pytest.mark.asyncio
async def test_document_processor_loads_pptx_with_metadata(tmp_path) -> None:
    path = tmp_path / "deck.pptx"
    _write_minimal_pptx(path)

    processor = DocumentProcessor.__new__(DocumentProcessor)
    processor.supported_types = ["pptx"]

    documents = await processor.load_document(path)

    assert documents
    assert documents[0].metadata["source_file"] == "deck.pptx"
    assert documents[0].metadata["file_type"] == "pptx"
