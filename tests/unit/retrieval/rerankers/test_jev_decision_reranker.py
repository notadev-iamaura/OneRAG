"""Jev decision filter contracts, with no external requests."""

import asyncio
import time
from copy import deepcopy
from unittest.mock import AsyncMock

import httpx
import pytest

from app.modules.core.retrieval.interfaces import SearchResult
from app.modules.core.retrieval.rerankers.jev_client import (
    JevAnswer,
    JevAPIError,
    TypeSafeJevClient,
)
from app.modules.core.retrieval.rerankers.jev_decision_reranker import (
    JevDecisionReranker,
)


def results(count: int) -> list[SearchResult]:
    return [SearchResult(str(i), f"passage {i}", 0.9 - i * 0.1, {"source": str(i)}) for i in range(count)]


def assert_fallback(output, incoming):
    assert [doc.id for doc in output] == [doc.id for doc in incoming]
    for copied, original in zip(output, incoming, strict=True):
        assert copied is not original
        assert copied.metadata is not original.metadata
        assert copied.score == original.score
        assert copied.metadata["jev_outcome"] == "fallback"
        assert "rerank_method" not in copied.metadata
        assert "jev_outcome" not in original.metadata


def results_with_metadata_score() -> list[SearchResult]:
    incoming = [
        SearchResult(str(i), f"passage {i}", 0.0, {"score": 0.1, "source": str(i)})
        for i in range(2)
    ]
    for item in incoming:
        item.score = 0.95
    return incoming


class FakeClient:
    def __init__(self, probabilities: list[float | None], error_kind: str = "timeout") -> None:
        self.probabilities = probabilities
        self.error_kind = error_kind
        self.calls: list[str] = []

    async def ask(self, state: dict, questions: dict) -> dict[str, JevAnswer]:
        passage = state["passage"]
        self.calls.append(passage)
        probability = self.probabilities[int(passage.split()[-1])]
        if probability is None:
            raise JevAPIError(self.error_kind)
        return {"relevant": JevAnswer(probability)}


@pytest.mark.asyncio
async def test_shadow_identity_no_mutation_and_side_channel() -> None:
    incoming = results(3)
    original = deepcopy(incoming)
    received = []
    reranker = JevDecisionReranker(
        "key", client=FakeClient([0.9, 0.1, 0.7]),
        shadow_background=False, decision_sink=received.append,
    )
    output = await reranker.rerank("secret query", incoming)
    assert output is incoming
    assert all(a is b for a, b in zip(output, incoming, strict=True))
    assert incoming == original
    assert all("jev" not in item.metadata for item in incoming)
    batch = reranker.get_recent_decisions()[0]
    assert batch is received[0]
    assert [d.keep for d in batch.decisions] == [True, False, True]
    assert batch.applied is False
    assert reranker.supports_caching() is False


@pytest.mark.asyncio
async def test_shadow_respects_top_n() -> None:
    incoming = results(3)
    client = FakeClient([0.9, 0.1, 0.7])
    reranker = JevDecisionReranker(
        "key", client=client, shadow_background=False
    )
    output = await reranker.rerank("q", incoming, top_n=2)
    assert len(output) == 2
    assert all(output[i] is incoming[i] for i in range(2))
    assert len(reranker.get_recent_decisions()[-1].decisions) == 2
    assert client.calls == ["passage 0", "passage 1"]
    assert await reranker.rerank("q", incoming, top_n=None) is incoming


@pytest.mark.asyncio
async def test_shadow_background_returns_before_judgment() -> None:
    event = asyncio.Event()

    class WaitingClient:
        async def ask(self, state: dict, questions: dict) -> dict[str, JevAnswer]:
            await event.wait()
            return {"relevant": JevAnswer(0.8)}

    incoming = results(1)
    reranker = JevDecisionReranker("key", client=WaitingClient())
    assert await reranker.rerank("q", incoming) is incoming
    assert reranker.get_recent_decisions() == []
    event.set()
    await reranker.drain()
    assert len(reranker.get_recent_decisions()) == 1


