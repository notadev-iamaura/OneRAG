"""XLSX Document Loader"""

from datetime import date, datetime
from pathlib import Path

import pandas as pd
from langchain_core.documents import Document

from .....lib.logger import get_logger
from .base import DocumentLoaderStrategy
from .labels import get_loader_labels

logger = get_logger(__name__)


def _excel_value_to_text(value: object) -> str:
    """Excel 헤더/셀 값을 검색 친화적인 안정 문자열로 변환한다(GAP #6).

    pandas 기본 str()은 날짜 셀을 "2024-01-01 00:00:00"처럼 자정 노이즈가 붙은
    표현으로 직렬화해 검색 품질을 떨어뜨린다. pd.Timestamp/datetime/date는
    isoformat()으로 변환해 일관된 ISO 표현("2024-01-01T00:00:00")을 보장하고,
    그 외 값(문자열·숫자·불리언)은 기존 str() 동작을 그대로 유지한다(회귀 0).

    Args:
        value: Excel 헤더 또는 셀 원본 값.

    Returns:
        ISO 정규화된 문자열(날짜류) 또는 str() 변환 결과(그 외).
    """
    if isinstance(value, pd.Timestamp | datetime | date):
        return value.isoformat()
    return str(value)


class XLSXLoader(DocumentLoaderStrategy):
    """Excel 파일 로더"""

    @property
    def supported_extensions(self) -> list[str]:
        return [".xlsx", ".XLSX", ".xls", ".XLS"]

    async def load(self, file_path: Path) -> list[Document]:
        """XLSX 파일 로드"""
        try:
            labels = get_loader_labels()
            documents = []
            xl_file = pd.ExcelFile(file_path)
            for sheet_name in xl_file.sheet_names:
                df = pd.read_excel(file_path, sheet_name=sheet_name)
                # 헤더(컬럼명)·셀 값 모두 ISO 정규화를 적용해 날짜 노이즈를 제거한다(GAP #6).
                column_names = [_excel_value_to_text(col) for col in df.columns.tolist()]
                content_parts = [
                    f"{labels['sheet']}: {sheet_name}",
                    f"{labels['column']}: {', '.join(column_names)}",
                ]
                for _idx, row in df.iterrows():
                    row_text = [
                        f"{_excel_value_to_text(col)}: {_excel_value_to_text(value)}"
                        for col, value in row.items()
                        if pd.notna(value)
                    ]
                    if row_text:
                        content_parts.append(" | ".join(row_text))
                content = "\n".join(content_parts)
                documents.append(Document(page_content=content, metadata={"sheet": sheet_name}))
            logger.info(f"XLSX loaded: {len(xl_file.sheet_names)} sheets from {file_path.name}")
            return documents
        except Exception as e:
            logger.error(f"XLSX loading failed: {e}")
            raise ValueError(f"Failed to load XLSX file: {e}") from e
