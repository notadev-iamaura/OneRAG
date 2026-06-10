"""
Upload API endpoints
파일 업로드 및 문서 처리 API 엔드포인트
"""

import asyncio
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ..lib.auth import get_api_key
from ..lib.logger import get_logger
from ..modules.core.privacy.masker import DEFAULT_WHITELIST, PrivacyMasker
from .upload_job_store import (
    JsonUploadJobStore,
    PostgresUploadJobStore,
    SQLiteUploadJobStore,
    UploadJobStore,
)

logger = get_logger(__name__)

# PII 마스킹을 위한 인스턴스 (privacy.enabled 체크 후 초기화)
# DEFAULT_WHITELIST 사용 (오탐 방지: 이모님, 헬퍼님, 담당 등)
# Note: DI Container 외부에서 사용하므로 기본 화이트리스트 직접 지정
_privacy_masker: PrivacyMasker | None = PrivacyMasker(whitelist=list(DEFAULT_WHITELIST))
# ✅ H4 보안 패치: Upload API 인증 추가
# 파일 업로드/삭제는 시스템 변경이므로 인증 필요
router = APIRouter(tags=["Upload"], dependencies=[Depends(get_api_key)])
modules: dict[str, Any] = {}
config: dict[str, Any] = {}


def set_dependencies(app_modules: dict[str, Any], app_config: dict[str, Any]):
    """의존성 주입"""
    global modules, config, _privacy_masker
    modules = app_modules
    config = app_config

    # privacy.enabled: false → PII 마스킹 비활성화
    privacy_config = config.get("privacy", {})
    if not privacy_config.get("enabled", True):
        _privacy_masker = None
        logger.info("🔓 Upload API: PII 마스킹 비활성화됨 (privacy.enabled: false)")


JOBS_FILE = Path("/app/uploads/jobs.json")
JOBS_DB_FILE = Path("./uploads/upload_jobs.sqlite3")
DEFAULT_UPLOAD_JOB_RETENTION_SECONDS = 24 * 60 * 60
TERMINAL_UPLOAD_JOB_STATUSES = {"completed", "failed", "cancelled"}
POSTGRES_UPLOAD_JOB_STORE_TYPES = {"postgres", "postgresql", "cloudsql", "cloud_sql"}

# 스토어 인스턴스 캐시: 설정 시그니처가 바뀌면 재생성한다.
_upload_job_store: UploadJobStore | None = None
_upload_job_store_signature: tuple[str, str] | None = None


def _resolve_upload_job_store() -> UploadJobStore:
    """설정된 업로드 잡 스토어를 해석한다.

    기본값은 SQLite로, 프로세스 재시작에도 잡 상태가 보존된다(의존성 0).
    JSON은 명시적 로컬 개발용 폴백, Postgres는 멀티워커/오토스케일 공유용이다.
    """
    global _upload_job_store, _upload_job_store_signature
    upload_config = config.get("uploads", {}) if isinstance(config, dict) else {}
    store_config = upload_config.get("job_store", {}) if isinstance(upload_config, dict) else {}
    if not isinstance(store_config, dict):
        store_config = {}
    store_type = _upload_job_store_type(store_config=store_config)
    if store_type in {"json", "file"}:
        path_value = (
            os.getenv("ONERAG_UPLOAD_JOBS_FILE")
            or store_config.get("path")
            or store_config.get("file_path")
            or str(JOBS_FILE)
        )
        path = Path(str(path_value)).expanduser().resolve()
        signature = ("json", str(path))
        if _upload_job_store is None or _upload_job_store_signature != signature:
            _upload_job_store = JsonUploadJobStore(path)
            _upload_job_store_signature = signature
        return _upload_job_store
    if store_type in POSTGRES_UPLOAD_JOB_STORE_TYPES:
        database_url = (
            os.getenv("ONERAG_UPLOAD_JOB_DATABASE_URL")
            or store_config.get("database_url")
            or store_config.get("url")
            or os.getenv("DATABASE_URL")
        )
        signature = ("postgres", str(bool(database_url)))
        if _upload_job_store is None or _upload_job_store_signature != signature:
            _upload_job_store = PostgresUploadJobStore(str(database_url) if database_url else None)
            _upload_job_store_signature = signature
        return _upload_job_store
    if store_type not in {"sqlite", "sqlite3"}:
        logger.warning(f"Unknown upload job store type '{store_type}'; falling back to sqlite")
    upload_dir = Path(str(upload_config.get("directory", "./uploads"))).expanduser().resolve()
    path_value = (
        os.getenv("ONERAG_UPLOAD_JOB_DB_PATH")
        or store_config.get("path")
        or store_config.get("database_path")
        or str(upload_dir / JOBS_DB_FILE.name)
    )
    path = Path(str(path_value)).expanduser().resolve()
    signature = ("sqlite", str(path))
    if _upload_job_store is None or _upload_job_store_signature != signature:
        _upload_job_store = SQLiteUploadJobStore(path)
        _upload_job_store_signature = signature
    return _upload_job_store


def _upload_job_store_type(*, store_config: dict[str, Any] | None = None) -> str:
    """업로드 잡 스토어 타입을 해석한다 (env > config > 기본 sqlite)."""
    if store_config is None:
        upload_config = config.get("uploads", {}) if isinstance(config, dict) else {}
        store_config = upload_config.get("job_store", {}) if isinstance(upload_config, dict) else {}
        if not isinstance(store_config, dict):
            store_config = {}
    return str(
        os.getenv("ONERAG_UPLOAD_JOB_STORE")
        or store_config.get("type")
        or "sqlite"
    ).strip().lower()


def _is_shared_upload_job_store() -> bool:
    """여러 인스턴스가 공유하는(Postgres) 스토어인지 여부."""
    return _upload_job_store_type() in POSTGRES_UPLOAD_JOB_STORE_TYPES