@pytest.mark.asyncio
async def test_close_is_idempotent_and_drains_bounded() -> None:
    class WaitingClient:
        def __init__(self) -> None:
            self.aclose = AsyncMock()

        async def ask(self, state: dict, questions: dict) -> dict[str, JevAnswer]:
            await asyncio.sleep(10)
            return {"relevant": JevAnswer(0.8)}

    injected = WaitingClient()
    reranker = JevDecisionReranker(
        "key", client=injected, deadline_seconds=0.05
    )
    await reranker.rerank("q", results(1))
    await asyncio.sleep(0)
    started = time.monotonic()
    await reranker.close()
    assert time.monotonic() - started < 0.5
    assert not reranker._pending or all(task.cancelled() for task in reranker._pending)
    await reranker.close()
    injected.aclose.assert_not_awaited()

    owned = JevDecisionReranker("key", deadline_seconds=0.05)
    assert owned._client is not None
    client = owned._client
    client.aclose = AsyncMock(wraps=client.aclose)
    await owned.close()
    await owned.close()
    client.aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_enforce_filters_and_copies_without_score_change() -> None:
    incoming = results(3)
    original = deepcopy(incoming)
    reranker = JevDecisionReranker(
        "key", mode="enforce", client=FakeClient([0.9, 0.2, 0.7])
    )
    output = await reranker.rerank("q", incoming)
    assert [item.id for item in output] == ["0", "2"]
    assert [item.score for item in output] == [incoming[0].score, incoming[2].score]
    assert all(item is not incoming[int(item.id)] for item in output)
    assert all(item.metadata is not incoming[int(item.id)].metadata for item in output)
    assert all(item.metadata["jev"]["keep"] for item in output)
    assert incoming == original
    assert all("jev" not in item.metadata for item in incoming)
    assert reranker.get_recent_decisions()[0].applied is True


@pytest.mark.asyncio
async def test_enforce_preserves_score_when_metadata_has_score() -> None:
    incoming = results_with_metadata_score()
    reranker = JevDecisionReranker(
        "key", mode="enforce", client=FakeClient([0.9, 0.9])
    )
    output = await reranker.rerank("q", incoming)
    assert len(output) == 2
    for original, copied in zip(incoming, output, strict=True):
        assert copied is not original
        assert copied.score == original.score == 0.95
        assert copied.metadata["score"] == original.metadata["score"] == 0.1
        assert copied.metadata["jev"]["keep"] is True
        assert copied.__dict__["jev"] is copied.metadata["jev"]
        assert "jev" not in original.metadata


@pytest.mark.asyncio
async def test_backfilled_result_preserves_score_when_metadata_has_score() -> None:
    incoming = results_with_metadata_score()
    reranker = JevDecisionReranker(
        "key", mode="enforce", client=FakeClient([0.1, 0.1]), min_keep=1
    )
    output = await reranker.rerank("q", incoming)
    assert [item.id for item in output] == ["0"]
    assert output[0].score == incoming[0].score == 0.95
    assert output[0].metadata["score"] == 0.1
    assert output[0].metadata["jev"]["keep"] is False
    assert output[0].__dict__["jev"] is output[0].metadata["jev"]
    assert all("jev" not in item.metadata and item.score == 0.95 for item in incoming)


@pytest.mark.asyncio
async def test_min_keep_and_cap() -> None:
    incoming = results(5)
    client = FakeClient([0.1] * 5)
    reranker = JevDecisionReranker(
        "key", mode="enforce", client=client, min_keep=1, max_documents=2
    )
    output = await reranker.rerank("q", incoming)
    assert [item.id for item in output] == ["2", "3", "4"]
    assert len(client.calls) == 2
    assert [d.doc_id for d in reranker.get_recent_decisions()[0].decisions] == [
        "0", "1", "2", "3", "4"
    ]
    assert all(item is not incoming[int(item.id)] for item in output)
    assert incoming[0].metadata == {"source": "0"}


