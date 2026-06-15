"""원본 파일 보관 추상화(OriginalFileStorage) 단위 테스트.

검증 대상(#10, 멀티테넌트 제거 일반화):
    - local 백엔드 라운드트립(store → resolve → chunks/bytes)
    - 경로 traversal 가드(originals 루트 밖 경로 거부)
    - GCS 백엔드 미설정/미설치 시 graceful 에러
    - delete_original_reference 로컬 파일 정리
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.api.original_file_storage import (
    LOCAL_ORIGINAL_STORAGE_BACKEND,
    OriginalFileNotFoundError,
    OriginalFileStorageConfigurationError,
    delete_original_reference,
    original_file_bytes,
    original_storage_settings,
    resolve_original_reference,
    store_original_file,
)


def test_local_store_and_resolve_round_trip(tmp_path: Path) -> None:
    """local 백엔드에 저장한 원본을 다시 해석·읽을 수 있어야 한다."""
    content = b"hello original bytes"
    stored = store_original_file(
        content,
        app_config={},
        upload_dir=tmp_path,
        job_id="job-1",
        safe_filename="sample.pdf",
        content_type="application/pdf",
    )
    assert stored.backend == LOCAL_ORIGINAL_STORAGE_BACKEND
    assert stored.local_path is not None and stored.local_path.is_file()
    assert stored.metadata["original_file_path"] == str(stored.local_path)

    reference = resolve_original_reference(
        metadata=stored.metadata,
        app_config={},
        upload_dir=tmp_path,
    )
    assert reference.backend == LOCAL_ORIGINAL_STORAGE_BACKEND
    assert original_file_bytes(reference, app_config={}) == content


def test_local_resolve_rejects_path_outside_originals(tmp_path: Path) -> None:
    """originals 루트 밖의 경로는 보안상 거부되어야 한다."""
    outside = tmp_path / "outside.bin"
    outside.write_bytes(b"x")
    with pytest.raises(OriginalFileNotFoundError):
        resolve_original_reference(
            metadata={
                "original_storage_backend": LOCAL_ORIGINAL_STORAGE_BACKEND,
                "original_file_path": str(outside),
            },
            app_config={},
            upload_dir=tmp_path,
        )


def test_delete_original_reference_removes_local_file(tmp_path: Path) -> None:
    """delete_original_reference는 로컬 원본 파일을 제거해야 한다."""
    stored = store_original_file(
        b"data",
        app_config={},
        upload_dir=tmp_path,
        job_id="job-2",
        safe_filename="d.txt",
    )
    reference = resolve_original_reference(
        metadata=stored.metadata, app_config={}, upload_dir=tmp_path
    )
    assert reference.local_path is not None and reference.local_path.is_file()
    delete_original_reference(reference, app_config={})
    assert not reference.local_path.is_file()


def test_gcs_backend_requires_bucket(monkeypatch: pytest.MonkeyPatch) -> None:
    """GCS 백엔드 선택 시 버킷 미설정이면 구성 에러를 던져야 한다."""
    monkeypatch.setenv("ONERAG_ORIGINAL_STORAGE_BACKEND", "gcs")
    monkeypatch.delenv("ONERAG_ORIGINAL_GCS_BUCKET", raising=False)
    with pytest.raises(OriginalFileStorageConfigurationError):
        original_storage_settings({})


def test_unsupported_backend_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """지원하지 않는 백엔드명은 구성 에러를 던져야 한다."""
    monkeypatch.setenv("ONERAG_ORIGINAL_STORAGE_BACKEND", "s3")
    with pytest.raises(OriginalFileStorageConfigurationError):
        original_storage_settings({})


def test_default_backend_is_local(monkeypatch: pytest.MonkeyPatch) -> None:
    """기본 백엔드는 의존성 0의 local이어야 한다."""
    monkeypatch.delenv("ONERAG_ORIGINAL_STORAGE_BACKEND", raising=False)
    settings = original_storage_settings({})
    assert settings.backend == LOCAL_ORIGINAL_STORAGE_BACKEND