def _upload_job_store_fail_closed() -> bool:
    """공유 스토어 장애 시 예외를 전파(fail-closed)할지 여부.

    공유 스토어에서 조용히 빈 결과로 폴백하면 다른 인스턴스의 잡이
    유실된 것처럼 보이므로, 테스트 환경이 아니면 기본 fail-closed.
    """
    if not _is_shared_upload_job_store():
        return False
    environment = str(os.getenv("ENVIRONMENT") or config.get("environment") or "").lower()
    if environment == "test":
        return False
    return str(os.getenv("ONERAG_UPLOAD_JOB_STORE_FAIL_OPEN") or "").lower() not in {
        "1",
        "true",
        "yes",
    }


def _upload_job_retention_seconds() -> int:
    """종결(terminal) 잡의 보존 시간(초)을 해석한다."""
    upload_config = config.get("uploads", {}) if isinstance(config, dict) else {}
    store_config = upload_config.get("job_store", {}) if isinstance(upload_config, dict) else {}
    if not isinstance(store_config, dict):
        store_config = {}
    raw_value = (
        os.getenv("ONERAG_UPLOAD_JOB_RETENTION_SECONDS")
        or store_config.get("retention_seconds")
        or DEFAULT_UPLOAD_JOB_RETENTION_SECONDS
    )
    try:
        return max(0, int(raw_value))
    except (TypeError, ValueError):
        logger.warning(
            f"Invalid upload job retention value '{raw_value}'; using default "
            f"{DEFAULT_UPLOAD_JOB_RETENTION_SECONDS}s"
        )
        return DEFAULT_UPLOAD_JOB_RETENTION_SECONDS


def _coerce_job_timestamp(value: Any) -> float | None:
    """잡 타임스탬프(epoch 숫자/ISO 문자열)를 epoch float로 정규화한다."""
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str) and value.strip():
        try:
            normalized = value.replace("Z", "+00:00")
            return datetime.fromisoformat(normalized).timestamp()
        except ValueError:
            try:
                return float(value)
            except ValueError:
                return None
    return None


def _terminal_job_timestamp(job: dict[str, Any]) -> float | None:
    """종결 잡의 종료 시각을 추정한다 (보존 만료 판정용)."""
    for key in ("completed_at", "failed_at", "cancelled_at", "updated_at"):
        timestamp = _coerce_job_timestamp(job.get(key))
        if timestamp is not None:
            return timestamp
    start_time = _coerce_job_timestamp(job.get("start_time"))
    processing_time = _coerce_job_timestamp(job.get("processing_time"))
    if start_time is not None and processing_time is not None:
        return start_time + processing_time
    return start_time


def cleanup_upload_jobs(
    jobs: dict[str, dict[str, Any]],
    *,
    now: float | None = None,
    retention_seconds: int | None = None,
) -> int:
    """보존 기간이 지난 종결(terminal) 잡을 메모리 맵에서 제거한다."""
    retention = _upload_job_retention_seconds() if retention_seconds is None else retention_seconds
    if retention <= 0:
        return 0
    now_timestamp = datetime.now().timestamp() if now is None else now
    expired_job_ids: list[str] = []
    for job_id, job in jobs.items():
        if job.get("status") not in TERMINAL_UPLOAD_JOB_STATUSES:
            continue
        terminal_timestamp = _terminal_job_timestamp(job)
        if terminal_timestamp is None:
            continue
        if now_timestamp - terminal_timestamp >= retention:
            expired_job_ids.append(job_id)
    for job_id in expired_job_ids:
        del jobs[job_id]
    if expired_job_ids:
        logger.info(f"Cleaned up {len(expired_job_ids)} expired upload jobs")
    return len(expired_job_ids)


def load_upload_jobs() -> dict[str, dict[str, Any]]:
    """업로드 작업 상태를 durable store에서 로드"""
    try:
        store = _resolve_upload_job_store()
        if _is_shared_upload_job_store():
            cleanup_expired = getattr(store, "cleanup_expired", None)
            if callable(cleanup_expired):
                cleanup_expired(retention_seconds=_upload_job_retention_seconds())
        jobs = store.load_all()
        if cleanup_upload_jobs(jobs) and not _is_shared_upload_job_store():
            store.save_all(jobs)
        return jobs
    except Exception as e:
        logger.warning(f"Failed to load upload jobs: {e}")
        if _upload_job_store_fail_closed():
            raise
    return {}


def save_upload_jobs(jobs: dict[str, dict[str, Any]]):
    """업로드 작업 상태를 durable store에 저장"""
    try:
        if _is_shared_upload_job_store():
            # 오토스케일 환경에서 인스턴스 로컬 맵 전체 저장은 다른 인스턴스의
            # 잡을 덮어쓸 수 있으므로 공유 스토어에서는 per-job 저장만 허용한다.
            raise RuntimeError("Full-map upload job saves are disabled for shared job stores")
        cleanup_upload_jobs(jobs)
        _resolve_upload_job_store().save_all(jobs)
    except Exception as e:
        logger.error(f"Failed to save upload jobs: {e}")
        if _upload_job_store_fail_closed():
            raise


def save_upload_job(job_id: str) -> None:
    """단일 잡만 저장한다 (공유 스토어에서 무관한 행 덮어쓰기 방지)."""
    job = upload_jobs.get(job_id)
    if not isinstance(job, dict):
        return
    if _is_shared_upload_job_store():
        try:
            _resolve_upload_job_store().save_all({job_id: job})
        except Exception as e:
            logger.error(f"Failed to save upload job {job_id}: {e}")
            if _upload_job_store_fail_closed():
                raise
        return
    save_upload_jobs(upload_jobs)


