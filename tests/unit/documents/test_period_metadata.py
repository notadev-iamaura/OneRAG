"""파일명 연도/분기 메타데이터 추출 단위 테스트 (#27).

검증 항목:
    1. 범용 연도(19xx/20xx) 추출 → doc_years.
    2. 다국어 분기(Q1-4 / N분기) 추출 → quarter.
    3. 추출 실패 시 키 미포함(빈 값 미저장).
    4. config로 추가 분기 패턴 주입 가능(도메인 비종속).
"""

from __future__ import annotations

from app.modules.core.documents.document_processing import extract_period_metadata


def test_extract_year_western_pattern() -> None:
    meta = extract_period_metadata("financial_report_2024.pdf")
    assert meta["doc_years"] == [2024]


def test_extract_year_supports_19xx() -> None:
    meta = extract_period_metadata("archive_1998_summary.txt")
    assert meta["doc_years"] == [1998]


def test_extract_multiple_years_sorted_unique() -> None:
    meta = extract_period_metadata("compare_2023_vs_2024.xlsx")
    assert meta["doc_years"] == [2023, 2024]


def test_extract_quarter_english() -> None:
    meta = extract_period_metadata("financial_2024_Q2.xlsx")
    assert meta["quarter"] == "Q2"
    assert meta["doc_years"] == [2024]


def test_extract_quarter_korean() -> None:
    meta = extract_period_metadata("2024년_2분기_실적.pdf")
    assert meta["quarter"] == "Q2"
    assert meta["doc_years"] == [2024]


def test_extract_no_match_returns_empty_keys() -> None:
    meta = extract_period_metadata("notes.txt")
    assert "doc_years" not in meta
    assert "quarter" not in meta


def test_extract_with_extra_config_patterns() -> None:
    """config로 추가 분기 패턴(예: 일본어 第N四半期)을 주입해 도메인 확장이 가능해야 한다."""
    meta = extract_period_metadata(
        "report_第2四半期.pdf",
        extra_quarter_patterns=[r"第\s*([1-4])\s*四半期"],
    )
    assert meta["quarter"] == "Q2"
