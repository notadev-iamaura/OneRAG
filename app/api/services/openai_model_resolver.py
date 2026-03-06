"""
OpenAI 호환 API 모델 리졸버

슬래시 구분 모델 문자열(예: "openrouter/google/gemini-2.0-flash")을
내부 LLMClientFactory의 provider/model 설정으로 변환합니다.

사용 예:
    parse_model("ollama/qwen2.5:3b")  → ("ollama", "qwen2.5:3b")
    parse_model("gemini")              → ("gemini", None)  # 기본 모델
"""

from __future__ import annotations

from app.lib.logger import get_logger

logger = get_logger(__name__)

# LLMClientFactory._PROVIDER_REGISTRY 키와 일치하는 유효 provider 목록
VALID_PROVIDERS = {"google", "gemini", "openai", "anthropic", "claude", "openrouter", "ollama"}

# provider 별칭 정규화 (사용자 편의)
PROVIDER_ALIASES: dict[str, str] = {
    "gemini": "google",
    "claude": "anthropic",
}

# provider별 기본 모델 (sub_model 미지정 시 사용)
DEFAULT_MODELS: dict[str, str] = {
    "google": "gemini-2.0-flash",
    "openai": "gpt-4o",
    "anthropic": "claude-sonnet-4-5",
    "openrouter": "google/gemini-2.0-flash",
    "ollama": "llama3.2",
}

# /v1/models 엔드포인트에 노출할 모델 목록
AVAILABLE_MODELS = [
    {"id": "gemini", "description": "Google Gemini (기본 모델)"},
    {"id": "gemini/gemini-2.5-pro", "description": "Google Gemini 2.5 Pro"},
    {"id": "ollama", "description": "Ollama 로컬 LLM (기본 모델)"},
    {"id": "ollama/qwen2.5:3b", "description": "Ollama Qwen 2.5 3B"},
    {"id": "ollama/llama3.2", "description": "Ollama LLaMA 3.2"},
    {"id": "openrouter", "description": "OpenRouter (기본 모델)"},
    {"id": "openrouter/google/gemini-2.0-flash", "description": "OpenRouter → Gemini 2.0 Flash"},
    {"id": "openrouter/anthropic/claude-sonnet-4-5", "description": "OpenRouter → Claude Sonnet"},
    {"id": "claude", "description": "Anthropic Claude (기본 모델)"},
    {"id": "openai", "description": "OpenAI GPT (기본 모델)"},
]


def parse_model(model: str) -> tuple[str, str | None]:
    """
    모델 문자열을 provider와 sub_model로 분리

    Args:
        model: 슬래시 구분 모델 문자열

    Returns:
        (provider, sub_model) 튜플. sub_model이 없으면 None.

    Raises:
        ValueError: 미지원 provider인 경우

    Examples:
        parse_model("gemini")                          → ("gemini", None)
        parse_model("ollama/qwen2.5:3b")               → ("ollama", "qwen2.5:3b")
        parse_model("openrouter/google/gemini-2.0-flash") → ("openrouter", "google/gemini-2.0-flash")
    """
    if "/" in model:
        provider, sub_model = model.split("/", 1)
    else:
        provider = model
        sub_model = None

    provider_lower = provider.lower()

    if provider_lower not in VALID_PROVIDERS:
        raise ValueError(
            f"지원하지 않는 provider: '{provider}'. "
            f"사용 가능: {', '.join(sorted(VALID_PROVIDERS))}"
        )

    return provider_lower, sub_model


def resolve_model_config(provider: str, sub_model: str | None) -> dict[str, str]:
    """
    provider와 sub_model을 LLMClientFactory용 설정으로 변환

    Args:
        provider: provider 이름 (parse_model의 첫 번째 반환값)
        sub_model: 세부 모델 (parse_model의 두 번째 반환값)

    Returns:
        {"provider": "...", "model": "..."} 딕셔너리
    """
    # 별칭 정규화 (gemini → google, claude → anthropic)
    canonical_provider = PROVIDER_ALIASES.get(provider, provider)

    # 모델 결정: 지정된 모델 > 기본 모델
    model = sub_model or DEFAULT_MODELS.get(canonical_provider, "")

    return {
        "provider": canonical_provider,
        "model": model,
    }


def list_available_models() -> list[dict[str, str]]:
    """
    사용 가능한 모델 목록 반환 (/v1/models 엔드포인트용)

    Returns:
        모델 정보 딕셔너리 리스트
    """
    return AVAILABLE_MODELS.copy()
