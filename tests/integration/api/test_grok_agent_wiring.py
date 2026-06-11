"""
Grok answer / Agentic RAG 의존성 배선 회귀 테스트 (Phase 2.6 / P0)

목적:
    1) get_modules_dict가 dependency-injector async Singleton이 반환하는
       asyncio.Future를 전부 실제 인스턴스로 해소하는지 검증한다.
       unwrap 누락 시 truthy Future가 그대로 dict에 담겨
       - use_agent=true → agent_orchestrator.run AttributeError로 전 요청 실패
       - /v1 → retrieval.search AttributeError → except가 삼켜 무문서 답변
       이 발생하던 P0 결함을 회귀 방지한다 (결함 A 핵심 회귀 테스트).
    2) grok_answer_provider/agent_orchestrator 키가 modules dict에 노출되어
       RAGPipeline까지 전달 가능한지 검증한다.
"""

from __future__ import annotations

import asyncio
import inspect

import pytest

from app.lib.config_loader import load_config

# integration 마커: 기본 CI test 잡은 tests/integration을 ignore하므로
# 별도 P0 회귀 스텝(ci.yml) 또는 `-m integration`으로 실행된다.
pytestmark = pytest.mark.integration


async def test_modules_dict_resolves_async_singleton_futures() -> None:
    """modules dict의 모든 값이 Future/awaitable이 아닌 실제 인스턴스여야 한다.

    dependency-injector 4.x에서 비동기 팩토리(create_mcp_server_instance 등)에
    의존하는 Singleton은 동기 호출 시 항상 asyncio.Future를 반환한다
    (초기화 완료 후에도 finished Future). get_modules_dict가 이를 await로
    해소하지 않으면 사용 지점에서 AttributeError가 발생한다.
    """
    import main

    app = main.RAGChatbotApp()
    # 컨테이너에 설정 주입 (lifespan의 initialize_modules와 동일한 전제)
    app.container.config.from_dict(load_config(validate=False))

    modules = await app.get_modules_dict()

    # (a) 모든 값이 Future/awaitable 없이 해소되어야 한다 — 결함 A 핵심 단언
    for name, value in modules.items():
        assert not asyncio.isfuture(value), (
            f"modules['{name}']가 asyncio.Future로 남아 있음 (Future 미해소 회귀)"
        )
        assert not inspect.isawaitable(value), (
            f"modules['{name}']가 awaitable로 남아 있음 (Future 미해소 회귀)"
        )

    # (b) grok answer 모드 / Agentic RAG 의존성 키가 노출되어야 한다
    #     (누락 시 RAGPipeline에 전달되지 않아 GROK_003 / agent 모드 강등)
    assert "grok_answer_provider" in modules, "modules dict에 grok_answer_provider 키 누락"
    assert "agent_orchestrator" in modules, "modules dict에 agent_orchestrator 키 누락"

    # (c) agent_orchestrator는 None(mcp 비활성 시 자연 폴백: rag_pipeline의
    #     `if use_agent and self.agent_orchestrator:`가 falsy로 일반 RAG 진행)
    #     이거나, run 메서드를 가진 실제 오케스트레이터여야 한다.
    agent = modules["agent_orchestrator"]
    assert agent is None or hasattr(agent, "run"), (
        "agent_orchestrator가 run 메서드 없는 객체로 노출됨 "
        f"(type={type(agent).__name__}) — Future 미해소 또는 잘못된 배선"
    )