@pytest.mark.asyncio
async def test_min_keep_prevents_empty() -> None:
    incoming = results(2)
    reranker = JevDecisionReranker(
        "key", mode="enforce", client=FakeClient([0.1, 0.1]), min_keep=1
    )
    output = await reranker.rerank("q", incoming)
    assert [item.id for item in output] == ["0"]


@pytest.mark.asyncio
async def test_min_keep_never_exceeds_top_n() -> None:
    incoming = results(3)
    reranker = JevDecisionReranker(
        "key", mode="enforce", client=FakeClient([0.1] * 3), min_keep=3
    )
    assert [item.id for item in await reranker.rerank("q", incoming, top_n=2)] == ["0", "1"]


@pytest.mark.asyncio
async def test_all_kept_still_respects_top_n() -> None:
    incoming = results(3)
    reranker = JevDecisionReranker(
        "key", mode="enforce", client=FakeClient([0.9] * 3), min_keep=1
    )
    assert len(await reranker.rerank("q", incoming, top_n=2)) == 2
    assert len(await reranker.rerank("q", incoming, top_n=None)) == 3


@pytest.mark.asyncio
async def test_enforce_top_n_zero_returns_empty() -> None:
    reranker = JevDecisionReranker(
        "key", mode="enforce", client=FakeClient([0.9, 0.9])
    )
    assert await reranker.rerank("q", results(2), top_n=0) == []


@pytest.mark.asyncio
async def test_all_errors_fail_open() -> None:
    incoming = results(2)
    reranker = JevDecisionReranker(
        "key", mode="enforce", client=FakeClient([None, None], error_kind="http_500"),
        circuit_failure_threshold=1,
    )
    assert_fallback(await reranker.rerank("q", incoming), incoming)
    assert reranker.get_stats()["fail_open_count"] == 1
    assert_fallback(await reranker.rerank("q", incoming), incoming)
    assert reranker.get_stats()["circuit_open_skips"] == 1


@pytest.mark.asyncio
async def test_all_timeouts_open_circuit_once_per_batch() -> None:
    incoming = results(2)
    reranker = JevDecisionReranker(
        "key", mode="enforce", client=FakeClient([None, None]),
        circuit_failure_threshold=1,
    )
    for _ in range(3):
        assert_fallback(await reranker.rerank("q", incoming), incoming)
    assert reranker.get_stats()["circuit_open_skips"] == 2
    assert reranker.get_stats()["jev_requests"] == 2
    assert reranker.get_stats()["timeout_batches"] == 1
    assert reranker._consecutive_failures == 1
    assert reranker.get_stats()["circuit_generation"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["enforce", "shadow"])
async def test_batch_deadline_feeds_circuit_and_records(mode) -> None:
    class SlowClient:
        async def ask(self, state: dict, questions: dict) -> dict[str, JevAnswer]:
            await asyncio.sleep(1)
            return {"relevant": JevAnswer(0.9)}

    incoming = results(3)
    recorded = []
    reranker = JevDecisionReranker(
        "key", mode=mode, client=SlowClient(), shadow_background=False,
        deadline_seconds=0.02, circuit_failure_threshold=2, decision_sink=recorded.append,
    )
    for failures in range(1, 3):
        output = await reranker.rerank("q", incoming)
        if mode == "enforce":
            assert_fallback(output, incoming)
        else:
            assert output is incoming
        assert reranker._consecutive_failures == failures
        assert recorded[-1].fallback_reason == "batch_deadline"
        assert recorded[-1].outcome == "fallback"
    assert len(recorded) == 2
    assert reranker.get_stats()["batch_timeouts"] == 2
    requests = reranker.get_stats()["jev_requests"]
    await reranker.rerank("q", incoming)
    assert reranker.get_stats()["circuit_open_skips"] == 1
    assert reranker.get_stats()["jev_requests"] == requests
    assert reranker.get_stats()["circuit_state"] == "open"


