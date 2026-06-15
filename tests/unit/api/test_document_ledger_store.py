"""문서 수명주기 원장(SQLiteDocumentLedgerStore) 단위 테스트.

검증 대상(#38, 멀티테넌트 제거 일반화):
    - 업로드 문서 생성 + 원본 파일 메타 기록
    - replace_pages/replace_chunks 멱등 재처리
    - find_source_chunk 출처 역조회
    - tombstone_document soft-delete + 로컬 파일 정리
    - mark_status 상태 전이 + 감사 이벤트
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.api.document_ledger_store import SQLiteDocumentLedgerStore


@dataclass
class _FakeDoc:
    """LangChain Document 유사 객체(page_content + metadata)."""

    page_content: str
    metadata: dict[str, Any] = field(default_factory=dict)


def _make_store(tmp_path: Path) -> SQLiteDocumentLedgerStore:
    return SQLiteDocumentLedgerStore(tmp_path / "ledger.sqlite3")


def test_create_and_get_document(tmp_path: Path) -> None:
    """업로드 문서를 생성하면 조회·원본 파일 메타가 보존되어야 한다."""
    store = _make_store(tmp_path)
    store.create_uploaded_document(
        document_id="doc-1",
        filename="sample.pdf",
        file_type="pdf",
        file_size=1234,
        original_file_path="/data/originals/doc-1_sample.pdf",
        source_uri="file:///data/originals/doc-1_sample.pdf",
        metadata={"lang": "ko"},
    )
    document = store.get_document(document_id="doc-1")
    assert document is not None
    assert document["filename"] == "sample.pdf"
    assert document["status"] == "pending"
    original = store.get_original_file(document_id="doc-1")
    assert original is not None
    assert original["local_path"] == "/data/originals/doc-1_sample.pdf"


def test_replace_pages_and_chunks_idempotent(tmp_path: Path) -> None:
    """replace_pages/replace_chunks는 재호출 시 누적이 아닌 교체여야 한다."""
    store = _make_store(tmp_path)
    store.create_uploaded_document(
        document_id="doc-1",
        filename="sample.txt",
        file_type="txt",
        file_size=10,
        original_file_path="/data/originals/doc-1_sample.txt",
        source_uri=None,
    )
    docs = [_FakeDoc("page 1", {"page": 1}), _FakeDoc("page 2", {"page": 2})]
    assert store.replace_pages(document_id="doc-1", documents=docs) is True
    chunks = [
        {"content": "chunk a", "metadata": {"page": 1, "chunk_index": 0}, "id": "v-0"},
        {"content": "chunk b", "metadata": {"page": 2, "chunk_index": 1}, "id": "v-1"},
    ]
    assert store.replace_chunks(document_id="doc-1", chunks=chunks) is True
    # 재호출(교체) — 청크 1개로 축소
    assert store.replace_chunks(
        document_id="doc-1",
        chunks=[{"content": "only", "metadata": {"page": 1, "chunk_index": 0}}],
    ) is True
    found = store.find_source_chunk(
        document_id="doc-1", source_id="rag:doc-1:1:0"
    )
    assert found is not None
    assert found["content"] == "only"


def test_replace_pages_returns_false_for_missing_document(tmp_path: Path) -> None:
    """존재하지 않는 문서에 대한 replace_pages는 False여야 한다."""
    store = _make_store(tmp_path)
    assert store.replace_pages(document_id="missing", documents=[]) is False


def test_mark_status_records_completion(tmp_path: Path) -> None:
    """mark_status로 완료 상태 및 청크 수가 반영되어야 한다."""
    store = _make_store(tmp_path)
    store.create_uploaded_document(
        document_id="doc-1",
        filename="s.txt",
        file_type="txt",
        file_size=5,
        original_file_path="/data/originals/doc-1_s.txt",
        source_uri=None,
    )
    assert store.mark_status(
        document_id="doc-1", status="completed", chunk_count=3, processing_time=1.5
    ) is True
    document = store.get_document(document_id="doc-1")
    assert document is not None
    assert document["status"] == "completed"
    assert document["chunk_count"] == 3


def test_tombstone_document_soft_deletes_and_unlinks(tmp_path: Path) -> None:
    """tombstone_document는 soft-delete + 로컬 원본 파일을 정리해야 한다."""
    original = tmp_path / "doc-1_sample.txt"
    original.write_text("data", encoding="utf-8")
    store = _make_store(tmp_path)
    store.create_uploaded_document(
        document_id="doc-1",
        filename="sample.txt",
        file_type="txt",
        file_size=4,
        original_file_path=str(original),
        source_uri=None,
    )
    assert store.tombstone_document(document_id="doc-1") is True
    # soft-delete: 기본 조회에서 제외
    assert store.get_document(document_id="doc-1") is None
    # include_deleted로는 조회 가능(원장 보존)
    assert store.get_document(document_id="doc-1", include_deleted=True) is not None
    # 로컬 원본 파일은 제거됨
    assert not original.exists()
    # 목록에서도 제외
    listing = store.list_documents()
    assert listing["total_count"] == 0


def test_list_documents_pagination(tmp_path: Path) -> None:
    """list_documents는 soft-delete 제외 후 페이지네이션을 적용해야 한다."""
    store = _make_store(tmp_path)
    for index in range(3):
        store.create_uploaded_document(
            document_id=f"doc-{index}",
            filename=f"f-{index}.txt",
            file_type="txt",
            file_size=1,
            original_file_path=f"/data/originals/doc-{index}.txt",
            source_uri=None,
        )
    listing = store.list_documents(page=1, page_size=2)
    assert listing["total_count"] == 3
    assert len(listing["documents"]) == 2


def test_get_document_returns_none_without_database(tmp_path: Path) -> None:
    """DB 파일이 없으면 None을 반환해야 한다(조회만으로 생성 금지)."""
    store = SQLiteDocumentLedgerStore(tmp_path / "missing.sqlite3")
    assert store.get_document(document_id="doc-1") is None
