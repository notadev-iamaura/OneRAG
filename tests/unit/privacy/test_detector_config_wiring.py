"""
HybridPIIDetector config 배선(데드 키 아님) 테스트

privacy.yaml의 privacy.review.patterns / spacy_model 이 di_container를 통해
HybridPIIDetector에 실제로 전달되는지 검증한다.

배경: 과거 privacy.yaml의 review 블록이 최상위(top-level)에 위치해
config.privacy.review.*가 전부 None으로 해석되던 구조적 버그가 있었다.
이 테스트는 review 블록이 privacy 하위로 정렬되어 데드 키가 해소됐음을 증명한다.
"""

from __future__ import annotations

from app.core.di_container import AppContainer
from app.lib.config_loader import load_config
from app.modules.core.privacy.review.detector import HybridPIIDetector


def _build_detector() -> HybridPIIDetector:
    container = AppContainer()
    container.config.from_dict(load_config())
    return container.pii_detector()


def test_review_patterns_wired_from_yaml() -> None:
    """privacy.review.patterns가 탐지기 정규식으로 전달됨(데드 키 아님)"""
    detector = _build_detector()
    # 기본 한국 패턴이 실제 컴파일되어 인스턴스 속성에 반영돼야 한다.
    assert detector.SSN_PATTERN.pattern == HybridPIIDetector.DEFAULT_SSN_PATTERN
    assert detector.PHONE_PATTERN.pattern == HybridPIIDetector.DEFAULT_PHONE_PATTERN


def test_review_spacy_model_wired_from_yaml() -> None:
    """privacy.review.spacy_model이 탐지기로 전달됨(데드 키 아님)"""
    detector = _build_detector()
    # 과거엔 None이 주입됐다. 이제 yaml 값("ko_core_news_sm")이 전달돼야 한다.
    assert detector._spacy_model == "ko_core_news_sm"


def test_default_korean_detection_unchanged() -> None:
    """DI 경로에서 기본 한국 PII 탐지가 그대로 동작(회귀 0)"""
    detector = _build_detector()
    # NER 모델 미설치 환경에서도 Regex 경로는 동작한다.
    detector._enable_ner = False
    ents = detector.detect("연락처 010-1234-5678, 주민번호 901225-1234567")
    types = {e.entity_type.name for e in ents}
    assert "PHONE" in types
    assert "SSN" in types
