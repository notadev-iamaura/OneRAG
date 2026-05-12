from unittest.mock import MagicMock

import pytest
from langchain_core.documents import Document

from app.modules.core.documents.document_processing import DocumentProcessor


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
