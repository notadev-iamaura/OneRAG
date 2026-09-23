"""Jev decision filter contracts, with no external requests."""

import asyncio
import time
from copy import deepcopy

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
    assert await reranker.rerank("q", incoming) is incoming
    assert reranker.get_stats()["fail_open_count"] == 1
    assert await reranker.rerank("q", incoming) is incoming
    assert reranker.get_stats()["circuit_open_skips"] == 1


@pytest.mark.asyncio
async def test_all_timeouts_do_not_open_circuit() -> None:
    incoming = results(2)
    reranker = JevDecisionReranker(
        "key", mode="enforce", client=FakeClient([None, None]),
        circuit_failure_threshold=1,
    )
    for _ in range(3):
        assert await reranker.rerank("q", incoming) is incoming
    assert reranker.get_stats()["circuit_open_skips"] == 0
    assert reranker.get_stats()["jev_requests"] == 6
    assert reranker.get_stats()["timeout_batches"] == 3


@pytest.mark.asyncio
async def test_batch_deadline_does_not_feed_circuit() -> None:
    class SlowClient:
        async def ask(self, state: dict, questions: dict) -> dict[str, JevAnswer]:
            await asyncio.sleep(1)
            return {"relevant": JevAnswer(0.9)}

    incoming = results(1)
    reranker = JevDecisionReranker(
        "key", mode="enforce", client=SlowClient(),
        deadline_seconds=0.02, circuit_failure_threshold=1,
    )
    for _ in range(2):
        assert await reranker.rerank("q", incoming) is incoming
    assert reranker.get_stats()["batch_timeouts"] == 2
    assert reranker.get_stats()["circuit_open_skips"] == 0


@pytest.mark.asyncio
async def test_timeouts_do_not_reset_hard_failure_count() -> None:
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
    for _ in range(3):
        assert await reranker.rerank("q", incoming) is incoming
    assert reranker.get_stats()["timeout_batches"] == 1
    assert await reranker.rerank("q", incoming) is incoming
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
    assert all(output[i] is incoming[i] for i in range(2))
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
        assert await reranker.rerank("q", incoming) is incoming


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
        assert all(output[i] is incoming[i] for i in range(2))

    circuit = rerankers[-1]
    circuit._circuit_open_until = time.monotonic() + 1
    output = await circuit.rerank("q", incoming, top_n=1)
    assert len(output) == 1
    assert output[0] is incoming[0]

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
