"""RuleBasedExtractor 콘텐츠 타입 마커 config 외부화 테스트

`_infer_content_type`의 question/instruction/conversation 분류 마커를
생성자 인자(content_type_markers)로 외부화한 변경을 검증한다.

핵심 요구사항:
1. (회귀 0) 마커 미설정 시 코드 내장 한국어 기본 마커를 사용한다.
2. '?'(질문)는 언어 중립 신호라 마커와 무관하게 항상 적용된다.
3. (오버라이드) 마커 주입 시 비한국어 텍스트도 타입 분류된다.
"""

from __future__ import annotations

from app.modules.core.documents.metadata.rule_based import RuleBasedExtractor


def _extractor(markers: dict | None = None) -> RuleBasedExtractor:
    return RuleBasedExtractor(use_konlpy=False, content_type_markers=markers)


def test_content_type_default_korean_markers() -> None:
    """마커 미설정 시 한국어 기본 마커로 분류한다(회귀 0)."""
    ex = _extractor()
    assert ex._infer_content_type("이것은 무엇인가요") == "question"
    assert ex._infer_content_type("꼭 확인해주세요") == "instruction"
    # '안녕하세요'는 instruction 마커('하세요')가 먼저 매칭됨(기존 동작 보존)
    assert ex._infer_content_type("반갑습니다 문의 드립니다") == "conversation"
    assert ex._infer_content_type("일반 정보 텍스트입니다") == "info"


def test_content_type_question_mark_is_language_neutral() -> None:
    """'?'는 마커와 무관하게 항상 question으로 판정된다."""
    ex = _extractor()
    assert ex._infer_content_type("Is this correct?") == "question"
    # 마커를 비워도 '?'는 여전히 질문 판정
    ex_empty = _extractor({"question": [], "instruction": [], "conversation": []})
    assert ex_empty._infer_content_type("really?") == "question"


def test_content_type_markers_override_english() -> None:
    """마커 주입 시 영어 텍스트도 타입 분류된다."""
    ex = _extractor(
        {
            "question": ["what", "why", "how"],
            "instruction": ["please", "must"],
            "conversation": ["hello", "thanks"],
        }
    )
    assert ex._infer_content_type("what is this") == "question"
    assert ex._infer_content_type("please do this") == "instruction"
    assert ex._infer_content_type("hello there") == "conversation"
    # 한국어 기본 마커는 오버라이드로 더 이상 매칭 안 됨
    assert ex._infer_content_type("무엇입니까 라고 묻습니다") == "info"


def test_content_type_default_markers_class_attr_exists() -> None:
    """기본 마커는 클래스 상수로 노출되어 회귀 안전판 역할을 한다."""
    assert "question" in RuleBasedExtractor.DEFAULT_CONTENT_TYPE_MARKERS
    assert "어떻게" in RuleBasedExtractor.DEFAULT_CONTENT_TYPE_MARKERS["question"]
