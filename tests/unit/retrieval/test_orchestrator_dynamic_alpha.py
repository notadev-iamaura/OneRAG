"""질의 특성 기반 동적 하이브리드 alpha 테스트 (#35)

lexical(짧은 키워드/숫자/모델코드) 질의에서 BM25 가중을 강화하기 위해
오케스트레이터가 질의 특성을 보고 alpha를 동적으로 낮춰 retriever.search에
전달한다. 언어 중립 기본 패턴 + config extra_patterns로 일반화한다.

핵심 요구사항:
1. dynamic_alpha.enabled 기본 false → 항상 None(기존 동작 유지, 하위 호환).
2. enabled=true + 모델코드/숫자 질의 → lexical_alpha 반환.
3. enabled=true + 일반 자연어 질의 → None(기본 alpha 사용).
4. config extra_patterns로 도메인 패턴을 추가 주입할 수 있다(다국어 일반화).
5. search 경로에서 alpha가 None이 아니면 retriever.search에 alpha로 전달된다.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.modules.core.retrieval.interfaces import IRetriever
from app.modules.core.retrieval.orchestrator import RetrievalOrchestrator


def _make_retriever() -> MagicMock:
    retriever = MagicMock(spec=IRetriever)
    retriever.search = AsyncMock(return_value=[])
    retriever.health_check = AsyncMock(return_value=True)
    return retriever


def test_resolve_alpha_disabled_returns_none() -> None:
    """dynamic_alpha 비활성화(기본) 시 항상 None(기존 동작 유지)."""
    orch = RetrievalOrchestrator(retriever=_make_retriever(), config={})
    assert orch._resolve_alpha("VPS-1210B 사양") is None


def test_resolve_alpha_lexical_query_returns_lexical_alpha() -> None:
    """모델코드/숫자 lexical 질의는 lexical_alpha를 반환한다."""
    config = {
        "retrieval": {
            "dynamic_alpha": {"enabled": True, "lexical_alpha": 0.3},
        }
    }
    orch = RetrievalOrchestrator(retriever=_make_retriever(), config=config)
    # 모델코드(영문+숫자 조합)
    assert orch._resolve_alpha("VPS-1210B 사양") == 0.3
    # 2자리 이상 숫자
    assert orch._resolve_alpha("2024 매출") == 0.3


def test_resolve_alpha_natural_query_returns_none() -> None:
    """일반 자연어 질의는 None(기본 alpha 사용)."""
    config = {
        "retrieval": {
            "dynamic_alpha": {"enabled": True, "lexical_alpha": 0.3},
        }
    }
    orch = RetrievalOrchestrator(retriever=_make_retriever(), config=config)
    assert orch._resolve_alpha("환불 절차를 알려주세요") is None


def test_resolve_alpha_extra_patterns_from_config() -> None:
    """config extra_patterns로 도메인 패턴을 추가 주입할 수 있다(다국어 일반화)."""
    config = {
        "retrieval": {
            "dynamic_alpha": {
                "enabled": True,
                "lexical_alpha": 0.25,
                # 일본어 단위 등 도메인 패턴을 코드가 아닌 config로 주입
                "extra_patterns": [r"円台", r"第\d+条"],
            }
        }
    }
    orch = RetrievalOrchestrator(retriever=_make_retriever(), config=config)
    assert orch._resolve_alpha("価格は1000円台です") == 0.25
    assert orch._resolve_alpha("第3条の内容") == 0.25


@pytest.mark.asyncio
async def test_search_with_alpha_passes_to_retriever() -> None:
    """lexical 질의 시 retriever.search에 alpha가 전달된다."""
    config = {
        "retrieval": {
            "dynamic_alpha": {"enabled": True, "lexical_alpha": 0.2},
        }
    }
    retriever = _make_retriever()
    orch = RetrievalOrchestrator(retriever=retriever, config=config)

    await orch.search_and_rerank(
        query="VPS-1210B",
        top_k=5,
        rerank_enabled=False,
        query_expansion_enabled=False,
    )

    # retriever.search가 alpha=0.2와 함께 호출되어야 한다
    assert retriever.search.await_count >= 1
    call = retriever.search.await_args_list[0]
    assert call.kwargs.get("alpha") == 0.2


@pytest.mark.asyncio
async def test_search_without_dynamic_alpha_omits_alpha() -> None:
    """dynamic_alpha 비활성화 시 alpha 없이 기존 시그니처로 호출한다(하위 호환)."""
    retriever = _make_retriever()
    orch = RetrievalOrchestrator(retriever=retriever, config={})

    await orch.search_and_rerank(
        query="VPS-1210B",
        top_k=5,
        rerank_enabled=False,
        query_expansion_enabled=False,
    )

    call = retriever.search.await_args_list[0]
    # alpha 미전달 또는 None
    assert call.kwargs.get("alpha") is None
