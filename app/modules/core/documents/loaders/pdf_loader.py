"""
PDF Document Loader
PDF 파일 로딩 전략 구현

차용/개선 사항:
- #13: 스캔/빈 페이지를 폐기하지 않고 scanned_page/extraction_warnings 메타로 보존해
       침묵 손실(silent loss)을 진단 가능하게 한다.
- #12: 추출 품질 게이트(mojibake 감지 + PyMuPDF 재추출 폴백). 환경변수 opt-in, 기본 OFF.

범용화: 일본어 전용 CJK-공백 제거 정규식과 language_hint="ja" 하드코딩은
차용하지 않는다(한국어 등 공백 구분 언어의 어절 경계를 파괴하므로). NFKC 정규화 +
공백 정리만 채택하고, language_hint는 환경변수로 외부화하되 기본 None이다.
"""

import os
import re
import unicodedata
from pathlib import Path
from typing import Any

from langchain_core.documents import Document
from pypdf import PdfReader

from .....lib.logger import get_logger
from .base import DocumentLoaderStrategy

logger = get_logger(__name__)

# 페이지 메타데이터 상수
PDF_EXTRACTION_METHOD = "pypdf"
TABLE_EXTRACTION_STATUS = "not_attempted"
# 언어 힌트는 도메인 비종속을 위해 환경변수로 외부화한다(기본 None — JP "ja" 하드코딩 금지).
PDF_LANGUAGE_HINT_ENV = "ONERAG_PDF_LANGUAGE_HINT"

# 인덱싱 추출 품질 게이트(mojibake/PyMuPDF 폴백) 관련 환경변수 및 임계값
# 모든 신규 동작은 기본 OFF(opt-in)이므로 기존 동작에 영향을 주지 않는다.
PDF_QUALITY_GATE_ENV = "ONERAG_PDF_QUALITY_GATE"  # 품질 게이트 활성화(soft: 경고 기록)
PDF_QUALITY_GATE_FAIL_ENV = "ONERAG_PDF_QUALITY_GATE_FAIL"  # 미달 시 업로드 실패(hard)
PDF_QUALITY_MIN_GOOD_RATIO_ENV = "ONERAG_PDF_QUALITY_MIN_GOOD_RATIO"  # 정상문자비율 하한
PDF_QUALITY_MIN_CHARS_ENV = "ONERAG_PDF_QUALITY_MIN_CHARS"  # 추출 텍스트 길이 하한
# 기본 임계값: good_ratio<0.55 깨짐 의심 기준을 보수적으로 채택
DEFAULT_PDF_QUALITY_MIN_GOOD_RATIO = 0.55
DEFAULT_PDF_QUALITY_MAX_BAD_RATIO = 0.15  # PUA/그리스·키릴 등 깨짐 신호 상한
DEFAULT_PDF_QUALITY_MIN_CHARS = 50  # 너무 짧으면 비율 통계가 불안정하므로 검사 생략 기준
QUALITY_GATE_WARNING_LOW_GOOD_RATIO = "quality_gate_low_good_ratio"
QUALITY_GATE_WARNING_HIGH_BAD_RATIO = "quality_gate_high_bad_ratio"
QUALITY_GATE_WARNING_FITZ_RECOVERED = "quality_gate_pymupdf_recovered"
QUALITY_GATE_WARNING_FITZ_UNAVAILABLE = "quality_gate_pymupdf_unavailable"
QUALITY_GATE_WARNING_FITZ_FAILED = "quality_gate_pymupdf_failed"

try:  # PyMuPDF(fitz)는 선택 의존성. 미설치 환경에서도 graceful degradation 한다.
    import fitz  # type: ignore[import-untyped]

    PYMUPDF_AVAILABLE = True
except ImportError:  # pragma: no cover - 설치 여부에 따른 분기
    fitz = None  # type: ignore[assignment]
    PYMUPDF_AVAILABLE = False


def _pdf_language_hint() -> str | None:
    """PDF 언어 힌트(환경변수). 미설정 시 None(도메인 비종속 기본값)."""
    value = os.getenv(PDF_LANGUAGE_HINT_ENV)
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _normalize_pdf_text(text: str | None) -> str:
    """추출 텍스트를 경량 정리한다(어절 공백 보존).

    NFKC 정규화 + 개행 정규화(\\r\\n→\\n) + 줄당 연속 공백 단일화/strip만 수행한다.
    일본어 전용 CJK-문자간 공백 제거 정규식은 차용하지 않는다 —
    한국어/영어 등 공백 구분 언어의 어절 경계를 파괴하기 때문이다.
    """
    if not text:
        return ""
    normalized = unicodedata.normalize("NFKC", text).replace("\r\n", "\n").replace("\r", "\n")
    lines: list[str] = []
    for line in normalized.splitlines():
        cleaned_line = re.sub(r"[ \t\f\v]+", " ", line).strip()
        if cleaned_line:
            lines.append(cleaned_line)
    return "\n".join(lines)


