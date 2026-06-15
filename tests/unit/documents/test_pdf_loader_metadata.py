"""PDF 로더 메타데이터 보존 + 품질 게이트 단위 테스트 (#13, #12).

검증 항목:
    #13) 스캔/빈 페이지를 폐기하지 않고 scanned_page/extraction_warnings 메타로 방출.
    #13) 페이지 추출 예외도 빈 Document + text_extraction_failed 경고로 보존.
    #12) 품질 게이트 기본 OFF: 무동작.
    #12) soft 모드: mojibake(PUA) 텍스트에 extraction_warnings 기록.
    #12) fitz 미설치 시 quality_gate_pymupdf_unavailable 경고.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from langchain_core.documents import Document

import app.modules.core.documents.loaders.pdf_loader as pdf_loader
from app.modules.core.documents.loaders.pdf_loader import (
    PDFLoader,
    _apply_quality_gate,
    _normalize_pdf_text,
    _scan_text_quality,
)


class _FakePage:
    """pypdf Page 스텁: extract_text 결과 또는 예외를 흉내낸다."""

    def __init__(self, text: str | None = None, *, raises: Exception | None = None) -> None:
        self._text = text
        self._raises = raises

    def extract_text(self) -> str:
        if self._raises is not None:
            raise self._raises
        return self._text or ""


class _FakeReader:
    def __init__(self, pages: list[_FakePage]) -> None:
        self.pages = pages


@pytest.fixture
def patch_reader(monkeypatch: pytest.MonkeyPatch):
    """PdfReader를 스텁으로 교체해 실제 PDF 없이 페이지 시퀀스를 주입한다."""

    def _apply(pages: list[_FakePage]) -> None:
        monkeypatch.setattr(pdf_loader, "PdfReader", lambda *_a, **_k: _FakeReader(pages))

    return _apply


@pytest.mark.asyncio
async def test_scanned_pages_are_emitted_with_metadata(
    patch_reader, tmp_path: Path
) -> None:
    """빈 텍스트(스캔본) 페이지도 폐기하지 않고 scanned_page 메타와 함께 방출한다."""
    patch_reader([_FakePage("실제 텍스트"), _FakePage(""), _FakePage("   ")])
    pdf_path = tmp_path / "scan.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake")

    docs = await PDFLoader().load(pdf_path)

    assert len(docs) == 3  # 빈 페이지도 모두 방출(침묵 손실 방지)
    assert docs[0].metadata["scanned_page"] is False
    assert docs[0].metadata["extraction_warnings"] == []
    assert docs[1].metadata["scanned_page"] is True
    assert docs[1].metadata["extraction_warnings"] == ["no_extractable_text"]
    assert docs[2].metadata["scanned_page"] is True
    assert docs[2].metadata["extraction_warnings"] == ["no_extractable_text"]
    # 페이지 진단 메타 일관성
    assert docs[1].metadata["page_number"] == 2
    assert docs[1].metadata["page_index"] == 1
    assert docs[1].metadata["extraction_method"] == "pypdf"


@pytest.mark.asyncio
async def test_page_extraction_failure_is_preserved(patch_reader, tmp_path: Path) -> None:
    """페이지 추출 예외도 drop하지 않고 빈 Document + 경고 메타로 보존한다."""
    patch_reader([_FakePage(raises=ValueError("boom"))])
    pdf_path = tmp_path / "broken.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake")

    docs = await PDFLoader().load(pdf_path)

    assert len(docs) == 1
    assert docs[0].page_content == ""
    assert docs[0].metadata["scanned_page"] is True
    warnings = docs[0].metadata["extraction_warnings"]
    assert any(w.startswith("text_extraction_failed") for w in warnings)


def test_normalize_pdf_text_preserves_word_spacing() -> None:
    """범용화: 한국어/영어 어절 공백을 파괴하지 않아야 한다(JP CJK-공백제거 정규식 미차용)."""
    assert _normalize_pdf_text("안녕 하세요 world") == "안녕 하세요 world"
    assert _normalize_pdf_text("foo\r\nbar") == "foo\nbar"
    assert _normalize_pdf_text("  여러   공백  ") == "여러 공백"
    assert _normalize_pdf_text(None) == ""


def test_scan_text_quality_flags_pua_as_bad() -> None:
    good = _scan_text_quality("정상적인 한국어 텍스트입니다")
    assert good["good_ratio"] > 0.9
    # PUA(사적사용영역) 문자 덩어리 = mojibake 신호
    bad = _scan_text_quality("")
    assert bad["bad_ratio"] == 1.0
    assert bad["good_ratio"] == 0.0


def test_quality_gate_disabled_by_default_is_noop(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """기본 OFF: 입력 documents를 그대로 반환(무동작)."""
    monkeypatch.delenv("ONERAG_PDF_QUALITY_GATE", raising=False)
    docs = [Document(page_content="" * 50, metadata={})]
    result = _apply_quality_gate(docs, tmp_path / "x.pdf")
    assert result is docs


def test_quality_gate_soft_records_warning_when_fitz_unavailable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """soft 모드 + fitz 미설치: 경고를 메타에 기록하고 진행(graceful)."""
    monkeypatch.setenv("ONERAG_PDF_QUALITY_GATE", "1")
    monkeypatch.delenv("ONERAG_PDF_QUALITY_GATE_FAIL", raising=False)
    monkeypatch.setattr(pdf_loader, "PYMUPDF_AVAILABLE", False)
    monkeypatch.setattr(pdf_loader, "fitz", None)

    # good_ratio가 0이 되도록 PUA 문자만으로 구성(min_chars=50 초과)
    docs = [Document(page_content="" * 100, metadata={})]
    result = _apply_quality_gate(docs, tmp_path / "broken.pdf")

    warnings = result[0].metadata["extraction_warnings"]
    assert "quality_gate_low_good_ratio" in warnings
    assert "quality_gate_pymupdf_unavailable" in warnings


def test_quality_gate_hard_raises(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """hard 모드: 폴백 후에도 미달이면 ValueError로 업로드 실패 처리."""
    monkeypatch.setenv("ONERAG_PDF_QUALITY_GATE", "1")
    monkeypatch.setenv("ONERAG_PDF_QUALITY_GATE_FAIL", "1")
    monkeypatch.setattr(pdf_loader, "PYMUPDF_AVAILABLE", False)
    monkeypatch.setattr(pdf_loader, "fitz", None)

    docs = [Document(page_content="" * 100, metadata={})]
    with pytest.raises(ValueError, match="품질"):
        _apply_quality_gate(docs, tmp_path / "broken.pdf")
