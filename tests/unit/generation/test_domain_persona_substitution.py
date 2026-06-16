"""
생성 프롬프트 도메인 페르소나 치환 테스트 (9차 범용화)

generator가 시스템/스타일 프롬프트의 {domain_name}/{system_role} 등
도메인 placeholder를 채우는 배선이 없어 리터럴 토큰이 LLM에 누출되던
결함을 수정한 변경을 검증한다. domain.generation config로 오버라이드
가능하고, 미설정 시 중립 기본값으로 치환되어 누출이 0이다.
"""

from unittest.mock import MagicMock

from app.modules.core.generation.generator import GenerationModule


def _module(config: dict) -> GenerationModule:
    return GenerationModule(config=config, prompt_manager=MagicMock())


class TestResolveDomainPersona:
    def test_defaults_when_unset(self):
        """domain.generation 미설정 시 중립 기본값 사용."""
        persona = GenerationModule._resolve_domain_persona({})
        assert persona["domain_name"] == ""
        assert persona["system_role"]  # 비어있지 않은 중립 기본
        assert persona["domain_description"]

    def test_empty_yaml_value_keeps_code_default(self):
        """빈 yaml 값은 코드 중립 기본값을 유지(빈 불릿 방지)."""
        cfg = {"domain": {"generation": {"system_role": "", "domain_name": ""}}}
        persona = GenerationModule._resolve_domain_persona(cfg)
        assert persona["system_role"] == GenerationModule._DOMAIN_PERSONA_DEFAULTS["system_role"]
        assert persona["domain_name"] == ""

    def test_override_from_config(self):
        cfg = {
            "domain": {
                "generation": {
                    "domain_name": "보험",
                    "system_role": "보험 상품 상담 전문가",
                }
            }
        }
        persona = GenerationModule._resolve_domain_persona(cfg)
        assert persona["domain_name"] == "보험"
        assert persona["system_role"] == "보험 상품 상담 전문가"


class TestApplyDomainPersona:
    def test_no_literal_placeholder_leaks(self):
        """치환 후 {domain_name}/{system_role}/{domain_description} 리터럴이 남지 않는다."""
        m = _module({})
        text = "당신은 {domain_name} 전문가입니다.\n- {system_role}\n- {domain_description}"
        out = m._apply_domain_persona(text)
        assert "{domain_name}" not in out
        assert "{system_role}" not in out
        assert "{domain_description}" not in out

    def test_output_language_token_preserved(self):
        """{output_language}는 도메인 치환 단계에서 건드리지 않는다."""
        m = _module({})
        out = m._apply_domain_persona("답변은 {output_language}로. 역할: {system_role}")
        assert "{output_language}" in out  # 별도 단계에서 치환됨
        assert "{system_role}" not in out

    def test_config_override_applied_in_substitution(self):
        m = _module({"domain": {"generation": {"domain_name": "보험"}}})
        out = m._apply_domain_persona("당신은 {domain_name} 전문가입니다.")
        assert out == "당신은 보험 전문가입니다."

    def test_default_system_role_substituted_naturally(self):
        """미설정 시 {system_role}이 중립 한국어 기본 문구로 치환된다(누출 없음)."""
        m = _module({})
        out = m._apply_domain_persona("- {system_role}")
        assert out.startswith("- ")
        assert "{system_role}" not in out
        assert out.strip() != "-"  # 빈 불릿이 아님
