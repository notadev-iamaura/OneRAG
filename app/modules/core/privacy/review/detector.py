"""
하이브리드 PII 탐지기 (HybridPIIDetector)

3단계 탐지 전략:
1. Regex 기반: 전화번호, 이메일, 주민번호 등 정형 패턴 (빠름)
2. spaCy NER 기반: 인명, 주소, 기관명 등 문맥 인식 (정확함)
3. 도메인 화이트리스트: 도메인 특화 용어 오탐 방지

구현일: 2025-12-01
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Protocol

from .models import DetectionMethod, PIIEntity, PIIType

if TYPE_CHECKING:
    from spacy.language import Language
    from spacy.tokens import Doc

logger = logging.getLogger(__name__)


class PIIDetectorProtocol(Protocol):
    """PII 탐지기 프로토콜 (인터페이스)"""

    def detect(self, text: str) -> list[PIIEntity]:
        """텍스트에서 PII 엔티티 탐지"""
        ...

    def detect_batch(self, texts: list[str]) -> list[list[PIIEntity]]:
        """배치 탐지 (성능 최적화)"""
        ...


class HybridPIIDetector:
    """
    하이브리드 PII 탐지기

    Regex + spaCy NER 조합으로 높은 정확도와 빠른 속도 달성.
    도메인 화이트리스트로 도메인 관련 용어 오탐 방지.

    사용 예시:
        detector = HybridPIIDetector()
        entities = detector.detect("김철수 고객님 연락처: 010-1234-5678")
        # entities[0].entity_type == PIIType.PHONE
    """

    # 버전 (감사 로그용)
    VERSION = "1.0.0"

    # ========================================
    # Regex 패턴 정의
    # ========================================

    # 전화번호 패턴 (010, 011, 016, 017, 018, 019)
    PHONE_PATTERN = re.compile(r"(?:010|011|016|017|018|019)[-.\s]?\d{3,4}[-.\s]?\d{4}")

    # 이메일 패턴
    EMAIL_PATTERN = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")

    # 주민등록번호 패턴 (YYMMDD-GXXXXXX)
    SSN_PATTERN = re.compile(r"\d{6}[-\s]?[1-4]\d{6}")

    # 계좌번호 패턴 (다양한 형식)
    # 국민: 123456-12-123456, 신한: 110-123-456789 등
    ACCOUNT_PATTERN = re.compile(r"\d{3,6}[-\s]?\d{2,6}[-\s]?\d{4,6}(?:[-\s]?\d{1,4})?")

    # 신용카드 번호 패턴 (4자리-4자리-4자리-4자리)
    CARD_PATTERN = re.compile(r"\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}")

    # 사업자 전화번호 패턴 (마스킹 제외용)
    BUSINESS_PHONE_PATTERN = re.compile(r"(?:02|0[3-6][1-5])[-\s]?\d{3,4}[-\s]?\d{4}")

    # spaCy NER 레이블 → PIIType 매핑
    NER_LABEL_MAPPING: dict[str, PIIType] = {
        "PERSON": PIIType.PERSON_NAME,
        "PER": PIIType.PERSON_NAME,
        "PS": PIIType.PERSON_NAME,  # KLUE 형식
        "LOC": PIIType.ADDRESS,
        "GPE": PIIType.ADDRESS,
        "LC": PIIType.ADDRESS,  # KLUE 형식
        "FAC": PIIType.ADDRESS,  # 시설물
        "ORG": PIIType.ORGANIZATION,
        "OG": PIIType.ORGANIZATION,  # KLUE 형식
    }

    def __init__(
        self,
        spacy_model: str = "ko_core_news_sm",
        whitelist: list[str] | None = None,
        enable_ner: bool = True,
        context_window: int = 30,
    ):
        """
        Args:
            spacy_model: spaCy 모델명 (ko_core_news_sm/md/lg)
            whitelist: 도메인 화이트리스트 (오탐 방지)
            enable_ner: NER 탐지 활성화 여부 (비활성화 시 Regex만 사용)
            context_window: 문맥 추출 윈도우 크기 (감사용)
        """
        self._nlp: Language | None = None
        self._spacy_model = spacy_model
        self._enable_ner = enable_ner
        self._context_window = context_window

        # 도메인 화이트리스트 (오탐 방지)
        self.whitelist: set[str] = set(
            whitelist
            or [
                "담당",
                "관리자",
                "직원",
                "고객",
                "가족",
                "친구",
                "가이드",
                "지원",
                "문의",
                "안내",
                "확인",
                "추천",
                "팀장",
                "매니저",
                "대표",
            ]
        )

        logger.info(
            f"HybridPIIDetector 초기화: model={spacy_model}, "
            f"ner={enable_ner}, whitelist_size={len(self.whitelist)}"
        )

    @property
    def nlp(self) -> Language | None:
        """
        spaCy 모델 Lazy Loading

        모델 로드는 비용이 높으므로 첫 사용 시점에 로드.
        로드 실패 시 None 반환 (Graceful Degradation).
        """
        if self._nlp is None and self._enable_ner:
            try:
                import spacy

                self._nlp = spacy.load(self._spacy_model)
                logger.info(f"spaCy 모델 로드 완료: {self._spacy_model}")
            except OSError as e:
                logger.warning(
                    f"spaCy 모델 로드 실패 ({self._spacy_model}): {e}. "
                    "NER 탐지 비활성화됨. 'python -m spacy download ko_core_news_sm' 실행 필요."
                )
                self._enable_ner = False
            except ImportError:
                logger.warning("spaCy 미설치. NER 탐지 비활성화됨. 'pip install spacy' 실행 필요.")
                self._enable_ner = False

        return self._nlp

    def detect(self, text: str) -> list[PIIEntity]:
        """
        텍스트에서 PII 엔티티 탐지

        3단계 파이프라인:
        1. Regex 탐지 (정형 패턴)
        2. NER 탐지 (문맥 인식)
        3. 화이트리스트 필터링 (오탐 제거)

        Args:
            text: 탐지 대상 텍스트

        Returns:
            탐지된 PIIEntity 목록 (위치순 정렬)
        """
        if not text or not text.strip():
            return []

        entities: list[PIIEntity] = []

        # 1단계: Regex 기반 탐지 (빠름)
        entities.extend(self._detect_with_regex(text))

        # 2단계: spaCy NER 기반 탐지 (정확함)
        if self._enable_ner and self.nlp is not None:
            entities.extend(self._detect_with_ner(text))

        # 3단계: 화이트리스트 필터링 (오탐 제거)
        entities = self._apply_whitelist_filter(entities)

        # 중복 제거 및 정렬
        entities = self._deduplicate_and_sort(entities)

        if entities:
            logger.debug(f"PII 탐지 완료: {len(entities)}개 엔티티")

        return entities

    def detect_batch(self, texts: list[str]) -> list[list[PIIEntity]]:
        """
        배치 탐지 (성능 최적화)

        spaCy pipe()를 사용하여 배치 처리 최적화.

        Args:
            texts: 탐지 대상 텍스트 목록

        Returns:
            각 텍스트별 PIIEntity 목록
        """
        if not texts:
            return []

        results: list[list[PIIEntity]] = []

        # NER 배치 처리 준비
        docs: list[Doc | None]
        if self._enable_ner and self.nlp is not None:
            # spaCy pipe()로 배치 처리
            docs = list(self.nlp.pipe(texts, batch_size=50))
        else:
            docs = [None] * len(texts)

        for _i, (text, doc) in enumerate(zip(texts, docs, strict=False)):
            entities: list[PIIEntity] = []

            # Regex 탐지
            entities.extend(self._detect_with_regex(text))

            # NER 탐지 (doc이 있는 경우)
            if doc is not None:
                entities.extend(self._extract_ner_entities(text, doc))

            # 필터링 및 정리
            entities = self._apply_whitelist_filter(entities)
            entities = self._deduplicate_and_sort(entities)

            results.append(entities)

        return results

    def _detect_with_regex(self, text: str) -> list[PIIEntity]:
        """
        Regex 기반 PII 탐지

        정형화된 패턴(전화번호, 이메일, 주민번호 등)을 빠르게 탐지.
        """
        entities: list[PIIEntity] = []

        # 패턴별 탐지
        pattern_configs: list[tuple[re.Pattern[str], PIIType, float]] = [
            (self.SSN_PATTERN, PIIType.SSN, 0.99),  # 주민번호 (높은 신뢰도)
            (self.CARD_PATTERN, PIIType.CARD, 0.95),  # 카드번호
            (self.EMAIL_PATTERN, PIIType.EMAIL, 0.98),  # 이메일
            (self.PHONE_PATTERN, PIIType.PHONE, 0.95),  # 전화번호
            (self.ACCOUNT_PATTERN, PIIType.ACCOUNT, 0.85),  # 계좌번호 (오탐 가능)
        ]

        for pattern, pii_type, confidence in pattern_configs:
            for match in pattern.finditer(text):
                value = match.group()

                # 전화번호: 사업자 전화번호 제외
                if pii_type == PIIType.PHONE and self._is_business_phone(value):
                    continue

                # 계좌번호: 날짜 패턴 제외 (YYYY-MM-DD 형식)
                if pii_type == PIIType.ACCOUNT and self._looks_like_date(value):
                    continue

                entities.append(
                    PIIEntity(
                        entity_type=pii_type,
                        value=value,
                        start_pos=match.start(),
                        end_pos=match.end(),
                        confidence=confidence,
                        detection_method=DetectionMethod.REGEX,
                        context=self._extract_context(text, match.start(), match.end()),
                    )
                )

        return entities

    def _detect_with_ner(self, text: str) -> list[PIIEntity]:
        """
        spaCy NER 기반 PII 탐지

        문맥을 인식하여 인명, 주소, 기관명 등을 정확하게 탐지.
        """
        if self.nlp is None:
            return []

        doc = self.nlp(text)
        return self._extract_ner_entities(text, doc)

    def _extract_ner_entities(self, text: str, doc: Doc) -> list[PIIEntity]:
        """spaCy Doc에서 PII 엔티티 추출"""
        entities: list[PIIEntity] = []

        for ent in doc.ents:
            pii_type = self.NER_LABEL_MAPPING.get(ent.label_)

            if pii_type is None:
                continue

            # 너무 짧은 엔티티 제외 (1글자)
            if len(ent.text.strip()) <= 1:
                continue

            entities.append(
                PIIEntity(
                    entity_type=pii_type,
                    value=ent.text,
                    start_pos=ent.start_char,
                    end_pos=ent.end_char,
                    confidence=0.80,  # NER 기본 신뢰도
                    detection_method=DetectionMethod.NER,
                    context=self._extract_context(text, ent.start_char, ent.end_char),
                )
            )

        return entities

    def _apply_whitelist_filter(self, entities: list[PIIEntity]) -> list[PIIEntity]:
        """
        도메인 화이트리스트 적용

        도메인 특화 용어("고객", "담당" 등)를 오탐에서 제외.
        """
        filtered: list[PIIEntity] = []

        for entity in entities:
            value = entity.value.strip()

            # 화이트리스트 정확히 일치
            if value in self.whitelist:
                continue

            # 화이트리스트 단어 포함 여부 (인명/주소의 경우)
            if entity.entity_type in (PIIType.PERSON_NAME, PIIType.ADDRESS):
                if any(w in value for w in self.whitelist):
                    continue

            filtered.append(entity)

        return filtered

    def _deduplicate_and_sort(self, entities: list[PIIEntity]) -> list[PIIEntity]:
        """
        중복 제거 및 위치 기준 정렬

        동일 위치에 여러 탐지가 있는 경우, 신뢰도가 높은 것 우선.
        """
        if not entities:
            return []

        # 위치별 그룹핑 (겹치는 엔티티 처리)
        seen_ranges: list[tuple[int, int]] = []
        unique: list[PIIEntity] = []

        # 신뢰도 높은 순 → 시작 위치 순 정렬
        sorted_entities = sorted(entities, key=lambda e: (-e.confidence, e.start_pos))

        for entity in sorted_entities:
            # 기존 범위와 겹치는지 확인
            overlaps = any(
                self._ranges_overlap(entity.start_pos, entity.end_pos, start, end)
                for start, end in seen_ranges
            )

            if not overlaps:
                unique.append(entity)
                seen_ranges.append((entity.start_pos, entity.end_pos))

        # 최종 위치순 정렬
        return sorted(unique, key=lambda e: e.start_pos)

    def _extract_context(self, text: str, start: int, end: int) -> str:
        """주변 문맥 추출 (감사 로그용)"""
        ctx_start = max(0, start - self._context_window)
        ctx_end = min(len(text), end + self._context_window)

        prefix = "..." if ctx_start > 0 else ""
        suffix = "..." if ctx_end < len(text) else ""

        return f"{prefix}{text[ctx_start:ctx_end]}{suffix}"

    def _is_business_phone(self, phone: str) -> bool:
        """사업자 전화번호인지 확인 (지역번호 시작)"""
        # 숫자만 추출
        digits = re.sub(r"[-.\s]", "", phone)

        # 010 등 개인번호로 시작하면 개인
        if digits.startswith(("010", "011", "016", "017", "018", "019")):
            return False

        # 02, 031 등 지역번호로 시작하면 사업자
        if digits.startswith("02") or (digits.startswith("0") and len(digits) >= 9):
            return True

        return False

    def _looks_like_date(self, text: str) -> bool:
        """날짜 패턴인지 확인 (계좌번호 오탐 방지)"""
        # 숫자만 추출
        digits = re.sub(r"[-.\s]", "", text)

        # 8자리 날짜 형식 (YYYYMMDD)
        if len(digits) == 8:
            try:
                year = int(digits[:4])
                month = int(digits[4:6])
                day = int(digits[6:8])
                if 1900 <= year <= 2100 and 1 <= month <= 12 and 1 <= day <= 31:
                    return True
            except ValueError:
                pass

        return False

    @staticmethod
    def _ranges_overlap(start1: int, end1: int, start2: int, end2: int) -> bool:
        """두 범위가 겹치는지 확인"""
        return not (end1 <= start2 or end2 <= start1)
