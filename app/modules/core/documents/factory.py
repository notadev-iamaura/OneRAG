"""
Document Processor Factory - 문서 처리 전략 팩토리 패턴
"""

from typing import Any

from app.lib.logger import get_logger

from .base import BaseDocumentProcessor
from .processors import FAQProcessor

logger = get_logger(__name__)


class DocumentProcessorFactory:
    """
    문서 유형에 따라 적절한 프로세서를 생성하는 팩토리 클래스

    Factory 패턴을 사용하여 문서 유형별 프로세서 생성을 캡슐화합니다.

    지원하는 문서 유형:
    - 'faq': FAQProcessor (MVP)
    - 'guidebook': GuidebookProcessor (Phase 2, 미구현)
    - 'chatlog': ChatLogProcessor (Phase 2, 미구현)

    사용 예시:
        >>> processor = DocumentProcessorFactory.create('faq')
        >>> chunks = processor.process('data/faq.xlsx')

        >>> # 커스텀 설정
        >>> processor = DocumentProcessorFactory.create(
        ...     'faq',
        ...     content_template='Q: {question}\\nA: {answer}'
        ... )
    """

    # 등록된 프로세서 매핑 (Phase별 확장 가능)
    _processors = {
        "faq": FAQProcessor,
        # Phase 2에서 추가 예정:
        # 'guidebook': GuidebookProcessor,
        # 'chatlog': ChatLogProcessor,
        # 'weblink': WebLinkProcessor,
    }

    @classmethod
    def create(cls, doc_type: str, **kwargs: Any) -> BaseDocumentProcessor:
        """
        문서 유형에 맞는 프로세서 생성

        Args:
            doc_type: 문서 유형 ('faq', 'guidebook', 'chatlog')
            **kwargs: 프로세서별 추가 인자
                - content_template: 청크 내용 템플릿 (FAQ)
                - chunker: 커스텀 청킹 전략
                - metadata_extractor: 커스텀 메타데이터 추출기

        Returns:
            BaseDocumentProcessor 구현체

        Raises:
            ValueError: 지원하지 않는 문서 유형

        사용 예시:
            >>> # 기본 FAQ 프로세서
            >>> processor = DocumentProcessorFactory.create('faq')

            >>> # 커스텀 템플릿 사용
            >>> processor = DocumentProcessorFactory.create(
            ...     'faq',
            ...     content_template='Q: {question}\\nA: {answer}'
            ... )

            >>> # 커스텀 전략 주입
            >>> from app.modules.core.documents.chunking import SimpleChunker
            >>> processor = DocumentProcessorFactory.create(
            ...     'faq',
            ...     chunker=SimpleChunker(...)
            ... )
        """
        # 대소문자 구분 없이 처리
        doc_type_normalized = doc_type.lower().strip()

        if doc_type_normalized not in cls._processors:
            available = ", ".join(cls._processors.keys())
            raise ValueError(
                f"Unsupported document type: '{doc_type}'. " f"Available types: {available}"
            )

        processor_class = cls._processors[doc_type_normalized]
        logger.info(f"Creating {processor_class.__name__} for doc_type='{doc_type}'")

        try:
            processor = processor_class(**kwargs)
            logger.info(f"{processor_class.__name__} created successfully")
            return processor

        except Exception as e:
            logger.error(f"Failed to create {processor_class.__name__}: {e}")
            raise

    @classmethod
    def register(cls, doc_type: str, processor_class: type[BaseDocumentProcessor]) -> None:
        """
        새로운 프로세서 등록 (확장성)

        사용자가 커스텀 프로세서를 동적으로 등록할 수 있습니다.

        Args:
            doc_type: 문서 유형 이름
            processor_class: BaseDocumentProcessor 구현 클래스

        Raises:
            TypeError: BaseDocumentProcessor를 상속하지 않은 클래스
            ValueError: 이미 등록된 doc_type

        사용 예시:
            >>> class MyProcessor(BaseDocumentProcessor):
            ...     def load(self, source):
            ...         return Document(...)
            >>> DocumentProcessorFactory.register('custom', MyProcessor)
            >>> processor = DocumentProcessorFactory.create('custom')
        """
        # 타입 검증
        if not issubclass(processor_class, BaseDocumentProcessor):
            raise TypeError(f"{processor_class.__name__} must inherit from BaseDocumentProcessor")

        # 중복 검증
        if doc_type in cls._processors:
            logger.warning(f"Overwriting existing processor for doc_type='{doc_type}'")

        cls._processors[doc_type] = processor_class  # type: ignore[assignment]
        logger.info(f"Registered {processor_class.__name__} for doc_type='{doc_type}'")

    @classmethod
    def get_supported_types(cls) -> list[str]:
        """
        지원하는 문서 유형 목록 반환

        Returns:
            문서 유형 리스트
        """
        return list(cls._processors.keys())

    @classmethod
    def is_supported(cls, doc_type: str) -> bool:
        """
        문서 유형 지원 여부 확인

        Args:
            doc_type: 확인할 문서 유형

        Returns:
            지원 여부
        """
        return doc_type.lower().strip() in cls._processors

    @classmethod
    def get_processor_info(cls, doc_type: str) -> dict[str, Any]:
        """
        프로세서 정보 반환

        Args:
            doc_type: 문서 유형

        Returns:
            프로세서 정보 딕셔너리

        Raises:
            ValueError: 지원하지 않는 문서 유형
        """
        doc_type_normalized = doc_type.lower().strip()

        if doc_type_normalized not in cls._processors:
            raise ValueError(f"Unsupported document type: '{doc_type}'")

        processor_class = cls._processors[doc_type_normalized]

        return {
            "doc_type": doc_type,
            "processor_class": processor_class.__name__,
            "module": processor_class.__module__,
            "docstring": processor_class.__doc__,
        }

    @classmethod
    def get_all_info(cls) -> dict[str, dict[str, Any]]:
        """
        모든 프로세서 정보 반환

        Returns:
            {doc_type: info} 형태의 딕셔너리
        """
        return {doc_type: cls.get_processor_info(doc_type) for doc_type in cls._processors.keys()}
