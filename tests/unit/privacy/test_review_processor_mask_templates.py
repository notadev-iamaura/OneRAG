"""
PIIReviewProcessor 마스킹 라벨(mask_templates) 외부화 테스트

10차 도메인-범용화: PIIReviewProcessor의 마스킹 치환 라벨('[전화번호]'/'[이메일]'
등)이 한국어 클래스 상수로 하드코딩돼 비한국어 운영자가 코드 포크 없이 영어
라벨로 바꿀 수 없던 finding을 config/env 오버라이드 경로 신설로 해소한다.

검증 항목:
(a) 미설정 시 한국어 기본 라벨 + 실제 마스킹 동작 유지(회귀 0).
(b) config(생성자) 주입 시 영어 라벨 오버라이드 동작.
(c) DI 경로(di_container)에서 privacy.review.mask_templates가 실제로 전달됨
    (데드 키 아님). yaml 기본값이 빈 dict({})이므로 코드 기본(한국어)으로 폴백.
"""

from __future__ import annotations

from typing import Any, cast

from app.core.di_container import AppContainer
from app.lib.config_loader import load_config
from app.modules.core.privacy.review.models import (
    DetectionMethod,
    PIIEntity,
    PIIType,
)
from app.modules.core.privacy.review.processor import PIIReviewProcessor


def _make_processor(
    mask_templates: dict[str, str] | None = None,
) -> PIIReviewProcessor:
    """마스킹 메서드(_mask_entities/_get_mask)만 검증하는 경량 프로세서 생성.

    _mask_entities/_get_mask는 detector/policy_engine/audit_logger를 사용하지
    않으므로(순수 라벨 치환), 의존성은 가짜 객체를 주입한다.
    """
    dummy = cast(Any, object())
    return PIIReviewProcessor(
        detector=dummy,
        policy_engine=dummy,
        audit_logger=dummy,
        enabled=True,
        mask_templates=mask_templates,
    )


def _entity(entity_type: PIIType, value: str, start: int) -> PIIEntity:
    """테스트용 PIIEntity 생성 헬퍼."""
    return PIIEntity(
        entity_type=entity_type,
        value=value,
        start_pos=start,
        end_pos=start + len(value),
        confidence=0.99,
        detection_method=DetectionMethod.REGEX,
    )


# ----------------------------------------------------------------------------
# (a) 미설정 시 한국어 기본 라벨 + 실제 마스킹 동작 유지 (회귀 0)
# ----------------------------------------------------------------------------
def test_default_korean_labels_unchanged() -> None:
    """mask_templates 미설정 시 한국어 기본 라벨이 그대로 유지됨(회귀 0)."""
    proc = _make_processor()
    # 인스턴스 맵이 클래스 기본값과 byte-identical 해야 한다.
    assert proc.MASK_TEMPLATES == PIIReviewProcessor.DEFAULT_MASK_TEMPLATES
    assert proc.MASK_TEMPLATES[PIIType.PHONE] == "[전화번호]"
    assert proc.MASK_TEMPLATES[PIIType.EMAIL] == "[이메일]"
    assert proc.MASK_TEMPLATES[PIIType.SSN] == "[주민등록번호]"


def test_default_korean_masking_behavior() -> None:
    """미설정 시 실제 마스킹 결과가 한국어 라벨로 치환됨(회귀 0)."""
    proc = _make_processor()
    text = "연락처 010-1234-5678 입니다"
    # "010-1234-5678" 위치
    start = text.index("010")
    entity = _entity(PIIType.PHONE, "010-1234-5678", start)
    masked = proc._mask_entities(text, [entity])
    assert masked == "연락처 [전화번호] 입니다"


def test_default_unknown_fallback_label() -> None:
    """미정의 PIIType은 한국어 UNKNOWN 라벨('[개인정보]')로 폴백(회귀 0)."""
    proc = _make_processor()
    entity = _entity(PIIType.UNKNOWN, "secret", 0)
    assert proc._get_mask(entity) == "[개인정보]"


# ----------------------------------------------------------------------------
# (b) config 주입 시 영어 라벨 오버라이드 동작
# ----------------------------------------------------------------------------
def test_english_label_override() -> None:
    """mask_templates 주입 시 영어 라벨로 오버라이드됨."""
    proc = _make_processor(
        mask_templates={
            "phone": "[Phone]",
            "email": "[Email]",
            "ssn": "[SSN]",
        }
    )
    assert proc.MASK_TEMPLATES[PIIType.PHONE] == "[Phone]"
    assert proc.MASK_TEMPLATES[PIIType.EMAIL] == "[Email]"
    assert proc.MASK_TEMPLATES[PIIType.SSN] == "[SSN]"


