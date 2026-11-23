"""
RuleBasedRouter 매칭 언어 config 배선 테스트

routing.yaml의 `routing.language`가 실제 규칙 매칭 언어로 전달되는지
(데드 키가 아닌지) 검증한다. 핵심 목적:
- 기본값 'ko'로 기존 동작 보존(회귀 0)
- config(en)로 routing_rules_v2.yaml의 영어 키워드/응답 세트 활성화(데드 키 해소)
"""

from unittest.mock import patch

import pytest

from app.modules.core.routing.rule_based_router import RuleBasedRouter


class TestRouterLanguageConfig:
    """RuleBasedRouter가 config로 매칭 언어를 결정하는지 검증"""

    def _make_router(self, language: str | None) -> RuleBasedRouter:
        """디스크 config 로드를 막고 언어만 주입한 라우터 생성 헬퍼"""
        with patch.object(RuleBasedRouter, "_load_config", return_value={}):
            with patch.object(RuleBasedRouter, "_load_rules", return_value={}):
                return RuleBasedRouter(enabled=True, language=language)

    def test_default_language_is_ko(self) -> None:
        """language 미지정 + routing.language 없으면 기본 'ko'(회귀 0)"""
        with patch.object(RuleBasedRouter, "_load_config", return_value={}):
            with patch.object(RuleBasedRouter, "_load_rules", return_value={}):
                with patch.object(
                    RuleBasedRouter, "_resolve_rule_language", return_value="ko"
                ):
                    router = RuleBasedRouter(enabled=True)
        assert router._rule_language == "ko"

    def test_explicit_language_overrides(self) -> None:
        """명시적 language 인자가 최우선"""
        router = self._make_router("en")
        assert router._rule_language == "en"

    def test_resolve_reads_routing_language(self) -> None:
        """_resolve_rule_language가 routing.language를 읽는다(데드 키 아님)"""
        fake_config = {"routing": {"language": "en"}}
        with patch(
            "app.lib.config_loader.load_config", return_value=fake_config
        ):
            with patch.object(RuleBasedRouter, "_load_config", return_value={}):
                with patch.object(RuleBasedRouter, "_load_rules", return_value={}):
                    router = RuleBasedRouter(enabled=True)
        assert router._rule_language == "en"

    def test_resolve_defaults_ko_when_missing(self) -> None:
        """routing.language 미설정이면 'ko'로 폴백(회귀 0)"""
        with patch("app.lib.config_loader.load_config", return_value={"routing": {}}):
            with patch.object(RuleBasedRouter, "_load_config", return_value={}):
                with patch.object(RuleBasedRouter, "_load_rules", return_value={}):
                    router = RuleBasedRouter(enabled=True)
        assert router._rule_language == "ko"

    def test_resolve_defaults_ko_on_load_failure(self) -> None:
        """config 로드 실패해도 'ko'로 폴백(라우터 동작 보존)"""
        with patch(
            "app.lib.config_loader.load_config", side_effect=RuntimeError("boom")
        ):
            with patch.object(RuleBasedRouter, "_load_config", return_value={}):
                with patch.object(RuleBasedRouter, "_load_rules", return_value={}):
                    router = RuleBasedRouter(enabled=True)
        assert router._rule_language == "ko"

    async def test_en_language_activates_english_keywords(self) -> None:
        """en 설정 시 routing_rules_v2.yaml의 영어 키워드/응답이 활성화(데드 키 해소)"""
        router = self._make_router("en")

        # 영어 인사 키워드("hello")는 ko 고정 시 dead였던 세트
        result = await router.check_rules("hello there")

        assert result is not None
        assert result.route == "direct_answer"
        # 영어 응답 세트가 사용되어야 함(한국어 응답이 아님)
        assert result.direct_answer is not None
        assert "Hello" in result.direct_answer or "assist" in result.direct_answer

    async def test_ko_language_unchanged(self) -> None:
        """ko(기본) 설정 시 한국어 인사가 그대로 매칭(회귀 0)"""
        router = self._make_router("ko")

        result = await router.check_rules("안녕하세요")

        assert result is not None
        assert result.route == "direct_answer"
        assert result.direct_answer is not None
        # 한국어 응답 세트 사용
        assert "안녕" in result.direct_answer or "도와" in result.direct_answer

    @pytest.mark.parametrize(
        ("language", "query"),
        [
            ("ko", "올해 감사 보고서를 작성한 부서는 어디인가요?"),
            ("ko", "첫 정기 점검은 언제 시작되나요?"),
            ("ko", "안녕하세요, 이 장비가 작동하는 온도 범위를 알려 주세요."),
            ("en", "Which department owns this document?"),
            ("en", "Hello, where is the maintenance manual?"),
        ],
    )
    async def test_information_request_reaches_search(self, language: str, query: str) -> None:
        match = await self._make_router(language).check_rules(query)
        assert match is None or match.route != "direct_answer"

    @pytest.mark.parametrize(
        ("language", "query", "rule"),
        [("ko", "  감사합니다! 😊", "thanks"), ("en", "  HI   there!!", "greeting")],
    )
    async def test_standalone_social_message(self, language: str, query: str, rule: str) -> None:
        match = await self._make_router(language).check_rules(query)
        assert match is not None and match.rule_name == rule and match.route == "direct_answer"
