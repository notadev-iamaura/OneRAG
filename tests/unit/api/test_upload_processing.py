import asyncio
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

    async def embed_chunks_parallel(self, chunks: list[str]) -> list[dict[str, Any]]:
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


@pytest.mark.asyncio
async def test_guarded_processing_times_out_marks_failed_and_cleans_up(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """처리가 제한 시간을 넘으면 job을 failed로 표시하고 자원을 정리한다."""
    job_id = "job-proc-timeout"
    file_path = tmp_path / "sample.txt"
    file_path.write_text("sample", encoding="utf-8")
    upload.upload_jobs[job_id] = {
        "job_id": job_id,
        "status": "pending",
        "progress": 0,
        "message": "queued",
        "start_time": 1.0,
    }

    # 처리를 제한 시간보다 오래 걸리게 만들어 타임아웃을 유발한다.
    async def slow_process(*args: object, **kwargs: object) -> None:
        await asyncio.sleep(5)

    monkeypatch.setattr(upload, "process_document_background", slow_process)
    monkeypatch.setattr(upload, "_document_processing_timeout_seconds", lambda: 0.05)
    retrieval = FakeRetrievalModule(
        {"success_count": 0, "error_count": 0, "total_count": 0, "errors": []}
    )
    monkeypatch.setattr(upload, "modules", {"retrieval": retrieval})

    await upload.process_document_background_guarded(
        job_id, file_path, "sample.txt", "txt"
    )

    assert upload.upload_jobs[job_id]["status"] == "failed"
    assert "시간 초과" in upload.upload_jobs[job_id]["message"]
    assert upload.upload_jobs[job_id]["retry_safe"] is True
    # 임시파일 정리
    assert not file_path.exists()
    # 부분 적재 벡터 정리 시도(best-effort): delete_document가 호출됐다.
    assert retrieval.deleted_document_id == job_id


@pytest.mark.asyncio
async def test_guarded_processing_completes_normally(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """제한 시간 내 정상 처리는 guarded 래퍼를 그대로 통과해 completed가 된다."""
    job_id = "job-proc-ok"
    file_path = tmp_path / "sample.txt"
    file_path.write_text("sample", encoding="utf-8")
    upload.upload_jobs[job_id] = {
        "job_id": job_id,
        "status": "pending",
        "progress": 0,
        "message": "queued",
        "start_time": 1.0,
    }
    processor = FakeDocumentProcessor(
        [{"content": "a", "embedding": [0.1], "metadata": {"document_id": job_id}}]
    )
    retrieval = FakeRetrievalModule(
        {"success_count": 1, "error_count": 0, "total_count": 1, "errors": []}
    )
    monkeypatch.setattr(
        upload, "modules", {"document_processor": processor, "retrieval": retrieval}
    )
    monkeypatch.setattr(upload, "_document_processing_timeout_seconds", lambda: 60.0)

    await upload.process_document_background_guarded(
        job_id, file_path, "sample.txt", "txt"
    )

    assert upload.upload_jobs[job_id]["status"] == "completed"


def test_document_processing_timeout_seconds_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """타임아웃 값 해석: config > env > 기본 1500초, 그리고 최소 60초 보장."""
    monkeypatch.delenv("ONERAG_UPLOAD_PROCESSING_TIMEOUT_SECONDS", raising=False)
    monkeypatch.setattr(upload, "config", {})
    assert upload._document_processing_timeout_seconds() == 1500.0

    monkeypatch.setenv("ONERAG_UPLOAD_PROCESSING_TIMEOUT_SECONDS", "900")
    assert upload._document_processing_timeout_seconds() == 900.0

    # config가 env보다 우선한다.
    monkeypatch.setattr(
        upload, "config", {"uploads": {"processing_timeout_seconds": 1200}}
    )
    assert upload._document_processing_timeout_seconds() == 1200.0

    # 과도하게 짧은 값은 최소 60초로 보정한다.
    monkeypatch.setattr(upload, "config", {"uploads": {"processing_timeout_seconds": 1}})
    assert upload._document_processing_timeout_seconds() == 60.0
