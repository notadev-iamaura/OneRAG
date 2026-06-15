"""BGE 다국어 로컬 리랭커(#18) 단위 테스트.

torch/transformers 미설치 환경에서도 동작하도록 설계한다:
- 점수 계산 자체는 `validate_runtime=False` + `_compute_scores` mock으로 우회한다.
- 따라서 BGEReranker의 핵심 로직(점수 정렬/top_n/timeout/협조적 중단)은
  무거운 의존성 없이 검증된다.
- factory 통합(approach=local/provider=bge)도 동일하게 mock 없이 등록만 검증한다.

본 디렉토리는 conftest.py의 OPTIONAL_PROVIDER_TEST_PATHS에 포함되어 기본 게이트에서는
수집 제외되며, ONERAG_RUN_OPTIONAL_PROVIDER_TESTS=1 일 때만 실행된다.
"""

import threading
import time

import pytest

from app.modules.core.retrieval.interfaces import SearchResult


def _search_result(doc_id: str, content: str, score: float = 0.1) -> SearchResult:
    """테스트용 SearchResult 생성 헬퍼."""
    return SearchResult(
        id=doc_id,
        content=content,
        score=score,
        metadata={"source": f"{doc_id}.pdf"},
    )


def test_bge_reranker_requires_transformers_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """torch/transformers 미설치 시 명확한 ImportError로 안내한다."""
    from app.modules.core.retrieval.rerankers import bge_reranker

    monkeypatch.setattr(bge_reranker, "HAS_BGE_RUNTIME", False)

    with pytest.raises(ImportError, match="torch and transformers"):
        bge_reranker.BGEReranker()


def test_bge_reranker_initializes_config_without_loading_model() -> None:
    """validate_runtime=False면 모델 로드 없이 설정만 초기화한다."""
    from app.modules.core.retrieval.rerankers.bge_reranker import BGEReranker

    reranker = BGEReranker(
        top_n=10,
        max_documents=16,
        batch_size=8,
        device="cpu",
        validate_runtime=False,
    )

    assert reranker.model_name == "BAAI/bge-reranker-v2-m3"
    assert reranker.top_n == 10
    assert reranker.max_documents == 16
    assert reranker.batch_size == 8
    assert reranker.device == "cpu"


