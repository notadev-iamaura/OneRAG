"""
RuleBasedExtractor 카테고리 키워드 도메인 범용화 테스트

예약형 서비스업 카테고리 키워드(예약/계약, 비용/요금, 문의/상담, 위치/주소 등)
하드코딩을 제거하고 config 주입으로 전환한 변경을 검증한다.

핵심 단언:
- (a) config 미설정 시 카테고리가 추출되지 않음(도메인 중립 = 빈 dict)
- (b) category_keywords 주입 시 카테고리 분류 동작
"""

from app.modules.core.documents.metadata.rule_based import RuleBasedExtractor
from app.modules.core.documents.models import Chunk


def _chunk(text: str) -> Chunk:
    """테스트용 청크 생성 헬퍼"""
    return Chunk(content=text)


class TestCategoryKeywordsNeutralDefault:
    """기본값(도메인 중립) 검증"""

    def test_no_domain_keywords_class_attr(self) -> None:
        """클래스 상수 DOMAIN_KEYWORDS가 제거되어야 한다"""
        assert not hasattr(RuleBasedExtractor, "DOMAIN_KEYWORDS"), (
            "도메인 키워드는 클래스 상수가 아닌 config 주입이어야 한다"
        )

    def test_default_category_keywords_empty(self) -> None:
        """기본 생성 시 category_keywords는 빈 dict여야 한다"""
        extractor = RuleBasedExtractor(use_konlpy=False)
        assert extractor.category_keywords == {}

    def test_no_categories_extracted_by_default(self) -> None:
        """config 미설정 시 카테고리가 추출되지 않아야 한다(오염 방지)"""
        extractor = RuleBasedExtractor(use_konlpy=False)
        # 과거 예약형 도메인 키워드였던 단어가 포함되어도 카테고리 미추출
        metadata = extractor.extract(_chunk("예약 비용 문의 위치 안내입니다."))
        assert "categories" not in metadata, (
            "도메인 미설정 시 잘못된 카테고리 오염이 발생하면 안 됨"
        )


class TestCategoryKeywordsInjection:
    """config 주입 시 카테고리 분류 동작 검증"""

    def test_injected_keywords_extract_categories(self) -> None:
        """주입한 키워드로 카테고리 추출이 동작해야 한다"""
        keywords = {
            "진료": ["진료", "처방"],
            "보험": ["보험", "청구"],
        }
        extractor = RuleBasedExtractor(use_konlpy=False, category_keywords=keywords)
        metadata = extractor.extract(_chunk("진료 후 처방전과 보험 청구 안내입니다."))
        assert "categories" in metadata
        assert "진료" in metadata["categories"]
        assert "보험" in metadata["categories"]

    def test_unmatched_text_no_categories(self) -> None:
        """주입했어도 매칭 안 되면 카테고리가 없어야 한다"""
        keywords = {"진료": ["진료", "처방"]}
        extractor = RuleBasedExtractor(use_konlpy=False, category_keywords=keywords)
        metadata = extractor.extract(_chunk("전혀 관련 없는 일반적인 문장입니다."))
        assert "categories" not in metadata
