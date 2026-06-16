"""XLSXLoader 날짜 셀 ISO 정규화 테스트 (GAP #6 차용).

검증 대상:
- 날짜/타임스탬프 셀이 pandas 기본 str()의 "2024-01-01 00:00:00" 노이즈 대신
  isoformat() 안정 표현으로 직렬화되는지(_excel_value_to_text).
- 헤더(컬럼명)와 셀 값 모두에 동일 정규화가 적용되는지.
- 일반 문자열/숫자 값은 기존 str() 동작과 동일하게 보존되는지(회귀 0).
"""

from datetime import date, datetime
from pathlib import Path

import pandas as pd
import pytest

from app.modules.core.documents.loaders.xlsx_loader import (
    XLSXLoader,
    _excel_value_to_text,
)


def test_excel_value_to_text_normalizes_timestamp() -> None:
    """pd.Timestamp는 isoformat()으로 변환되어 시각 노이즈가 제거된다."""
    value = pd.Timestamp("2024-01-01")
    assert _excel_value_to_text(value) == value.isoformat()
    # 자정(00:00:00) 노이즈가 본문에 남지 않아야 한다
    assert " 00:00:00" not in _excel_value_to_text(value)


def test_excel_value_to_text_normalizes_datetime_and_date() -> None:
    """datetime/date도 isoformat()으로 변환된다."""
    dt = datetime(2024, 3, 15, 9, 30, 0)
    d = date(2024, 3, 15)
    assert _excel_value_to_text(dt) == dt.isoformat()
    assert _excel_value_to_text(d) == d.isoformat()


def test_excel_value_to_text_preserves_non_date_values() -> None:
    """문자열/숫자/불리언은 기존 str() 동작과 동일하게 유지된다(회귀 방지)."""
    assert _excel_value_to_text("문서 제목") == "문서 제목"
    assert _excel_value_to_text(42) == "42"
    assert _excel_value_to_text(3.14) == "3.14"
    assert _excel_value_to_text(True) == "True"


@pytest.mark.asyncio
async def test_xlsx_load_emits_iso_dates(tmp_path: Path) -> None:
    """실제 xlsx 로드 시 날짜 컬럼·셀이 ISO 문자열로 직렬화된다."""
    df = pd.DataFrame(
        {
            "출하일": [pd.Timestamp("2024-01-01"), pd.Timestamp("2024-02-02")],
            "수량": [100, 200],
        }
    )
    xlsx_path = tmp_path / "sample.xlsx"
    df.to_excel(xlsx_path, index=False, sheet_name="출하내역")

    loader = XLSXLoader()
    documents = await loader.load(xlsx_path)

    assert len(documents) == 1
    content = documents[0].page_content
    # ISO 표현이 본문에 존재하고, 자정 노이즈는 없어야 한다
    assert "2024-01-01T00:00:00" in content
    assert "2024-01-01 00:00:00" not in content
    # 일반 숫자 셀은 그대로 보존
    assert "수량: 100" in content
