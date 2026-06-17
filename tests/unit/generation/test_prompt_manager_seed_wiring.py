"""
PromptManager 시드 프롬프트 외부화 배선 테스트 (17차 범용화)

PromptManager.__init__의 default_prompts 파라미터가 생성자엔 노출됐으나
di_container 배선이 없고 prompts.yaml 키도 없던 '데드 주입 경로'를,
prompts.seed_prompts config로 배선한 변경을 검증한다(null→코드 내장
한국어 기본 DEFAULT_SEED_PROMPTS, 회귀 0).
"""

from app.core.di_container import AppContainer
from app.modules.core.generation.prompt_manager import (
    DEFAULT_SEED_PROMPTS,
    PromptManager,
)


class TestSeedPromptsDefault:
    def test_none_falls_back_to_builtin_korean(self, tmp_path):
        """default_prompts=None 시 코드 내장 한국어 시드 사용(회귀 0)."""
        pm = PromptManager(
            storage_path=str(tmp_path),
            use_database=False,
            default_prompts=None,
        )
        assert pm._default_prompts is DEFAULT_SEED_PROMPTS

    def test_override_seed_prompts(self, tmp_path):
        """default_prompts 주입 시 시드를 교체한다(코드 포크 불필요)."""
        custom = [
            {
                "name": "system",
                "content": "You are a helpful assistant.",
                "description": "custom",
                "category": "system",
                "is_active": True,
            }
        ]
        pm = PromptManager(
            storage_path=str(tmp_path),
            use_database=False,
            default_prompts=custom,
        )
        assert pm._default_prompts == custom


class TestDiContainerWiring:
    def test_provider_passes_default_prompts(self):
        """di_container prompt_manager provider가 default_prompts를 배선한다(데드키 아님)."""
        kwargs = AppContainer.prompt_manager.kwargs
        assert "default_prompts" in kwargs

    def test_config_default_is_none(self):
        """prompts.seed_prompts 기본값이 null → None으로 로드(회귀 0)."""
        from app.lib.config_loader import load_config

        config = load_config()
        assert config.get("prompts", {}).get("seed_prompts") is None
