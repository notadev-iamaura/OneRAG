"""XLSX Document Loader"""

from pathlib import Path

import pandas as pd
from langchain_core.documents import Document

from .....lib.logger import get_logger
from .base import DocumentLoaderStrategy

logger = get_logger(__name__)


class XLSXLoader(DocumentLoaderStrategy):
    """Excel 파일 로더"""

    @property
    def supported_extensions(self) -> list[str]:
        return [".xlsx", ".XLSX", ".xls", ".XLS"]

    async def load(self, file_path: Path) -> list[Document]:
        """XLSX 파일 로드"""
        try:
            documents = []
            xl_file = pd.ExcelFile(file_path)
            for sheet_name in xl_file.sheet_names:
                df = pd.read_excel(file_path, sheet_name=sheet_name)
                column_names = [str(col) for col in df.columns.tolist()]
                content_parts = [f"시트: {sheet_name}", f"컬럼: {', '.join(column_names)}"]
                for _idx, row in df.iterrows():
                    row_text = [
                        f"{str(col)}: {value}"
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
