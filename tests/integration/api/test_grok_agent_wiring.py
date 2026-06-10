"""
Grok answer / Agentic RAG 의존성 배선 테스트 (Phase 2.6)

목적:
    chat_service가 RAGPipeline에 grok_answer_provider/agent_orchestrator를
    전달하지 않아 grok answer 모드(GROK_003 에러)와 use_agent=true(일반 RAG로
    강등)가 동작 불가하던 결함을 회귀 방지한다.
"""

from __future__ import annotations

import inspect

from app.lib.config_loader import load_config


def test_modules_dict_exposes_grok_and_agent() -> None:
    """get_modules_dict가 grok_answer_provider/agent_orchestrator를 노출해야 한다."""
    import main

    source = inspect.getsource(main.RAGChatbotApp.get_modules_dict)
    assert '"grok_answer_provider"' in source
    assert '"agent_orchestrator"' in source


def test_chat_service_passes_grok_and_agent() -> None:
    """ChatService가 두 의존성을 RAGPipeline 생성에 전달해야 한다."""
    from app.api.services.chat_service import ChatService

    source = inspect.getsource(ChatService.__init__)
    assert "grok_answer_provider=modules.get" in source
    assert "agent_orchestrator=modules.get" in source


def test_container_resolves_grok_and_agent() -> None:
    """컨테이너가 두 provider를 None이 아닌 인스턴스로 생성해야 한다."""
    from app.core.di_container import AppContainer

    container = AppContainer()
    container.config.from_dict(load_config(validate=False))

    grok = container.grok_answer_provider()
    agent = container.agent_orchestrator()
    assert grok is not None, "grok_answer_provider가 생성되지 않음"
    assert agent is not None, "agent_orchestrator가 생성되지 않음"
