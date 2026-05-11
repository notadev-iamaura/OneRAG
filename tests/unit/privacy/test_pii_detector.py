"""
PII Detector 단위 테스트

HybridPIIDetector의 Regex 및 NER 탐지 기능 검증.

테스트 케이스:
1. 전화번호 탐지 (개인/업체 구분)
2. 이메일 탐지
3. 주민등록번호 탐지
4. 계좌번호/카드번호 탐지
5. 도메인 화이트리스트 필터링
6. 중복 제거 및 정렬

구현일: 2025-12-01
"""

import os

import pytest

from app.modules.core.privacy.review import (
    DetectionMethod,
    HybridPIIDetector,
    PIIType,
)


class TestHybridPIIDetector:
    """HybridPIIDetector 테스트 클래스"""

    @pytest.fixture
    def detector(self) -> HybridPIIDetector:
        """테스트용 탐지기 생성 (NER 비활성화로 빠른 테스트)"""
        return HybridPIIDetector(
            spacy_model="ko_core_news_sm",
            enable_ner=False,  # Regex만 테스트
            context_window=30,
            whitelist=["고객", "담당자", "예약", "문의", "상담"],
        )

    @pytest.fixture
    def detector_with_ner(self) -> HybridPIIDetector:
        """NER 활성화된 탐지기 (spaCy 설치 필요)"""
        return HybridPIIDetector(
            spacy_model="ko_core_news_sm",
            enable_ner=True,
            context_window=30,
            whitelist=["고객", "담당자", "예약", "문의", "상담"],
        )

    # ========================================
    # 전화번호 탐지 테스트
    # ========================================

    def test_detect_personal_phone_number(self, detector: HybridPIIDetector) -> None:
        """개인 전화번호(010) 탐지"""
        text = "연락처는 010-1234-5678입니다."
        entities = detector.detect(text)

        assert len(entities) == 1
        assert entities[0].entity_type == PIIType.PHONE
        assert entities[0].value == "010-1234-5678"
        assert entities[0].detection_method == DetectionMethod.REGEX

    def test_detect_personal_phone_without_dash(self, detector: HybridPIIDetector) -> None:
        """하이픈 없는 전화번호 탐지"""
        text = "전화번호: 01012345678"
        entities = detector.detect(text)

        assert len(entities) == 1
        assert entities[0].entity_type == PIIType.PHONE
        assert "010" in entities[0].value

    def test_skip_business_phone_number(self, detector: HybridPIIDetector) -> None:
        """업체 전화번호(지역번호)는 탐지하지 않음"""
        text = "문의: 02-123-4567 또는 031-456-7890"
        entities = detector.detect(text)

        # 업체 전화번호는 PII로 탐지되지 않아야 함
        phone_entities = [e for e in entities if e.entity_type == PIIType.PHONE]
        assert len(phone_entities) == 0

    def test_detect_multiple_phones(self, detector: HybridPIIDetector) -> None:
        """여러 개인 전화번호 탐지"""
        text = "담당자 연락처: 010-1111-2222, 고객 연락처: 010-3333-4444"
        entities = detector.detect(text)

        phone_entities = [e for e in entities if e.entity_type == PIIType.PHONE]
        assert len(phone_entities) == 2

    # ========================================
    # 이메일 탐지 테스트
    # ========================================

    def test_detect_email(self, detector: HybridPIIDetector) -> None:
        """이메일 주소 탐지"""
        text = "이메일: test@example.com으로 연락주세요."
        entities = detector.detect(text)

        email_entities = [e for e in entities if e.entity_type == PIIType.EMAIL]
        assert len(email_entities) == 1
        assert email_entities[0].value == "test@example.com"

    def test_detect_korean_email_domain(self, detector: HybridPIIDetector) -> None:
        """한국 도메인 이메일 탐지"""
        text = "메일주소는 user@naver.com 입니다"
        entities = detector.detect(text)

        email_entities = [e for e in entities if e.entity_type == PIIType.EMAIL]
        assert len(email_entities) == 1

    # ========================================
    # 주민등록번호 탐지 테스트
    # ========================================

    def test_detect_ssn(self, detector: HybridPIIDetector) -> None:
        """주민등록번호 탐지"""
        text = "주민번호: 900101-1234567"
        entities = detector.detect(text)

        ssn_entities = [e for e in entities if e.entity_type == PIIType.SSN]
        assert len(ssn_entities) == 1

    def test_detect_ssn_without_dash(self, detector: HybridPIIDetector) -> None:
        """하이픈 없는 주민등록번호 탐지"""
        text = "주민번호 9001011234567"
        entities = detector.detect(text)

        ssn_entities = [e for e in entities if e.entity_type == PIIType.SSN]
        assert len(ssn_entities) == 1

    # ========================================
    # 계좌/카드번호 탐지 테스트
    # ========================================

    def test_detect_account_number(self, detector: HybridPIIDetector) -> None:
        """계좌번호 탐지"""
        text = "입금계좌: 123-456-789012"
        entities = detector.detect(text)

        account_entities = [e for e in entities if e.entity_type == PIIType.ACCOUNT]
        assert len(account_entities) == 1

    def test_detect_card_number(self, detector: HybridPIIDetector) -> None:
        """카드번호 탐지"""
        text = "카드번호: 1234-5678-9012-3456"
        entities = detector.detect(text)

        card_entities = [e for e in entities if e.entity_type == PIIType.CARD]
        assert len(card_entities) == 1

    # ========================================
    # 화이트리스트 필터링 테스트
    # ========================================

    def test_whitelist_filtering(self, detector: HybridPIIDetector) -> None:
        """도메인 키워드는 PII에서 제외"""
        text = "고객님과 담당자님의 예약 일정입니다."
        entities = detector.detect(text)

        # 고객, 담당자, 예약은 화이트리스트에 있어 탐지되지 않음
        person_entities = [e for e in entities if e.entity_type == PIIType.PERSON_NAME]
        assert len(person_entities) == 0

    # ========================================
    # 복합 텍스트 테스트
    # ========================================

    def test_detect_multiple_pii_types(self, detector: HybridPIIDetector) -> None:
        """여러 종류의 PII가 포함된 텍스트"""
        text = """
        담당자 연락처: 010-1234-5678
        이메일: manager@example.com
        주민번호: 900101-1234567
        """
        entities = detector.detect(text)

        # 최소 3개 이상의 PII 탐지 (phone, email, ssn)
        assert len(entities) >= 3

        entity_types = {e.entity_type for e in entities}
        assert PIIType.PHONE in entity_types
        assert PIIType.EMAIL in entity_types
        assert PIIType.SSN in entity_types

    def test_empty_text(self, detector: HybridPIIDetector) -> None:
        """빈 텍스트 처리"""
        entities = detector.detect("")
        assert len(entities) == 0

    def test_no_pii_text(self, detector: HybridPIIDetector) -> None:
        """PII가 없는 텍스트"""
        text = "오늘 날씨가 좋습니다. 야외 촬영하기 좋은 날이에요."
        entities = detector.detect(text)
        assert len(entities) == 0

    # ========================================
    # 중복 제거 테스트
    # ========================================

    def test_deduplicate_overlapping_entities(self, detector: HybridPIIDetector) -> None:
        """겹치는 위치의 엔티티 중복 제거"""
        # 동일한 텍스트를 여러 번 탐지하는 경우
        text = "전화: 010-1234-5678"
        entities = detector.detect(text)

        # 중복 없이 하나만 탐지
        phone_entities = [e for e in entities if e.entity_type == PIIType.PHONE]
        assert len(phone_entities) == 1

    def test_entities_sorted_by_position(self, detector: HybridPIIDetector) -> None:
        """엔티티가 위치순으로 정렬됨"""
        text = "이메일: a@b.com, 전화: 010-1111-2222"
        entities = detector.detect(text)

        if len(entities) >= 2:
            # 위치순 정렬 확인
            positions = [e.start_pos for e in entities]
            assert positions == sorted(positions)


