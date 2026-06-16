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
    BATCH_USER_PROMPT_TEMPLATE,
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

    def test_batch_user_prompt_default_equals_builtin(self) -> None:
        """배치 사용자 프롬프트: 오버라이드 없으면 내장 BATCH_USER_PROMPT_TEMPLATE를
        문서 개수/본문으로 치환한 결과와 byte 동일 (배치 비대칭 해소 회귀 0)."""
        docs = [{"content": "문서A"}, {"content": "문서B 내용"}]
        _, user = build_batch_enrichment_prompt(docs)

        # 내장 배치 템플릿을 직접 치환한 기대값과 byte 동일해야 함
        expected_content = ""
        for i, doc in enumerate(docs[:10], 1):
            expected_content += f"\n\n--- 문서 {i} ---\n{doc['content']}"
        expected = BATCH_USER_PROMPT_TEMPLATE.format(
            doc_count=2, batch_content=expected_content
        )
        assert user == expected
        # 한국어 배치 안내 문구가 그대로 유지됨
        assert "JSON 배열로 응답해주세요" in user
        assert "문서A" in user and "문서B 내용" in user


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

    def test_batch_user_prompt_override(self) -> None:
        """배치 사용자 프롬프트 오버라이드: 코드 변경 없이 영어 템플릿으로 교체되며
        {doc_count}/{batch_content} 플레이스홀더가 보존·치환된다 (비대칭 회귀 방지)."""
        docs = [{"content": "alpha"}, {"content": "beta"}]
        _, user = build_batch_enrichment_prompt(
            docs,
            user_prompt_template="Analyze {doc_count} texts:\n{batch_content}\nReturn JSON array.",
        )
        # 한국어 내장 배치 문구가 사라지고 영어 템플릿이 적용됨
        assert "JSON 배열로 응답해주세요" not in user
        assert user.startswith("Analyze 2 texts:")
        assert user.endswith("Return JSON array.")
        # {batch_content} 치환 보존 (문서 헤더 + 본문)
        assert "--- 문서 1 ---\nalpha" in user
        assert "--- 문서 2 ---\nbeta" in user

    def test_batch_user_prompt_override_independent_of_single(self) -> None:
        """단건 user_prompt_template만 바꿔도 배치 경로는 영향받지 않는다.
        (배치는 별도 batch_user_prompt_template 키만 따른다 — 비대칭 노브 무시 방지의 핵심)."""
        docs = [{"content": "gamma"}]
        # 단건 템플릿을 배치 빌더에 넘기지 않으면(=None) 배치는 내장 한국어 기본값 유지
        _, user = build_batch_enrichment_prompt(docs, user_prompt_template=None)
        assert "JSON 배열로 응답해주세요" in user


class TestEnrichmentServiceConfigWiring:
    """EnrichmentService가 enrichment.prompt.* 를 EnrichmentConfig로 매핑(데드 키 아님)"""

    def test_default_config_has_none_prompts(self) -> None:
        """(a) prompt 섹션 없으면 오버라이드 필드 None → 코드 내장 기본값"""
        svc = EnrichmentService(config={"enrichment": {"enabled": False}})
        assert svc.enrichment_config.system_prompt is None
        assert svc.enrichment_config.few_shot_examples is None
        assert svc.enrichment_config.user_prompt_template is None
        # 배치 전용 키도 기본 None → 코드 내장 한국어 배치 기본값 사용
        assert svc.enrichment_config.batch_user_prompt_template is None
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
                        "batch_user_prompt_template": (
                            "Batch {doc_count}:\n{batch_content}"
                        ),
                        "include_examples": False,
                    },
                }
            }
        )
        assert svc.enrichment_config.system_prompt == "CUSTOM-SYS"
        assert svc.enrichment_config.few_shot_examples == "CUSTOM-FEW"
        assert svc.enrichment_config.user_prompt_template == "Analyze: {content}"
        # 배치 전용 키가 EnrichmentConfig로 전달됨 (데드 키 아님)
        assert (
            svc.enrichment_config.batch_user_prompt_template
            == "Batch {doc_count}:\n{batch_content}"
        )
        assert svc.enrichment_config.include_examples is False

    def test_batch_template_flows_config_to_builder(self) -> None:
        """end-to-end: enrichment.prompt.batch_user_prompt_template →
        EnrichmentConfig → build_batch_enrichment_prompt 오버라이드 경로가 실제 적용됨.
        (운영자가 배치 노브를 바꾸면 배치 프롬프트가 실제로 바뀌는지 = 비대칭 회귀 방지)."""
        svc = EnrichmentService(
            config={
                "enrichment": {
                    "enabled": False,
                    "prompt": {
                        "batch_user_prompt_template": (
                            "EN-BATCH {doc_count}:\n{batch_content}"
                        ),
                    },
                }
            }
        )
        # llm_enricher.py:enrich_batch 가 넘기는 인자와 동일하게 호출
        _, user = build_batch_enrichment_prompt(
            [{"content": "x"}, {"content": "y"}],
            include_examples=svc.enrichment_config.include_examples,
            system_prompt=svc.enrichment_config.system_prompt,
            few_shot_examples=svc.enrichment_config.few_shot_examples,
            user_prompt_template=svc.enrichment_config.batch_user_prompt_template,
        )
        assert user.startswith("EN-BATCH 2:")
        assert "JSON 배열로 응답해주세요" not in user
        assert "--- 문서 1 ---\nx" in user and "--- 문서 2 ---\ny" in user
