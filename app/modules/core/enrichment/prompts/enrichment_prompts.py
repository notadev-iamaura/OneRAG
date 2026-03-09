"""
Enrichment 프롬프트 템플릿

LLM 문서 보강을 위한 범용 프롬프트를 정의합니다.
어떤 도메인의 텍스트에도 적용 가능한 메타데이터 추출 프롬프트입니다.
"""

# 시스템 프롬프트 (공통) — 도메인에 무관하게 텍스트 분석
SYSTEM_PROMPT = """당신은 텍스트 데이터를 분석하여 메타데이터를 추출하는 AI 어시스턴트입니다.
주어진 텍스트를 분석하여 다음 정보를 정확하게 추출해주세요:

1. category: 주요 카테고리 (예: "기술", "비즈니스", "교육", "건강", "제품" 등)
2. subcategory: 세부 카테고리 (예: "프로그래밍", "마케팅", "튜토리얼" 등)
3. intent: 텍스트의 주요 의도 (예: "정보 제공", "문제 해결", "안내", "설명" 등)
4. content_type: 콘텐츠 유형 (예: "FAQ", "가이드", "보고서", "공지사항" 등)
5. keywords: 핵심 키워드 리스트 (3-7개, 중요도 순)
6. summary: 텍스트 요약 (한 줄, 50자 이내)
7. is_tool_related: 도구/기능 관련 여부 (true/false)
8. requires_db_check: 데이터베이스 확인 필요 여부 (true/false)

응답은 반드시 JSON 형식으로만 작성하고, 다른 설명은 추가하지 마세요."""

# Few-shot 예시 (2개) — 범용 문서 메타데이터 추출 예시
FEW_SHOT_EXAMPLES = """
예시 1:
입력:
Python에서 리스트 컴프리헨션을 사용하면 반복문을 한 줄로 작성할 수 있습니다. 예를 들어 [x*2 for x in range(10)]은 0부터 9까지의 숫자를 2배로 만든 리스트를 생성합니다. 조건문도 추가할 수 있어 필터링과 변환을 동시에 처리합니다.

출력:
{
  "category": "기술",
  "subcategory": "프로그래밍",
  "intent": "정보 제공",
  "content_type": "튜토리얼",
  "keywords": ["Python", "리스트 컴프리헨션", "반복문", "필터링", "변환"],
  "summary": "Python 리스트 컴프리헨션 사용법 설명",
  "is_tool_related": true,
  "requires_db_check": false
}

예시 2:
입력:
2024년 하반기 매출이 전년 대비 15% 증가했습니다. 주요 성장 요인은 신규 고객 유입과 기존 고객의 재구매율 향상입니다. 특히 온라인 채널의 매출 비중이 40%에서 55%로 확대되었으며, 모바일 결제 비율도 크게 늘었습니다.

출력:
{
  "category": "비즈니스",
  "subcategory": "매출분석",
  "intent": "정보 제공",
  "content_type": "보고서",
  "keywords": ["매출", "성장률", "온라인 채널", "재구매율", "모바일 결제"],
  "summary": "2024년 하반기 매출 15% 증가, 온라인 채널 성장",
  "is_tool_related": false,
  "requires_db_check": true
}
"""

# 사용자 프롬프트 템플릿 — 범용 텍스트 분석
USER_PROMPT_TEMPLATE = """다음 텍스트를 분석하여 JSON 형식으로 메타데이터를 추출해주세요:

{content}

위 내용을 분석하여 다음 JSON 형식으로 응답해주세요:
{{
  "category": "주요 카테고리",
  "subcategory": "세부 카테고리",
  "intent": "텍스트의 주요 의도",
  "content_type": "콘텐츠 유형",
  "keywords": ["키워드1", "키워드2", "키워드3"],
  "summary": "한 줄 요약",
  "is_tool_related": false,
  "requires_db_check": false
}}

주의: JSON만 출력하고 다른 설명은 추가하지 마세요."""


def build_enrichment_prompt(content: str, include_examples: bool = True) -> tuple[str, str]:
    """
    보강 프롬프트 생성

    Args:
        content: 분석할 문서 내용
        include_examples: Few-shot 예시 포함 여부 (기본: True)

    Returns:
        tuple[str, str]: (system_prompt, user_prompt)

    사용 예시:
        >>> system_prompt, user_prompt = build_enrichment_prompt(
        ...     "Python 리스트 컴프리헨션 사용법에 대한 설명입니다."
        ... )
        >>> # LLM에 전달
        >>> response = llm.chat([
        ...     {"role": "system", "content": system_prompt},
        ...     {"role": "user", "content": user_prompt}
        ... ])
    """
    # 시스템 프롬프트 구성
    system_prompt = SYSTEM_PROMPT
    if include_examples:
        system_prompt += "\n\n" + FEW_SHOT_EXAMPLES

    # 사용자 프롬프트 구성
    user_prompt = USER_PROMPT_TEMPLATE.format(content=content)

    return system_prompt, user_prompt


def build_batch_enrichment_prompt(
    documents: list[dict], include_examples: bool = True
) -> tuple[str, str]:
    """
    배치 보강 프롬프트 생성 (최대 10개 문서)

    Args:
        documents: 분석할 문서 리스트 (각 문서는 content 필드 포함)
        include_examples: Few-shot 예시 포함 여부 (기본: True)

    Returns:
        tuple[str, str]: (system_prompt, user_prompt)

    사용 예시:
        >>> documents = [
        ...     {"content": "Python 리스트 컴프리헨션 설명..."},
        ...     {"content": "2024년 하반기 매출 보고서..."}
        ... ]
        >>> system_prompt, user_prompt = build_batch_enrichment_prompt(documents)
    """
    # 시스템 프롬프트 (동일)
    system_prompt = SYSTEM_PROMPT
    if include_examples:
        system_prompt += "\n\n" + FEW_SHOT_EXAMPLES

    # 배치 사용자 프롬프트 구성
    batch_content = ""
    for i, doc in enumerate(documents[:10], 1):  # 최대 10개
        content = doc.get("content", "")
        batch_content += f"\n\n--- 문서 {i} ---\n{content}"

    user_prompt = f"""다음 {len(documents[:10])}개의 텍스트를 각각 분석하여 JSON 배열로 응답해주세요:
{batch_content}

각 문서에 대해 다음 JSON 형식으로 응답해주세요 (배열 형태):
[
  {{
    "category": "주요 카테고리",
    "subcategory": "세부 카테고리",
    "intent": "텍스트의 주요 의도",
    "content_type": "콘텐츠 유형",
    "keywords": ["키워드1", "키워드2"],
    "summary": "한 줄 요약",
    "is_tool_related": false,
    "requires_db_check": false
  }},
  ...
]

주의: JSON 배열만 출력하고 다른 설명은 추가하지 마세요."""

    return system_prompt, user_prompt
