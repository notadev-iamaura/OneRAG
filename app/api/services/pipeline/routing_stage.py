"""1단계 라우팅 + 2단계 컨텍스트 준비(세션 컨텍스트, 멀티턴 재작성, 쿼리 확장).

rag_pipeline.py 의 RAGPipeline 에서 분리한 단계 믹스인. 동작은 분리 전과 동일하다.
"""
from __future__ import annotations

import os
import time
from typing import Any, cast

from ....lib.langfuse_client import observe  # Langfuse 트레이싱
from ....lib.logger import get_logger
from ....lib.types import RAGResultDict
from .base import PipelineStateBase
from .models import PreparedContext, RouteDecision

logger = get_logger(__name__)


# RuleBasedRouter 클래스 지연 임포트 캐시(_create_rule_based_router 가 1회만 임포트)
RuleBasedRouter: Any | None = None


class RoutingStageMixin(PipelineStateBase):
    """1단계 라우팅 + 2단계 컨텍스트 준비(세션 컨텍스트, 멀티턴 재작성, 쿼리 확장)."""


    def _create_rule_based_router(self) -> Any:
        """
        RuleBasedRouter 인스턴스를 생성한다 (__init__ eager / route_query lazy 공용).

        모듈 전역 캐시(RuleBasedRouter)를 활용해 임포트는 1회만 수행한다.
        생성 로직을 단일 지점으로 모아 eager/lazy 두 경로가 갈라지지 않게 한다.

        Returns:
            RuleBasedRouter 인스턴스 (enabled=True)

        Raises:
            Exception: 설정 파일 로드 실패 등 생성 실패 시 호출부에서 처리
        """
        global RuleBasedRouter
        if RuleBasedRouter is None:
            from ....modules.core.routing.rule_based_router import (
                RuleBasedRouter as _RuleBasedRouter,
            )

            RuleBasedRouter = _RuleBasedRouter

        return RuleBasedRouter(enabled=True)


    def _build_blocked_decision(
        self,
        message: str,
        start_time: float,
        routing_metadata: dict[str, Any],
        answer: str | None,
        provider: str,
    ) -> RouteDecision:
        # topic 추출 실패가 규칙 차단 try를 깨뜨려 fail-open 되지 않게 한다.
        try:
            topic = self.extract_topic_func(message)
        except Exception:
            topic = "general"
        immediate_response = {
            "answer": answer or self._DEFAULT_BLOCKED_ANSWER,
            "sources": [],
            "tokens_used": 0,
            "topic": topic,
            "processing_time": time.time() - start_time,
            "search_count": 0,
            "ranked_count": 0,
            "model_info": {"provider": provider, "model": "N/A"},
            "routing_metadata": routing_metadata,
        }
        return RouteDecision(
            should_continue=False,
            immediate_response=cast(RAGResultDict, immediate_response),
            metadata=routing_metadata,
        )


    def _create_fallback_response(
        self, message: str, start_time: float, routing_metadata: dict[str, Any]
    ) -> RAGResultDict:
        """라우팅 실패 시 기본 응답 생성"""
        processing_time = time.time() - start_time
        return cast(
            RAGResultDict,
            {
                "answer": "응답을 생성할 수 없습니다.",
                "sources": [],
                "tokens_used": 0,
                "topic": self.extract_topic_func(message),
                "processing_time": processing_time,
                "search_results": 0,
                "ranked_results": 0,
                "model_info": {"provider": "system", "model": "fallback"},
                "routing_metadata": routing_metadata,
            },
        )


    async def route_query(self, message: str, session_id: str, start_time: float) -> RouteDecision:
        """
        1단계: 쿼리 라우팅 (규칙 기반 + LLM 폴백)

        - 규칙 기반 라우터 우선 시도 (YAML 규칙)
        - LLM 라우터 폴백 (규칙 실패 시)
        - direct_answer/blocked 처리

        Args:
            message: 사용자 쿼리
            session_id: 세션 ID
            start_time: 파이프라인 시작 시간

        Returns:
            RouteDecision: 라우팅 결정 (계속 진행 여부 + 즉시 응답)

        Raises:
            RoutingError: 라우팅 실패 시
        """
        logger.debug("[1단계] 쿼리 라우팅 시작")
        routing_metadata = {}
        session_context = None
        if self.session_module:
            try:
                conversation = await self.session_module.get_conversation(
                    session_id, max_exchanges=5
                )
                if conversation and isinstance(conversation, list):
                    session_context = "\n".join(
                        [
                            f"User: {ex.get('user', '')}\nAssistant: {ex.get('assistant', '')}"
                            for ex in conversation
                        ]
                    )
            except Exception as e:
                logger.warning(
                    "세션 컨텍스트 조회 실패",
                    extra={"error": str(e)},
                    exc_info=True
                )
        try:
            # __init__에서 1회 생성한 라우터를 재사용한다.
            # 초기화에 실패했던 경우에만 공용 헬퍼로 lazy 생성 폴백한다.
            # (일시적 실패였다면 여기서 복구되고, 성공 시 캐시되어 재시도 중단)
            rule_router = self.rule_based_router
            if rule_router is None:
                rule_router = self._create_rule_based_router()
                self.rule_based_router = rule_router

            rule_match = await rule_router.check_rules(message)
            if rule_match:
                routing_metadata = {
                    "route": rule_match.route,
                    "intent": rule_match.intent,
                    "domain": rule_match.domain,
                    "confidence": rule_match.confidence,
                    "source": "rule_based",
                    "rule_name": rule_match.rule_name,
                }
                logger.info(
                    "[규칙 기반 라우터] 매칭",
                    extra={
                        "rule_name": rule_match.rule_name,
                        "route": rule_match.route,
                        "domain": rule_match.domain
                    }
                )
                if rule_match.route == "direct_answer" and rule_match.direct_answer:
                    processing_time = time.time() - start_time
                    immediate_response = {
                        "answer": rule_match.direct_answer,
                        "sources": [],
                        "tokens_used": 0,
                        "topic": self.extract_topic_func(message),
                        "processing_time": processing_time,
                        "search_count": 0,
                        "ranked_count": 0,
                        "model_info": {"provider": "rule_based", "model": "N/A"},
                        "routing_metadata": routing_metadata,
                    }

                    logger.info(
                        "[즉시 응답] 규칙 기반 답변 반환",
                        extra={"processing_time": processing_time}
                    )
                    return RouteDecision(
                        should_continue=False,
                        immediate_response=cast(RAGResultDict, immediate_response),
                        metadata=routing_metadata,
                    )
                if rule_match.route == "blocked":
                    logger.warning(
                        "[차단] 규칙 기반 차단",
                        extra={"rule_name": rule_match.rule_name},
                    )
                    return self._build_blocked_decision(
                        message, start_time, routing_metadata,
                        rule_match.direct_answer, "rule_based",
                    )
                return RouteDecision(
                    should_continue=True, immediate_response=None, metadata=routing_metadata
                )
        except Exception as rule_error:
            logger.warning(
                "[RuleBasedRouter] 오류",
                extra={"error": str(rule_error)},
                exc_info=True
            )
        if not self.query_router or not self.query_router.enabled:
            logger.info("[LLM 라우터] 비활성화 - RAG 계속 진행")
            return RouteDecision(
                should_continue=True, immediate_response=None, metadata=routing_metadata
            )
        try:
            profile, routing = await self.query_router.analyze_and_route(
                message, session_context=session_context
            )

            # 🆕 dataclass 속성 접근으로 수정 (Oracle 권장사항)
            routing_metadata.update(
                {
                    "llm_route": routing.primary_route,  # ✅ .get() → 속성 접근
                    "llm_intent": profile.intent.value if profile.intent else "unknown",  # ✅
                    "llm_domain": profile.domain,  # ✅
                    "llm_confidence": routing.confidence,  # ✅
                    "llm_reasoning": routing.notes or "",  # ✅
                    "data_source": getattr(profile, "data_source", "general"),  # 🆕 신규 필드
                    "source": routing_metadata.get("source", "llm"),
                    "profile": profile,
                }
            )
            logger.info(
                "[LLM 라우터] 라우팅 완료",
                extra={
                    "route": routing.primary_route,
                    "data_source": routing_metadata['data_source'],
                    "intent": profile.intent.value if profile.intent else 'unknown',
                    "confidence": routing.confidence
                }
            )
            if routing.primary_route == "blocked":
                logger.warning(
                    "[차단] 쿼리가 차단됨",
                    extra={"reason": routing.notes}
                )
                return self._build_blocked_decision(
                    message, start_time, routing_metadata,
                    getattr(routing, "direct_answer", None), "query_router",
                )
            if routing.primary_route == "direct_answer" and getattr(
                routing, "direct_answer", ""
            ):
                processing_time = time.time() - start_time
                immediate_response = {
                    "answer": routing.direct_answer,
                    "sources": [],
                    "tokens_used": 0,
                    "topic": self.extract_topic_func(message),
                    "processing_time": processing_time,
                    "search_count": 0,
                    "ranked_count": 0,
                    "model_info": {"provider": "query_router", "model": "N/A"},
                    "routing_metadata": routing_metadata,
                }
                logger.info(
                    "[즉시 응답] LLM 라우터 direct_answer 반환",
                    extra={"processing_time": processing_time},
                )
                return RouteDecision(
                    should_continue=False,
                    immediate_response=cast(RAGResultDict, immediate_response),
                    metadata=routing_metadata,
                )
        except Exception as llm_error:
            logger.warning(
                "[LLM 라우터] 오류",
                extra={"error": str(llm_error)},
                exc_info=True
            )
            routing_metadata["fallback_reason"] = str(llm_error)
        logger.info("[라우팅 완료] RAG 파이프라인 계속 진행")
        return RouteDecision(
            should_continue=True, immediate_response=None, metadata=routing_metadata
        )


    def _resolve_rag_mode(self, options: dict[str, Any]) -> str:
        """Resolve local/grok_search/grok_answer without changing default local flow."""
        explicit_mode = options.get("rag_mode") or options.get("grok_mode")
        if explicit_mode:
            return self._normalize_rag_mode(str(explicit_mode))

        vector_db_config = self.config.get("vector_db", {})
        vector_provider = (
            vector_db_config.get("provider")
            or self.config.get("vector_store", {}).get("provider")
            or os.getenv("VECTOR_DB_PROVIDER", "")
        )
        if str(vector_provider).lower() != "grok":
            return "local"

        grok_config = self.config.get("grok", {})
        return self._normalize_rag_mode(str(grok_config.get("mode", "search")))


    @staticmethod
    def _normalize_rag_mode(mode: str) -> str:
        normalized = mode.strip().lower().replace("-", "_")
        aliases = {
            "local": "local",
            "standard": "local",
            "grok": "grok_search",
            "grok_search": "grok_search",
            "search": "grok_search",
            "grok_answer": "grok_answer",
            "answer": "grok_answer",
        }
        return aliases.get(normalized, "local")


    def _needs_standalone_rewrite(self, message: str) -> bool:
        """
        멀티턴 standalone rewrite가 필요한지 판정하는 게이트.

        후속 질문이 대명사/지시어/생략 표현에 의존하거나 너무 짧아
        그 자체로는 검색 맥락이 불충분한 경우에만 True를 반환한다.
        이미 자립적(충분히 길고 구체적)인 질문은 False를 반환해 불필요한
        LLM 호출과 지연을 막는다.

        Args:
            message: 후속 사용자 질문(원본)

        Returns:
            True면 재작성 필요(LLM 호출 대상), False면 게이트에서 건너뜀.
        """
        stripped = message.strip()
        if not stripped:
            return False

        # (1) 대명사/지시어/생략 표현 포함 → 자립 불가로 간주
        if any(pattern in stripped for pattern in self.multiturn_followup_dependent_patterns):
            return True

        # (1-b) 문장 시작 위치의 접속사만 후속 신호로 취급
        #       (문장 중간 "A 그리고 B"는 자립 질문이므로 제외)
        if any(stripped.startswith(pattern) for pattern in self.multiturn_followup_start_patterns):
            return True

        # (2) 짧은 후속 질문(맥락 생략형). 어절(공백 분리) 기준으로 판단.
        #     예: "정규직 요건은?" 처럼 핵심 대상(프로그램명 등)이 생략된 형태.
        #     충분히 긴 질문은 자립적으로 보고 건너뛴다.
        word_count = len(stripped.split())
        if word_count <= self.multiturn_short_question_max_words:
            return True

        # (3) 그 외 길고 구체적인 질문은 자립적으로 간주 → 재작성 불필요
        return False


    def _postprocess_rewritten_query(self, content: str | None) -> str:
        """
        LLM 재작성 결과를 검색에 안전하게 투입하도록 경량 정제한다.

        모델이 프롬프트 지시를 어기고 여러 줄/머리말 라벨/따옴표를 붙이는 경우를
        방어한다. 첫 번째 비어있지 않은 줄만 취하고, "재작성: " 같은 라벨과
        앞뒤 따옴표를 제거한다.

        Args:
            content: LLM 원본 응답 텍스트(None 가능)

        Returns:
            정제된 한 줄 질문 문자열(정제 후 비면 빈 문자열).
        """
        if not content:
            return ""

        # 첫 번째 비어있지 않은 줄만 사용 (여러 줄 방어)
        first_line = ""
        for line in content.splitlines():
            if line.strip():
                first_line = line.strip()
                break
        if not first_line:
            return ""

        # 라벨 접두어 제거 (예: "재작성된 질문: ...")
        first_line = self._REWRITE_LABEL_PATTERN.sub("", first_line).strip()

        # 앞뒤 따옴표 제거 (직선/곡선 따옴표 모두)
        first_line = first_line.strip("\"'“”‘’").strip()

        return str(first_line)


    async def _rewrite_standalone_query(
        self, message: str, session_context: str | None
    ) -> str:
        """
        직전 대화 맥락을 반영해 후속 질문을 자립적(standalone) 질문으로 재작성.

        게이트(`_needs_standalone_rewrite`)와 사전 조건(설정 활성화, 세션 맥락,
        llm_factory 존재)을 모두 통과한 경우에만 LLM을 호출한다. 재작성에
        실패하면(예외/빈 결과) 원본 질문으로 graceful 폴백하여 검색을 계속한다.

        Args:
            message: 후속 사용자 질문(원본)
            session_context: 직전 대화 컨텍스트 문자열(없으면 재작성 생략)

        Returns:
            재작성된 standalone 질문, 또는 폴백 시 원본 질문.
        """
        # 사전 조건 확인 (어느 하나라도 불충족이면 원본 반환)
        if not self.multiturn_rewrite_enabled:
            return message
        if not session_context or not session_context.strip():
            return message
        if self.llm_factory is None:
            logger.debug("standalone rewrite 생략: llm_factory 없음")
            return message

        # 게이트: 자립적 질문이면 LLM 호출 없이 건너뜀
        if not self._needs_standalone_rewrite(message):
            logger.debug(
                "standalone rewrite 게이트 통과(자립적 질문), 재작성 생략",
                extra={"message": message[:40]},
            )
            return message

        # LLM 재작성 프롬프트 구성 (설정 템플릿 기반, 기본값=한국어 프롬프트)
        # 템플릿에 {session_context}/{message} 외 중괄호가 있어도 깨지지 않도록
        # 안전 치환한다(format은 임의 중괄호에 취약).
        # 컴파일된 패턴으로 두 토큰을 단일 패스 치환해, 치환 값 내부에
        # 리터럴 토큰이 있어도 재치환되지 않도록 차단한다.
        values = {"{session_context}": session_context, "{message}": message}
        prompt = self._REWRITE_PLACEHOLDER_PATTERN.sub(
            lambda m: values[m.group(0)], self.multiturn_rewrite_prompt_template
        )

        try:
            # 결정적(temperature=0.0) 호출로 재작성의 비결정성을 차단.
            # max_tokens는 thinking(추론) 모델이 추론에 토큰을 소진해 출력이
            # 빈 채 truncate되는 회귀(실가동 관측)를 막기 위해 넉넉히 둔다.
            content, provider = await self.llm_factory.generate_with_fallback(
                prompt=prompt,
                system_prompt=None,
                preferred_provider=self.multiturn_rewrite_provider,
                temperature=0.0,
                max_tokens=2048,
            )
            rewritten = self._postprocess_rewritten_query(content)
            # 빈 결과/비정상적으로 긴 결과는 신뢰하지 않고 폴백
            if not rewritten or len(rewritten) > len(message) + 200:
                logger.warning(
                    "standalone rewrite 결과 비정상, 원본 사용",
                    extra={"original": message[:40]},
                )
                return message

            logger.info(
                "standalone rewrite 성공",
                extra={
                    "provider": provider,
                    "original": message[:40],
                    "rewritten": rewritten[:60],
                },
            )
            return rewritten
        except Exception as e:
            # LLM 실패는 채팅을 깨뜨리지 않고 원본으로 폴백
            logger.warning(
                "standalone rewrite 실패, 원본 사용",
                extra={"error": str(e), "original": message[:40]},
                exc_info=True,
            )
            return message


    # NOTE: _get_score_multipliers() 함수 제거됨 (2026-01-02)
    # 스코어 가중치는 ScoringService(rag.yaml의 scoring 섹션)에서 관리됩니다.
    # 마이그레이션 가이드: DOMAIN_CUSTOMIZATION_GUIDE.md 참조

    @observe(name="Query Expansion & Context Preparation", capture_input=False, capture_output=False)
    async def prepare_context(self, message: str, session_id: str) -> PreparedContext:
        """
        2단계: 세션 컨텍스트 조회 + 쿼리 확장

        - 세션 모듈에서 최근 5개 대화 조회
        - 쿼리 확장 모듈로 쿼리 확장 (선택적)

        Args:
            message: 원본 쿼리
            session_id: 세션 ID

        Returns:
            PreparedContext: 세션 컨텍스트 + 확장된 쿼리
        """
        logger.debug("[3단계] 컨텍스트 준비 시작")
        session_context = None
        if self.session_module:
            try:
                context_string = await self.session_module.get_context_string(session_id)
                if context_string:
                    session_context = context_string
                    logger.debug(
                        "세션 컨텍스트 로드 성공",
                        extra={"context_length": len(context_string)}
                    )
                else:
                    logger.debug("세션 컨텍스트 비어있음")
            except Exception as e:
                logger.warning(
                    "세션 컨텍스트 조회 실패",
                    extra={"error": str(e)},
                    exc_info=True
                )

        # 멀티턴 standalone query rewrite (검색 측 맥락 보강, 기본 OFF)
        # 직전 대화가 있고 후속 질문이 자립적이지 않으면(대명사/생략/축약),
        # 직전 맥락을 반영한 standalone 질문으로 재작성해 검색에 투입한다.
        # 원본 질문(message)은 PreparedContext.original_query로 보존된다.
        search_message = await self._rewrite_standalone_query(message, session_context)

        # Multi-Query RRF: 모든 확장 쿼리와 가중치 추출
        expanded_query = search_message
        expanded_queries: list[str] = []
        query_weights: list[float] = []

        if self.query_expansion:
            try:
                logger.debug("쿼리 확장 시도")
                expansion_result = await self.query_expansion.expand_query(
                    query=search_message, context=session_context
                )

                if expansion_result and hasattr(expansion_result, "expansions"):
                    if expansion_result.expansions:
                        # metadata에서 raw_expanded_queries 추출 (weight 정보 포함)
                        raw_queries = expansion_result.metadata.get("raw_expanded_queries", [])

                        if raw_queries:
                            # 원본 데이터에서 쿼리와 가중치 추출
                            for item in raw_queries:
                                if isinstance(item, dict):
                                    query = item.get("query", "")
                                    weight = item.get("weight", 1.0)
                                    if query:
                                        expanded_queries.append(query)
                                        query_weights.append(weight)

                        # raw_queries가 없으면 expansions에서 추출 (가중치는 동일하게)
                        if not expanded_queries:
                            expanded_queries = expansion_result.expansions
                            query_weights = [1.0] * len(expanded_queries)

                        expanded_query = expanded_queries[0]  # 첫 번째 쿼리 (하위 호환성)
                        logger.info(
                            "쿼리 확장 성공",
                            extra={
                                "query_count": len(expanded_queries),
                                "weights": [f'{w:.1f}' for w in query_weights],
                                "original": message[:30],
                                "expanded": expanded_query[:30]
                            }
                        )
                    else:
                        logger.debug("쿼리 확장 결과 없음, 원본 사용")
                        expanded_queries = [search_message]
                        query_weights = [1.0]
                else:
                    logger.debug("쿼리 확장 결과 없음, 원본 사용")
                    expanded_queries = [search_message]
                    query_weights = [1.0]
            except Exception as e:
                logger.warning(
                    "쿼리 확장 실패, 원본 사용",
                    extra={"error": str(e)},
                    exc_info=True
                )
                expanded_queries = [search_message]
                query_weights = [1.0]
        else:
            # query_expansion 모듈 없음
            expanded_queries = [search_message]
            query_weights = [1.0]

        # 정확 식별자 보강(GAP A, 기본 OFF): 재작성된 검색 질문을 시드로 식별자/라틴
        # 구문 프로브 쿼리를 추가 주입한다. exact_identifier.enabled=false면 no-op.
        expanded_queries, query_weights = self._augment_search_queries_with_exact_terms(
            search_message,
            expanded_queries,
            query_weights,
        )
        expanded_query = expanded_queries[0] if expanded_queries else expanded_query

        # 멀티턴 anchor 추출(GAP B, 기본 OFF): 원본 질문(message)으로 오염 게이트를
        # 판정한다. multiturn_anchor.enabled=false면 빈 리스트(no-op).
        anchor_sources = await self._extract_anchor_sources(message, session_id)

        logger.debug(
            "[3단계] 컨텍스트 준비 완료",
            extra={"expanded_query": expanded_query[:50]}
        )
        return PreparedContext(
            session_context=session_context,
            expanded_query=expanded_query,
            original_query=message,
            expanded_queries=expanded_queries,
            query_weights=query_weights,
            anchor_sources=anchor_sources,
        )

