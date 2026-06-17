"""데모 RAG 프롬프트 config(환경변수) 외부화 테스트

demo_pipeline.py의 RAG 시스템/유저 프롬프트가 환경 변수
(DEMO_RAG_SYSTEM_PROMPT / DEMO_RAG_USER_TEMPLATE)로 외부화됐는지 검증한다.

핵심 요구사항:
1. (회귀 0) 환경 변수 미설정 시 기본 한국어 프롬프트를 그대로 사용한다.
2. (오버라이드) 환경 변수로 프롬프트를 바꾸면 모듈 재로딩 시 반영된다.
"""

from __future__ import annotations

import importlib

import app.api.demo.demo_pipeline as demo_pipeline
from app.api.demo.demo_pipeline import (
    DEFAULT_RAG_SYSTEM_PROMPT,
    DEFAULT_RAG_USER_TEMPLATE,
    _resolve_prompt,
)


def test_default_prompt_when_env_unset(monkeypatch) -> None:
    """환경 변수 미설정 시 기본값 반환(회귀 0)"""
    monkeypatch.delenv("DEMO_RAG_SYSTEM_PROMPT", raising=False)
    assert _resolve_prompt("DEMO_RAG_SYSTEM_PROMPT", DEFAULT_RAG_SYSTEM_PROMPT) == (
        DEFAULT_RAG_SYSTEM_PROMPT
    )


def test_blank_env_falls_back_to_default(monkeypatch) -> None:
    """공백 환경 변수는 기본값으로 폴백(마스킹 아닌 프롬프트지만 회귀 0)"""
    monkeypatch.setenv("DEMO_RAG_SYSTEM_PROMPT", "   ")
    assert _resolve_prompt("DEMO_RAG_SYSTEM_PROMPT", DEFAULT_RAG_SYSTEM_PROMPT) == (
        DEFAULT_RAG_SYSTEM_PROMPT
    )


def test_env_override_resolved(monkeypatch) -> None:
    """환경 변수가 설정되면 그 값을 사용한다."""
    monkeypatch.setenv("DEMO_RAG_USER_TEMPLATE", "CTX={context} Q={question}")
    assert _resolve_prompt("DEMO_RAG_USER_TEMPLATE", DEFAULT_RAG_USER_TEMPLATE) == (
        "CTX={context} Q={question}"
    )


def test_module_level_defaults_byte_identical(monkeypatch) -> None:
    """env 미설정 상태로 모듈 재로딩 시 모듈 상수가 기본값과 동일(회귀 0)"""
    monkeypatch.delenv("DEMO_RAG_SYSTEM_PROMPT", raising=False)
    monkeypatch.delenv("DEMO_RAG_USER_TEMPLATE", raising=False)
    reloaded = importlib.reload(demo_pipeline)
    try:
        assert reloaded.RAG_SYSTEM_PROMPT == reloaded.DEFAULT_RAG_SYSTEM_PROMPT
        assert reloaded.RAG_USER_TEMPLATE == reloaded.DEFAULT_RAG_USER_TEMPLATE
    finally:
        # 다른 테스트에 영향 없도록 원복
        importlib.reload(demo_pipeline)
