"""토픽 추출 단일 소스 유틸리티

세션 메타데이터용 토픽 라벨을 키워드 매칭으로 추출하는 순수 함수.
도메인 의존성이 없는 lib 계층 유틸이라 app.api(ChatService)와
app.core(DI 컨테이너)가 계층 위반 없이 공유할 수 있다.

주요 기능:
- extract_topic: 메시지 → 토픽 라벨(키워드 기반).
- 토픽 키워드는 config(routing.topic_keywords)로 외부화 가능하며,
  미설정 시 코드 내장 한국어 기본 맵을 사용한다(회귀 0).

의존성: 표준 라이브러리만 사용(외부/도메인 의존성 없음).
"""

from __future__ import annotations

# 코드 내장 한국어 기본 토픽 키워드(회귀 안전판).
# config 미설정 시 이 맵을 사용한다. 토픽은 세션 메타(cosmetic) 라벨이라
# 검색/라우팅 동작에는 영향을 주지 않는다.
#
# 단일 소스 통합: 과거 di_container(search/help/greeting/thanks)와
# ChatService(search/document/help/technical) 두 구현의 토픽을 합집합으로
# 통합해 양쪽 라벨을 모두 보존한다. 키 순서는 매칭 우선순위를 의미한다
# (먼저 매칭되는 토픽이 반환됨).
DEFAULT_TOPIC_KEYWORDS: dict[str, list[str]] = {
    "search": ["검색", "찾기", "찾아", "조회", "정보", "어디", "알려"],
    "document": ["문서", "파일", "자료", "데이터"],
    # technical을 help보다 먼저 두어 코드/개발 질문이 technical로 분류되게 한다
    # ('방법'이 help/technical에 모두 걸릴 수 있어 우선순위로 구분).
    "technical": ["기술", "개발", "코드", "프로그래밍"],
    "help": ["도움", "도와", "어떻게", "방법", "안내", "사용법", "매뉴얼", "설명"],
    "greeting": ["안녕", "반가워", "하이", "헬로"],
    "thanks": ["고마워", "감사", "땡큐"],
}


def extract_topic(
    message: object,
    topic_keywords: dict[str, list[str]] | None = None,
) -> str:
    """토픽 추출 단일 소스 함수(키워드 기반).

    di_container와 ChatService의 중복 구현을 통합한 단일 구현이다.
    토픽 키워드는 config(routing.topic_keywords)로 외부화할 수 있으며,
    미설정 시 코드 내장 한국어 기본 맵을 사용한다(회귀 0). 매칭이 없으면
    'general'을 반환한다(기존 동작 유지).

    Args:
        message: 사용자 메시지(문자열/리스트/기타 — 안전 변환).
        topic_keywords: 토픽→키워드 목록 맵. None/빈 dict이면 한국어 기본 맵 사용.

    Returns:
        분류된 토픽 라벨(미매칭 시 'general').
    """
    if isinstance(message, list):
        message = " ".join(str(item) for item in message)
    elif not isinstance(message, str):
        message = str(message)

    if not message:
        return "general"

    # config 주입 키워드 우선, 미설정/빈 dict 시 한국어 기본값(회귀 0)
    keywords = topic_keywords if topic_keywords else DEFAULT_TOPIC_KEYWORDS

    try:
        lower_message = message.lower()
        for topic, words in keywords.items():
            if any(word in lower_message for word in words):
                return topic
        return "general"
    except Exception:
        return "general"
