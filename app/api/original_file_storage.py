"""업로드 원본 파일 보관 추상화.

업로드된 원본 파일(PDF/DOCX 등)을 처리 후에도 영구 보관하기 위한 스토리지
어댑터입니다. 기본 백엔드는 의존성 0의 백엔드 로컬 파일시스템이며, GCS(Google
Cloud Storage)는 선택형(opt-in)으로 lazy import 가드를 통해 제공합니다.

주요 구성:
    - OriginalStorageSettings: 백엔드 해석 결과(local/gcs)
    - store_original_file: 원본 바이트를 보관하고 내부 메타데이터 반환
    - resolve_original_reference: 저장 메타데이터로부터 안전한 참조 해석
    - original_file_chunks / original_file_bytes: 스트리밍/일괄 읽기
    - materialize_original_to_path: 재처리용 임시 파일로 복원
    - delete_original_reference: 원본 정리

설계 노트:
    - 멀티테넌트(company_id) 결합을 OneRAG 단일 테넌트 구조에 맞춰 제거했다.
      originals 디렉토리는 테넌트 하위 경로 없이 upload_dir/originals 하나로 통합한다.
    - GCS는 google-cloud-storage 미설치 시 OriginalFileStorageConfigurationError로
      graceful하게 실패한다(코어 의존성 무게 0 유지). pyproject의 [gcs] extra로만 설치.

의존성: 표준 라이브러리만 사용(local). GCS 경로는 google-cloud-storage(optional).
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

LOCAL_ORIGINAL_STORAGE_BACKEND = "local"
GCS_ORIGINAL_STORAGE_BACKEND = "gcs"
DEFAULT_ORIGINAL_GCS_PREFIX = "originals"
ORIGINAL_FILE_CHUNK_SIZE = 1024 * 1024

# 잡 페이로드에 병합되는 원본 스토리지 메타데이터 키
ORIGINAL_STORAGE_METADATA_KEYS = frozenset(
    {
        "original_storage_backend",
        "original_gcs_bucket",
        "original_gcs_object",
    }
)


class OriginalFileStorageError(RuntimeError):
    """원본 파일 스토리지 기본 예외."""


class OriginalFileStorageConfigurationError(OriginalFileStorageError):
    """선택한 스토리지 백엔드를 사용할 수 없을 때 발생."""


class OriginalFileNotFoundError(OriginalFileStorageError):
    """저장된 원본을 인가/해석할 수 없을 때 발생."""


@dataclass(frozen=True)
class OriginalStorageSettings:
    """원본 스토리지 백엔드 해석 결과."""

    backend: str
    gcs_bucket: str | None = None
    gcs_prefix: str = DEFAULT_ORIGINAL_GCS_PREFIX
    gcs_project_id: str | None = None


@dataclass(frozen=True)
class StoredOriginalFile:
    """원본 보관 결과(잡 페이로드에 병합할 메타데이터 포함)."""

    backend: str
    metadata: dict[str, Any]
    local_path: Path | None = None
    source_uri: str | None = None


@dataclass(frozen=True)
class OriginalFileReference:
    """검증된 원본 참조(읽기/삭제 대상)."""

    backend: str
    local_path: Path | None = None
    gcs_bucket: str | None = None
    gcs_object: str | None = None


def original_storage_settings(app_config: dict[str, Any] | None) -> OriginalStorageSettings:
    """env/config에서 원본 스토리지 설정을 해석한다.

    우선순위: 환경변수(ONERAG_ORIGINAL_*) > config(uploads.original_storage) > 기본 local.

    Raises:
        OriginalFileStorageConfigurationError: 미지원 백엔드이거나 GCS 버킷 미설정.
    """
    upload_config = app_config.get("uploads", {}) if isinstance(app_config, dict) else {}
    if not isinstance(upload_config, dict):
        upload_config = {}
    storage_config = upload_config.get("original_storage", {})
    if not isinstance(storage_config, dict):
        storage_config = {}

    backend = str(
        os.getenv("ONERAG_ORIGINAL_STORAGE_BACKEND")
        or storage_config.get("backend")
        or storage_config.get("type")
        or LOCAL_ORIGINAL_STORAGE_BACKEND
    ).strip().lower()

    if backend in {"filesystem", "fs", "file"}:
        backend = LOCAL_ORIGINAL_STORAGE_BACKEND
    if backend not in {LOCAL_ORIGINAL_STORAGE_BACKEND, GCS_ORIGINAL_STORAGE_BACKEND}:
        raise OriginalFileStorageConfigurationError(
            f"Unsupported original storage backend: {backend}"
        )

    if backend == LOCAL_ORIGINAL_STORAGE_BACKEND:
        return OriginalStorageSettings(backend=backend)

    gcs_bucket = str(
        os.getenv("ONERAG_ORIGINAL_GCS_BUCKET")
        or storage_config.get("bucket")
        or storage_config.get("gcs_bucket")
        or ""
    ).strip()
    if not gcs_bucket:
        raise OriginalFileStorageConfigurationError(
            "ONERAG_ORIGINAL_GCS_BUCKET is required when original storage backend is gcs"
        )

    gcs_prefix = _clean_object_prefix(
        str(
            os.getenv("ONERAG_ORIGINAL_GCS_PREFIX")
            or storage_config.get("prefix")
            or storage_config.get("gcs_prefix")
            or DEFAULT_ORIGINAL_GCS_PREFIX
        )
    )
    project_id = str(
        os.getenv("ONERAG_ORIGINAL_GCS_PROJECT_ID")
        or storage_config.get("project_id")
        or storage_config.get("gcs_project_id")
        or ""
    ).strip() or None
    return OriginalStorageSettings(
        backend=backend,
        gcs_bucket=gcs_bucket,
        gcs_prefix=gcs_prefix,
        gcs_project_id=project_id,
    )


def store_original_file(
    content: bytes,
    *,
    app_config: dict[str, Any] | None,
    upload_dir: Path,
    job_id: str,
    safe_filename: str,
    content_type: str | None = None,
) -> StoredOriginalFile:
    """업로드 원본 바이트를 보관하고 내부 메타데이터를 반환한다.

    Args:
        content: 원본 파일 바이트.
        app_config: 애플리케이션 config(스토리지 백엔드 해석용).
        upload_dir: 업로드 루트 디렉토리.
        job_id: 업로드 잡 식별자.
        safe_filename: 경로 안전 처리된 파일명.
        content_type: MIME 타입(GCS 업로드 시 사용).

    Returns:
        StoredOriginalFile. local 백엔드는 local_path/source_uri 포함.
    """
    settings = original_storage_settings(app_config)
    if settings.backend == LOCAL_ORIGINAL_STORAGE_BACKEND:
        original_path = build_local_original_path(
            upload_dir,
            job_id=job_id,
            safe_filename=safe_filename,
        )
        original_path.write_bytes(content)
        source_uri = original_path.as_uri()
        return StoredOriginalFile(
            backend=LOCAL_ORIGINAL_STORAGE_BACKEND,
            local_path=original_path,
            source_uri=source_uri,
            metadata={
                "original_storage_backend": LOCAL_ORIGINAL_STORAGE_BACKEND,
                "original_file_path": str(original_path),
                "source_uri": source_uri,
            },
        )

    object_name = build_gcs_original_object_name(
        settings,
        job_id=job_id,
        safe_filename=safe_filename,
    )
    try:
        client = _create_gcs_storage_client(settings.gcs_project_id)
        bucket = client.bucket(settings.gcs_bucket)
        blob = bucket.blob(object_name)
        blob.upload_from_string(
            content,
            content_type=content_type or "application/octet-stream",
        )
    except OriginalFileStorageError:
        raise
    except Exception:
        raise OriginalFileStorageError("original object storage upload failed") from None
    return StoredOriginalFile(
        backend=GCS_ORIGINAL_STORAGE_BACKEND,
        metadata={
            "original_storage_backend": GCS_ORIGINAL_STORAGE_BACKEND,
            "original_gcs_bucket": settings.gcs_bucket,
            "original_gcs_object": object_name,
        },
    )


def metadata_has_original_reference(metadata: dict[str, Any]) -> bool:
    """메타데이터에 사용 가능한 원본 참조가 있는지 여부."""
    if metadata.get("original_file_path"):
        return True
    return bool(metadata.get("original_gcs_bucket") and metadata.get("original_gcs_object"))


def original_storage_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    """잡 페이로드에서 원본 스토리지 메타데이터만 추출한다."""
    if not isinstance(metadata, dict):
        return {}
    return {
        key: metadata[key]
        for key in ORIGINAL_STORAGE_METADATA_KEYS
        if metadata.get(key) not in (None, "")
    }


def resolve_original_reference(
    *,
    metadata: dict[str, Any],
    app_config: dict[str, Any] | None,
    upload_dir: Path,
) -> OriginalFileReference:
    """저장 메타데이터로부터 검증된 원본 참조를 해석한다.

    local 백엔드는 originals 루트 밖의 경로를 거부하고, GCS는 구성된 버킷/접두만
    허용해 경로 우회를 차단한다.

    Raises:
        OriginalFileNotFoundError: 참조가 없거나 인가 범위를 벗어났거나 누락된 경우.
    """
    backend = str(metadata.get("original_storage_backend") or "").strip().lower()
    if not backend:
        backend = (
            LOCAL_ORIGINAL_STORAGE_BACKEND
            if metadata.get("original_file_path")
            else GCS_ORIGINAL_STORAGE_BACKEND
        )

    if backend == LOCAL_ORIGINAL_STORAGE_BACKEND:
        original_path_value = metadata.get("original_file_path")
        if not original_path_value:
            raise OriginalFileNotFoundError("missing local original path")
        original_path = Path(str(original_path_value)).expanduser()
        if not original_path.is_absolute():
            original_path = upload_dir / original_path
        originals_dir = local_originals_directory(upload_dir)
        try:
            original_path.resolve().relative_to(originals_dir.resolve())
        except ValueError as error:
            raise OriginalFileNotFoundError("local original is outside originals root") from error
        if not original_path.is_file():
            raise OriginalFileNotFoundError("local original is missing")
        return OriginalFileReference(
            backend=LOCAL_ORIGINAL_STORAGE_BACKEND, local_path=original_path
        )

    if backend != GCS_ORIGINAL_STORAGE_BACKEND:
        raise OriginalFileNotFoundError("unsupported original storage backend")

    settings = original_storage_settings(app_config)
    if settings.backend != GCS_ORIGINAL_STORAGE_BACKEND:
        raise OriginalFileNotFoundError("gcs original storage is not configured")

    bucket = str(metadata.get("original_gcs_bucket") or "")
    object_name = str(metadata.get("original_gcs_object") or "")
    if bucket != settings.gcs_bucket or not object_name:
        raise OriginalFileNotFoundError("gcs original reference does not match configured bucket")

    document_id = str(metadata.get("document_id") or metadata.get("job_id") or "")
    expected_prefix = (
        f"{settings.gcs_prefix}/{_safe_object_component(document_id, fallback='document')}/"
    )
    if not object_name.startswith(expected_prefix):
        raise OriginalFileNotFoundError("gcs original reference is outside document prefix")

    return OriginalFileReference(
        backend=GCS_ORIGINAL_STORAGE_BACKEND,
        gcs_bucket=bucket,
        gcs_object=object_name,
    )


def original_file_chunks(
    reference: OriginalFileReference,
    *,
    app_config: dict[str, Any] | None,
    chunk_size: int = ORIGINAL_FILE_CHUNK_SIZE,
) -> Iterator[bytes]:
    """원본 파일을 청크 단위로 스트리밍한다(StreamingResponse용)."""
    if reference.backend == LOCAL_ORIGINAL_STORAGE_BACKEND:
        if reference.local_path is None:
            raise OriginalFileNotFoundError("missing local original path")
        return _local_file_chunks(reference.local_path, chunk_size)

    blob = _authorized_gcs_blob(reference, app_config=app_config)
    return _gcs_blob_chunks(blob, chunk_size)


def original_file_bytes(
    reference: OriginalFileReference,
    *,
    app_config: dict[str, Any] | None,
) -> bytes:
    """원본 파일 전체 바이트를 반환한다."""
    if reference.backend == LOCAL_ORIGINAL_STORAGE_BACKEND:
        if reference.local_path is None:
            raise OriginalFileNotFoundError("missing local original path")
        try:
            return reference.local_path.read_bytes()
        except OSError as error:
            raise OriginalFileNotFoundError("local original cannot be read") from error

    blob = _authorized_gcs_blob(reference, app_config=app_config)
    try:
        result = blob.download_as_bytes()
        return bytes(result)
    except Exception:
        raise OriginalFileStorageError("original object storage download failed") from None


def materialize_original_to_path(
    reference: OriginalFileReference,
    destination: Path,
    *,
    app_config: dict[str, Any] | None,
) -> None:
    """원본을 재처리용 임시 파일 경로로 복원한다."""
    if reference.backend == LOCAL_ORIGINAL_STORAGE_BACKEND:
        if reference.local_path is None:
            raise OriginalFileNotFoundError("missing local original path")
        shutil.copyfile(reference.local_path, destination)
        return

    try:
        content = original_file_bytes(reference, app_config=app_config)
        destination.write_bytes(content)
    except OSError as error:
        raise OriginalFileStorageError("original materialization failed") from error


def delete_original_reference(
    reference: OriginalFileReference,
    *,
    app_config: dict[str, Any] | None,
) -> None:
    """보관된 원본을 삭제한다(local 파일 unlink / GCS blob delete)."""
    if reference.backend == LOCAL_ORIGINAL_STORAGE_BACKEND:
        if reference.local_path and reference.local_path.is_file():
            reference.local_path.unlink()
        return

    blob = _authorized_gcs_blob(reference, app_config=app_config, require_exists=False)
    try:
        blob.delete()
    except Exception:
        raise OriginalFileStorageError("original object storage delete failed") from None


def build_local_original_path(
    upload_dir: Path, *, job_id: str, safe_filename: str
) -> Path:
    """로컬 원본 보관 경로(upload_dir/originals/{job_id}_{filename})를 생성한다."""
    originals_dir = local_originals_directory(upload_dir)
    originals_dir.mkdir(parents=True, exist_ok=True)
    original_path = originals_dir / f"{_safe_path_component(job_id)}_{safe_filename}"
    _ensure_child_path(original_path, originals_dir)
    return original_path


def local_originals_directory(upload_dir: Path) -> Path:
    """로컬 originals 루트 디렉토리를 반환한다(단일 테넌트, 하위 경로 없음)."""
    return upload_dir / "originals"


def build_gcs_original_object_name(
    settings: OriginalStorageSettings,
    *,
    job_id: str,
    safe_filename: str,
) -> str:
    """GCS 오브젝트 이름(prefix/{job_id}/{filename})을 생성한다."""
    safe_job_id = _safe_object_component(job_id, fallback="document")
    safe_object_filename = _safe_object_component(safe_filename, fallback="original")
    return f"{settings.gcs_prefix}/{safe_job_id}/{safe_object_filename}"


def _authorized_gcs_blob(
    reference: OriginalFileReference,
    *,
    app_config: dict[str, Any] | None,
    require_exists: bool = True,
) -> Any:
    """참조가 구성된 GCS 버킷과 일치하는지 검증한 blob을 반환한다."""
    settings = original_storage_settings(app_config)
    if (
        reference.backend != GCS_ORIGINAL_STORAGE_BACKEND
        or not reference.gcs_bucket
        or not reference.gcs_object
        or reference.gcs_bucket != settings.gcs_bucket
    ):
        raise OriginalFileNotFoundError("gcs original reference is not authorized")
    try:
        client = _create_gcs_storage_client(settings.gcs_project_id)
        bucket = client.bucket(reference.gcs_bucket)
        blob = bucket.blob(reference.gcs_object)
        if require_exists and hasattr(blob, "exists") and not blob.exists():
            raise OriginalFileNotFoundError("gcs original object is missing")
    except OriginalFileStorageError:
        raise
    except Exception:
        raise OriginalFileNotFoundError("gcs original object cannot be resolved") from None
    return blob


def _local_file_chunks(path: Path, chunk_size: int) -> Iterator[bytes]:
    """로컬 파일을 청크 단위로 읽는 제너레이터."""
    with path.open("rb") as stream:
        while True:
            chunk = stream.read(chunk_size)
            if not chunk:
                break
            yield chunk


def _gcs_blob_chunks(blob: Any, chunk_size: int) -> Iterator[bytes]:
    """GCS blob을 청크 단위로 스트리밍한다(open 미지원 시 일괄 폴백)."""
    try:
        stream = blob.open("rb")
    except AttributeError:
        try:
            data = blob.download_as_bytes()
        except Exception:
            raise OriginalFileStorageError("original object storage download failed") from None
        yield bytes(data)
        return
    except Exception:
        raise OriginalFileStorageError("original object storage download failed") from None

    try:
        with stream:
            while True:
                chunk = stream.read(chunk_size)
                if not chunk:
                    break
                yield chunk
    except Exception:
        raise OriginalFileStorageError("original object storage download failed") from None


def _create_gcs_storage_client(project_id: str | None = None) -> Any:
    """GCS 클라이언트를 lazy import로 생성한다(미설치 시 구성 에러)."""
    try:
        from google.cloud import storage
    except ImportError as error:
        raise OriginalFileStorageConfigurationError(
            "google-cloud-storage is required for GCS original storage"
        ) from error
    if project_id:
        return storage.Client(project=project_id)
    return storage.Client()


def _safe_path_component(value: str, *, fallback: str = "unknown") -> str:
    """경로 안전 문자열로 정규화한다(영숫자/-/_/. 만 허용)."""
    safe = "".join(char if char.isalnum() or char in ("-", "_", ".") else "_" for char in value)
    safe = safe.strip("._")
    return safe or fallback


def _safe_object_component(value: str, *, fallback: str) -> str:
    """오브젝트 경로 컴포넌트를 안전하게 정규화한다(basename 기준)."""
    return _safe_path_component(Path(str(value)).name, fallback=fallback)


def _clean_object_prefix(prefix: str) -> str:
    """GCS 접두 경로를 안전 컴포넌트로 정리한다."""
    parts = [
        _safe_object_component(part, fallback="")
        for part in str(prefix).split("/")
        if part and part not in {".", ".."}
    ]
    parts = [part for part in parts if part]
    return "/".join(parts) or DEFAULT_ORIGINAL_GCS_PREFIX


def _ensure_child_path(path: Path, parent: Path) -> None:
    """path가 parent 하위 경로인지 검증한다(아니면 ValueError 전파)."""
    path.resolve().relative_to(parent.resolve())