def _pdf_page_metadata(
    page_index: int,
    *,
    scanned_page: bool,
    extraction_warnings: list[str] | None = None,
) -> dict[str, object]:
    """페이지별 진단 메타데이터를 구성한다(#13).

    page_content가 비어도 이 메타와 함께 Document를 방출해 '어느 페이지가 왜
    누락됐는지'를 추후 진단할 수 있게 한다.
    """
    return {
        "page_number": page_index + 1,
        "page_index": page_index,
        "extraction_method": PDF_EXTRACTION_METHOD,
        "language_hint": _pdf_language_hint(),
        "scanned_page": scanned_page,
        "extraction_warnings": extraction_warnings or [],
        "table_count": 0,
        "table_extraction_status": TABLE_EXTRACTION_STATUS,
    }


def _env_bool(name: str, *, default: bool) -> bool:
    """환경변수를 불리언으로 해석한다."""
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _env_int(name: str, *, default: int, minimum: int) -> int:
    """환경변수를 정수로 해석하되 하한을 강제한다."""
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    try:
        value = int(raw_value)
    except ValueError:
        logger.warning("%s must be an integer; using default %s", name, default)
        return default
    return max(minimum, value)


def _env_float(name: str, *, default: float, minimum: float, maximum: float) -> float:
    """환경변수를 float 임계값으로 해석하되 범위를 강제한다."""
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    try:
        value = float(raw_value)
    except ValueError:
        logger.warning("%s must be a float; using default %s", name, default)
        return default
    return max(minimum, min(maximum, value))


def _quality_char_class(ch: str) -> str:
    """문자를 정상(CJK/ASCII) / 깨짐(PUA/그리스·키릴) / 기타로 분류한다.

    언어 무관: 한글 완성형/자모, 히라가나/가타카나, CJK 한자, 전각/ASCII를 모두
    'good'으로 분류하므로 다국어 PDF에 그대로 동작한다. PUA(사적사용영역)와
    그리스/키릴 대량 등장은 깨진 폰트(mojibake)의 전형적 신호로 'bad' 처리한다.
    """
    code = ord(ch)
    if ch.isascii():
        return "ascii"
    # 한글(완성형/자모/호환자모)
    if 0xAC00 <= code <= 0xD7A3 or 0x1100 <= code <= 0x11FF or 0x3130 <= code <= 0x318F:
        return "cjk"
    # 히라가나/가타카나
    if 0x3040 <= code <= 0x30FF:
        return "cjk"
    # CJK 한자
    if 0x4E00 <= code <= 0x9FFF or 0x3400 <= code <= 0x4DBF:
        return "cjk"
    # CJK 기호/전각
    if 0x3000 <= code <= 0x303F or 0xFF00 <= code <= 0xFFEF:
        return "cjk"
    # 사적사용영역(PUA): 깨진 폰트의 전형적 신호
    if 0xE000 <= code <= 0xF8FF:
        return "pua"
    # 그리스/키릴: 다량 등장하면 mojibake 신호
    if 0x0370 <= code <= 0x03FF or 0x0400 <= code <= 0x04FF:
        return "greek_cyrillic"
    return "other"


def _scan_text_quality(text: str) -> dict[str, float | int]:
    """추출 텍스트의 정상문자비율(good_ratio)과 깨짐비율(bad_ratio)을 계산한다.

    Args:
        text: 검사 대상 추출 텍스트(공백 제외 문자 기준으로 비율 산출)

    Returns:
        total/good_ratio/bad_ratio를 담은 딕셔너리. 비공백 문자가 없으면
        good_ratio=0.0, bad_ratio=1.0을 반환한다(스캔본/빈 페이지로 간주).
    """
    counts = {"ascii": 0, "cjk": 0, "pua": 0, "greek_cyrillic": 0, "other": 0}
    total = 0
    for ch in text:
        if ch.isspace():
            continue
        total += 1
        counts[_quality_char_class(ch)] += 1
    if total == 0:
        return {"total": 0, "good_ratio": 0.0, "bad_ratio": 1.0}
    good = counts["ascii"] + counts["cjk"]
    bad = counts["pua"] + counts["greek_cyrillic"]
    return {
        "total": total,
        "good_ratio": round(good / total, 3),
        "bad_ratio": round(bad / total, 3),
    }


def _quality_gate_enabled() -> bool:
    """품질 게이트(soft) 활성화 여부. 기본 OFF."""
    return _env_bool(PDF_QUALITY_GATE_ENV, default=False)