def delete_upload_job(job_id: str) -> None:
    """잡 1건을 스토어에서 삭제한다 (공유 스토어는 행 단위 삭제)."""
    if _is_shared_upload_job_store():
        try:
            store = _resolve_upload_job_store()
            delete = getattr(store, "delete", None)
            if callable(delete):
                delete(job_id)
        except Exception as e:
            logger.error(f"Failed to delete upload job {job_id}: {e}")
            if _upload_job_store_fail_closed():
                raise
        return
    save_upload_jobs(upload_jobs)


def _reload_upload_jobs_if_needed(job_id: str | None = None) -> None:
    """공유 스토어 사용 시 또는 캐시 미스 시 프로세스 로컬 잡 캐시를 갱신한다."""
    global upload_jobs
    if _is_shared_upload_job_store() or (job_id is not None and job_id not in upload_jobs):
        loaded_jobs = load_upload_jobs()
        if _is_shared_upload_job_store() or job_id is None or job_id in loaded_jobs:
            upload_jobs = loaded_jobs


def _shared_upload_worker_lease_seconds() -> int:
    """공유 스토어 워커의 잡 lease 시간(초)을 해석한다."""
    raw_value = os.getenv("ONERAG_UPLOAD_JOB_WORKER_LEASE_SECONDS") or "7200"
    try:
        return max(300, int(raw_value))
    except (TypeError, ValueError):
        logger.warning(
            "Invalid ONERAG_UPLOAD_JOB_WORKER_LEASE_SECONDS value '%s'; using 7200s",
            raw_value,
        )
        return 7200


def _initial_upload_jobs() -> dict[str, dict[str, Any]]:
    """모듈 import 시점의 초기 잡 맵을 로드한다.

    공유(Postgres) 스토어는 import 시점에 DB 연결을 만들지 않도록 건너뛴다.
    """
    if _is_shared_upload_job_store():
        logger.info("Skipping import-time shared upload job load")
        return {}
    return load_upload_jobs()


upload_jobs: dict[str, dict[str, Any]] = _initial_upload_jobs()


class DocumentInfo(BaseModel):
    """문서 정보 모델"""

    id: str
    filename: str
    file_type: str
    file_size: int
    upload_date: str
    status: str
    chunk_count: int | None = None
    processing_time: float | None = None
    error_message: str | None = None


class UploadResponse(BaseModel):
    """업로드 응답 모델"""

    job_id: str
    message: str
    filename: str
    file_size: int
    estimated_processing_time: float
    timestamp: str


class JobStatusResponse(BaseModel):
    """작업 상태 응답 모델"""

    job_id: str
    status: str
    progress: float
    message: str
    filename: str
    chunk_count: int | None = None
    processing_time: float | None = None
    error_message: str | None = None
    timestamp: str


class DocumentListResponse(BaseModel):
    """문서 목록 응답 모델"""

    documents: list[DocumentInfo]
    total_count: int
    page: int
    page_size: int
    has_next: bool


class BulkDeleteRequest(BaseModel):
    """벌크 삭제 요청 모델"""

    ids: list[str] = Field(..., description="삭제할 문서 ID 목록")


class BulkDeleteResponse(BaseModel):
    """벌크 삭제 응답 모델"""

    deleted_count: int
    failed_count: int
    failed_ids: list[str] = []
    message: str
    timestamp: str


def get_upload_directory() -> Path:
    """업로드 디렉토리 반환"""
    upload_path = config.get("uploads", {}).get("directory", "./uploads")
    upload_dir = Path(upload_path).resolve()
    try:
        upload_dir.mkdir(exist_ok=True, parents=True)
        temp_dir = upload_dir / "temp"
        temp_dir.mkdir(exist_ok=True)
    except PermissionError:
        upload_dir = Path("/app/uploads")
        upload_dir.mkdir(exist_ok=True, parents=True)
        temp_dir = upload_dir / "temp"
        temp_dir.mkdir(exist_ok=True)
    return upload_dir


def estimate_processing_time(file_size: int, file_type: str) -> float:
    """파일 크기와 타입을 기반으로 처리 시간 예측"""
    base_time = 20.0
    size_mb = file_size / (1024 * 1024)
    processing_rates = {
        "pdf": 15.0,
        "docx": 10.0,
        "pptx": 12.0,
        "xlsx": 20.0,
        "txt": 3.0,
        "md": 3.0,
        "html": 8.0,
        "csv": 12.0,
        "json": 5.0,
    }
    ext = file_type.lower()
    rate = processing_rates.get(ext, 10.0)
    estimated_time = base_time + size_mb * rate
    if size_mb > 10:
        extra_penalty = (size_mb - 10) * 3
        estimated_time += extra_penalty
    return max(30.0, min(estimated_time, 1800.0))


def _document_processing_timeout_seconds() -> float:
    """백그라운드 문서 처리의 최대 허용 시간(초)을 반환한다.

    BackgroundTasks 처리에는 본래 상한이 없어, 처리가 지연되면
    프론트 polling 한도(약 30분)를 넘겨 좀비 작업으로 남는다. 이 값을 프론트
    polling보다 짧게(기본 25분) 두어 백엔드가 먼저 명시적으로 실패시킨다.

    우선순위: uploads.processing_timeout_seconds(config) >
    ONERAG_UPLOAD_PROCESSING_TIMEOUT_SECONDS(env) > 기본 1500초.
    """
    upload_config = config.get("uploads", {}) if isinstance(config, dict) else {}
    raw: Any = upload_config.get("processing_timeout_seconds")
    if raw is None:
        raw = os.getenv("ONERAG_UPLOAD_PROCESSING_TIMEOUT_SECONDS")
    try:
        value = float(raw) if raw is not None else 1500.0
    except (TypeError, ValueError):
        logger.warning(
            "Invalid upload processing timeout %r; falling back to 1500s", raw
        )
        value = 1500.0
    # 최소 60초 보장(과도하게 짧은 설정으로 정상 처리가 끊기는 것 방지).
    return max(60.0, value)


