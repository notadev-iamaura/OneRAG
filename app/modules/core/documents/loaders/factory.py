"""
Loader Factory
Strategy 패턴 기반 로더 팩토리
"""

from pathlib import Path

from .....lib.logger import get_logger
from .base import DocumentLoaderStrategy
from .csv_loader import CSVLoader
from .docx_loader import DOCXLoader
from .html_loader import HTMLLoader
from .json_loader import JSONLoader
from .markdown_loader import MarkdownLoader
from .pdf_loader import PDFLoader
from .pptx_loader import PPTXLoader
from .text_loader import TextLoader
from .xlsx_loader import XLSXLoader

logger = get_logger(__name__)


class LoaderFactory:
    """
    문서 로더 팩토리

    파일 확장자에 따라 적절한 로더를 반환하는 팩토리 클래스.
    Strategy 패턴으로 구현되어 새로운 파일 타입 추가가 용이함.

    Usage:
        loader = LoaderFactory.get_loader("example.pdf")
        documents = await loader.load(Path("example.pdf"))
    """

    # 로더 인스턴스 캐싱 (싱글톤 패턴)
    _loaders: dict[str, DocumentLoaderStrategy] = {
        ".pdf": PDFLoader(),
        ".txt": TextLoader(),
        ".text": TextLoader(),
        ".docx": DOCXLoader(),
        ".doc": DOCXLoader(),  # #26: 레거시 .doc는 LibreOffice 변환 후 DOCX 경로 재사용
        ".pptx": PPTXLoader(),
        ".xlsx": XLSXLoader(),
        ".xls": XLSXLoader(),
        ".csv": CSVLoader(),
        ".html": HTMLLoader(),
        ".htm": HTMLLoader(),
        ".md": MarkdownLoader(),
        ".markdown": MarkdownLoader(),
        ".json": JSONLoader(),
    }

    @classmethod
    def get_loader(cls, file_path: str | Path) -> DocumentLoaderStrategy | None:
        """
        파일 경로에 맞는 로더 반환

        Args:
            file_path: 파일 경로 (문자열 또는 Path 객체)

        Returns:
            적절한 로더 인스턴스, 지원하지 않는 파일 타입이면 None

        Example:
            >>> loader = LoaderFactory.get_loader("document.pdf")
            >>> loader = LoaderFactory.get_loader(Path("document.pdf"))
        """
        if isinstance(file_path, str):
            file_path = Path(file_path)

        ext = file_path.suffix.lower()

        if ext not in cls._loaders:
            logger.warning(f"Unsupported file type: {ext}")
            return None

        logger.debug(f"Loader selected for {ext}: {cls._loaders[ext].__class__.__name__}")
        return cls._loaders[ext]

    @classmethod
    def register_loader(cls, extension: str, loader: DocumentLoaderStrategy) -> None:
        """
        새로운 로더 등록 (런타임 확장 가능)

        Args:
            extension: 파일 확장자 (예: '.pdf')
            loader: 로더 인스턴스

        Example:
            >>> custom_loader = MyCustomLoader()
            >>> LoaderFactory.register_loader('.custom', custom_loader)
        """
        if not extension.startswith("."):
            extension = f".{extension}"

        cls._loaders[extension.lower()] = loader
        logger.info(f"Registered new loader for {extension}: {loader.__class__.__name__}")

    @classmethod
    def get_supported_extensions(cls) -> list[str]:
        """
        지원하는 모든 파일 확장자 반환

        Returns:
            확장자 리스트
        """
        return list(cls._loaders.keys())

    @classmethod
    def is_supported(cls, file_path: str | Path) -> bool:
        """
        파일 타입 지원 여부 확인

        Args:
            file_path: 파일 경로

        Returns:
            지원 여부
        """
        if isinstance(file_path, str):
            file_path = Path(file_path)

        return file_path.suffix.lower() in cls._loaders
