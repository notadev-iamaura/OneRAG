from pathlib import Path
from typing import Any

import pytest

from app.api import upload


class FakeDocumentProcessor:
    def __init__(self, embedded_chunks: list[dict[str, Any]]) -> None:
        self.embedded_chunks = embedded_chunks
        self.load_metadata: dict[str, Any] | None = None

    async def load_document(self, file_path: str, metadata: dict[str, Any]) -> list[str]:
        self.load_metadata = metadata
        return [file_path]

    async def split_documents(self, docs: list[str]) -> list[str]:
        return ["chunk-1", "chunk-2"]

    async def embed_chunks(self, chunks: list[str]) -> list[dict[str, Any]]:
        return self.embedded_chunks


class FakeRetrievalModule:
    def __init__(self, result: dict[str, Any]) -> None:
        self.result = result
        self.deleted_document_id: str | None = None

    async def add_documents(self, documents: list[dict[str, Any]]) -> dict[str, Any]:
        return self.result

    async def delete_document(self, document_id: str) -> bool:
        self.deleted_document_id = document_id
        return True


@pytest.fixture(autouse=True)
def isolate_upload_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(upload, "upload_jobs", {})
    monkeypatch.setattr(upload, "save_upload_jobs", lambda jobs: None)
    monkeypatch.setattr(upload, "_privacy_masker", None)


@pytest.mark.asyncio
async def test_process_document_background_marks_partial_vector_save_as_failed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    job_id = "job-123"
    file_path = tmp_path / "sample.txt"
    file_path.write_text("sample", encoding="utf-8")
    upload.upload_jobs[job_id] = {"start_time": 1.0}

    processor = FakeDocumentProcessor(
        [
            {"content": "a", "embedding": [0.1], "metadata": {"document_id": job_id}},
            {"content": "b", "embedding": [0.2], "metadata": {"document_id": job_id}},
        ]
    )
    retrieval = FakeRetrievalModule(
        {
            "success_count": 1,
            "error_count": 1,
            "total_count": 2,
            "errors": ["문서에 'embedding' 필드가 없습니다."],
        }
    )
    monkeypatch.setattr(
        upload,
        "modules",
        {"document_processor": processor, "retrieval": retrieval},
    )

    await upload.process_document_background(job_id, file_path, "sample.txt", "txt")

    assert upload.upload_jobs[job_id]["status"] == "failed"
    assert "Vector DB 저장 실패" in upload.upload_jobs[job_id]["error_message"]
    assert retrieval.deleted_document_id == job_id
    assert not file_path.exists()


@pytest.mark.asyncio
async def test_process_document_background_passes_stable_document_id(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    job_id = "job-456"
    file_path = tmp_path / "sample.txt"
    file_path.write_text("sample", encoding="utf-8")
    upload.upload_jobs[job_id] = {"start_time": 1.0}

    processor = FakeDocumentProcessor(
        [{"content": "a", "embedding": [0.1], "metadata": {"document_id": job_id}}]
    )
    retrieval = FakeRetrievalModule(
        {"success_count": 1, "error_count": 0, "total_count": 1, "errors": []}
    )
    monkeypatch.setattr(
        upload,
        "modules",
        {"document_processor": processor, "retrieval": retrieval},
    )

    await upload.process_document_background(job_id, file_path, "sample.txt", "txt")

    assert upload.upload_jobs[job_id]["status"] == "completed"
    assert processor.load_metadata is not None
    assert processor.load_metadata["document_id"] == job_id
    assert processor.load_metadata["source_file"] == "sample.txt"
    assert not file_path.exists()