def test_english_override_masking_behavior() -> None:
    """오버라이드 주입 시 실제 마스킹 결과가 영어 라벨로 치환됨."""
    proc = _make_processor(mask_templates={"phone": "[Phone]"})
    text = "Contact 010-1234-5678 please"
    start = text.index("010")
    entity = _entity(PIIType.PHONE, "010-1234-5678", start)
    masked = proc._mask_entities(text, [entity])
    assert masked == "Contact [Phone] please"


def test_partial_override_falls_back_to_korean() -> None:
    """일부 키만 주입 시 나머지 키는 한국어 기본값으로 폴백(회귀 0 + 부분 오버라이드)."""
    proc = _make_processor(mask_templates={"phone": "[Phone]"})
    # 주입한 키는 영어
    assert proc.MASK_TEMPLATES[PIIType.PHONE] == "[Phone]"
    # 미주입 키는 한국어 기본값 유지
    assert proc.MASK_TEMPLATES[PIIType.EMAIL] == "[이메일]"
    assert proc.MASK_TEMPLATES[PIIType.SSN] == "[주민등록번호]"


def test_unknown_fallback_label_overridable() -> None:
    """UNKNOWN 폴백 라벨도 오버라이드 가능(미정의 PIIType이 영어 폴백으로 치환)."""
    proc = _make_processor(mask_templates={"unknown": "[PII]"})
    entity = _entity(PIIType.UNKNOWN, "secret", 0)
    assert proc._get_mask(entity) == "[PII]"


def test_override_accepts_piitype_keys() -> None:
    """PIIType enum 키로도 오버라이드 주입 가능(yaml 문자열 키와 동등)."""
    proc = _make_processor(
        mask_templates=cast("dict[str, str]", {PIIType.PHONE: "[Phone]"})
    )
    assert proc.MASK_TEMPLATES[PIIType.PHONE] == "[Phone]"


# ----------------------------------------------------------------------------
# (c) DI 경로(di_container) 데드 키 아님 검증
# ----------------------------------------------------------------------------
# 주: pii_review_processor 전체 인스턴스화는 형제 provider(pii_policy_engine)의
# 별개 배선 이슈에 묶여 있어, 본 finding(mask_templates)과 무관하게 실패할 수
# 있다. 따라서 데드 키 검증은 (1) provider 정의에 mask_templates 인자가 실제로
# 배선됐는지, (2) 그 인자가 가리키는 config 키가 privacy.yaml에서 로드되는지,
# (3) 그 config 값이 PIIReviewProcessor로 흐를 때 한국어 기본으로 폴백하는지를
# 인스턴스화에 의존하지 않고 검증한다.
def _load_review_config() -> dict[str, Any]:
    """privacy.review 서브트리를 로드한다."""
    cfg = load_config()
    return cast("dict[str, Any]", cfg["privacy"]["review"])


def test_mask_templates_config_key_exists_in_yaml() -> None:
    """privacy.review.mask_templates 키가 privacy.yaml에 실제로 존재(데드 키 아님).

    기본값은 빈 dict({})이어야 한다(회귀 0: 미설정 시 코드 한국어 폴백).
    """
    review_cfg = _load_review_config()
    assert "mask_templates" in review_cfg
    assert review_cfg["mask_templates"] == {}


def test_mask_templates_wired_in_provider_definition() -> None:
    """di_container의 pii_review_processor provider에 mask_templates 인자가 배선됨.

    provider 정의의 키워드 인자를 직접 검사해 데드 키가 아님을 증명한다
    (형제 provider 배선 이슈와 무관하게 mask_templates 경로만 검증).
    """
    container = AppContainer()
    container.config.from_dict(load_config())
    provider = container.pii_review_processor
    # dependency_injector provider는 kwargs를 노출한다.
    assert "mask_templates" in provider.kwargs


def test_config_default_flows_to_korean_fallback() -> None:
    """yaml 기본값(빈 dict)이 PIIReviewProcessor로 흐르면 한국어로 폴백(회귀 0).

    di_container가 주입하는 값(config.privacy.review.mask_templates == {})을
    그대로 생성자에 넣어, 코드 기본 한국어 라벨로 폴백함을 검증한다.
    """
    review_cfg = _load_review_config()
    proc = _make_processor(mask_templates=review_cfg["mask_templates"])
    assert proc.MASK_TEMPLATES == PIIReviewProcessor.DEFAULT_MASK_TEMPLATES
    text = "연락처 010-1234-5678"
    start = text.index("010")
    entity = _entity(PIIType.PHONE, "010-1234-5678", start)
    assert proc._mask_entities(text, [entity]) == "연락처 [전화번호]"
