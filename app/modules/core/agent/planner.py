"""
AgentPlanner - LLM 기반 도구 선택

ReAct 패턴에서 "Reasoning" 담당 컴포넌트.
사용자 쿼리와 현재 상태를 분석하여 적절한 도구를 선택합니다.
OpenAI Function Calling 형식의 스키마를 LLM에 전달하여
구조화된 도구 선택 결과를 얻습니다.

주요 기능:
- 도구 스키마를 프롬프트에 포함하여 LLM이 적절한 도구 선택
- 이전 스텝 컨텍스트를 활용한 연속적 추론
- JSON 응답 파싱 및 폴백 처리
- 도구 호출 ID 자동 생성

사용 예시:
    planner = AgentPlanner(llm_client, mcp_server, config)
    tool_calls, reasoning, should_continue = await planner.plan(state)
"""

import json
import re
from typing import Any

from ....lib.logger import get_logger
from .interfaces import AgentConfig, AgentState, ToolCall

logger = get_logger(__name__)


# 도구 선택 프롬프트 템플릿
PLANNER_SYSTEM_PROMPT = """당신은 RAG 시스템의 도구 선택 에이전트입니다.
사용자 질문과 현재 상태를 분석하여 적절한 도구를 선택하세요.

## 사용 가능한 도구:
{tool_schemas}

## 응답 형식 (JSON만 출력):
{{
    "reasoning": "도구 선택 이유 (한국어, 1-2문장)",
    "tool_calls": [
        {{
            "tool_name": "도구 이름",
            "arguments": {{"arg1": "value1"}}
        }}
    ],
    "should_continue": true/false,
    "direct_answer": "도구 없이 답변 가능한 경우 (선택적)"
}}

## 도구별 사용 가이드라인:

### 벡터 검색 도구
- **search_weaviate**: 문서 내용 기반 시맨틱 검색
  - 사용 시점: 일반적인 정보 검색, 유사 문서 찾기
  - 예시: "강남 맛집 찾아줘", "최신 노트북 추천"

### 메타데이터/SQL 도구
- **query_sql**: 자연어를 SQL로 변환하여 구조화된 데이터 검색
  - 사용 시점: 날짜, 숫자, 필터 조건이 포함된 질문
  - 예시: "2024년 매출", "가격이 100만원 이하인 상품"

### 문서 조회 도구
- **get_document_by_id**: UUID로 특정 문서 직접 조회
  - 사용 시점: 이전 검색에서 발견한 문서의 상세 정보가 필요할 때
  - 예시: 이전 스텝에서 찾은 문서 ID로 상세 조회

### GraphRAG 도구 (엔티티 관계 탐색)
- **search_graph**: 지식 그래프에서 엔티티와 관계 검색
  - 사용 시점: 엔티티 간 관계를 파악해야 할 때
  - 파라미터:
    - query (필수): 검색어
    - entity_types (선택): 엔티티 타입 필터 ["company", "person", "location"]
    - top_k (선택): 최대 결과 수 (기본값: 10)
  - 예시: "A회사와 B회사의 제휴 관계", "강남 지역 맛집들 간의 연결"

- **get_neighbors**: 특정 엔티티의 이웃 노드 탐색
  - 사용 시점: 특정 엔티티와 연결된 다른 엔티티들을 탐색할 때
  - 파라미터:
    - entity_id (필수): 탐색 시작점 엔티티 ID
    - relation_types (선택): 관계 타입 필터 ["partnership", "located_in"]
    - max_depth (선택): 탐색 깊이 (기본값: 1)
  - 예시: "X사와 연결된 모든 파트너사", "A의 협력사들"

## 도구 선택 의사결정 트리:

| 질문 유형 | 권장 도구 | 이유 |
|----------|----------|------|
| 단순 정보 검색 | search_weaviate | 시맨틱 유사도 기반 검색 |
| 관계/연결 질문 | search_graph | 그래프 구조로 관계 탐색 |
| 이웃/파트너 탐색 | get_neighbors | 특정 노드 중심 탐색 |
| 숫자/날짜 조건 | query_sql | SQL로 정확한 필터링 |
| 상세 정보 조회 | get_document_by_id | 이미 알고 있는 ID 사용 |
| 복합 질문 | 도구 조합 | 여러 도구 순차 사용 |

## 판단 규칙:
1. 정보 검색이 필요하면 search_weaviate를 사용하세요
2. 엔티티 간 관계 탐색이 필요하면 search_graph를 사용하세요
3. 특정 엔티티와 연결된 항목 탐색은 get_neighbors를 사용하세요
4. 메타데이터(날짜, 숫자 등) 조회는 query_sql을 사용하세요
5. 특정 문서 상세 조회는 get_document_by_id를 사용하세요
6. 인사말, 간단한 질문은 도구 없이 직접 답변하세요 (tool_calls=[])
7. 복잡한 질문은 여러 도구를 조합하세요
8. 이전 스텝 결과를 활용하여 다음 행동을 결정하세요
9. 충분한 정보를 얻었으면 should_continue=false로 종료하세요

## 중요:
- 반드시 JSON 형식으로만 응답하세요
- 마크다운 코드 블록(```)은 사용하지 마세요
"""