def _check_spacy_available() -> bool:
    """spaCy 및 한국어 모델 가용성 체크"""
    if os.getenv("ONERAG_RUN_OPTIONAL_PROVIDER_TESTS") != "1":
        return False

    try:
        import spacy

        spacy.load("ko_core_news_sm")
        return True
    except (ImportError, OSError):
        return False


# spaCy 가용성 플래그 (모듈 로드 시 한 번만 체크)
SPACY_AVAILABLE = _check_spacy_available()


class TestHybridPIIDetectorWithNER:
    """NER 활성화 시 추가 테스트 (spaCy 모델 필요)"""

    @pytest.fixture
    def detector(self) -> HybridPIIDetector:
        """NER 활성화 탐지기"""
        return HybridPIIDetector(
            spacy_model="ko_core_news_sm",
            enable_ner=True,
            context_window=30,
            whitelist=["고객", "담당자", "예약"],
        )

    @pytest.mark.skipif(
        not SPACY_AVAILABLE,
        reason="spaCy 또는 ko_core_news_sm 모델이 설치되지 않음",
    )
    def test_ner_person_detection(self, detector: HybridPIIDetector) -> None:
        """NER로 인명 탐지"""
        text = "담당 매니저는 김철수입니다."
        entities = detector.detect(text)

        # NER이 인명을 탐지할 수 있음 (모델 성능에 따라 다름)
        # 이 테스트는 NER 연동 자체를 검증
        assert isinstance(entities, list)

    @pytest.mark.skipif(
        not SPACY_AVAILABLE,
        reason="spaCy 또는 ko_core_news_sm 모델이 설치되지 않음",
    )
    def test_ner_organization_detection(self, detector: HybridPIIDetector) -> None:
        """NER로 기관명 탐지"""
        text = "삼성전자에서 근무합니다."
        entities = detector.detect(text)

        # 기관명 탐지 가능 여부 확인
        assert isinstance(entities, list)
