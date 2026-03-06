"""
OpenAI 모델 리졸버 테스트

슬래시 구분 모델 문자열을 provider/sub-model로 파싱하고,
사용 가능한 모델 목록을 반환합니다.
"""

import pytest


class TestParseModel:
    """모델 문자열 파싱 테스트"""

    def test_provider_only(self):
        """provider만 지정 시 기본 모델 사용"""
        from app.api.services.openai_model_resolver import parse_model

        provider, sub_model = parse_model("gemini")
        assert provider == "gemini"
        assert sub_model is None

    def test_provider_with_model(self):
        """provider/model 형식 파싱"""
        from app.api.services.openai_model_resolver import parse_model

        provider, sub_model = parse_model("ollama/qwen2.5:3b")
        assert provider == "ollama"
        assert sub_model == "qwen2.5:3b"

    def test_openrouter_nested_model(self):
        """openrouter/vendor/model 형식 (슬래시 2개)"""
        from app.api.services.openai_model_resolver import parse_model

        provider, sub_model = parse_model("openrouter/google/gemini-2.0-flash")
        assert provider == "openrouter"
        assert sub_model == "google/gemini-2.0-flash"

    def test_openrouter_anthropic(self):
        """openrouter/anthropic/claude-sonnet-4-5"""
        from app.api.services.openai_model_resolver import parse_model

        provider, sub_model = parse_model("openrouter/anthropic/claude-sonnet-4-5")
        assert provider == "openrouter"
        assert sub_model == "anthropic/claude-sonnet-4-5"

    def test_google_alias(self):
        """google은 gemini의 별칭"""
        from app.api.services.openai_model_resolver import parse_model

        provider, sub_model = parse_model("google/gemini-2.5-pro")
        assert provider == "google"
        assert sub_model == "gemini-2.5-pro"

    def test_unknown_provider(self):
        """미지원 provider 시 ValueError"""
        from app.api.services.openai_model_resolver import parse_model

        with pytest.raises(ValueError, match="지원하지 않는 provider"):
            parse_model("unknown_provider")


class TestResolveModelConfig:
    """모델 설정 해석 테스트"""

    def test_resolve_gemini_default(self):
        """gemini 기본 설정 해석"""
        from app.api.services.openai_model_resolver import resolve_model_config

        config = resolve_model_config("gemini", None)
        assert config["provider"] == "google"
        assert config["model"] is not None  # 기본 모델 존재

    def test_resolve_ollama_with_model(self):
        """ollama 특정 모델 지정"""
        from app.api.services.openai_model_resolver import resolve_model_config

        config = resolve_model_config("ollama", "qwen2.5:3b")
        assert config["provider"] == "ollama"
        assert config["model"] == "qwen2.5:3b"

    def test_resolve_openrouter_with_vendor_model(self):
        """openrouter 벤더/모델 조합"""
        from app.api.services.openai_model_resolver import resolve_model_config

        config = resolve_model_config("openrouter", "google/gemini-2.0-flash")
        assert config["provider"] == "openrouter"
        assert config["model"] == "google/gemini-2.0-flash"


class TestListAvailableModels:
    """사용 가능 모델 목록 테스트"""

    def test_returns_model_list(self):
        """모델 목록 반환"""
        from app.api.services.openai_model_resolver import list_available_models

        models = list_available_models()
        assert len(models) >= 4  # gemini, ollama, openrouter, claude 최소
        ids = [m["id"] for m in models]
        assert "gemini" in ids
        assert "ollama" in ids