def _quality_gate_fail_enabled() -> bool:
    """품질 미달 시 업로드 실패 처리(hard) 여부. 기본 OFF."""
    return _env_bool(PDF_QUALITY_GATE_FAIL_ENV, default=False)


def _assess_documents_quality(documents: list[Document]) -> dict[str, Any]:
    """문서(페이지 묶음) 전체 텍스트를 합쳐 추출 품질을 평가한다.

    Returns:
        passed(bool), good_ratio(float), bad_ratio(float), chars(int),
        reasons(list[str])를 담은 딕셔너리.
    """
    combined = "\n".join((document.page_content or "") for document in documents)
    chars = len(combined.strip())
    stats = _scan_text_quality(combined)
    min_good = _env_float(
        PDF_QUALITY_MIN_GOOD_RATIO_ENV,
        default=DEFAULT_PDF_QUALITY_MIN_GOOD_RATIO,
        minimum=0.0,
        maximum=1.0,
    )
    min_chars = _env_int(
        PDF_QUALITY_MIN_CHARS_ENV,
        default=DEFAULT_PDF_QUALITY_MIN_CHARS,
        minimum=0,
    )
    good_ratio = float(stats["good_ratio"])
    bad_ratio = float(stats["bad_ratio"])
    reasons: list[str] = []
    # 텍스트가 거의 없으면(스캔본 등) 비율 통계가 무의미하므로 mojibake 판정을 보류한다.
    # 이런 케이스는 scanned_page/no_extractable_text 경로(#13)가 담당한다.
    if chars < min_chars:
        return {
            "passed": True,
            "good_ratio": good_ratio,
            "bad_ratio": bad_ratio,
            "chars": chars,
            "reasons": reasons,
        }
    if good_ratio < min_good:
        reasons.append(QUALITY_GATE_WARNING_LOW_GOOD_RATIO)
    if bad_ratio > DEFAULT_PDF_QUALITY_MAX_BAD_RATIO:
        reasons.append(QUALITY_GATE_WARNING_HIGH_BAD_RATIO)
    return {
        "passed": not reasons,
        "good_ratio": good_ratio,
        "bad_ratio": bad_ratio,
        "chars": chars,
        "reasons": reasons,
    }


def _load_with_pymupdf(file_path: Path) -> list[Document] | None:
    """PyMuPDF(fitz)로 PDF를 재추출한다(품질 게이트 폴백 전용).

    PyMuPDF는 선택 의존성이므로 미설치 시 None을 반환한다(graceful degradation).
    추출 실패 시에도 예외를 전파하지 않고 None을 반환해 기존 pypdf 결과를 보존한다.

    Args:
        file_path: 재추출 대상 PDF 경로

    Returns:
        페이지별 Document 리스트. 사용 불가/실패 시 None.
    """
    if not PYMUPDF_AVAILABLE or fitz is None:
        return None
    documents: list[Document] = []
    try:
        with fitz.open(str(file_path)) as pdf:
            for page_index, page in enumerate(pdf):
                raw_text = page.get_text("text")
                text = _normalize_pdf_text(raw_text)
                warnings = ["no_extractable_text"] if not text else []
                warnings.append("extraction_method_pymupdf")
                documents.append(
                    Document(
                        page_content=text,
                        metadata=_pdf_page_metadata(
                            page_index,
                            scanned_page=not bool(text),
                            extraction_warnings=warnings,
                        ),
                    )
                )
        logger.info(
            "PyMuPDF fallback extracted %s pages from %s",
            len(documents),
            file_path.name,
        )
        return documents or None
    except Exception as error:  # noqa: BLE001 - 폴백은 절대 업로드를 깨지 않는다
        logger.warning(
            "PyMuPDF fallback extraction failed for %s: %s",
            file_path.name,
            type(error).__name__,
        )
        return None


