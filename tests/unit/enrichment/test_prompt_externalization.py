"""
Enrichment 프롬프트 외부화 회귀/오버라이드 테스트

코드에 하드코딩됐던 enrichment 시스템 프롬프트/few-shot/사용자 프롬프트를
config(EnrichmentConfig + enrichment.yaml)로 외부화한 것이 다음을 만족하는지 검증:

(a) 미설정 시 코드 내장 한국어 기본 프롬프트와 동일 (회귀 0)
(b) 오버라이드 시 코드 변경 없이 프롬프트가 실제로 바뀜
(c) 변수 치환({content}) 보존
+ EnrichmentService._parse_enrichment_config가 enrichment.prompt.* 를 읽는지(데드 키 아님)
"""

from app.modules.core.enrichment.prompts.enrichment_prompts import (
    FEW_SHOT_EXAMPLES,
    SYSTEM_PROMPT,
    build_batch_enrichment_prompt,
    build_enrichment_prompt,
)
from app.modules.core.enrichment.services.enrichment_service import EnrichmentService


class TestEnrichmentPromptDefault:
    """(a) 미설정 시 코드 내장 한국어 기본 프롬프트 동치"""

    def test_single_default_equals_builtin(self) -> None:
        """단건: 오버라이드 없으면 내장 SYSTEM_PROMPT + FEW_SHOT + {content} 치환"""
        system, user = build_enrichment_prompt("문서 내용입니다")
        # 시스템 프롬프트 = 내장 시스템 + few-shot 결합과 byte 동일
        assert system == SYSTEM_PROMPT + "\n\n" + FEW_SHOT_EXAMPLES
        # 한국어 카테고리 라벨이 그대로 유지됨
        assert "기술" in system and "비즈니스" in system
        # (c) {content} 치환 보존
        assert "문서 내용입니다" in user

    def test_batch_default_equals_builtin(self) -> None:
        """배치: 오버라이드 없으면 내장 시스템 프롬프트 사용"""
        system, user = build_batch_enrichment_prompt([{"content": "문서A"}])
        assert system == SYSTEM_PROMPT + "\n\n" + FEW_SHOT_EXAMPLES
        assert "문서A" in user


class TestEnrichmentPromptOverride:
    """(b)(c) 오버라이드 시 코드 변경 없이 프롬프트 교체 + 변수 보존"""

    def test_single_override(self) -> None:
        system, user = build_enrichment_prompt(
            "doc text",
            system_prompt="You are a metadata extractor.",
            few_shot_examples="Example: ...",
            user_prompt_template="Analyze: {content}",
        )
        assert system == "You are a metadata extractor.\n\nExample: ..."
        # 한국어 내장 프롬프트가 사라짐
        assert "메타데이터를 추출하는 AI 어시스턴트" not in system
        # (c) {content} 치환 보존
        assert user == "Analyze: doc text"

    def test_override_without_examples(self) -> None:
        """include_examples=False면 few-shot 미포함"""
        system, _ = build_enrichment_prompt(
            "x",
            include_examples=False,
            system_prompt="SYS-ONLY",
        )
        assert system == "SYS-ONLY"

    def test_batch_override(self) -> None:
        system, _ = build_batch_enrichment_prompt(
            [{"content": "d"}],
            system_prompt="Batch sys",
            few_shot_examples="ex",
        )
        assert system == "Batch sys\n\nex"


class TestEnrichmentServiceConfigWiring:
    """EnrichmentService가 enrichment.prompt.* 를 EnrichmentConfig로 매핑(데드 키 아님)"""

    def test_default_config_has_none_prompts(self) -> None:
        """(a) prompt 섹션 없으면 오버라이드 필드 None → 코드 내장 기본값"""
        svc = EnrichmentService(config={"enrichment": {"enabled": False}})
        assert svc.enrichment_config.system_prompt is None
        assert svc.enrichment_config.few_shot_examples is None
        assert svc.enrichment_config.user_prompt_template is None
        assert svc.enrichment_config.include_examples is True

    def test_config_reads_prompt_section(self) -> None:
        """(b) enrichment.prompt.* 가 EnrichmentConfig 필드로 전달됨"""
        svc = EnrichmentService(
            config={
                "enrichment": {
                    "enabled": False,
                    "prompt": {
                        "system_prompt": "CUSTOM-SYS",
                        "few_shot_examples": "CUSTOM-FEW",
                        "user_prompt_template": "Analyze: {content}",
                        "include_examples": False,
                    },
                }
            }
        )
        assert svc.enrichment_config.system_prompt == "CUSTOM-SYS"
        assert svc.enrichment_config.few_shot_examples == "CUSTOM-FEW"
        assert svc.enrichment_config.user_prompt_template == "Analyze: {content}"
        assert svc.enrichment_config.include_examples is False