def validate_file(file: UploadFile) -> dict[str, Any]:
    """파일 검증"""
    supported_types = {
        "application/pdf": "pdf",
        "text/plain": "txt",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation": "pptx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
        "text/csv": "csv",
        "text/html": "html",
        "text/markdown": "md",
        "application/json": "json",
    }
    if file.content_type not in supported_types:
        ext = Path(file.filename or "unknown").suffix.lower()[1:]
        if ext not in supported_types.values():
            return {
                "valid": False,
                "error": {
                    "error": "지원하지 않는 파일 형식",
                    "message": f"'{file.content_type}' 형식은 지원되지 않습니다",
                    "suggestion": "지원 형식: PDF, DOCX, PPTX, TXT, MD, CSV, XLSX, HTML, JSON",
                    "file_name": file.filename,
                    "file_type": file.content_type,
                    "supported_extensions": [
                        ".pdf",
                        ".docx",
                        ".pptx",
                        ".txt",
                        ".md",
                        ".csv",
                        ".xlsx",
                        ".html",
                        ".json",
                    ],
                },
            }
        file_type = ext
    else:
        file_type = supported_types[file.content_type]
    max_size = config.get("uploads", {}).get("max_file_size", 50 * 1024 * 1024)
    if file.size and file.size > max_size:
        max_size_mb = max_size / (1024 * 1024)
        file_size_mb = file.size / (1024 * 1024)
        return {
            "valid": False,
            "error": {
                "error": "파일 크기 초과",
                "message": f"파일 크기({file_size_mb:.1f}MB)가 최대 허용 크기({max_size_mb:.0f}MB)를 초과했습니다",
                "suggestion": "파일을 압축하거나 여러 파일로 분할하여 업로드하세요",
                "file_name": file.filename,
                "file_size_mb": round(file_size_mb, 1),
                "max_size_mb": int(max_size_mb),
            },
        }
    return {"valid": True, "file_type": file_type}


async def process_document_background(job_id: str, file_path: Path, filename: str, file_type: str):
    """백그라운드 문서 처리"""
    try:
        upload_jobs[job_id].update(
            {"status": "processing", "progress": 10, "message": "문서 처리 시작..."}
        )
        save_upload_job(job_id)
        document_processor = modules.get("document_processor")
        retrieval_module = modules.get("retrieval")
        if not document_processor or not retrieval_module:
            raise Exception("Required modules not available")
        # 일부 DI 구성(예: chroma)에서 retrieval 모듈이 코루틴/Future로 지연 제공되므로,
        # add_documents 호출 전에 실제 모듈로 해소한다('_asyncio.Future' has no attribute 방지).
        if asyncio.iscoroutine(retrieval_module) or isinstance(retrieval_module, asyncio.Future):
            retrieval_module = await retrieval_module
        logger.info(f"Loading document: {filename}")
        upload_jobs[job_id].update({"progress": 30, "message": "문서 로딩 중..."})
        save_upload_job(job_id)
        file_size = file_path.stat().st_size

        # PII 마스킹: 파일명에서 개인정보 마스킹 (활성화 시에만)
        # 예: "홍길동 고객님.txt" → "고객_고객님.txt"
        if _privacy_masker:
            masked_filename = _privacy_masker.mask_filename(filename)
            if masked_filename != filename:
                logger.info(f"파일명 PII 마스킹 적용: {filename} → {masked_filename}")
        else:
            masked_filename = filename  # PII 마스킹 비활성화 시 원본 사용

        docs = await document_processor.load_document(
            str(file_path),
            {
                "document_id": job_id,
                "source_file": masked_filename,
                "file_type": file_type,
                "original_file_size": file_size,
            },
        )
        logger.info(f"Splitting document into chunks: {len(docs)} documents")
        upload_jobs[job_id].update({"progress": 50, "message": "문서 분할 중..."})
        save_upload_job(job_id)
        chunks = await document_processor.split_documents(docs)
        logger.info(f"Document split into {len(chunks)} chunks")
        upload_jobs[job_id].update(
            {"progress": 70, "message": f"임베딩 생성 중... ({len(chunks)}개 청크)"}
        )
        save_upload_job(job_id)
        # 병렬 임베딩 사용: 청크를 워커별로 분할해 동시 임베딩한다.
        # 대용량 PDF(수백~수천 청크)에서 직렬 embed_chunks 대비 처리 시간을 단축해
        # 프론트엔드 polling 한도 내 완료 가능성을 높인다 (순서 보장됨).
        embedded_chunks = await document_processor.embed_chunks_parallel(chunks)
        upload_jobs[job_id].update(
            {"progress": 90, "message": f"벡터 DB에 저장 중... ({len(embedded_chunks)}개 임베딩)"}
        )
        save_upload_job(job_id)
        index_result = await retrieval_module.add_documents(embedded_chunks)
        if isinstance(index_result, dict):
            success_count = int(index_result.get("success_count", 0))
            error_count = int(index_result.get("error_count", 0))
            total_count = int(index_result.get("total_count", len(embedded_chunks)))
            if error_count > 0 or success_count != total_count:
                if success_count > 0 and hasattr(retrieval_module, "delete_document"):
                    try:
                        await retrieval_module.delete_document(job_id)
                    except Exception as cleanup_error:
                        logger.warning(
                            f"Partial upload cleanup failed for job_id={job_id}: {cleanup_error}"
                        )
                errors = index_result.get("errors") or ["unknown error"]
                first_error = errors[0] if isinstance(errors, list) else str(errors)
                raise RuntimeError(
                    "Vector DB 저장 실패: "
                    f"성공 {success_count}/{total_count}, 실패 {error_count}. "
                    f"첫 번째 오류: {first_error}"
                )
        elif isinstance(index_result, int) and index_result != len(embedded_chunks):
            raise RuntimeError(
                "Vector DB 저장 실패: "
                f"성공 {index_result}/{len(embedded_chunks)}, 실패 {len(embedded_chunks) - index_result}"
            )
        try:
            os.unlink(file_path)
        except Exception as e:
            logger.warning(f"Failed to delete temp file: {e}")
        processing_time = datetime.now().timestamp() - upload_jobs[job_id]["start_time"]
        upload_jobs[job_id].update(
            {
                "status": "completed",
                "progress": 100,
                "message": "문서 처리 완료",
                "chunk_count": len(chunks),
                "processing_time": processing_time,
            }
        )
        save_upload_job(job_id)
        logger.info(
            f"Document processing completed: {filename}, {len(chunks)} chunks, {processing_time:.2f}s"
        )
    except Exception as error:
        logger.error(f"Document processing failed: {error}")
        upload_jobs[job_id].update(
            {
                "status": "failed",
                "progress": 0,
                "message": "문서 처리 실패",
                "error_message": str(error),
            }
        )
        save_upload_job(job_id)
        try:
            if file_path.exists():
                os.unlink(file_path)
        except Exception:
            pass


