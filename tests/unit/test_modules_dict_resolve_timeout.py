"""
get_modules_dict awaitable 해소 타임아웃 테스트

목적:
    main.get_modules_dict가 async provider의 Future/awaitable을 일괄 await할 때
    타임아웃 없이 무기한 행(hang)에 빠지는 결함을 회귀 방지한다.
    - 행 걸리는 provider가 있으면 _MODULE_RESOLVE_TIMEOUT_S 안에
      "어느 키의 provider가 행인지" 명시한 RuntimeError로 전환되어야 한다
      (fail-fast 유지 + 진단 가능성 확보).
    - 정상 awaitable은 기존처럼 인스턴스로 해소되어야 한다.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import MagicMock

import pytest

import main


def _build_rag_app_with_fake_container() -> tuple[Any, MagicMock]:
    """가짜 컨테이너를 주입한 RAGChatbotApp 인스턴스 생성

    __init__이 실제 AppContainer를 생성하지 않도록 __new__로 우회하고,
    모든 provider 호출이 동기 인스턴스(MagicMock)를 반환하는 컨테이너를 주입한다.

    Returns:
        (RAGChatbotApp 인스턴스, 가짜 컨테이너) 튜플
    """
    rag_app = main.RAGChatbotApp.__new__(main.RAGChatbotApp)
    fake_container = MagicMock()
    rag_app.container = fake_container
    return rag_app, fake_container


@pytest.mark.unit
class TestModulesDictResolveTimeout:
    """get_modules_dict의 awaitable 해소 타임아웃 동작 검증"""

    async def test_hanging_provider_raises_runtime_error_with_key_name(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """
        행 걸리는 provider가 키 이름이 포함된 RuntimeError로 전환되는지 검증

        Given: agent_orchestrator provider가 영원히 완료되지 않는 Future 반환
        When: 타임아웃 상수를 0.05초로 단축 후 get_modules_dict 호출
        Then: 'agent_orchestrator' 키 이름이 포함된 RuntimeError 발생 (무한 행 금지)
        """
        # 타임아웃 상수를 테스트용으로 단축 (실제 60초 대기 방지)
        monkeypatch.setattr(main, "_MODULE_RESOLVE_TIMEOUT_S", 0.05)

        rag_app, fake_container = _build_rag_app_with_fake_container()
        # 영원히 resolve되지 않는 Future — async provider 행(hang) 시뮬레이션
        hanging_future: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
        fake_container.agent_orchestrator = MagicMock(return_value=hanging_future)

        with pytest.raises(RuntimeError, match="agent_orchestrator") as exc_info:
            await rag_app.get_modules_dict()

        # 원인 체인 보존 검증 (TimeoutError에서 변환됐음을 진단 가능해야 함)
        assert isinstance(exc_info.value.__cause__, TimeoutError)

    async def test_normal_awaitable_resolved_within_timeout(self) -> None:
        """
        정상 awaitable이 타임아웃 내에 인스턴스로 해소되는지 검증 (기존 동작 보존)

        Given: generation provider가 이미 완료된 Future(인스턴스 포함) 반환
        When: get_modules_dict 호출
        Then: Future가 unwrap되어 실제 인스턴스가 dict에 담김
        """
        rag_app, fake_container = _build_rag_app_with_fake_container()
        sentinel = object()
        finished_future: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
        finished_future.set_result(sentinel)
        fake_container.generation = MagicMock(return_value=finished_future)

        modules = await rag_app.get_modules_dict()

        # Future가 아닌 실제 인스턴스로 해소되어야 함 (AttributeError P0 결함 방지)
        assert modules["generation"] is sentinel
        # 다른 모듈들은 awaitable이 아니므로 그대로 유지
        assert "llm_factory" in modules
