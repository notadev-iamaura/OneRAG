"""토픽 추출 단일 소스 통합 + config 외부화 테스트

di_container와 ChatService의 중복 토픽 추출 구현을 단일 함수(extract_topic)로
통합하고, 토픽 키워드를 config(routing.topic_keywords)로 외부화한 변경을 검증한다.

핵심 요구사항:
1. (DRY) 단일 소스 함수 extract_topic 존재 및 동작.
2. (회귀 0) 키워드 미설정 시 코드 내장 한국어 기본 맵을 사용한다.
3. (오버라이드) 키워드 주입 시 비한국어 메시지도 토픽 분류된다.
4. (데드 키 아님) build_extract_topic_func가 routing.topic_keywords를 읽는다.
5. 안전 입력 처리(리스트/비문자열/빈 문자열 → 'general').
"""

from __future__ import annotations

from app.core.di_container import (
    build_extract_topic_func,
    extract_topic,
    extract_topic_default,
)


def test_extract_topic_default_korean_keywords() -> None:
    """키워드 미설정 시 한국어 기본 맵으로 분류한다(회귀 0)."""
    assert extract_topic("검색해줘") == "search"
    assert extract_topic("어떻게 하나요 도움") == "help"
    assert extract_topic("안녕하세요") == "greeting"
    assert extract_topic("고마워요") == "thanks"
    assert extract_topic("그냥 일상 대화") == "general"


def test_extract_topic_default_func_delegates() -> None:
    """RAGPipeline 주입용 extract_topic_default도 동일 한국어 동작(회귀 0)."""
    assert extract_topic_default("검색해줘") == "search"
    assert extract_topic_default("hello world") == "general"  # 한국어 미매칭


def test_extract_topic_safe_inputs() -> None:
    """리스트/비문자열/빈 입력을 안전 처리한다."""
    assert extract_topic("") == "general"
    assert extract_topic(["검색", "요청"]) == "search"
    assert extract_topic(12345) == "general"


def test_extract_topic_override_keywords() -> None:
    """키워드 주입 시 비한국어 메시지도 분류된다."""
    keywords = {"search": ["find", "lookup"], "help": ["help", "guide"]}
    assert extract_topic("please find it", keywords) == "search"
    assert extract_topic("need a guide", keywords) == "help"
    # 한국어 기본 키워드는 더 이상 사용되지 않는다(주입 맵으로 대체)
    assert extract_topic("검색", keywords) == "general"


def test_extract_topic_empty_keywords_falls_back() -> None:
    """빈 dict 키워드는 한국어 기본 맵으로 폴백한다(회귀 0)."""
    assert extract_topic("검색해줘", {}) == "search"


def test_build_extract_topic_func_reads_config() -> None:
    """build_extract_topic_func가 routing.topic_keywords를 실제로 읽는다(데드 키 아님)."""
    config = {"routing": {"topic_keywords": {"search": ["find"]}}}
    fn = build_extract_topic_func(config)
    assert fn("find it") == "search"
    assert fn("검색") == "general"  # 주입 맵으로 대체됨

    # config 미설정 시 한국어 기본값으로 폴백
    fn_default = build_extract_topic_func({})
    assert fn_default("검색해줘") == "search"
