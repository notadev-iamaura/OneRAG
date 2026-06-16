"""CSV Document Loader"""

from pathlib import Path

import pandas as pd
from langchain_core.documents import Document

from .....lib.logger import get_logger
from .base import DocumentLoaderStrategy
from .labels import get_loader_labels

logger = get_logger(__name__)


class CSVLoader(DocumentLoaderStrategy):
    """CSV 파일 로더"""

    @property
    def supported_extensions(self) -> list[str]:
        return [".csv", ".CSV"]

    async def load(self, file_path: Path) -> list[Document]:
        """CSV 파일 로드"""
        try:
            labels = get_loader_labels()
            df = pd.read_csv(file_path)
            content_parts = [f"{labels['column']}: {', '.join(df.columns.tolist())}"]
            for _idx, row in df.iterrows():
                row_text = [f"{col}: {value}" for col, value in row.items() if pd.notna(value)]
                if row_text:
                    content_parts.append(" | ".join(row_text))
            content = "\n".join(content_parts)
            documents = [Document(page_content=content, metadata={})]
            logger.info(f"CSV loaded: {len(df)} rows from {file_path.name}")
            return documents
        except Exception as e:
            logger.error(f"CSV loading failed: {e}")
            raise ValueError(f"Failed to load CSV file: {e}") from e
