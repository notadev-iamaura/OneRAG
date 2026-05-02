"""
Rule-Based Metadata Extractor - 규칙 기반 메타데이터 추출 (MVP)
"""

import re
from typing import Any

from app.lib.logger import get_logger

from ..models import Chunk
from .base import BaseMetadataExtractor

logger = get_logger(__name__)


class RuleBasedExtractor(BaseMetadataExtractor):
    """
    규칙 기반 메타데이터 추출기

    정규식과 키워드 매칭을 사용하여 메타데이터를 추출합니다.
    LLM을 사용하지 않으므로 비용이 없고 속도가 빠릅니다.

    추출 항목:
    - contains_numeric: 수치/금액 정보 포함 여부
    - keywords: 핵심 키워드 리스트 (한국어 형태소 분석)
    - has_date: 날짜 정보 포함 여부
    - has_phone: 전화번호 포함 여부
    - has_email: 이메일 포함 여부
    - content_type: 콘텐츠 유형 (question, instruction, info 등)

    사용 예시:
        >>> extractor = RuleBasedExtractor()
        >>> chunk = Chunk(content="서비스 이용 방법은...")
        >>> metadata = extractor.extract(chunk)
        >>> metadata['keywords']
        ['서비스', '이용', '방법']
    """

    # 정규식 패턴 (클래스 변수로 한 번만 컴파일)
    NUMERIC_PATTERN = re.compile(r"\d{1,3}(,\d{3})*원|\d+만원|₩\d+")
    DATE_PATTERN = re.compile(r"\d{4}년\s*\d{1,2}월\s*\d{1,2}일|\d{1,2}월\s*\d{1,2}일")
    PHONE_PATTERN = re.compile(r"\d{2,3}-\d{3,4}-\d{4}")
    EMAIL_PATTERN = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")

    # 도메인별 키워드 (범용 예시)
    DOMAIN_KEYWORDS = {
        "정보": ["정보", "안내", "설명", "내용"],
        "절차": ["방법", "절차", "이용", "가이드"],
        "비용": ["가격", "비용", "금액", "요금", "예산"],
        "문의": ["문의", "답변", "질문", "상담"],
        "예약": ["예약", "계약", "일정", "날짜"],
        "위치": ["위치", "주소", "장소", "지도"],
    }

    def __init__(self, use_konlpy: bool = True):
        """
        RuleBasedExtractor 초기화

        Args:
            use_konlpy: KoNLPy 형태소 분석기 사용 여부 (기본: True)
                        False면 단순 공백 분리 사용
        """
        self.use_konlpy = use_konlpy
        self.okt = None

        if self.use_konlpy:
            try:
                from konlpy.tag import Okt

                self.okt = Okt()
                logger.debug("KoNLPy Okt initialized for keyword extraction")
            except ImportError:
                logger.warning(
                    "KoNLPy not available. Install with: pip install konlpy. "
                    "Using simple word splitting instead."
                )
                self.use_konlpy = False

    def extract(self, chunk: Chunk) -> dict[str, Any]:
        """
        청크에서 메타데이터 추출

        Args:
            chunk: 메타데이터를 추출할 청크

        Returns:
            추출된 메타데이터 딕셔너리
        """
        self.validate_chunk(chunk)

        content = chunk.content
        metadata = {}

        # 1. 수치/금액 정보 추출
        metadata["contains_numeric"] = bool(self.NUMERIC_PATTERN.search(content))
        if metadata["contains_numeric"]:
            numeric_matches = self.NUMERIC_PATTERN.findall(content)
            metadata["numeric_mentions"] = len(numeric_matches)  # type: ignore[assignment]

        # 2. 날짜 정보 추출
        metadata["has_date"] = bool(self.DATE_PATTERN.search(content))  # type: ignore[assignment]

        # 3. 전화번호 추출
        metadata["has_phone"] = bool(self.PHONE_PATTERN.search(content))  # type: ignore[assignment]

        # 4. 이메일 추출
        metadata["has_email"] = bool(self.EMAIL_PATTERN.search(content))  # type: ignore[assignment]

        # 5. 키워드 추출
        keywords = self._extract_keywords(content)
        metadata["keywords"] = keywords[:10]  # type: ignore[assignment]  # 상위 10개만
        metadata["keyword_count"] = len(keywords)  # type: ignore[assignment]

        # 6. 도메인 카테고리 추출
        categories = self._extract_categories(content)
        if categories:
            metadata["categories"] = categories  # type: ignore[assignment]

        # 7. 콘텐츠 유형 추론
        content_type = self._infer_content_type(content)
        metadata["content_type"] = content_type  # type: ignore[assignment]

        # 8. 텍스트 통계
        metadata["sentence_count"] = content.count(".") + content.count("?") + content.count("!")  # type: ignore[assignment]
        metadata["char_count"] = len(content)  # type: ignore[assignment]
        metadata["word_count"] = len(content.split())  # type: ignore[assignment]

        logger.debug(
            f"Extracted metadata: {len(keywords)} keywords, "
            f"categories: {categories}, type: {content_type}"
        )

        return metadata

    def _extract_keywords(self, text: str) -> list[str]:
        """
        텍스트에서 키워드 추출

        Args:
            text: 추출할 텍스트

        Returns:
            키워드 리스트
        """
        if self.okt:
            # 형태소 분석기로 명사 추출
            nouns = self.okt.nouns(text)
            # 2글자 이상 명사만 필터링
            keywords = [noun for noun in nouns if len(noun) >= 2]
        else:
            # 단순 공백 분리 (fallback)
            words = text.split()
            # 3글자 이상 단어만 필터링
            keywords = [word.strip() for word in words if len(word.strip()) >= 3]

        # 중복 제거하면서 순서 유지
        seen = set()
        unique_keywords = []
        for keyword in keywords:
            if keyword not in seen:
                seen.add(keyword)
                unique_keywords.append(keyword)

        return unique_keywords

    def _extract_categories(self, text: str) -> list[str]:
        """
        도메인별 카테고리 추출

        Args:
            text: 추출할 텍스트

        Returns:
            카테고리 리스트
        """
        categories = []

        for category, keywords in self.DOMAIN_KEYWORDS.items():
            for keyword in keywords:
                if keyword in text:
                    categories.append(category)
                    break  # 한 카테고리당 한 번만 추가

        return categories

    def _infer_content_type(self, text: str) -> str:
        """
        콘텐츠 유형 추론

        Args:
            text: 추론할 텍스트

        Returns:
            콘텐츠 유형 ('question', 'instruction', 'info', 'conversation')
        """
        # 질문 패턴
        if "?" in text or any(q in text for q in ["언제", "어디", "무엇", "어떻게", "왜"]):
            return "question"

        # 지시/안내 패턴
        if any(i in text for i in ["해주세요", "하세요", "합니다", "주의"]):
            return "instruction"

        # 대화 패턴
        if any(c in text for c in ["안녕", "감사", "문의", "답변"]):
            return "conversation"

        # 기본: 정보
        return "info"

    def validate_chunk(self, chunk: Chunk) -> None:
        """
        청크 검증

        Args:
            chunk: 검증할 청크

        Raises:
            ValueError: 잘못된 청크
        """
        super().validate_chunk(chunk)

        # 최소 길이 체크 (너무 짧으면 메타데이터 추출 의미 없음)
        if len(chunk.content) < 10:
            logger.warning(f"Chunk content too short ({len(chunk.content)} chars)")
