"""
Document Model - 원본 문서 데이터 모델
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, ClassVar


@dataclass
class Document:
    """
    원본 문서를 표현하는 데이터 모델

    문서 로딩 단계에서 생성되며, 청킹 전의 원본 데이터를 담고 있습니다.

    Attributes:
        source: 문서 출처 (파일 경로, URL 등)
        doc_type: 문서 유형. 도메인 중립 기본은 'FAQ'/'Custom'이며, 운영자는
            DocumentProcessorFactory.register()로 자기 문서종류를 등록하면
            자동으로 허용된다(VALID_DOC_TYPES에 추가됨).
        data: 원본 데이터 (dict 리스트, 텍스트 등)
        metadata: 문서 메타데이터
        created_at: 생성 시각 (UTC)

    사용 예시:
        >>> doc = Document(
        ...     source='data/faq.xlsx',
        ...     doc_type='FAQ',
        ...     data=[{'질문': '...', '답변': '...'}]
        ... )
        >>> print(doc.doc_type)
        FAQ
        >>> print(doc.total_items)
        175
    """

    # 허용 문서종류(도메인 중립 기본). 특정 도메인 종류를 박지 않는다.
    # DocumentProcessorFactory.register()가 등록 종류를 여기에 추가하므로,
    # 커스텀 프로세서를 등록한 운영자의 문서종류가 코드 포크 없이 허용된다
    # (닫힌 enum이 register() 확장성과 충돌하던 잠재 버그 해소). 대소문자 무시.
    VALID_DOC_TYPES: ClassVar[set[str]] = {"FAQ", "Custom"}

    source: str | Path
    doc_type: str
    data: Any
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        """초기화 후 검증 및 자동 메타데이터 생성"""
        # source를 Path 객체로 변환
        if isinstance(self.source, str):
            self.source = Path(self.source)

        # doc_type 검증 — 도메인 중립 기본 + factory.register()로 확장된 종류 허용.
        # 대소문자 무시(factory 키는 소문자, Document는 TitleCase를 쓰므로).
        allowed = {t.lower() for t in self.VALID_DOC_TYPES}
        if self.doc_type.lower() not in allowed:
            raise ValueError(
                f"Invalid doc_type: {self.doc_type}. "
                f"Must be one of {sorted(self.VALID_DOC_TYPES)} "
                "또는 DocumentProcessorFactory.register()로 등록된 종류."
            )

        # 자동 메타데이터 추가
        if "source_name" not in self.metadata:
            self.metadata["source_name"] = (
                self.source.name if isinstance(self.source, Path) else str(self.source)
            )

        if "doc_type" not in self.metadata:
            self.metadata["doc_type"] = self.doc_type

    @property
    def total_items(self) -> int:
        """데이터 항목 개수"""
        if isinstance(self.data, list):
            return len(self.data)
        elif isinstance(self.data, dict):
            return len(self.data)
        elif isinstance(self.data, str):
            return 1
        return 0

    @property
    def is_structured(self) -> bool:
        """구조화된 데이터 여부 (리스트 또는 딕셔너리)"""
        return isinstance(self.data, list | dict)

    def to_dict(self) -> dict[str, Any]:
        """딕셔너리로 변환"""
        return {
            "source": str(self.source),
            "doc_type": self.doc_type,
            "data": self.data,
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat(),
            "total_items": self.total_items,
            "is_structured": self.is_structured,
        }

    def __repr__(self) -> str:
        """문자열 표현"""
        source_name = self.source.name if isinstance(self.source, Path) else str(self.source)
        return (
            f"Document(source='{source_name}', "
            f"doc_type='{self.doc_type}', "
            f"total_items={self.total_items})"
        )