async def _finalize_upload_job_timed_out(
    *,
    job_id: str,
    file_path: Path,
    timeout_seconds: float,
) -> None:
    """처리 타임아웃 시 job을 failed로 표시하고 임시파일/부분 벡터를 정리한다.

    wait_for가 처리를 CancelledError로 중단하면 process_document_background의
    정상 정리 경로가 실행되지 않으므로, 여기서 명시적으로 마무리한다.
    """
    logger.error(
        "Document processing timed out after %.0fs: job_id=%s", timeout_seconds, job_id
    )
    # 부분 적재된 벡터 정리(best-effort): 타임아웃 시점에 일부 청크만 적재됐을 수 있다.
    try:
        retrieval_module = modules.get("retrieval")
        # 일부 DI 구성(예: chroma)에서 retrieval 모듈이 코루틴/Future로 지연 제공됨
        if asyncio.iscoroutine(retrieval_module) or isinstance(retrieval_module, asyncio.Future):
            retrieval_module = await retrieval_module
        if retrieval_module is not None and hasattr(retrieval_module, "delete_document"):
            await retrieval_module.delete_document(job_id)
    except Exception as cleanup_error:
        logger.warning(
            "Timed-out upload vector cleanup failed for job_id=%s: %s",
            job_id,
            cleanup_error,
        )
    job = upload_jobs.get(job_id)
    if isinstance(job, dict):
        job.update(
            {
                "status": "failed",
                "progress": 0,
                "message": "문서 처리 시간 초과",
                "error_message": (
                    "문서 처리가 제한 시간을 초과했습니다. 파일을 더 작게 분할해 "
                    "다시 시도하세요."
                ),
                "internal_error_message": (
                    f"processing timed out after {timeout_seconds:.0f}s"
                ),
                "failed_at": datetime.now().isoformat(),
                "retry_safe": True,
            }
        )
        save_upload_job(job_id)
    try:
        if file_path.exists():
            os.unlink(file_path)
    except Exception:
        pass


async def process_document_background_guarded(
    job_id: str,
    file_path: Path,
    filename: str,
    file_type: str,
) -> None:
    """타임아웃 가드를 적용해 백그라운드 문서 처리를 실행한다.

    전체 처리를 wait_for로 감싸 제한 시간을 초과하면 처리를 중단하고 job을
    명시적으로 failed 처리한다(좀비 작업 방지). 정상 처리는 그대로 통과한다.
    """
    timeout_seconds = _document_processing_timeout_seconds()
    try:
        await asyncio.wait_for(
            process_document_background(job_id, file_path, filename, file_type),
            timeout=timeout_seconds,
        )
    except TimeoutError:
        await _finalize_upload_job_timed_out(
            job_id=job_id,
            file_path=file_path,
            timeout_seconds=timeout_seconds,
        )


async def process_queued_upload_job_once(worker_id: str = "local-worker") -> dict[str, Any]:
    """대기 중인 업로드 잡 1건을 처리한다 (워커 진입점).

    FastAPI는 보통 BackgroundTasks로 process_document_background를 실행하지만,
    공유(Postgres) 스토어 멀티워커 구성·로컬 smoke 테스트에서는 이 진입점이
    같은 단일 잡 워커 역할을 한다(업로드 API 계약 불변).
    """
    global upload_jobs
    if _is_shared_upload_job_store():
        store = _resolve_upload_job_store()
        lease_seconds = _shared_upload_worker_lease_seconds()
        # 만료된 lease의 잡을 큐로 복구한 뒤, 원자적으로 다음 잡을 확보한다.
        recover_stale = getattr(store, "recover_stale", None)
        if callable(recover_stale):
            recover_stale()
        claim_next = getattr(store, "claim_next", None)
        if not callable(claim_next):
            return {"processed": False, "job_id": None, "status": "claim_unavailable"}
        job = claim_next(worker_id=worker_id, lease_seconds=lease_seconds)
        if not isinstance(job, dict):
            return {"processed": False, "job_id": None, "status": "empty"}
        job_id = str(job["job_id"])
        processing_attempt_id = str(job.get("processing_attempt_id") or uuid4())
        update_claimed_job = getattr(store, "update_claimed_job", None)
        if callable(update_claimed_job):
            updated_job = update_claimed_job(
                job_id=job_id,
                worker_id=worker_id,
                updates={"processing_attempt_id": processing_attempt_id},
                lease_seconds=lease_seconds,
            )
            if isinstance(updated_job, dict):
                job = updated_job
        job["processing_attempt_id"] = processing_attempt_id
        upload_jobs[job_id] = job
        await process_document_background(
            job_id,
            Path(str(job["temp_file_path"])),
            str(job.get("filename") or "unknown"),
            str(job["file_type"]),
        )
        _reload_upload_jobs_if_needed(job_id)
        return {
            "processed": True,
            "job_id": job_id,
            "status": upload_jobs.get(job_id, {}).get("status"),
        }

    # 로컬(SQLite/JSON) 스토어: 메모리 맵에서 가장 오래된 대기 잡을 처리한다.
    pending_jobs = sorted(
        (
            (job_id, job)
            for job_id, job in upload_jobs.items()
            if job.get("status") in {"pending", "queued", "retrying"}
        ),
        key=lambda item: (item[1].get("start_time") or 0, item[0]),
    )
    if not pending_jobs:
        return {"processed": False, "job_id": None, "status": "empty"}

    job_id, job = pending_jobs[0]
    processing_attempt_id = str(job.get("processing_attempt_id") or uuid4())
    job["processing_attempt_id"] = processing_attempt_id
    job["claimed_by"] = worker_id
    save_upload_job(job_id)

    await process_document_background(
        job_id,
        Path(str(job["temp_file_path"])),
        str(job.get("filename") or "unknown"),
        str(job["file_type"]),
    )
    return {
        "processed": True,
        "job_id": job_id,
        "status": upload_jobs.get(job_id, {}).get("status"),
    }


