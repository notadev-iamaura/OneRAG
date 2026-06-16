"""
Point Rule Processor - 포인트 규정 문서 전용 프로세서

포인트 규정 Excel 파일을 로드하고 처리하는 전용 프로세서입니다.
각 포인트 항목을 개별 청크로 변환하여 검색 최적화를 수행합니다.

처리 파이프라인:
1. Excel 파일 로드 (Sheet1 사용)
2. 컬럼 검증 (항목명 필수)
3. 항목별 청킹 (1 항목 = 1 청크)
4. 메타데이터 추출 (point_amount, category 등)

파일 형식 요구사항:
- Excel (.xlsx, .xls)
- 필수 컬럼: '항목명'
- 권장 컬럼: '주제', '포인트적립액', '우수포인트 적립액', '횟수', '상세 적립규정'

사용 예시:
    >>> processor = PointRuleProcessor()
    >>> chunks = processor.process('data/포인트 규정.xlsx')
    >>> len(chunks)
    83
    >>> chunks[0].metadata['point_amount']
    30000
"""

from pathlib import Path
from typing import Any

import pandas as pd

from app.lib.logger import get_logger

from ..base import BaseDocumentProcessor
from ..chunking import PointRuleChunker
from ..metadata import RuleBasedExtractor
from ..models import Document

logger = get_logger(__name__)


