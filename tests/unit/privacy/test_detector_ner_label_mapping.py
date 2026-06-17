"""HybridPIIDetector NER 라벨 매핑 외부화 테스트

spaCy NER 라벨 → PIIType 매핑을 __init__ 인자(ner_label_mapping)로
오버라이드 가능한지(데드 상수 아님), 미설정 시 한국/KLUE 기본 매핑으로
폴백하는지(회귀 0) 검증한다.

배경: spacy_model은 config로 교체 가능했으나 라벨 매핑이 코드 상수에만
있어 새 모델(예: 영어 en_core_web_sm)의 라벨 체계를 인식시키려면 코드
포크가 필요했다. 이 변경으로 라벨 매핑도 config로 주입 가능해졌다.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.modules.core.privacy.review import (
    HybridPIIDetector,
    PIIType,
)


# spaCy Doc/Ent를 흉내 내는 경량 스텁(실제 spaCy 모델 미설치 환경에서도 동작).
@dataclass
class _FakeEnt:
    label_: str
    text: str
    start_char: int
    end_char: int


@dataclass
class _FakeDoc:
    ents: list[_FakeEnt]


def _detector(
    ner_label_mapping: dict[str, PIIType | str] | None = None,
) -> HybridPIIDetector:
    """NER 비활성(모델 로드 회피) + 라벨 매핑만 주입하는 헬퍼."""
    return HybridPIIDetector(
        enable_ner=False,
        whitelist=[],
        ner_label_mapping=ner_label_mapping,
    )


def test_default_mapping_unchanged_when_unset() -> None:
    """매핑 미설정 시 한국/KLUE 기본 매핑이 그대로 적용된다(회귀 0)."""
    det = _detector(None)
    assert det.NER_LABEL_MAPPING == HybridPIIDetector.DEFAULT_NER_LABEL_MAPPING
    # KLUE 전용 라벨도 기본 매핑에 포함됨
    assert det.NER_LABEL_MAPPING["PS"] == PIIType.PERSON_NAME
    assert det.NER_LABEL_MAPPING["LC"] == PIIType.ADDRESS
    assert det.NER_LABEL_MAPPING["OG"] == PIIType.ORGANIZATION


def test_empty_mapping_falls_back_to_default() -> None:
    """빈 dict 주입 시 기본 매핑으로 폴백한다(회귀 0)."""
    det = _detector({})
    assert det.NER_LABEL_MAPPING == HybridPIIDetector.DEFAULT_NER_LABEL_MAPPING


def test_default_mapping_used_in_ner_extraction() -> None:
    """기본 매핑이 실제 NER 추출 경로에서 PIIType로 변환된다(데드 상수 아님)."""
    det = _detector(None)
    doc = _FakeDoc(
        ents=[
            _FakeEnt(label_="PS", text="김철수", start_char=0, end_char=3),
            _FakeEnt(label_="OG", text="삼성전자", start_char=5, end_char=9),
        ]
    )
    ents = det._extract_ner_entities("김철수 삼성전자 문의", doc)  # type: ignore[arg-type]
    types = {e.entity_type for e in ents}
    assert PIIType.PERSON_NAME in types
    assert PIIType.ORGANIZATION in types


def test_override_with_pii_type_values() -> None:
    """PIIType 인스턴스 값으로 라벨 매핑 오버라이드(코드 경로)."""
    det = _detector({"PERSON": PIIType.PERSON_NAME, "GPE": PIIType.ADDRESS})
    # 영어 모델 라벨만 매핑되고 KLUE 기본 라벨은 사라진다(통째 오버라이드).
    assert det.NER_LABEL_MAPPING == {
        "PERSON": PIIType.PERSON_NAME,
        "GPE": PIIType.ADDRESS,
    }
    assert "PS" not in det.NER_LABEL_MAPPING


def test_override_with_string_values_coerced_to_enum() -> None:
    """yaml 형식(문자열 값)으로 주입해도 PIIType로 정규화된다."""
    det = _detector(
        {
            "PERSON": "person_name",
            "GPE": "address",
            "ORG": "organization",
        }
    )
    assert det.NER_LABEL_MAPPING["PERSON"] == PIIType.PERSON_NAME
    assert det.NER_LABEL_MAPPING["GPE"] == PIIType.ADDRESS
    assert det.NER_LABEL_MAPPING["ORG"] == PIIType.ORGANIZATION


def test_override_changes_ner_extraction_label_recognition() -> None:
    """오버라이드한 영어 라벨이 NER 추출에서 실제로 인식된다(데드 키 해소)."""
    # 기본 매핑에는 영어 'PERSON'이 이미 있으므로, 기본엔 없는 커스텀 라벨로 검증.
    det = _detector({"CUSTOM_NAME": "person_name"})
    doc = _FakeDoc(
        ents=[_FakeEnt(label_="CUSTOM_NAME", text="Alice", start_char=0, end_char=5)]
    )
    ents = det._extract_ner_entities("Alice is here", doc)  # type: ignore[arg-type]
    assert any(e.entity_type == PIIType.PERSON_NAME for e in ents)

    # 오버라이드로 기본 KLUE 라벨(PS)은 더 이상 인식되지 않아야 한다.
    doc_klue = _FakeDoc(
        ents=[_FakeEnt(label_="PS", text="김철수", start_char=0, end_char=3)]
    )
    ents_klue = det._extract_ner_entities("김철수", doc_klue)  # type: ignore[arg-type]
    assert ents_klue == []