def _apply_quality_gate(
    documents: list[Document],
    file_path: Path,
) -> list[Document]:
    """추출 품질 게이트를 적용한다(미달 시 PyMuPDF 폴백). 환경변수 opt-in, 기본 OFF.

    - ONERAG_PDF_QUALITY_GATE 미설정(기본) → 입력 documents를 그대로 반환(무동작).
    - 활성화 시 good_ratio/길이 검사 → 미달이면 PyMuPDF 재추출 시도.
    - 폴백 후에도 미달이면 extraction_warnings에 사유 기록(soft).
    - ONERAG_PDF_QUALITY_GATE_FAIL 추가 활성화 시 미달이면 ValueError(hard).

    Args:
        documents: pypdf 등으로 1차 추출된 Document 리스트
        file_path: 폴백 재추출에 사용할 원본 PDF 경로

    Returns:
        최종 채택된 Document 리스트(원본 또는 폴백 결과).

    Raises:
        ValueError: hard 모드에서 폴백 후에도 품질 미달인 경우.
    """
    if not _quality_gate_enabled():
        return documents
    assessment = _assess_documents_quality(documents)
    if assessment["passed"]:
        return documents

    logger.warning(
        "PDF quality gate flagged %s: good_ratio=%.3f bad_ratio=%.3f chars=%s reasons=%s",
        file_path.name,
        assessment["good_ratio"],
        assessment["bad_ratio"],
        assessment["chars"],
        assessment["reasons"],
    )

    final_documents = documents
    gate_warnings = list(assessment["reasons"])
    fitz_documents = _load_with_pymupdf(file_path)
    if fitz_documents is None:
        gate_warnings.append(
            QUALITY_GATE_WARNING_FITZ_UNAVAILABLE
            if not PYMUPDF_AVAILABLE
            else QUALITY_GATE_WARNING_FITZ_FAILED
        )
    else:
        fitz_assessment = _assess_documents_quality(fitz_documents)
        if fitz_assessment["passed"]:
            # 폴백이 품질을 회복함 → 폴백 결과 채택, 회복 경고만 남긴다.
            for document in fitz_documents:
                existing = document.metadata.get("extraction_warnings")
                warnings = list(existing) if isinstance(existing, list) else []
                warnings.append(QUALITY_GATE_WARNING_FITZ_RECOVERED)
                document.metadata["extraction_warnings"] = warnings
            logger.info(
                "PDF quality gate recovered via PyMuPDF for %s: good_ratio=%.3f",
                file_path.name,
                fitz_assessment["good_ratio"],
            )
            return fitz_documents
        # 폴백도 미달 → 더 나은 쪽(good_ratio 높은 쪽)을 채택하고 경고 유지.
        if fitz_assessment["good_ratio"] > assessment["good_ratio"]:
            final_documents = fitz_documents
            gate_warnings = list(fitz_assessment["reasons"])
        gate_warnings.append(QUALITY_GATE_WARNING_FITZ_FAILED)

    if _quality_gate_fail_enabled():
        # hard 모드: 조용히 깨진 채 인덱싱하지 않고 업로드를 실패시킨다.
        raise ValueError(
            f"PDF 추출 품질이 기준에 미달하여 인덱싱을 중단했습니다: {file_path.name} "
            f"(good_ratio={assessment['good_ratio']:.3f}, "
            f"bad_ratio={assessment['bad_ratio']:.3f}, 사유={gate_warnings})"
        )

    # soft 모드: 경고를 모든 페이지 메타데이터에 기록해 가시화한 뒤 진행한다.
    for document in final_documents:
        existing = document.metadata.get("extraction_warnings")
        warnings = list(existing) if isinstance(existing, list) else []
        for reason in gate_warnings:
            if reason not in warnings:
                warnings.append(reason)
        document.metadata["extraction_warnings"] = warnings
    return final_documents


class PDFLoader(DocumentLoaderStrategy):
    """PDF 파일 로더"""

    @property
    def supported_extensions(self) -> list[str]:
        return [".pdf", ".PDF"]

    async def load(self, file_path: Path) -> list[Document]:
        """PDF 파일 로드(pypdf).

        #13: 빈/스캔 페이지도 진단 메타와 함께 방출한다(침묵 손실 방지).
        #12: 추출 후 품질 게이트(기본 OFF)를 적용해 mojibake를 가시화/차단한다.
        """
        documents: list[Document] = []
        try:
            with open(file_path, "rb") as file:
                reader = PdfReader(file)
                for page_index, page in enumerate(reader.pages):
                    try:
                        text = _normalize_pdf_text(page.extract_text())
                        warnings = ["no_extractable_text"] if not text else []
                        documents.append(
                            Document(
                                page_content=text,
                                metadata=_pdf_page_metadata(
                                    page_index,
                                    scanned_page=not bool(text),
                                    extraction_warnings=warnings,
                                ),
                            )
                        )
                    except Exception as e:  # noqa: BLE001 - 페이지 실패도 보존(drop 금지)
                        logger.warning(
                            f"Failed to extract text from page {page_index + 1}: {e}"
                        )
                        documents.append(
                            Document(
                                page_content="",
                                metadata=_pdf_page_metadata(
                                    page_index,
                                    scanned_page=True,
                                    extraction_warnings=[f"text_extraction_failed: {e}"],
                                ),
                            )
                        )
            logger.info(f"PDF loaded: {len(documents)} pages from {file_path.name}")
            # 추출 품질 게이트 적용(기본 OFF). mojibake 미달 시 PyMuPDF 폴백/경고/실패 처리.
            return _apply_quality_gate(documents, file_path)
        except Exception as e:
            logger.error(f"PDF loading failed for {file_path}: {e}")
            raise ValueError(f"Failed to load PDF file: {e}") from e