@router.post("/upload", response_model=UploadResponse)
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    metadata: str | None = Form(None),
):
    """문서 업로드"""
    try:
        validation = validate_file(file)
        if not validation["valid"]:
            raise HTTPException(status_code=400, detail=validation["error"])
        file_type = validation["file_type"]
        job_id = str(uuid4())
        upload_dir = get_upload_directory()
        temp_dir = upload_dir / "temp"
        safe_filename = Path(file.filename or "unknown").name
        if not safe_filename or safe_filename.startswith("."):
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "잘못된 파일명",
                    "message": "파일명이 유효하지 않습니다",
                    "suggestion": "올바른 파일명을 사용하여 다시 업로드하세요 (숨김 파일은 업로드할 수 없습니다)",
                    "file_name": file.filename,
                },
            )
        file_path = temp_dir / f"{job_id}_{safe_filename}"
        try:
            resolved_path = file_path.resolve()
            resolved_temp_dir = temp_dir.resolve()
            if not str(resolved_path).startswith(str(resolved_temp_dir)):
                logger.error(f"Path Traversal 시도 차단: {file.filename}")
                raise HTTPException(
                    status_code=400,
                    detail={
                        "error": "보안 검증 실패",
                        "message": "파일 경로에서 보안 위협이 감지되었습니다",
                        "suggestion": "파일명에 특수문자나 경로 문자(.., /)가 포함되지 않았는지 확인하세요",
                        "file_name": file.filename,
                    },
                )
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"파일 경로 검증 실패: {e}")
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "파일 경로 검증 실패",
                    "message": "파일 경로를 검증하는 중 오류가 발생했습니다",
                    "suggestion": "파일명에 특수문자가 포함되지 않았는지 확인하고 다시 시도하세요",
                    "file_name": file.filename,
                    "technical_error": str(e),
                },
            ) from e
        with open(file_path, "wb") as buffer:
            content = await file.read()
            buffer.write(content)
        file_size = len(content)
        filename = file.filename or "unknown"
        upload_jobs[job_id] = {
            "job_id": job_id,
            "filename": filename,
            "file_type": file_type,
            "file_size": file_size,
            "status": "pending",
            "progress": 0,
            "message": "업로드 완료, 처리 대기 중...",
            "start_time": datetime.now().timestamp(),
            "chunk_count": None,
            "processing_time": None,
            "error_message": None,
            # 워커 진입점(process_queued_upload_job_once)이 재처리할 수 있도록 기록
            "temp_file_path": str(file_path),
        }
        save_upload_job(job_id)
        background_tasks.add_task(
            process_document_background_guarded, job_id, file_path, filename, file_type
        )
        estimated_time = estimate_processing_time(file_size, file_type)
        logger.info(f"Document upload initiated: {file.filename}, job_id: {job_id}")
        size_mb = file_size / (1024 * 1024)
        if estimated_time > 60:
            time_msg = f"약 {estimated_time / 60:.1f}분"
        else:
            time_msg = f"약 {estimated_time:.0f}초"
        if size_mb > 10:
            warning_msg = (
                " ⚠️ 대용량 파일로 인해 처리 시간이 오래 걸릴 수 있습니다. 브라우저를 닫지 마세요."
            )
        else:
            warning_msg = ""
        user_message = f"파일 업로드 완료! 문서 처리 중입니다. 예상 시간: {time_msg} (파일 크기: {size_mb:.1f}MB){warning_msg}"
        return UploadResponse(
            job_id=job_id,
            message=user_message,
            filename=filename,
            file_size=file_size,
            estimated_processing_time=estimated_time,
            timestamp=datetime.now().isoformat(),
        )
    except HTTPException:
        raise
    except Exception as error:
        logger.error(f"Upload error: {error}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "error": "업로드 실패",
                "message": "파일 업로드 중 오류가 발생했습니다",
                "suggestion": "네트워크 연결을 확인하고 다시 시도하세요. 문제가 지속되면 관리자에게 문의하세요",
                "file_name": file.filename if file and hasattr(file, "filename") else None,
                "retry_after": 30,
                "technical_error": str(error),
            },
        ) from error


@router.get("/upload/status/{job_id}", response_model=JobStatusResponse)
async def get_upload_status(job_id: str):
    """업로드 작업 상태 조회"""
    # 공유 스토어 사용 시 다른 인스턴스의 갱신을 반영하고, 캐시 미스 시 재로드한다.
    _reload_upload_jobs_if_needed(job_id)
    if job_id not in upload_jobs:
        logger.warning(f"Job {job_id} not found even after reload")
        raise HTTPException(
            status_code=404,
            detail={
                "error": "작업을 찾을 수 없음",
                "message": "요청하신 업로드 작업을 찾을 수 없습니다",
                "suggestion": "서버가 재시작되었을 수 있습니다. 파일을 다시 업로드해주세요",
                "job_id": job_id,
                "retry_upload": True,
            },
        )
    job = upload_jobs[job_id]
    current_processing_time = None
    if job["status"] == "processing":
        current_processing_time = datetime.now().timestamp() - job["start_time"]
    logger.info(f"Job {job_id} status: {job['status']}, progress: {job['progress']}%")
    return JobStatusResponse(
        job_id=job_id,
        status=job["status"],
        progress=job["progress"],
        message=job["message"],
        filename=job["filename"],
        chunk_count=job["chunk_count"],
        processing_time=job["processing_time"] or current_processing_time,
        error_message=job["error_message"],
        timestamp=datetime.now().isoformat(),
    )