class PointRuleProcessor(BaseDocumentProcessor):
    """
    포인트 규정 문서 전용 프로세서

    Excel 파일에서 포인트 규정 데이터를 로드하고 처리합니다.
    - 1개 항목 = 1개 청크 (PointRuleChunker)
    - 규칙 기반 메타데이터 추출 (RuleBasedExtractor)
    - HTML 상세 규정 파싱 지원

    Attributes:
        sheet_name: 읽을 시트 이름 (기본: 'Sheet1' 또는 첫 번째 시트)
        parse_html: HTML 콘텐츠 파싱 여부 (기본: True)

    사용 예시:
        >>> processor = PointRuleProcessor()
        >>> chunks = processor.process('data/포인트 규정.xlsx')
        >>> chunks[0].metadata['category']
        '소개포인트'
    """

    def __init__(
        self,
        chunker: PointRuleChunker | None = None,
        metadata_extractor: RuleBasedExtractor | None = None,
        sheet_name: str | int = 0,  # 첫 번째 시트
        parse_html: bool = True,
        category_keywords: dict[str, list[str]] | None = None,
    ):
        """
        PointRuleProcessor 초기화

        Args:
            chunker: 청킹 전략 (기본: PointRuleChunker)
            metadata_extractor: 메타데이터 추출 전략 (기본: RuleBasedExtractor)
            sheet_name: 읽을 시트 이름 또는 인덱스 (기본: 0 = 첫 번째 시트)
            parse_html: HTML 콘텐츠 파싱 여부 (기본: True)
            category_keywords: 도메인 카테고리 분류 키워드. 기본 추출기를 생성할 때
                주입한다(미지정 시 도메인 중립 — 카테고리 미추출). domain.yaml의
                `domain.metadata.category_keywords`에서 전달.
        """
        # 기본 전략 설정
        if chunker is None:
            chunker = PointRuleChunker(parse_html=parse_html)

        if metadata_extractor is None:
            metadata_extractor = RuleBasedExtractor(
                use_konlpy=True,
                category_keywords=category_keywords,
            )

        super().__init__(
            chunker=chunker,
            metadata_extractor=metadata_extractor,
            validator=None,  # 별도 검증기 불필요 (load에서 검증)
        )

        self.sheet_name = sheet_name
        self.parse_html = parse_html
        logger.info(f"PointRuleProcessor initialized (sheet={sheet_name})")

    def load(self, source: str | Path) -> Document:
        """
        포인트 규정 파일 로드

        Args:
            source: 파일 경로 (Excel)

        Returns:
            Document 객체

        Raises:
            FileNotFoundError: 파일을 찾을 수 없음
            ValueError: 지원하지 않는 파일 형식 또는 잘못된 컬럼 구조
        """
        file_path = Path(source) if isinstance(source, str) else source

        # 파일 존재 확인
        if not file_path.exists():
            raise FileNotFoundError(f"Point rule file not found: {file_path}")

        # 파일 확장자 확인
        ext = file_path.suffix.lower()
        if ext not in [".xlsx", ".xls"]:
            raise ValueError(f"Unsupported file format: {ext}. " f"Expected: .xlsx or .xls")

        logger.info(f"Loading point rule file: {file_path.name}")

        try:
            # Excel 파일 로드
            df = pd.read_excel(file_path, sheet_name=self.sheet_name)

            logger.info(f"Loaded {len(df)} items from {file_path.name}")
            logger.debug(f"Columns: {list(df.columns)}")

            # 컬럼 검증
            self._validate_columns(df)

            # NaN 값 처리
            df = df.fillna("")

            # DataFrame을 딕셔너리 리스트로 변환
            rule_data = df.to_dict("records")

            # Document 객체 생성
            document = Document(
                source=file_path,
                doc_type="POINT_RULE",
                data=rule_data,
                metadata={
                    "file_type": ext[1:],  # .xlsx -> xlsx
                    "total_items": len(rule_data),
                    "columns": list(df.columns),
                    "sheet_name": str(self.sheet_name),
                },
            )

            logger.info(f"Point rule Document created: {len(rule_data)} items")
            return document

        except pd.errors.ParserError as e:
            logger.error(f"Failed to parse point rule file: {e}")
            raise ValueError(f"Invalid file format: {e}") from e

        except Exception as e:
            logger.error(f"Failed to load point rule file: {e}")
            raise

    def _validate_columns(self, df: pd.DataFrame) -> None:
        """
        DataFrame 컬럼 검증

        Args:
            df: 검증할 DataFrame

        Raises:
            ValueError: 필수 컬럼 누락
        """
        columns = df.columns.tolist()
        logger.debug(f"DataFrame columns: {columns}")

        # 필수 컬럼: 항목명
        required_columns = ["항목명"]

        missing = [col for col in required_columns if col not in columns]
        if missing:
            raise ValueError(
                f"Required columns not found: {missing}. " f"Available columns: {columns}"
            )

        # 권장 컬럼 확인 (경고만)
        recommended_columns = ["주제", "포인트적립액", "상세 적립규정"]
        missing_recommended = [col for col in recommended_columns if col not in columns]
        if missing_recommended:
            logger.warning(f"Recommended columns not found: {missing_recommended}")

        logger.debug("Point rule DataFrame columns validated")

    def validate(self, document: Document) -> Document:
        """
        포인트 규정 문서 검증

        Args:
            document: 검증할 문서

        Returns:
            검증된 문서

        Raises:
            ValueError: 검증 실패
        """
        # 기본 검증
        super().validate(document)

        # 포인트 규정 특화 검증
        if document.doc_type != "POINT_RULE":
            raise ValueError(f"Expected doc_type 'POINT_RULE', got '{document.doc_type}'")

        if not isinstance(document.data, list):
            raise ValueError("Point rule data must be a list")

        if len(document.data) == 0:
            raise ValueError("Point rule data cannot be empty")

        logger.debug(f"Point rule document validated: {len(document.data)} items")
        return document

    def get_stats(self) -> dict[str, Any]:
        """
        프로세서 통계 반환

        Returns:
            통계 딕셔너리
        """
        stats = super().get_stats()
        stats.update(
            {
                "doc_type": "POINT_RULE",
                "phase": "MVP",
                "sheet_name": self.sheet_name,
                "parse_html": self.parse_html,
                "supported_formats": [".xlsx", ".xls"],
            }
        )
        return stats