PLANNER_USER_PROMPT = """## 사용자 질문:
{query}

## 이전 대화 컨텍스트:
{context}

위 정보를 바탕으로 다음 행동을 결정하세요.
JSON 형식으로만 응답하세요."""


class AgentPlanner:
    """
    LLM 기반 도구 선택기

    ReAct 패턴에서 "Reasoning" 담당.
    사용자 쿼리와 현재 상태를 분석하여
    어떤 도구를 어떤 인자로 호출할지 결정합니다.

    Attributes:
        _llm_client: LLM 클라이언트 (generate_text 메서드 필요)
        _mcp_server: MCP 서버 (도구 스키마 조회용)
        _config: 에이전트 설정
    """

    def __init__(
        self,
        llm_client: Any,
        mcp_server: Any,
        config: AgentConfig,
    ):
        """
        AgentPlanner 초기화

        Args:
            llm_client: LLM 클라이언트 (generate_text 메서드 필요)
            mcp_server: MCP 서버 (도구 스키마 조회용)
            config: 에이전트 설정

        Raises:
            ValueError: 필수 의존성 누락 시
        """
        if llm_client is None:
            raise ValueError("llm_client는 필수입니다")
        if mcp_server is None:
            raise ValueError("mcp_server는 필수입니다")

        self._llm_client = llm_client
        self._mcp_server = mcp_server
        self._config = config

        logger.info(
            f"AgentPlanner 초기화: model={config.selector_model}, "
            f"fallback={config.fallback_tool}"
        )

    async def plan(
        self,
        state: AgentState,
    ) -> tuple[list[ToolCall], str, bool]:
        """
        다음 행동 계획 (도구 선택)

        현재 상태를 분석하여 다음에 호출할 도구를 결정합니다.
        LLM을 사용하여 지능적으로 도구를 선택합니다.

        Args:
            state: 현재 에이전트 상태 (원본 쿼리 + 이전 스텝 히스토리)

        Returns:
            tuple[list[ToolCall], str, bool]:
                - tool_calls: 호출할 도구 리스트
                - reasoning: LLM의 추론 (왜 이 도구를 선택했는지)
                - should_continue: 계속 반복할지 여부

        Note:
            LLM 호출 실패 시 폴백 도구를 반환합니다.
        """
        try:
            # 1. 도구 스키마 조회
            tool_schemas = self._mcp_server.get_tool_schemas()
            tool_schemas_str = json.dumps(tool_schemas, indent=2, ensure_ascii=False)

            # 2. 이전 컨텍스트 생성
            context = state.get_context_for_llm() or "없음 (첫 번째 스텝)"

            # 3. 프롬프트 구성
            system_prompt = PLANNER_SYSTEM_PROMPT.format(
                tool_schemas=tool_schemas_str
            )
            user_prompt = PLANNER_USER_PROMPT.format(
                query=state.original_query,
                context=context,
            )

            # 4. LLM 호출
            response = await self._llm_client.generate_text(
                prompt=user_prompt,
                system_prompt=system_prompt,
            )

            # 5. 응답 파싱
            return self._parse_response(response, state.original_query)

        except Exception as e:
            logger.error(f"AgentPlanner 에러: {e}")
            return self._fallback(state.original_query)

    def _parse_response(
        self,
        response: str,
        original_query: str,
    ) -> tuple[list[ToolCall], str, bool]:
        """
        LLM 응답 파싱

        JSON 형식의 LLM 응답을 파싱하여 도구 호출 리스트로 변환합니다.
        마크다운 코드 블록 처리 및 에러 복구를 포함합니다.

        Args:
            response: LLM 응답 문자열
            original_query: 원본 쿼리 (폴백용)

        Returns:
            tuple[list[ToolCall], str, bool]:
                - tool_calls: 파싱된 도구 호출 리스트
                - reasoning: 추론 텍스트
                - should_continue: 계속 여부
        """
        try:
            json_str = self._extract_json(response)
            data = json.loads(json_str)

            # 필드 추출 (기본값 포함)
            reasoning = data.get("reasoning", "")
            should_continue = data.get("should_continue", True)

            # 도구 호출 리스트 생성
            tool_calls = []
            for tc in data.get("tool_calls", []):
                tool_name = tc.get("tool_name", "")
                if not tool_name:
                    # tool_name이 없으면 건너뜀
                    logger.warning("tool_name 누락된 도구 호출 건너뜀")
                    continue

                arguments = tc.get("arguments", {})
                if not isinstance(arguments, dict):
                    arguments = {}

                tool_call = ToolCall(
                    tool_name=tool_name,
                    arguments=arguments,
                    reasoning=reasoning,
                )
                tool_calls.append(tool_call)

            logger.info(
                f"AgentPlanner: {len(tool_calls)}개 도구 선택 "
                f"({[tc.tool_name for tc in tool_calls]})"
            )

            return tool_calls, reasoning, should_continue

        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.warning(f"LLM 응답 파싱 실패: {e}, 폴백 사용")
            return self._fallback(original_query)

    def _extract_json(self, response: str) -> str:
        """
        응답에서 JSON 문자열 추출

        마크다운 코드 블록(```json ... ```)이나
        순수 JSON 문자열을 추출합니다.

        Args:
            response: LLM 응답 원문

        Returns:
            추출된 JSON 문자열
        """
        response = response.strip()

        # 마크다운 코드 블록 처리 (```json ... ``` 또는 ``` ... ```)
        json_match = re.search(r"```(?:json)?\s*(.*?)\s*```", response, re.DOTALL)
        if json_match:
            return json_match.group(1).strip()

        # 직접 JSON 파싱 시도 (코드 블록 없는 경우)
        return response

    def _fallback(
        self,
        query: str,
    ) -> tuple[list[ToolCall], str, bool]:
        """
        폴백 도구 선택

        LLM 호출 실패 또는 파싱 실패 시 기본 검색 도구를 사용합니다.

        Args:
            query: 원본 쿼리 (검색에 사용)

        Returns:
            tuple[list[ToolCall], str, bool]:
                - [폴백 도구 호출]
                - "폴백 모드" 메시지
                - True (계속 진행)
        """
        fallback_tool = ToolCall(
            tool_name=self._config.fallback_tool,
            arguments={"query": query, "top_k": 10},
            reasoning="폴백: 기본 검색 수행",
        )

        logger.info(f"AgentPlanner 폴백: {self._config.fallback_tool}")

        return [fallback_tool], "폴백 모드: 기본 검색 수행", True