@pytest.mark.asyncio
async def test_timeouts_add_to_hard_failure_count() -> None:
    class AlternatingClient:
        def __init__(self) -> None:
            self.calls = 0

        async def ask(self, state: dict, questions: dict) -> dict[str, JevAnswer]:
            self.calls += 1
            raise JevAPIError("timeout" if self.calls == 2 else "http_500")

    incoming = results(1)
    reranker = JevDecisionReranker(
        "key", mode="enforce", client=AlternatingClient(),
        circuit_failure_threshold=2,
    )
    for _ in range(2):
        assert_fallback(await reranker.rerank("q", incoming), incoming)
    assert reranker.get_stats()["timeout_batches"] == 1
    assert reranker._consecutive_failures == 2
    assert reranker.get_stats()["jev_requests"] == 2
    assert_fallback(await reranker.rerank("q", incoming), incoming)
    assert reranker.get_stats()["circuit_open_skips"] == 1


@pytest.mark.asyncio
async def test_enforce_deadline_fails_open_with_top_n() -> None:
    class SlowClient:
        async def ask(self, state: dict, questions: dict) -> dict[str, JevAnswer]:
            await asyncio.sleep(1)
            return {"relevant": JevAnswer(0.1)}

    incoming = results(3)
    reranker = JevDecisionReranker(
        "key", mode="enforce", client=SlowClient(), deadline_seconds=0.02
    )
    started = time.monotonic()
    output = await reranker.rerank("q", incoming, top_n=2)
    assert time.monotonic() - started < 0.5
    assert len(output) == 2
    assert_fallback(output, incoming[:2])
    assert reranker.get_stats()["fail_open_count"] == 1
    assert reranker.get_stats()["batch_timeouts"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [httpx.Response(503), httpx.Response(200, json={})])
async def test_http_and_parse_failure_fail_open(response: httpx.Response) -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: response)
    ) as http:
        client = TypeSafeJevClient("test-key", client=http)
        incoming = results(1)
        reranker = JevDecisionReranker("test-key", mode="enforce", client=client)
        assert_fallback(await reranker.rerank("q", incoming), incoming)


@pytest.mark.asyncio
async def test_partial_error_keeps_failed_document() -> None:
    incoming = results(3)
    reranker = JevDecisionReranker(
        "key", mode="enforce", client=FakeClient([0.1, None, 0.8])
    )
    output = await reranker.rerank("q", incoming)
    assert [item.id for item in output] == ["1", "2"]
    assert output[0].metadata["jev"]["status"] == "error"
    assert reranker.get_recent_decisions()[0].decisions[1].error_kind == "timeout"


@pytest.mark.asyncio
async def test_missing_key_and_off_are_passthrough() -> None:
    incoming = results(2)
    no_key = JevDecisionReranker(None, mode="enforce")
    assert await no_key.rerank("q", incoming) is incoming
    assert no_key.get_stats()["disabled_reason"] == "missing_api_key"
    off = JevDecisionReranker("key", mode="off", client=FakeClient([0.1, 0.1]))
    assert await off.rerank("q", incoming) is incoming
    assert off.get_recent_decisions() == []


@pytest.mark.asyncio
async def test_passthrough_paths_respect_top_n() -> None:
    incoming = results(3)
    rerankers = [
        JevDecisionReranker(None, mode="enforce"),
        JevDecisionReranker("key", mode="off"),
        JevDecisionReranker("key", mode="enforce", client=FakeClient([None] * 3)),
    ]
    for reranker in rerankers:
        output = await reranker.rerank("q", incoming, top_n=2)
        assert len(output) == 2
        assert [doc.id for doc in output] == [doc.id for doc in incoming[:2]]

    circuit = rerankers[-1]
    circuit._circuit_open_until = time.monotonic() + 1
    output = await circuit.rerank("q", incoming, top_n=1)
    assert len(output) == 1
    assert_fallback(output, incoming[:1])

    shadow = JevDecisionReranker("key", client=FakeClient([0.9] * 3))
    shadow._max_pending = 0
    output = await shadow.rerank("q", incoming, top_n=1)
    assert len(output) == 1
    assert output[0] is incoming[0]


