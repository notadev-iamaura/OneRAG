"""
FAQ Processor - FAQ 문서 전용 프로세서 (MVP)
"""

from pathlib import Path
from typing import Any

import pandas as pd

from app.lib.logger import get_logger

from ..base import BaseDocumentProcessor
from ..chunking import SimpleChunker
from ..metadata import RuleBasedExtractor
from ..models import Document

logger = get_logger(__name__)


class FAQProcessor(BaseDocumentProcessor):
    """
    FAQ 문서 전용 프로세서

    Excel/CSV 파일에서 FAQ 데이터를 로드하고 처리합니다.
    - 1개 FAQ = 1개 청크 (SimpleChunker)
    - 규칙 기반 메타데이터 추출 (RuleBasedExtractor)

    파일 형식 요구사항:
    - Excel (.xlsx, .xls) 또는 CSV (.csv)
    - 필수 컬럼: '질문' or 'question', '답변' or 'answer'
    - 선택 컬럼: '섹션명' or 'section', '카테고리' or 'category'

    사용 예시:
        >>> processor = FAQProcessor()
        >>> chunks = processor.process('data/faq.xlsx')
        >>> len(chunks)
        175
        >>> chunks[0].metadata['section']
        '서비스'
    """

    def __init__(
        self,
        chunker: SimpleChunker | None = None,
        metadata_extractor: RuleBasedExtractor | None = None,
        # 범용화: 기본 content_template을 언어중립("{question}\n{answer}")으로 통일한다.
        # 과거 기본값("질문: ...\n답변: ...")은 한국어 라벨이 섞여 SimpleChunker의
        # 기본값과도 불일치했다. 한국어 라벨이 필요한 운영자는 인자/팩토리로
        # content_template을 명시 주입하면 된다(예: "질문: {question}\n답변: {answer}").
        content_template: str = "{question}\n{answer}",
        category_keywords: dict[str, list[str]] | None = None,
        content_type_markers: dict[str, list[str]] | None = None,
        column_aliases: dict[str, list[str]] | None = None,
        numeric_pattern: str | None = None,
        date_pattern: str | None = None,
        phone_pattern: str | None = None,
        use_konlpy: bool = True,
    ):
        """
        FAQProcessor 초기화

        Args:
            chunker: 청킹 전략 (기본: SimpleChunker)
            metadata_extractor: 메타데이터 추출 전략 (기본: RuleBasedExtractor)
            content_template: 청크 내용 생성 템플릿. 기본값은 언어중립
                "{question}\n{answer}"(SimpleChunker와 통일). 한국어 라벨이
                필요하면 "질문: {question}\n답변: {answer}"처럼 명시 주입한다.
            category_keywords: 도메인 카테고리 분류 키워드. 기본 추출기를 생성할 때
                주입한다(미지정 시 도메인 중립 — 카테고리 미추출). domain.yaml의
                `domain.metadata.category_keywords`에서 전달.
            content_type_markers: 콘텐츠 타입 추론 마커. 기본 추출기 생성 시 주입한다.
                미지정 시 코드 내장 한국어 기본 마커 사용(회귀 0). domain.yaml의
                `domain.metadata.content_type_markers`에서 전달.
            column_aliases: 질문/답변/섹션/카테고리 컬럼 별칭 맵
                ({"question": [...], "answer": [...], "section": [...], "category": [...]}).
                기본 청커(SimpleChunker)에 주입한다(section/category도 청커가 메타
                인식에 사용). 미지정 시 코드 내장 ko+en 기본 별칭 사용(회귀 0).
                uploads.yaml의 `uploads.faq.column_aliases`에서 전달.
            numeric_pattern: 수치/금액 탐지 정규식. 기본 추출기(RuleBasedExtractor)
                생성 시 주입한다. 미지정 시 코드 내장 한국어 통화 패턴 사용(회귀 0).
                domain.yaml의 `domain.metadata.numeric_pattern`에서 전달.
            date_pattern: 날짜 탐지 정규식. 미지정 시 한국어 날짜 패턴 사용(회귀 0).
                domain.yaml의 `domain.metadata.date_pattern`에서 전달.
            phone_pattern: 전화번호 탐지 정규식. 미지정 시 한국 전화형식 사용(회귀 0).
                domain.yaml의 `domain.metadata.phone_pattern`에서 전달.
            use_konlpy: 기본 추출기의 KoNLPy(한국어 형태소 분석기 Okt) 사용 여부.
                기본 True(회귀 0). 비한국어 운영자는 False로 주입해 한국어 전용
                의존성 로드 시도를 끌 수 있다(미설치 시 공백 분리 폴백은 항상 안전).
        """
        # 기본 전략 설정
        if chunker is None:
            chunker = SimpleChunker(
                content_template=content_template,
                column_aliases=column_aliases,
            )

        if metadata_extractor is None:
            metadata_extractor = RuleBasedExtractor(
                use_konlpy=use_konlpy,
                category_keywords=category_keywords,
                content_type_markers=content_type_markers,
                numeric_pattern=numeric_pattern,
                date_pattern=date_pattern,
                phone_pattern=phone_pattern,
            )

        # 컬럼 검증/메타에서 재사용하기 위해 별칭을 청커와 단일 소스로 공유한다.
        self.column_aliases = chunker.column_aliases

        super().__init__(
            chunker=chunker,
            metadata_extractor=metadata_extractor,
            validator=None,  # FAQ는 별도 검증기 불필요
        )

        self.content_template = content_template
        logger.info("FAQProcessor initialized for MVP phase")

    def load(self, source: str | Path) -> Document:
        """
        FAQ 파일 로드

        Args:
            source: 파일 경로 (Excel 또는 CSV)

        Returns:
            Document 객체

        Raises:
            FileNotFoundError: 파일을 찾을 수 없음
            ValueError: 지원하지 않는 파일 형식 또는 잘못된 컬럼 구조
        """
        file_path = Path(source) if isinstance(source, str) else source

        # 파일 존재 확인
        if not file_path.exists():
            raise FileNotFoundError(f"FAQ file not found: {file_path}")

        # 파일 확장자 확인
        ext = file_path.suffix.lower()
        if ext not in [".xlsx", ".xls", ".csv"]:
            raise ValueError(f"Unsupported file format: {ext}. " f"Expected: .xlsx, .xls, or .csv")

        logger.info(f"Loading FAQ file: {file_path.name} ({ext})")

        try:
            # 파일 로드
            if ext == ".csv":
                df = pd.read_csv(file_path)
            else:
                df = pd.read_excel(file_path)

            logger.info(f"Loaded {len(df)} FAQ items from {file_path.name}")

            # 컬럼 검증
            self._validate_columns(df)

            # DataFrame을 딕셔너리 리스트로 변환
            faq_data = df.to_dict("records")

            # Document 객체 생성
            document = Document(
                source=file_path,
                doc_type="FAQ",
                data=faq_data,
                metadata={
                    "file_type": ext[1:],  # .xlsx -> xlsx
                    "total_items": len(faq_data),
                    "columns": list(df.columns),
                },
            )

            logger.info(f"FAQ Document created: {document}")
            return document

        except pd.errors.ParserError as e:
            logger.error(f"Failed to parse FAQ file: {e}")
            raise ValueError(f"Invalid file format: {e}") from e

        except Exception as e:
            logger.error(f"Failed to load FAQ file: {e}")
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

        # 필수 컬럼: 질문, 답변 (청커와 동일한 단일 소스 별칭 재사용 — 중복 제거)
        question_keys = self.column_aliases.get("question", [])
        answer_keys = self.column_aliases.get("answer", [])

        has_question = any(key in columns for key in question_keys)
        has_answer = any(key in columns for key in answer_keys)

        if not has_question:
            raise ValueError(
                f"Required column '질문' or 'question' not found. " f"Available columns: {columns}"
            )

        if not has_answer:
            raise ValueError(
                f"Required column '답변' or 'answer' not found. " f"Available columns: {columns}"
            )

        logger.debug("FAQ DataFrame columns validated")

    def validate(self, document: Document) -> Document:
        """
        FAQ 문서 검증

        Args:
            document: 검증할 문서

        Returns:
            검증된 문서

        Raises:
            ValueError: 검증 실패
        """
        # 기본 검증
        super().validate(document)

        # FAQ 특화 검증
        if document.doc_type != "FAQ":
            raise ValueError(f"Expected doc_type 'FAQ', got '{document.doc_type}'")

        if not isinstance(document.data, list):
            raise ValueError("FAQ data must be a list")

        if len(document.data) == 0:
            raise ValueError("FAQ data cannot be empty")

        logger.debug(f"FAQ document validated: {len(document.data)} items")
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
                "doc_type": "FAQ",
                "phase": "MVP",
                "content_template": self.content_template,
                "supported_formats": [".xlsx", ".xls", ".csv"],
            }
        )
        return stats
