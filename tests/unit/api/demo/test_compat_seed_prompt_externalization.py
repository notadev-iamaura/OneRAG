"""데모 시드 프롬프트 config(환경변수) 외부화 테스트

compat_router.py의 _default_prompts()가 데모 프롬프트 관리 UI 시드로 채우는
한국어 content/description이 환경 변수로 외부화됐는지 검증한다.

대상 환경 변수:
- DEMO_SEED_SYSTEM_CONTENT / DEMO_SEED_SYSTEM_DESCRIPTION
- DEMO_SEED_CONCISE_CONTENT / DEMO_SEED_CONCISE_DESCRIPTION
- DEMO_SEED_DETAILED_CONTENT / DEMO_SEED_DETAILED_DESCRIPTION

핵심 요구사항:
1. (회귀 0) 환경 변수 미설정 시 기존 한국어 시드를 그대로 사용한다.
2. (오버라이드) 환경 변수 주입 시 해당 값으로 시드가 채워진다.
3. name/category 등 안정 식별자는 변하지 않는다.
"""

from __future__ import annotations

from typing import Any

from app.api.demo.compat_router import _default_prompts, _resolve_seed


def _by_name(prompts: list[dict[str, Any]], name: str) -> dict[str, Any]:
    """name으로 시드 프롬프트 하나를 찾는다."""
    return next(p for p in prompts if p["name"] == name)


# =============================================================================
# (a) 미설정 시 한국어 기본 시드 — 회귀 0
# =============================================================================


def test_default_seeds_when_env_unset(monkeypatch) -> None:
    """환경 변수 미설정 시 기존 한국어 시드 content/description을 그대로 사용(회귀 0)."""
    for key in (
        "DEMO_SEED_SYSTEM_CONTENT",
        "DEMO_SEED_SYSTEM_DESCRIPTION",
        "DEMO_SEED_CONCISE_CONTENT",
        "DEMO_SEED_CONCISE_DESCRIPTION",
        "DEMO_SEED_DETAILED_CONTENT",
        "DEMO_SEED_DETAILED_DESCRIPTION",
    ):
        monkeypatch.delenv(key, raising=False)

    prompts = _default_prompts()

    system = _by_name(prompts, "default-system")
    assert system["content"] == (
        "당신은 RAG 기반 질문 답변 시스템입니다. "
        "제공된 문서를 기반으로 정확하고 도움이 되는 답변을 작성하세요."
    )
    assert system["description"] == "기본 시스템 프롬프트"

    concise = _by_name(prompts, "concise-style")
    assert concise["content"] == "핵심만 간결하게 답변하세요. 불필요한 설명은 생략합니다."
    assert concise["description"] == "간결한 답변 스타일"

    detailed = _by_name(prompts, "detailed-style")
    assert detailed["content"] == (
        "상세하고 포괄적으로 답변하세요. "
        "관련 배경 지식과 예시를 포함하여 설명합니다."
    )
    assert detailed["description"] == "상세한 답변 스타일"


def test_identifiers_and_flags_unchanged_when_env_unset(monkeypatch) -> None:
    """name/category/is_active 등 안정 식별자는 외부화와 무관하게 유지(회귀 0)."""
    for key in (
        "DEMO_SEED_SYSTEM_CONTENT",
        "DEMO_SEED_CONCISE_CONTENT",
        "DEMO_SEED_DETAILED_CONTENT",
    ):
        monkeypatch.delenv(key, raising=False)

    prompts = _default_prompts()
    assert [p["name"] for p in prompts] == [
        "default-system",
        "concise-style",
        "detailed-style",
    ]
    assert _by_name(prompts, "default-system")["category"] == "system"
    assert _by_name(prompts, "default-system")["is_active"] is True
    assert _by_name(prompts, "concise-style")["category"] == "style"
    assert _by_name(prompts, "concise-style")["is_active"] is False
    assert _by_name(prompts, "detailed-style")["is_active"] is False


def test_blank_env_falls_back_to_default(monkeypatch) -> None:
    """공백 환경 변수는 기본값으로 폴백(회귀 0)."""
    monkeypatch.setenv("DEMO_SEED_SYSTEM_CONTENT", "   ")
    assert _resolve_seed("DEMO_SEED_SYSTEM_CONTENT", "기본값") == "기본값"


# =============================================================================
# (b) env 주입 시 오버라이드
# =============================================================================


def test_env_override_applied_to_seeds(monkeypatch) -> None:
    """환경 변수 주입 시 해당 값으로 시드 content/description이 채워진다."""
    monkeypatch.setenv(
        "DEMO_SEED_SYSTEM_CONTENT",
        "You are a RAG-based QA system. Answer using the provided documents.",
    )
    monkeypatch.setenv("DEMO_SEED_SYSTEM_DESCRIPTION", "Default system prompt")
    monkeypatch.setenv("DEMO_SEED_CONCISE_CONTENT", "Answer concisely.")
    monkeypatch.setenv("DEMO_SEED_DETAILED_CONTENT", "Answer in detail.")

    prompts = _default_prompts()

    system = _by_name(prompts, "default-system")
    assert system["content"] == (
        "You are a RAG-based QA system. Answer using the provided documents."
    )
    assert system["description"] == "Default system prompt"
    # name/category는 식별자라 유지
    assert system["name"] == "default-system"
    assert system["category"] == "system"

    assert _by_name(prompts, "concise-style")["content"] == "Answer concisely."
    assert _by_name(prompts, "detailed-style")["content"] == "Answer in detail."
    # 미설정한 description은 한국어 기본 유지 (부분 오버라이드 회귀 0)
    assert _by_name(prompts, "concise-style")["description"] == "간결한 답변 스타일"
