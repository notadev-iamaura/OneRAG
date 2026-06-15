"""레거시 .doc 로더 단위 테스트 (#26).

검증 항목:
    1. DOCXLoader.supported_extensions에 .doc 포함, factory 등록.
    2. soffice/libreoffice 부재 시 명확한 ValueError(graceful-optional).
    3. soffice 존재 시 변환 경로가 _load_docx를 재사용(monkeypatch 변환 mock).
    4. DOCX(.docx) 경로는 회귀 없이 기존 동작 유지.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import app.modules.core.documents.loaders.docx_loader as docx_loader
from app.modules.core.documents.loaders.docx_loader import DOCXLoader
from app.modules.core.documents.loaders.factory import LoaderFactory


def test_doc_extension_supported_and_registered() -> None:
    loader = DOCXLoader()
    assert ".doc" in loader.supported_extensions
    assert ".docx" in loader.supported_extensions
    # factory가 .doc를 DOCXLoader로 매핑해야 한다(#26).
    assert isinstance(LoaderFactory.get_loader("legacy.doc"), DOCXLoader)


@pytest.mark.asyncio
async def test_legacy_doc_without_soffice_raises_clear_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """soffice/libreoffice 미발견 시 명확한 안내 메시지로 실패해야 한다(필수 의존성 미추가)."""
    monkeypatch.setattr(docx_loader.shutil, "which", lambda _name: None)
    monkeypatch.setattr(docx_loader, "_resolve_soffice_override", lambda: None)
    doc_path = tmp_path / "legacy.doc"
    doc_path.write_bytes(b"\xd0\xcf\x11\xe0 fake-ole")

    with pytest.raises(ValueError, match="(?i)libreoffice|soffice"):
        await DOCXLoader().load(doc_path)


@pytest.mark.asyncio
async def test_legacy_doc_conversion_reuses_docx_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """soffice 변환 경로가 변환된 docx로 _load_docx를 재사용해야 한다."""
    doc_path = tmp_path / "legacy.doc"
    doc_path.write_bytes(b"\xd0\xcf\x11\xe0 fake-ole")

    # soffice 탐지 통과
    monkeypatch.setattr(docx_loader.shutil, "which", lambda name: "/usr/bin/soffice")

    converted_marker: dict[str, Path] = {}

    def _fake_run(cmd, **_kwargs):  # type: ignore[no-untyped-def]
        # --outdir 다음 인자가 출력 디렉토리
        outdir = Path(cmd[cmd.index("--outdir") + 1])
        produced = outdir / f"{doc_path.stem}.docx"
        produced.write_bytes(b"converted")
        converted_marker["path"] = produced

        class _R:
            returncode = 0
            stdout = ""
            stderr = ""

        return _R()

    monkeypatch.setattr(docx_loader.subprocess, "run", _fake_run)

    from langchain_core.documents import Document

    captured: dict[str, Path] = {}

    def _fake_load_docx(self, path: Path):  # type: ignore[no-untyped-def]
        captured["path"] = path
        return [Document(page_content="변환됨", metadata={})]

    monkeypatch.setattr(DOCXLoader, "_load_docx", _fake_load_docx)

    docs = await DOCXLoader().load(doc_path)

    assert docs[0].page_content == "변환됨"
    # _load_docx가 변환 산출물(.docx)로 호출돼야 한다
    assert captured["path"].suffix == ".docx"