@pytest.mark.asyncio
async def test_sink_failure_is_swallowed() -> None:
    def broken_sink(batch) -> None:
        raise RuntimeError("sink")

    incoming = results(1)
    reranker = JevDecisionReranker(
        "key", client=FakeClient([0.8]),
        shadow_background=False, decision_sink=broken_sink,
    )
    assert await reranker.rerank("q", incoming) is incoming


@pytest.mark.asyncio
@pytest.mark.parametrize("kinds", [
    ["timeout", "timeout"], ["http_500", "http_500"], ["http_500", "timeout"],
])
async def test_all_error_kinds_count_once(kinds):
    class Client:
        async def ask(self, state, questions):
            raise JevAPIError(kinds[int(state["passage"].split()[-1])])

    reranker = JevDecisionReranker("test-key", mode="enforce", client=Client())
    for count in range(1, 3):
        output = await reranker.rerank("q", results(2))
        assert all(doc.metadata["jev_fallback_reason"] == "all_error" for doc in output)
        assert reranker._consecutive_failures == count
    assert len(reranker.get_recent_decisions()) == 2


@pytest.mark.asyncio
async def test_partial_error_resets_failure_count():
    client = FakeClient([None, None])
    reranker = JevDecisionReranker("test-key", mode="enforce", client=client)
    await reranker.rerank("q", results(2))
    assert reranker._consecutive_failures == 1
    client.probabilities = [0.9, None]
    output = await reranker.rerank("q", results(2))
    assert reranker._consecutive_failures == 0
    assert reranker.get_stats()["partial_error_batches"] == 1
    assert all(doc.metadata["jev_outcome"] == "judged" for doc in output)


class ControlledClient:
    """Events control completion order without sleep-based concurrency assumptions."""

    def __init__(self):
        self.started = asyncio.Queue()
        self.calls = []
        self.active = 0

    async def ask(self, state, questions):
        response = asyncio.get_running_loop().create_future()
        self.calls.append((state["query"], state["passage"]))
        self.active += 1
        await self.started.put(response)
        try:
            return {"relevant": JevAnswer(await response)}
        finally:
            self.active -= 1


@pytest.mark.asyncio
@pytest.mark.parametrize("probe", [False, True])
async def test_caller_cancellation_propagates_and_releases_probe(probe):
    client = ControlledClient()
    reranker = JevDecisionReranker("test-key", mode="enforce", client=client, concurrency=1)
    reranker._consecutive_failures = 1
    if probe:
        reranker._circuit_open_until = time.monotonic() - 1
    before = (reranker._consecutive_failures, reranker._circuit_generation, reranker._circuit_open_until)
    task = asyncio.create_task(reranker.rerank("q", results(3)))
    await client.started.get()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert (reranker._consecutive_failures, reranker._circuit_generation,
            reranker._circuit_open_until) == before
    assert not reranker._probe_in_flight
    assert client.active == 0
    assert reranker._sem._value == 1
    assert reranker.get_recent_decisions() == []
    assert reranker.get_stats()["batch_timeouts"] == 0
    if probe:
        retry = asyncio.create_task(reranker.rerank("retry", results(1)))
        (await client.started.get()).set_result(0.9)
        await retry
        assert reranker.get_stats()["circuit_state"] == "closed"


@pytest.mark.asyncio
@pytest.mark.parametrize("late_failure", [False, True])
async def test_late_batch_cannot_change_new_generation(late_failure):
    client = ControlledClient()
    reranker = JevDecisionReranker("test-key", mode="enforce", client=client,
                                   circuit_failure_threshold=1)
    late = asyncio.create_task(reranker.rerank("late", results(1)))
    late_response = await client.started.get()
    opener = asyncio.create_task(reranker.rerank("opener", results(1)))
    (await client.started.get()).set_exception(JevAPIError("http_500"))
    await opener
    before = (reranker._consecutive_failures, reranker._circuit_generation, reranker._circuit_open_until)
    if late_failure:
        late_response.set_exception(JevAPIError("timeout"))
    else:
        late_response.set_result(0.9)
    await late
    assert (reranker._consecutive_failures, reranker._circuit_generation,
            reranker._circuit_open_until) == before
    assert reranker.get_stats()["circuit_state"] == "open"


