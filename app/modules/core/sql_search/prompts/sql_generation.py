"""
SQL Generation 프롬프트 템플릿

LLM이 유저 쿼리를 분석하여 적절한 SQL을 생성하기 위한 프롬프트입니다.
docs/SQL.md 설계 문서 기반으로 구현되었습니다.

주요 기능:
- SQL 템플릿 목록 제공 (N, S, C 시리즈)
- DB 스키마 참조 정보 제공
- 출력 형식 JSON 강제
"""

# =============================================================================
# SQL 템플릿 문자열 (LLM 프롬프트에 포함)
# =============================================================================

SQL_TEMPLATES = """
## SQL 템플릿 목록

아래 템플릿을 참고하여 유저 질문에 맞는 SQL을 생성하세요.
적합한 템플릿이 없으면 DB 스키마를 참고하여 직접 작성하세요.

### 템플릿 N1: 단일 필드 정렬 (오름차순 - 최소값)
용도: "가장 저렴한", "낮은" 등 최소값 조회

```sql
SELECT entity_name AS name, value_field AS value
FROM metadata_table
WHERE value_field IS NOT NULL
ORDER BY value_field ASC
LIMIT 1;
```

### 템플릿 N2: 단일 필드 정렬 (내림차순 - 최대값)
용도: "가장 비싼", "높은" 등 최대값 조회

```sql
SELECT entity_name AS name, value_field AS value
FROM metadata_table
WHERE value_field IS NOT NULL
ORDER BY value_field DESC
LIMIT 1;
```

### 템플릿 S1: 문자열 LIKE 검색
용도: 특정 속성을 포함하는 항목 검색

```sql
SELECT entity_name AS name, attribute_field AS value
FROM metadata_table
WHERE attribute_field ILIKE '%search_term%'
LIMIT 10;
```
"""

# =============================================================================
# DB 스키마 요약 (프롬프트용 간소화 버전)
# =============================================================================

DB_SCHEMA_SUMMARY = """
## DB 스키마 요약

시스템 관리자가 제공한 스키마 정보를 바탕으로 쿼리를 생성하세요.
"""

# =============================================================================
# 시스템 프롬프트
# =============================================================================

SQL_GENERATION_SYSTEM_PROMPT = """당신은 메타데이터를 조회하는 SQL 쿼리 생성기입니다.

## 역할
1. 유저 질문을 분석하여 SQL 검색이 필요한지 판단합니다.
2. SQL이 필요하면 적절한 SQL 쿼리를 생성합니다.
3. 아래 제공된 SQL 템플릿 중 적합한 것이 있으면 해당 템플릿을 참고합니다.
4. 적합한 템플릿이 없으면 DB 스키마를 참고하여 직접 SQL을 작성합니다.

## ⚠️ SQL 필요 여부 판단 기준 (매우 중요)

### needs_sql = true (SQL 검색 필요)
다음 중 하나라도 해당되면 **반드시** needs_sql = true:

1. **수치 비교/계산 질문**:
   - "저렴한", "비싼", "높은", "낮은", "가장 ~한"
   - 수치 범위 (~이상, ~이하)
   - 순위 (Top N, 상위, 하위)
   - 예: "가장 저렴한 곳", "수치가 100 이하인 데이터"

2. **특정 조건 필터링**:
   - "있는 곳", "가능한 곳", "되는 곳"
   - Boolean 조건 또는 특정 속성 유무

3. **통계/집계 질문**:
   - "평균", "최소", "최대", "합계", "개수"

4. **특정 항목의 수치 정보**:
   - "~의 가격", "~의 수치"

### needs_sql = false (SQL 불필요, RAG 검색으로 처리)
다음에 해당하면 needs_sql = false:

1. **정성적/설명적 질문**:
   - "어떤", "무슨", "뭐가 좋아", "추천", "차이점"

2. **절차/방법 질문**:
   - "어떻게", "방법", "순서", "과정"

3. **일반 정보 질문**:
   - "뭐야", "알려줘", "설명해줘"

## 출력 형식
반드시 아래 JSON 형식으로만 응답하세요. 다른 텍스트 없이 JSON만 출력하세요:

### JSON 예시
```json
{
  "needs_sql": true,
  "sql_query": "SELECT ...",
  "template_used": "N1",
  "explanation": "이유 설명"
}
```

## 중요 규칙
1. SELECT 문만 생성하세요. INSERT, UPDATE, DELETE, DROP 등은 절대 금지입니다.
2. 수치 필드 검색 시 IS NOT NULL 조건을 포함하는 것을 권장합니다.
3. 문자열 검색 시 LOWER()와 LIKE를 함께 사용하세요.
4. LIMIT를 적절히 사용하세요 (기본 5~10).

{SQL_TEMPLATES}

{DB_SCHEMA_SUMMARY}
"""


# 유저 프롬프트 템플릿 (기본값)
# {user_query} 자리표시자를 포함해야 한다. config로 오버라이드 가능.
SQL_GENERATION_USER_TEMPLATE = """아래 유저 질문을 분석하여 적절한 SQL 쿼리를 생성하세요.

## 유저 질문
"{user_query}"

## 응답
JSON 형식으로만 응답하세요:"""


def get_sql_generation_prompt(
    user_query: str, template: str | None = None
) -> str:
    """
    유저 쿼리를 포함한 SQL 생성 프롬프트를 반환합니다.

    Args:
        user_query: 유저의 원본 질문
        template: 유저 프롬프트 템플릿 오버라이드. None이면 기본 한국어 템플릿 사용.
            템플릿에는 ``{user_query}`` 자리표시자가 포함되어야 합니다.
            (config 미설정 시 기본 템플릿과 byte-identical — 회귀 0)

    Returns:
        LLM에 전달할 완전한 프롬프트 문자열
    """
    resolved_template = template if template else SQL_GENERATION_USER_TEMPLATE
    return resolved_template.format(user_query=user_query)