@pytest.mark.asyncio
async def test_bge_rerank_scores_candidates_and_applies_top_n(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """점수 계산 후 내림차순 정렬 + top_n + max_documents 절단을 검증한다."""
    from app.modules.core.retrieval.rerankers.bge_reranker import BGEReranker

    reranker = BGEReranker(
        top_n=10,
        max_documents=3,
        batch_size=2,
        device="cpu",
        validate_runtime=False,
    )
    reranker._tokenizer = object()
    reranker._model = object()
    captured_pairs: list[list[str]] = []

    def fake_compute_scores(
        pairs: list[list[str]], cancel_event: threading.Event | None = None
    ) -> list[float]:
        captured_pairs.extend(pairs)
        return [0.2, 0.9, 0.4]

    monkeypatch.setattr(reranker, "_compute_scores", fake_compute_scores)

    results = [
        _search_result("a", "first candidate"),
        _search_result("b", "best candidate"),
        _search_result("c", "second best"),
        _search_result("d", "not scored"),
    ]

    reranked = await reranker.rerank("query", results, top_n=2)

    assert [item.id for item in reranked] == ["b", "c"]
    assert [item.score for item in reranked] == [0.9, 0.4]
    # max_documents=3 이므로 4번째 문서("d")는 점수화되지 않는다.
    assert captured_pairs == [
        ["query", "first candidate"],
        ["query", "best candidate"],
        ["query", "second best"],
    ]
    assert reranker.stats["successful_requests"] == 1
    assert reranker.stats["total_documents_scored"] == 3


@pytest.mark.asyncio
async def test_bge_rerank_empty_results_returns_empty() -> None:
    """빈 입력은 빈 리스트를 반환한다(초기화 우회)."""
    from app.modules.core.retrieval.rerankers.bge_reranker import BGEReranker

    reranker = BGEReranker(device="cpu", validate_runtime=False)
    assert await reranker.rerank("query", []) == []


@pytest.mark.asyncio
async def test_bge_rerank_propagates_scoring_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """점수 계산 실패는 숨기지 않고 전파하며 실패 통계를 기록한다."""
    from app.modules.core.retrieval.rerankers.bge_reranker import BGEReranker

    reranker = BGEReranker(device="cpu", validate_runtime=False)
    reranker._tokenizer = object()
    reranker._model = object()

    def fail_compute_scores(
        pairs: list[list[str]], cancel_event: threading.Event | None = None
    ) -> list[float]:
        raise RuntimeError("model failure")

    monkeypatch.setattr(reranker, "_compute_scores", fail_compute_scores)

    with pytest.raises(RuntimeError, match="model failure"):
        await reranker.rerank("query", [_search_result("a", "candidate")])

    assert reranker.stats["failed_requests"] == 1


@pytest.mark.asyncio
async def test_bge_rerank_times_out_on_slow_scoring(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """느린 점수 계산은 timeout으로 끊겨 무한 대기를 방지한다(P1-B).

    BGE reranker는 CPU 바운드 점수 계산을 별도 스레드에서 실행하고
    timeout을 적용한다. timeout보다 오래 걸리면 TimeoutError로 끊긴다.
    """
    from app.modules.core.retrieval.rerankers.bge_reranker import BGEReranker

    # timeout을 0.1초로 매우 짧게 설정
    reranker = BGEReranker(
        device="cpu",
        validate_runtime=False,
        timeout=0.1,
    )
    reranker._tokenizer = object()
    reranker._model = object()

    def slow_compute_scores(
        pairs: list[list[str]], cancel_event: threading.Event | None = None
    ) -> list[float]:
        time.sleep(2.0)  # timeout(0.1초)보다 오래
        return [0.5 for _ in pairs]

    monkeypatch.setattr(reranker, "_compute_scores", slow_compute_scores)

    start = time.monotonic()
    with pytest.raises(TimeoutError):
        await reranker.rerank("query", [_search_result("a", "candidate")])
    elapsed = time.monotonic() - start

    # 무한 대기가 아니라 timeout 직후 끊겨야 한다(2초 sleep 전에).
    assert elapsed < 1.5
    assert reranker.stats["failed_requests"] == 1


@pytest.mark.asyncio
async def test_bge_rerank_no_timeout_when_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """timeout 미설정(None)이면 정상 점수 계산은 그대로 통과한다(회귀 가드)."""
    from app.modules.core.retrieval.rerankers.bge_reranker import BGEReranker

    reranker = BGEReranker(
        device="cpu",
        validate_runtime=False,
        timeout=None,
    )
    reranker._tokenizer = object()
    reranker._model = object()

    monkeypatch.setattr(
        reranker,
        "_compute_scores",
        lambda pairs, cancel_event=None: [0.7 for _ in pairs],
    )

    reranked = await reranker.rerank("query", [_search_result("a", "candidate")])

    assert len(reranked) == 1
    assert reranked[0].score == 0.7


@pytest.mark.asyncio
async def test_bge_compute_scores_cooperative_cancellation() -> None:
    """I1: cancel_event가 set되면 실제 _compute_scores가 배치 경계에서 조기 종료한다.

    timeout으로 wait_for를 끊어도 백그라운드 스레드가 전체 배치 추론을 끝까지
    수행하면 동시 다발 timeout 시 워커 고갈 위험이 있다. 협조적 중단으로
    배치 경계마다 cancel_event를 검사해 좀비 스레드를 빠르게 회수한다.

    실제 _compute_scores의 배치 경계 검사를 검증한다(fake로 대체하지 않음).
    cancel_event를 미리 set하면 첫 배치 경계에서 토크나이저/모델을 건드리기
    전에 즉시 RuntimeError로 빠져나와야 한다.
    """
    from app.modules.core.retrieval.rerankers.bge_reranker import BGEReranker

    reranker = BGEReranker(device="cpu", validate_runtime=False, batch_size=1)
    # 초기화 가드(_tokenizer/_model None 체크)를 통과시키되, 배치 본문이
    # 실제로 실행되면 호출 시 실패하는 더미를 둔다(=배치 본문 미진입을 강제 검증).
    reranker._tokenizer = object()
    reranker._model = object()

    cancel_event = threading.Event()
    cancel_event.set()  # 호출 전부터 취소 상태

    # 첫 배치 경계에서 cancel을 감지해 RuntimeError로 즉시 종료해야 한다.
    with pytest.raises(RuntimeError, match="cancelled"):
        reranker._compute_scores([["q", "d1"], ["q", "d2"]], cancel_event)


@pytest.mark.asyncio
async def test_bge_rerank_sets_cancel_event_on_timeout() -> None:
    """I1: timeout 발동 시 rerank가 cancel_event를 set해 스레드를 조기 회수한다.

    실제 _compute_scores가 cancel_event를 주기적으로 검사하므로, rerank의
    timeout 핸들러가 cancel_event.set()을 호출하면 백그라운드 스레드가 배치
    경계에서 빠르게 빠져나온다(좀비 스레드 방지).
    """
    from app.modules.core.retrieval.rerankers.bge_reranker import BGEReranker

    reranker = BGEReranker(device="cpu", validate_runtime=False, timeout=0.1)
    reranker._tokenizer = object()
    reranker._model = object()

    thread_exited = threading.Event()

    def slow_cancellable_scores(
        pairs: list[list[str]], cancel_event: threading.Event | None = None
    ) -> list[float]:
        # cancel_event가 set될 때까지 짧은 폴링으로 대기(배치 경계 검사 모방).
        try:
            for _ in range(200):  # 최대 ~2초
                if cancel_event is not None and cancel_event.is_set():
                    raise RuntimeError("cancelled at batch boundary")
                time.sleep(0.01)
            return [0.5 for _ in pairs]
        finally:
            thread_exited.set()

    reranker._compute_scores = slow_cancellable_scores  # type: ignore[method-assign]

    with pytest.raises(TimeoutError):
        await reranker.rerank("query", [_search_result("a", "candidate")])

    # 핵심: timeout 후 cancel_event가 set되어 스레드가 빠르게 종료되어야 한다.
    assert thread_exited.wait(timeout=1.0), (
        "timeout 후 백그라운드 스레드가 조기 종료되지 않음 "
        "→ cancel_event.set() 미호출(좀비 스레드)"
    )


def test_bge_reranker_supports_caching_and_stats() -> None:
    """결정론적 모델이므로 캐싱 지원, get_stats는 success_rate를 포함한다."""
    from app.modules.core.retrieval.rerankers.bge_reranker import BGEReranker

    reranker = BGEReranker(device="cpu", validate_runtime=False)
    assert reranker.supports_caching() is True

    stats = reranker.get_stats()
    assert stats["model_name"] == "BAAI/bge-reranker-v2-m3"
    assert stats["success_rate"] == 0.0
    assert stats["device"] == "cpu"


# ========================================
# Factory 통합 검증 (approach=local / provider=bge)
# ========================================


def test_factory_registers_bge_provider_under_local_approach() -> None:
    """레지스트리에 bge가 local approach provider로 등록되어 있다."""
    from app.modules.core.retrieval.rerankers.factory import (
        APPROACH_REGISTRY,
        PROVIDER_REGISTRY,
        RerankerFactoryV2,
    )

    assert "bge" in APPROACH_REGISTRY["local"]["providers"]
    assert "bge" in PROVIDER_REGISTRY
    assert PROVIDER_REGISTRY["bge"]["api_key_env"] is None
    assert (
        PROVIDER_REGISTRY["bge"]["default_config"]["model"]
        == "BAAI/bge-reranker-v2-m3"
    )
    assert "bge" in RerankerFactoryV2.get_providers_for_approach("local")


def test_factory_creates_bge_reranker(monkeypatch: pytest.MonkeyPatch) -> None:
    """approach=local/provider=bge 설정으로 BGEReranker가 생성된다.

    torch/transformers 미설치 환경 대비: 생성 시 runtime 검증을 우회하도록
    BGEReranker.__init__의 validate_runtime 기본 동작을 mock으로 통제하지 않고,
    factory가 timeout 등 설정을 올바르게 전달하는지 검증한다.
    """
    import app.modules.core.retrieval.rerankers.bge_reranker as bge_mod
    from app.modules.core.retrieval.rerankers.factory import RerankerFactoryV2

    # 미설치 환경에서도 생성 경로를 검증할 수 있도록 runtime 플래그를 강제 활성화.
    # (실제 모델 로드는 initialize() 호출 전까지 발생하지 않으므로 안전하다.)
    monkeypatch.setattr(bge_mod, "HAS_BGE_RUNTIME", True)

    config = {
        "reranking": {
            "approach": "local",
            "provider": "bge",
            "bge": {
                "model": "BAAI/bge-reranker-v2-m3",
                "batch_size": 4,
                "timeout": 12.5,
            },
        }
    }

    reranker = RerankerFactoryV2.create(config)

    assert reranker.__class__.__name__ == "BGEReranker"
    assert reranker.batch_size == 4  # type: ignore[attr-defined]
    assert reranker.timeout == 12.5  # type: ignore[attr-defined]


def test_factory_bge_uses_default_config_when_unspecified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """bge 세부 설정 미지정 시 기본값으로 생성된다(timeout None=무제한)."""
    import app.modules.core.retrieval.rerankers.bge_reranker as bge_mod
    from app.modules.core.retrieval.rerankers.factory import RerankerFactoryV2

    monkeypatch.setattr(bge_mod, "HAS_BGE_RUNTIME", True)

    config = {
        "reranking": {
            "approach": "local",
            "provider": "bge",
        }
    }

    reranker = RerankerFactoryV2.create(config)

    assert reranker.__class__.__name__ == "BGEReranker"
    # 기본 timeout 키가 default_config에 없으므로 None(무제한)으로 폴백.
    assert reranker.timeout is None  # type: ignore[attr-defined]
    assert reranker.batch_size == 8  # type: ignore[attr-defined]


def test_factory_invalid_local_provider_raises() -> None:
    """local approach에 미지원 provider 지정 시 ValueError."""
    from app.modules.core.retrieval.rerankers.factory import RerankerFactoryV2

    config = {
        "reranking": {
            "approach": "local",
            "provider": "nonexistent",
        }
    }

    with pytest.raises(ValueError, match="사용할 수 없습니다"):
        RerankerFactoryV2.create(config)