def _coerce_document_upload_date(value: Any) -> str:
    """문서 업로드 일시를 ISO 문자열로 정규화한다.

    - bool은 int의 하위 타입이라 epoch(1초)로 오인될 수 있으므로 먼저 배제한다.
    - 숫자 epoch은 UTC 기준으로 변환해 항상 시간대 정보를 부여한다(naive/aware 혼합 방지).
    - 파싱 불가능한 문자열은 원본을 그대로 두고, 후속 단계에서 안전하게 처리한다.
    """
    if isinstance(value, bool):
        return datetime.now(UTC).isoformat()
    if isinstance(value, int | float) and value > 0:
        return datetime.fromtimestamp(value, tz=UTC).isoformat()
    if isinstance(value, str) and value.strip():
        normalized = value.strip()
        try:
            return datetime.fromisoformat(normalized.replace("Z", "+00:00")).isoformat()
        except ValueError:
            return normalized
    return datetime.now(UTC).isoformat()


@router.get("/upload/documents", response_model=DocumentListResponse)
async def list_documents(page: int = 1, page_size: int = 20):
    """문서 목록 조회"""
    try:
        retrieval_module = modules.get("retrieval")
        if not retrieval_module:
            raise HTTPException(
                status_code=500,
                detail={
                    "error": "시스템 모듈 사용 불가",
                    "message": "문서 검색 모듈을 사용할 수 없습니다",
                    "suggestion": "서버 상태를 확인하고 관리자에게 문의하세요",
                    "module_name": "retrieval",
                    "retry_after": 60,
                },
            )
        logger.info(f"Listing documents: page={page}, page_size={page_size}")
        documents_data = await retrieval_module.list_documents(page=page, page_size=page_size)
        logger.info(f"Retrieved documents_data: {documents_data}")
        documents = []
        for doc_data in documents_data.get("documents", []):
            # upload_date가 누락/None/0 등 falsy면 created_at으로 폴백한다.
            # (dict.get의 기본값은 '키 부재'에만 적용되므로, 값이 None/0인 경우를 별도 처리)
            raw_upload_date = doc_data.get("upload_date")
            if not raw_upload_date:
                raw_upload_date = doc_data.get("created_at", 0)
            upload_date = _coerce_document_upload_date(raw_upload_date)
            documents.append(
                DocumentInfo(
                    id=doc_data.get("id", "unknown"),
                    filename=doc_data.get("filename", "unknown"),
                    file_type=doc_data.get("file_type", "unknown"),
                    file_size=doc_data.get("file_size", 0),
                    upload_date=upload_date,
                    status="completed",
                    chunk_count=doc_data.get("chunk_count", 0),
                )
            )
        total_count = documents_data.get("total_count", len(documents))
        response = DocumentListResponse(
            documents=documents,
            total_count=total_count,
            page=page,
            page_size=page_size,
            has_next=page * page_size < total_count,
        )
        logger.info(f"Returning response: {len(documents)} documents, total={total_count}")
        return response
    except HTTPException:
        raise
    except Exception as error:
        logger.error(f"List documents error: {error}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "error": "문서 목록 조회 실패",
                "message": "문서 목록을 불러오는 중 오류가 발생했습니다",
                "suggestion": "잠시 후 다시 시도하거나 관리자에게 문의하세요",
                "page": page,
                "page_size": page_size,
                "retry_after": 30,
                "technical_error": str(error),
            },
        ) from error


@router.delete("/upload/documents/{document_id}")
async def delete_document(document_id: str):
    """문서 삭제"""
    try:
        retrieval_module = modules.get("retrieval")
        if not retrieval_module:
            raise HTTPException(
                status_code=500,
                detail={
                    "error": "시스템 모듈 사용 불가",
                    "message": "문서 검색 모듈을 사용할 수 없습니다",
                    "suggestion": "서버 상태를 확인하고 관리자에게 문의하세요",
                    "module_name": "retrieval",
                    "retry_after": 60,
                },
            )
        await retrieval_module.delete_document(document_id)
        logger.info(f"Document deleted: {document_id}")
        return {
            "message": "Document deleted successfully",
            "document_id": document_id,
            "timestamp": datetime.now().isoformat(),
        }
    except HTTPException:
        raise
    except Exception as error:
        logger.error(f"Delete document error: {error}")
        raise HTTPException(
            status_code=500,
            detail={
                "error": "문서 삭제 실패",
                "message": "문서를 삭제하는 중 오류가 발생했습니다",
                "suggestion": "문서가 이미 삭제되었거나 접근 권한이 없을 수 있습니다. 다시 시도하거나 관리자에게 문의하세요",
                "document_id": document_id,
                "retry_after": 30,
                "technical_error": str(error),
            },
        ) from error


