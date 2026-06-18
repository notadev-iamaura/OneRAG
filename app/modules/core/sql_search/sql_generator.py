"""
SQL Generator 모듈

LLM을 호출하여 유저 쿼리에 맞는 SQL을 생성합니다.
OpenRouter API를 통해 Claude 모델을 사용합니다.

주요 기능:
- 유저 쿼리 분석 및 SQL 생성
- SQL 템플릿 참조 또는 직접 생성
- SQL Injection 방지 (SELECT만 허용)
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any

from openai import OpenAI

from ....lib.langfuse_client import observe, record_generation
from ....lib.logger import get_logger
from .prompts.sql_generation import SQL_GENERATION_SYSTEM_PROMPT, get_sql_generation_prompt

logger = get_logger(__name__)

# OpenRouter API 기본 URL
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


@dataclass
class SingleSQLQuery:
    """단일 SQL 쿼리 정보 (멀티 쿼리 지원용)"""

    sql_query: str
    template_used: str | None
    explanation: str
    target_category: str | None = None


@dataclass
class SQLGenerationResult:
    """SQL 생성 결과 데이터 클래스 (멀티 쿼리 지원)"""

    needs_sql: bool
    sql_query: str | None  # 단일 쿼리 (하위 호환성)
    template_used: str | None
    explanation: str
    raw_response: str = ""
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    # 멀티 쿼리 지원 필드
    queries: list[SingleSQLQuery] = field(default_factory=list)
    is_multi_query: bool = False

    @property
    def is_success(self) -> bool:
        """SQL 생성 성공 여부"""
        if self.is_multi_query:
            return self.error is None and len(self.queries) > 0
        return self.error is None and (not self.needs_sql or self.sql_query is not None)

    @property
    def query_count(self) -> int:
        """생성된 쿼리 수"""
        if self.is_multi_query:
            return len(self.queries)
        return 1 if self.sql_query else 0


class SQLGenerator:
    """
    SQL Generator - LLM 기반 SQL 쿼리 생성기

    OpenRouter를 통해 Claude 모델에 SQL 생성을 요청합니다.
    생성된 SQL은 SELECT만 허용하는 안전 검증을 거칩니다.
    """

    # 위험한 SQL 키워드 (SELECT 외 모든 DML/DDL)
    DANGEROUS_KEYWORDS = frozenset(
        [
            "INSERT",
            "UPDATE",
            "DELETE",
            "DROP",
            "ALTER",
            "TRUNCATE",
            "CREATE",
            "REPLACE",
            "GRANT",
            "REVOKE",
            "EXECUTE",
            "EXEC",
            "MERGE",
            "CALL",
            "DO",
            "HANDLER",
            "LOAD",
            "UNLOAD",
        ]
    )

    def __init__(
        self,
        config: dict[str, Any],
        api_key: str | None = None,
    ):
        """
        SQL Generator 초기화

        Args:
            config: SQL 검색 설정
            api_key: OpenRouter API 키 (없으면 환경변수에서 로드)
        """
        self.config = config
        self.api_key = api_key or os.environ.get("OPENROUTER_API_KEY", "")

        if not self.api_key:
            logger.warning("OPENROUTER_API_KEY가 설정되지 않았습니다")

        # OpenAI 클라이언트 (OpenRouter 호환)
        self._client: OpenAI | None = None

        # 설정값
        self.model = config.get("model", "anthropic/claude-opus-4.5")
        self.max_tokens = config.get("max_tokens", 1024)
        self.temperature = config.get("temperature", 0.1)  # SQL 생성은 일관성이 중요

        # 프롬프트 외부화 (sql_search.generator.prompts.*)
        # 미설정 시 모듈 기본 프롬프트로 폴백한다(회귀 0).
        prompts_cfg = config.get("prompts") or {}
        self._system_prompt: str = (
            prompts_cfg.get("system") or SQL_GENERATION_SYSTEM_PROMPT
        )
        # 유저 프롬프트 템플릿은 {user_query} 자리표시자를 포함해야 한다.
        self._user_template: str | None = prompts_cfg.get("user_template") or None

        logger.info(
            f"SQLGenerator 초기화: model={self.model}, "
            f"prompts_overridden={bool(prompts_cfg)}"
        )

    @property
    def client(self) -> OpenAI:
        """OpenAI 클라이언트 (지연 초기화)"""
        if self._client is None:
            self._client = OpenAI(
                base_url=OPENROUTER_BASE_URL,
                api_key=self.api_key,
            )
        return self._client

    @observe(
        as_type="generation",
        name="SQL Generation",
        capture_input=False,
        capture_output=False,
    )
    async def generate(
        self,
        user_query: str,
        schema_summary: str | None = None,
        templates: str | None = None,
    ) -> SQLGenerationResult:
        """
        유저 쿼리를 분석하여 SQL을 생성합니다.

        Args:
            user_query: 유저의 원본 질문
            schema_summary: DB 스키마 요약 (없으면 기본값)
            templates: SQL 템플릿 목록 (없으면 기본값)

        Returns:
            SQLGenerationResult: SQL 생성 결과
        """
        if not self.api_key:
            return SQLGenerationResult(
                needs_sql=False,
                sql_query=None,
                template_used=None,
                explanation="API 키가 설정되지 않았습니다",
                error="OPENROUTER_API_KEY not configured",
            )

        try:
            # LLM 호출
            logger.info(f"SQL 생성 요청: query={user_query[:50]}...")

            system_prompt = self._system_prompt
            if schema_summary:
                system_prompt = system_prompt.replace("{DB_SCHEMA_SUMMARY}", schema_summary)
            if templates:
                system_prompt = system_prompt.replace("{SQL_TEMPLATES}", templates)

            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": get_sql_generation_prompt(
                            user_query, template=self._user_template
                        ),
                    },
                ],
                max_tokens=self.max_tokens,
                temperature=self.temperature,
            )

            raw_response = response.choices[0].message.content or ""
            logger.debug(f"LLM 응답: {raw_response[:200]}...")

            # SQL 생성 LLM 호출의 토큰/비용을 Langfuse generation으로 기록(OpenAI SDK usage)
            usage = getattr(response, "usage", None)
            record_generation(
                model=self.model,
                prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0,
                completion_tokens=getattr(usage, "completion_tokens", 0) or 0,
                total_tokens=getattr(usage, "total_tokens", 0) or 0,
                model_parameters={"max_tokens": self.max_tokens, "temperature": self.temperature},
            )

            # JSON 파싱
            result = self._parse_response(raw_response)
            result.raw_response = raw_response

            # SQL 검증 (멀티 쿼리 지원)
            if result.needs_sql:
                if result.is_multi_query:
                    # 멀티 쿼리: 각 쿼리 개별 검증
                    valid_queries = []
                    for query in result.queries:
                        if query.sql_query and self._validate_sql(query.sql_query):
                            valid_queries.append(query)
                        else:
                            logger.warning(
                                f"멀티 쿼리 중 검증 실패: {query.sql_query[:50] if query.sql_query else 'None'}"
                            )

                    if not valid_queries:
                        result.error = "모든 SQL 쿼리가 검증에 실패했습니다 (SELECT만 허용)"
                        result.queries = []
                        result.sql_query = None
                    else:
                        result.queries = valid_queries
                        result.sql_query = valid_queries[0].sql_query  # 하위 호환성
                        logger.info(f"멀티 쿼리 검증 완료: {len(valid_queries)}개 쿼리 통과")
                elif result.sql_query:
                    # 단일 쿼리: 기존 검증 방식
                    if not self._validate_sql(result.sql_query):
                        result.error = "생성된 SQL이 안전하지 않습니다 (SELECT만 허용)"
                        result.sql_query = None
                        logger.warning(f"SQL 검증 실패: {raw_response[:100]}")

            return result

        except json.JSONDecodeError as e:
            logger.error(f"JSON 파싱 실패: {e}")
            return SQLGenerationResult(
                needs_sql=False,
                sql_query=None,
                template_used=None,
                explanation="LLM 응답 파싱 실패",
                error=str(e),
            )
        except Exception as e:
            logger.error(f"SQL 생성 중 오류: {e}")
            return SQLGenerationResult(
                needs_sql=False,
                sql_query=None,
                template_used=None,
                explanation=f"SQL 생성 실패: {e}",
                error=str(e),
            )

    def _parse_response(self, raw_response: str) -> SQLGenerationResult:
        """
        LLM 응답을 파싱하여 SQLGenerationResult를 생성합니다.
        단일 쿼리와 멀티 쿼리 모두 지원합니다.

        Args:
            raw_response: LLM의 원본 응답

        Returns:
            SQLGenerationResult: 파싱된 결과 (단일/멀티 쿼리)
        """
        # JSON 블록 추출 (```json ... ``` 또는 그냥 JSON)
        json_match = re.search(r"```json\s*(.*?)\s*```", raw_response, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            # JSON 블록이 없으면 전체를 JSON으로 시도
            json_str = raw_response.strip()
            # 시작/끝의 불필요한 텍스트 제거
            if json_str.startswith("{"):
                json_str = json_str[json_str.index("{") :]
            if "}" in json_str:
                json_str = json_str[: json_str.rindex("}") + 1]

        data = json.loads(json_str)

        # 멀티 쿼리 여부 확인
        is_multi_query = data.get("is_multi_query", False)
        queries_data = data.get("queries", [])

        if is_multi_query and queries_data:
            # 멀티 쿼리 파싱
            queries = []
            for q in queries_data:
                single_query = SingleSQLQuery(
                    sql_query=q.get("sql_query", ""),
                    template_used=q.get("template_used"),
                    explanation=q.get("explanation", ""),
                    target_category=q.get("target_category"),
                )
                queries.append(single_query)

            logger.info(f"멀티 쿼리 파싱 완료: {len(queries)}개 쿼리 생성")

            return SQLGenerationResult(
                needs_sql=data.get("needs_sql", True),
                sql_query=queries[0].sql_query if queries else None,  # 하위 호환성
                template_used=queries[0].template_used if queries else None,
                explanation=data.get("explanation", ""),
                is_multi_query=True,
                queries=queries,
            )
        else:
            # 단일 쿼리 파싱 (기존 방식)
            return SQLGenerationResult(
                needs_sql=data.get("needs_sql", False),
                sql_query=data.get("sql_query"),
                template_used=data.get("template_used"),
                explanation=data.get("explanation", ""),
                is_multi_query=False,
                queries=[],
            )

    def _validate_sql(self, sql: str) -> bool:
        """
        생성된 SQL의 안전성을 검증합니다.

        Args:
            sql: 검증할 SQL 쿼리

        Returns:
            bool: 안전한 SQL인 경우 True
        """
        sql_upper = sql.strip().upper()

        # SELECT로 시작하는지 확인
        if not sql_upper.startswith("SELECT"):
            logger.warning(f"SQL이 SELECT로 시작하지 않음: {sql[:50]}")
            return False

        # 위험한 키워드 포함 여부 확인
        # 단어 경계를 확인하여 컬럼명과 구분
        for keyword in self.DANGEROUS_KEYWORDS:
            # 단어 경계를 포함한 패턴 (예: INSERT는 차단, INSERTED는 허용)
            pattern = rf"\b{keyword}\b"
            if re.search(pattern, sql_upper):
                logger.warning(f"SQL에 위험한 키워드 포함: {keyword}")
                return False

        # 세미콜론 여러 개 (다중 쿼리) 차단
        # 문자열 리터럴 내의 세미콜론은 제외
        sql_without_strings = re.sub(r"'[^']*'", "", sql)
        if sql_without_strings.count(";") > 1:
            logger.warning("SQL에 다중 쿼리 감지")
            return False

        return True

    def validate_sql(self, sql: str) -> bool:
        """
        외부에서 SQL 검증을 호출할 수 있는 공개 메서드

        Args:
            sql: 검증할 SQL 쿼리

        Returns:
            bool: 안전한 SQL인 경우 True
        """
        return self._validate_sql(sql)
