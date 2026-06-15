"""인프로세스 업로드 파이프라인 스모크 테스트 (stub 모듈 주입).

외부 서버/벡터DB/임베딩 API 없이, OneRAG의 단일 테넌트 업로드 API를
주입된 stub 모듈로 구동해 상태 전이를 검증한다:

    upload_document  -> 잡 생성(pending) + BackgroundTask 1건 등록
    process_queued_upload_job_once -> 워커가 잡 1건 처리(completed)
    get_upload_status -> completed, chunk_count 일치
    list_documents   -> total_count == 1, 경로 누수 없음
    delete_document  -> 목록 비워짐 + 보관 원본 파일 제거

왜 필요한가(범용 가치):
- 업로드 파이프라인의 모듈 계약(document_processor/retrieval 메서드 시그니처)과
  상태 전이가 깨지는 퇴행을 외부 의존성 0으로 잡는 결정론적 스모크.
- 경로 누수 가드(tmp_path가 응답 JSON에 노출되지 않음)는 도메인 무관하게 유용.

JapanRAG 원본 대비 일반화(제거/치환):
- 멀티테넌트(company_id), get_document_source_detail, extraction_summary,
  document_ledger, 일본어 골든 텍스트 등 JapanRAG 전용 가정 전부 제거.
- OneRAG retrieval/document_processor 시그니처에 맞춤
  (add_documents는 company_id 없음, 임베딩은 embed_chunks_parallel 사용).
- 픽스처 텍스트는 언어 중립 영어 문장으로 작성.

마커: integration(in-process 워커/SQLite를 구동하므로 unit 게이트에서 제외).
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import pytest
from fastapi import BackgroundTasks, UploadFile
from starlette.datastructures import Headers

from app.api import upload

pytestmark = [pytest.mark.integration]

# OneRAG document_processor가 반환하는 LangChain Document를 흉내내기 위한 최소 구조.
# 실제 langchain_core import를 피해 의존성을 늘리지 않는다(strict-signature 유지).


class _StubDocument:
    """page_content/metadata만 가진 최소 Document 스텁."""

    def __init__(self, page_content: str, metadata: dict[str, Any]) -> None:
        self.page_content = page_content
        self.metadata = metadata


class SmokeDocumentProcessor:
    """업로드 파이프라인이 호출하는 document_processor 계약을 구현한 stub.

    OneRAG process_document_background 가 호출하는 메서드:
    load_document(file_path, metadata) -> split_documents(docs) -> embed_chunks_parallel(chunks)
    """

    def __init__(self, page_contents: list[str]) -> None:
        self._page_contents = page_contents

    async def load_document(
        self, file_path: str, metadata: dict[str, Any]
    ) -> list[_StubDocument]:
        documents: list[_StubDocument] = []
        for index, content in enumerate(self._page_contents):
            documents.append(
                _StubDocument(
                    page_content=content,
                    metadata={
                        "document_id": metadata["document_id"],
                        "source_file": metadata["source_file"],
                        "page_number": index + 1,
                        "page_index": index,
                    },
                )
            )
        return documents

    async def split_documents(
        self, docs: list[_StubDocument]
    ) -> list[_StubDocument]:
        # 스모크에서는 분할 없이 페이지=청크 1:1로 둔다(상태 전이 검증이 목적).
        return docs

    async def embed_chunks_parallel(
        self, chunks: list[_StubDocument]
    ) -> list[dict[str, Any]]:
        embedded: list[dict[str, Any]] = []
        for index, chunk in enumerate(chunks):
            metadata = dict(chunk.metadata)
            metadata["chunk_index"] = index
            embedded.append(
                {
                    "id": f"vector-{index}",
                    "content": chunk.page_content,
                    "embedding": [0.1, 0.2, 0.3],
                    "metadata": metadata,
                }
            )
        return embedded


class SmokeRetrieval:
    """업로드 파이프라인이 호출하는 retrieval 계약을 구현한 stub (단일 테넌트).

    OneRAG는 add_documents/list_documents/delete_document를 company_id 없이 호출한다.
    """

    def __init__(self) -> None:
        # document_id -> 청크 리스트
        self._chunks: dict[str, list[dict[str, Any]]] = {}

    async def add_documents(self, documents: list[dict[str, Any]]) -> dict[str, Any]:
        for document in documents:
            metadata = dict(document.get("metadata") or {})
            document_id = str(metadata["document_id"])
            self._chunks.setdefault(document_id, []).append(
                {
                    "id": document.get("id"),
                    "content": document.get("content"),
                    "metadata": metadata,
                }
            )
        return {
            "success_count": len(documents),
            "error_count": 0,
            "total_count": len(documents),
            "errors": [],
        }

    async def delete_document(self, document_id: str) -> bool:
        return self._chunks.pop(document_id, None) is not None

    async def list_documents(
        self, page: int = 1, page_size: int = 20
    ) -> dict[str, Any]:
        documents = [
            {
                "id": document_id,
                "filename": chunks[0]["metadata"].get("source_file", "document.txt"),
                "file_type": "txt",
                "file_size": 1,
                "chunk_count": len(chunks),
                "upload_date": 1,
            }
            for document_id, chunks in self._chunks.items()
        ]
        start = max(page - 1, 0) * page_size
        return {
            "documents": documents[start : start + page_size],
            "total_count": len(documents),
        }


def _reset_upload_module_state(fixture_dir: Path) -> None:
    """upload 모듈의 전역 상태를 tmp_path 기반으로 초기화한다.

    SQLite 잡 스토어 + 로컬 원본 보관을 사용하므로 외부 의존성이 없다.
    """
    upload.config = {
        "uploads": {
            "directory": str(fixture_dir / "uploads"),
            "job_store": {
                "type": "sqlite",
                "database_path": str(fixture_dir / "upload_jobs.sqlite3"),
            },
        },
        "privacy": {"enabled": False},
    }
    upload.modules = {
        "document_processor": SmokeDocumentProcessor(
            ["Invoice total is 1000.", "Payment is due on 2026-05-31."]
        ),
        "retrieval": SmokeRetrieval(),
    }
    # 캐시/시그니처를 초기화해 새 SQLite 경로가 적용되도록 한다.
    upload.upload_jobs = {}
    upload._upload_job_store = None
    upload._upload_job_store_signature = None
    # PII 마스킹 비활성화(파일명 변형 방지).
    upload._privacy_masker = None


@pytest.mark.asyncio
@pytest.mark.timeout(30)
async def test_local_upload_worker_status_list_delete_smoke(tmp_path: Path) -> None:
    """업로드 -> 워커 -> 상태 -> 목록 -> 삭제 상태 전이를 인프로세스로 검증."""
    fixture_dir = tmp_path / "smoke"
    _reset_upload_module_state(fixture_dir)
    expected_chunk_count = 2  # 페이지 2개 = 청크 2개

    background_tasks = BackgroundTasks()
    response = await upload.upload_document(
        background_tasks,
        file=UploadFile(
            file=io.BytesIO(b"%PDF-1.4\n% local smoke\n"),
            filename="sample.pdf",
            headers=Headers({"content-type": "application/pdf"}),
        ),
        metadata='{"smoke": "local_upload_flow"}',
    )

    # 업로드 직후: 잡이 pending이고 백그라운드 처리 태스크 1건이 등록되어야 한다.
    assert len(background_tasks.tasks) == 1
    assert upload.upload_jobs[response.job_id]["status"] == "pending"

    # 워커가 대기 잡 1건을 처리해 completed로 전이시킨다.
    worker_result = await upload.process_queued_upload_job_once(worker_id="smoke-worker")
    assert worker_result["processed"] is True
    assert worker_result["job_id"] == response.job_id
    assert worker_result["status"] == "completed"

    # 상태 조회: completed + 청크 수 일치.
    status = await upload.get_upload_status(response.job_id)
    assert status.status == "completed"
    assert status.chunk_count == expected_chunk_count

    # 목록 조회: 문서 1건, 경로 누수 없음(도메인 무관 가드).
    listed = await upload.list_documents()
    assert listed.total_count == 1
    assert listed.documents[0].id == response.job_id
    assert listed.documents[0].filename == "sample.pdf"
    assert str(tmp_path) not in listed.model_dump_json()

    # 보관 원본 파일이 실제로 디스크에 존재하는지 확인 후 삭제로 정리되는지 검증.
    original_path_value = upload.upload_jobs[response.job_id].get("original_file_path")
    assert original_path_value, "로컬 백엔드는 보관 원본 경로를 반환해야 함"
    original_path = Path(original_path_value)
    assert original_path.exists()

    delete_response = await upload.delete_document(response.job_id)
    assert delete_response["document_id"] == response.job_id

    # 삭제 후: 목록 비워짐 + 보관 원본 제거.
    assert (await upload.list_documents()).total_count == 0
    assert not original_path.exists()