@router.post("/upload/documents/bulk-delete", response_model=BulkDeleteResponse)
async def bulk_delete_documents(request: BulkDeleteRequest):
    """문서 일괄 삭제"""
    try:
        retrieval_module = modules.get("retrieval")
        if not retrieval_module:
            raise HTTPException(
                status_code=500,
                detail={
                    "error": "시스템 모듈 사용 불가",
                    "message": "문서 검색 모듈을 사용할 수 없습니다",
                    "suggestion": "서버 상태를 확인하고 관리자에게 문의하세요",
                    "module_name": "retrieval",
                    "retry_after": 60,
                },
            )
        deleted_count = 0
        failed_count = 0
        failed_ids = []
        logger.info(f"Bulk delete requested for {len(request.ids)} documents: {request.ids}")
        for document_id in request.ids:
            try:
                if not document_id or document_id.strip() == "":
                    logger.warning(f"Skipping invalid document ID: {document_id}")
                    failed_count += 1
                    failed_ids.append(document_id)
                    continue
                await retrieval_module.delete_document(document_id)
                deleted_count += 1
                logger.info(f"Successfully deleted document: {document_id}")
            except Exception as delete_error:
                logger.error(f"Failed to delete document {document_id}: {delete_error}")
                failed_count += 1
                failed_ids.append(document_id)
        message = f"Bulk delete completed: {deleted_count} deleted, {failed_count} failed"
        logger.info(message)
        return BulkDeleteResponse(
            deleted_count=deleted_count,
            failed_count=failed_count,
            failed_ids=failed_ids,
            message=message,
            timestamp=datetime.now().isoformat(),
        )
    except HTTPException:
        raise
    except Exception as error:
        logger.error(f"Bulk delete error: {error}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "error": "일괄 삭제 실패",
                "message": "문서 일괄 삭제 중 오류가 발생했습니다",
                "suggestion": "네트워크 연결을 확인하고 다시 시도하거나 관리자에게 문의하세요",
                "requested_count": len(request.ids) if request and hasattr(request, "ids") else 0,
                "retry_after": 30,
                "technical_error": str(error),
            },
        ) from error


@router.get("/upload/documents/{document_id}/download")
async def download_document(document_id: str):
    """문서 다운로드 (벡터 DB에 저장된 청크 데이터를 텍스트로 재결합)

    원본 파일은 업로드 처리 후 삭제되므로,
    벡터 DB에 저장된 청크 내용을 결합하여 텍스트 파일로 제공합니다.
    """
    import io

    try:
        retrieval_module = modules.get("retrieval")
        if not retrieval_module:
            raise HTTPException(
                status_code=500,
                detail={
                    "error": "시스템 모듈 사용 불가",
                    "message": "문서 검색 모듈을 사용할 수 없습니다",
                    "suggestion": "서버 상태를 확인하고 관리자에게 문의하세요",
                },
            )

        # 문서의 모든 청크를 검색
        chunks = await retrieval_module.get_document_chunks(document_id)

        if not chunks:
            raise HTTPException(
                status_code=404,
                detail={
                    "error": "문서를 찾을 수 없음",
                    "message": "요청하신 문서를 찾을 수 없습니다",
                    "suggestion": "문서가 삭제되었거나 ID가 올바르지 않을 수 있습니다",
                    "document_id": document_id,
                },
            )

        # 청크 내용을 페이지/순서별로 정렬 후 결합
        sorted_chunks = sorted(
            chunks,
            key=lambda c: (
                c.get("metadata", {}).get("page", 0),
                c.get("metadata", {}).get("chunk_index", 0),
            ),
        )
        content = "\n\n".join(chunk.get("content", "") for chunk in sorted_chunks)

        # 파일명 추출 (메타데이터에서)
        first_chunk_meta = sorted_chunks[0].get("metadata", {})
        filename = first_chunk_meta.get("source_file", first_chunk_meta.get("filename", "document"))

        # 확장자가 없으면 .txt 추가
        if "." not in Path(filename).name:
            filename = f"{filename}.txt"
        # 원본이 바이너리 형식이면 .txt로 변환
        ext = Path(filename).suffix.lower()
        if ext in (".pdf", ".docx", ".pptx", ".xlsx"):
            filename = Path(filename).stem + ".txt"

        logger.info(f"Document download: {document_id}, {len(sorted_chunks)} chunks, filename={filename}")

        buffer = io.BytesIO(content.encode("utf-8"))
        return StreamingResponse(
            buffer,
            media_type="text/plain; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Content-Length": str(len(content.encode("utf-8"))),
            },
        )
    except HTTPException:
        raise
    except Exception as error:
        logger.error(f"Download document error: {error}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "error": "문서 다운로드 실패",
                "message": "문서를 다운로드하는 중 오류가 발생했습니다",
                "suggestion": "잠시 후 다시 시도하거나 관리자에게 문의하세요",
                "document_id": document_id,
                "technical_error": str(error),
            },
        ) from error


@router.get("/upload/supported-types")
async def get_supported_types():
    """지원하는 파일 타입 목록"""
    return {
        "supported_types": {
            "pdf": {
                "mime_type": "application/pdf",
                "description": "PDF documents",
                "max_size_mb": 10,
            },
            "docx": {
                "mime_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                "description": "Microsoft Word documents",
                "max_size_mb": 10,
            },
            "pptx": {
                "mime_type": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
                "description": "Microsoft PowerPoint presentations",
                "max_size_mb": 20,
            },
            "xlsx": {
                "mime_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                "description": "Microsoft Excel spreadsheets",
                "max_size_mb": 10,
            },
            "txt": {
                "mime_type": "text/plain",
                "description": "Plain text files",
                "max_size_mb": 10,
            },
            "csv": {
                "mime_type": "text/csv",
                "description": "Comma-separated values",
                "max_size_mb": 10,
            },
            "html": {"mime_type": "text/html", "description": "HTML documents", "max_size_mb": 10},
            "md": {
                "mime_type": "text/markdown",
                "description": "Markdown documents",
                "max_size_mb": 10,
            },
            "json": {
                "mime_type": "application/json",
                "description": "JSON documents",
                "max_size_mb": 10,
            },
        },
        "max_file_size": config.get("uploads", {}).get("max_file_size", 50 * 1024 * 1024),
        "max_files_per_request": 1,
    }