@pytest.mark.asyncio
@pytest.mark.parametrize("fails", [False, True])
async def test_cooldown_allows_exactly_one_probe(monkeypatch, fails):
    client = ControlledClient()
    reranker = JevDecisionReranker("test-key", mode="enforce", client=client,
        circuit_failure_threshold=1, circuit_cooldown_seconds=10)
    first = asyncio.create_task(reranker.rerank("open", results(1)))
    (await client.started.get()).set_exception(JevAPIError("http_500"))
    await first
    # Replace this module's clock only; do not change asyncio's clock.
    from types import SimpleNamespace

    cooldown_end = reranker._circuit_open_until
    monkeypatch.setattr("app.modules.core.retrieval.rerankers.jev_decision_reranker.time",
                        SimpleNamespace(monotonic=lambda: cooldown_end))
    tasks = [asyncio.create_task(reranker.rerank("probe", results(1))) for _ in range(8)]
    response = await client.started.get()
    assert reranker.get_stats()["circuit_state"] == "half_open"
    assert reranker.get_stats()["circuit_open_skips"] == 7
    assert len(client.calls) == 2
    if fails:
        response.set_exception(JevAPIError("timeout"))
    else:
        response.set_result(0.9)
    outputs = await asyncio.gather(*tasks)
    assert sum(output[0].metadata["jev_outcome"] == "fallback" for output in outputs) == (8 if fails else 7)
    assert not reranker._probe_in_flight
    assert reranker._circuit_generation == (2 if fails else 1)
    assert reranker._consecutive_failures == (2 if fails else 0)
    assert bool(reranker._circuit_open_until) is fails
    assert reranker.get_stats()["circuit_state"] == ("open" if fails else "closed")


@pytest.mark.asyncio
async def test_deadline_cancels_all_work_and_recovers_semaphore():
    client = ControlledClient()
    reranker = JevDecisionReranker("test-key", mode="enforce", client=client,
        concurrency=1, deadline_seconds=0.02)
    before = asyncio.all_tasks()
    output = await reranker.rerank("q", results(4), top_n=2)
    assert len(output) == 2
    assert output[0].metadata["jev_fallback_reason"] == "batch_deadline"
    assert len(client.calls) == 1
    assert client.active == 0
    assert reranker._sem._value == 1
    assert asyncio.all_tasks() == before


@pytest.mark.asyncio
async def test_queued_documents_recheck_generation_before_http():
    client = ControlledClient()
    reranker = JevDecisionReranker("test-key", mode="enforce", client=client,
        concurrency=1, circuit_failure_threshold=1, deadline_seconds=1)
    # Occupy the semaphore with an older batch. A newer batch times out while
    # queued and opens the circuit; its queued work and the older tail cannot send.
    old = asyncio.create_task(reranker.rerank("old", results(3)))
    response = await client.started.get()
    # The first batch's wait_for has captured its original deadline.
    reranker.deadline_seconds = 0.005
    await reranker.rerank("opener", results(1))
    assert reranker._circuit_generation == 1
    response.set_result(0.9)
    await old
    assert client.calls == [("old", "passage 0")]
    old_batch = reranker.get_recent_decisions()[-1]
    assert [d.error_kind for d in old_batch.decisions] == [None, "circuit_open", "circuit_open"]
    assert reranker._consecutive_failures == 1


@pytest.mark.asyncio
async def test_negative_limit_rejected_without_http():
    client = FakeClient([0.9])
    reranker = JevDecisionReranker("test-key", mode="enforce", client=client)
    with pytest.raises(ValueError):
        await reranker.rerank("q", [], top_n=-1)
    assert await reranker.rerank("q", results(1), top_n=0) == []
    assert client.calls == []
