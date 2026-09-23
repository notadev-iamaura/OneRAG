"""Fail-open Jev decision filter for retrieved passages."""

import asyncio
import copy
import hashlib
import inspect
import time
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from typing import Any, Literal

from .....lib.logger import get_logger
from ..interfaces import SearchResult
from .jev_client import JevAPIError, TypeSafeJevClient

logger = get_logger(__name__)

Mode = Literal["off", "shadow", "enforce"]
DecisionStatus = Literal["ok", "error", "skipped_cap"]

DEFAULT_INSTRUCTIONS = (
    "Does the passage contain information that helps answer the query? "
    "Judge usefulness for answering, not topical similarity. "
    "Passage may be Korean or English."
)


@dataclass(frozen=True)
class JevDecision:
    doc_id: str
    position: int
    probability: float | None
    confidence: float | None
    keep: bool
    status: DecisionStatus
    error_kind: str | None = None


@dataclass(frozen=True)
class JevDecisionBatch:
    query_hash: str
    mode: Mode
    model: str
    decisions: tuple[JevDecision, ...]
    latency_ms: float
    applied: bool
    error: str | None


DecisionSink = Callable[[JevDecisionBatch], Awaitable[None] | None]


class JevDecisionReranker:
    """Judge results without shadow mutation; min_keep stays within top_n."""

    name = "jev-decision"
    enabled = True

    def __init__(
        self,
        api_key: str | None,
        mode: Mode = "shadow",
        model: str = "jev-1.13.0",
        endpoint: str = "https://api.typesafe.ai/v1/systemone",
        question_type: Literal["noul", "score"] = "noul",
        instructions: str | None = None,
        min_relevance: float = 0.5,
        min_keep: int = 1,
        max_documents: int = 20,
        max_passage_chars: int = 2000,
        score_scale_max: float = 1.0,
        timeout: float = 3.0,
        deadline_seconds: float = 5.0,
        concurrency: int = 4,
        shadow_background: bool = True,
        circuit_failure_threshold: int = 5,
        circuit_cooldown_seconds: float = 30.0,
        decision_sink: DecisionSink | None = None,
        client: TypeSafeJevClient | None = None,
        recent_maxlen: int = 200,
    ) -> None:
        if mode not in ("off", "shadow", "enforce"):
            raise ValueError("invalid Jev mode")
        if not 0 <= min_relevance <= 1 or min_keep < 1:
            raise ValueError("invalid Jev relevance or min_keep")
        if max_documents < 1 or max_passage_chars < 1 or concurrency < 1:
            raise ValueError("invalid Jev request limits")
        if deadline_seconds <= 0:
            raise ValueError("invalid Jev batch deadline")
        self.mode = mode
        self.model = model
        self.question_type = question_type
        self.instructions = instructions or DEFAULT_INSTRUCTIONS
        self.min_relevance = min_relevance
        self.min_keep = min_keep
        self.max_documents = max_documents
        self.max_passage_chars = max_passage_chars
        self.shadow_background = shadow_background
        self.deadline_seconds = deadline_seconds
        self._disabled_reason = "missing_api_key" if not api_key else None
        self._client = (
            client
            or TypeSafeJevClient(
                api_key=api_key or "",
                model=model,
                endpoint=endpoint,
                timeout=timeout,
                score_scale_max=score_scale_max,
            )
            if api_key and mode != "off"
            else None
        )
        self._owns_client = client is None
        self._sem = asyncio.Semaphore(concurrency)
        self._max_pending = concurrency * 4
        self._pending: set[asyncio.Task[None]] = set()
        self._closed = False
        self._recent: deque[JevDecisionBatch] = deque(maxlen=recent_maxlen)
        self._decision_sink = decision_sink
        self._circuit_failure_threshold = circuit_failure_threshold
        self._circuit_cooldown_seconds = circuit_cooldown_seconds
        self._consecutive_failures = 0
        self._circuit_open_until = 0.0
        self.stats: dict[str, int] = {
            "total_calls": 0,
            "jev_requests": 0,
            "jev_failures": 0,
            "docs_judged": 0,
            "docs_dropped": 0,
            "fail_open_count": 0,
            "batch_timeouts": 0,
            "timeout_batches": 0,
            "circuit_open_skips": 0,
            "shadow_tasks_dropped": 0,
        }

    async def rerank(
        self, query: str, results: list[SearchResult], top_n: int | None = None
    ) -> list[SearchResult]:
        if not results:
            return self._passthrough(results, top_n)
        self.stats["total_calls"] += 1
        base = results
        if self.mode == "off" or self._client is None:
            return self._passthrough(base, top_n)
        if time.monotonic() < self._circuit_open_until:
            self.stats["circuit_open_skips"] += 1
            return self._passthrough(base, top_n)

        if self.mode == "shadow":
            base = self._passthrough(base, top_n)

        snapshot = tuple(
            (result.id, result.content[: self.max_passage_chars])
            for result in base[: self.max_documents]
        )
        doc_ids = tuple(result.id for result in base)
        if self.mode == "shadow":
            if self.shadow_background:
                if len(self._pending) >= self._max_pending:
                    self.stats["shadow_tasks_dropped"] += 1
                    return self._passthrough(base, top_n)
                task = asyncio.create_task(self._judge_and_record(query, snapshot, doc_ids))
                self._pending.add(task)
                task.add_done_callback(self._pending.discard)
            else:
                await self._judge_and_record(query, snapshot, doc_ids)
            return self._passthrough(base, top_n)

        try:
            batch = await asyncio.wait_for(
                self._judge(query, snapshot, doc_ids), timeout=self.deadline_seconds
            )
        except TimeoutError:
            # Cancellation skips _judge's circuit accounting.
            self.stats["batch_timeouts"] += 1
            self.stats["fail_open_count"] += 1
            return self._passthrough(base, top_n)
        judged = [d for d in batch.decisions if d.status != "skipped_cap"]
        if judged and all(d.status == "error" for d in judged):
            self.stats["fail_open_count"] += 1
            await self._record(batch)
            return self._passthrough(base, top_n)
        limit = len(base) if top_n is None else min(top_n, len(base))
        keep_floor = min(self.min_keep, limit)
        keep_positions = {d.position for d in batch.decisions if d.keep}
        if len(keep_positions) < keep_floor:
            keep_positions.update(range(keep_floor))
        selected = [
            self._copy_with_decision(result, decision)
            for result, decision in zip(base, batch.decisions, strict=True)
            if decision.position in keep_positions
        ]
        self.stats["docs_dropped"] += len(base) - len(selected)
        await self._record(replace(batch, applied=len(selected) != len(base)))
        return selected[:limit]

    def _passthrough(
        self, results: list[SearchResult], top_n: int | None
    ) -> list[SearchResult]:
        if top_n is None or top_n >= len(results):
            return results
        return results[:top_n]

    async def _judge_and_record(
        self, query: str, snapshot: tuple[tuple[str, str], ...], doc_ids: tuple[str, ...]
    ) -> None:
        batch = await self._judge(query, snapshot, doc_ids)
        await self._record(batch)

    async def _judge(
        self, query: str, snapshot: tuple[tuple[str, str], ...], doc_ids: tuple[str, ...]
    ) -> JevDecisionBatch:
        started = time.monotonic()

        async def judge_one(position: int, doc_id: str, passage: str) -> JevDecision:
            async with self._sem:
                self.stats["jev_requests"] += 1
                try:
                    assert self._client is not None
                    question: dict[str, Any] = {
                        "type": self.question_type,
                        "instructions": self.instructions,
                    }
                    if self.question_type == "score":
                        question["criteria"] = ["unrelated", "directly answers the query"]  # TypeSafe ScoreQuestion: array of levels
                    answer = (await self._client.ask(
                        {"query": query, "passage": passage}, {"relevant": question}
                    ))["relevant"]
                    self.stats["docs_judged"] += 1
                    return JevDecision(
                        doc_id, position, answer.probability, answer.confidence,
                        answer.probability >= self.min_relevance, "ok",
                    )
                except Exception as exc:
                    self.stats["jev_failures"] += 1
                    error_kind = exc.kind if isinstance(exc, JevAPIError) else "unexpected"
                    return JevDecision(
                        doc_id, position, None, None, True, "error", error_kind
                    )

        judged = await asyncio.gather(
            *(judge_one(i, doc_id, passage) for i, (doc_id, passage) in enumerate(snapshot))
        )
        errors = [decision for decision in judged if decision.status == "error"]
        all_failed = bool(judged) and len(errors) == len(judged)
        hard = [decision for decision in errors if decision.error_kind != "timeout"]
        if not all_failed:
            self._consecutive_failures = 0
        elif hard:
            self._consecutive_failures += 1
            if self._consecutive_failures >= self._circuit_failure_threshold:
                self._circuit_open_until = time.monotonic() + self._circuit_cooldown_seconds
        else:
            self.stats["timeout_batches"] += 1
        decisions = (*judged, *(
            JevDecision(doc_ids[i], i, None, None, True, "skipped_cap")
            for i in range(len(snapshot), len(doc_ids))
        ))
        return JevDecisionBatch(
            hashlib.sha256(query.encode()).hexdigest()[:16],
            self.mode,
            self.model,
            decisions,
            (time.monotonic() - started) * 1000,
            False,
            "jev_failure" if judged and all(d.status == "error" for d in judged) else None,
        )

    async def _record(self, batch: JevDecisionBatch) -> None:
        self._recent.append(batch)
        if self._decision_sink is not None:
            try:
                result = self._decision_sink(batch)
                if inspect.isawaitable(result):
                    await result
            except Exception:
                logger.warning("jev_decision_sink_failed")
        logger.info(
            "jev_decision",
            extra={
                "mode": batch.mode,
                "model": batch.model,
                "query_hash": batch.query_hash,
                "n_judged": sum(d.status == "ok" for d in batch.decisions),
                "n_drop_would": sum(not d.keep for d in batch.decisions),
                "error_kinds": sorted({
                    d.error_kind for d in batch.decisions if d.error_kind is not None
                }),
                "latency_ms": batch.latency_ms,
            },
        )

    def _copy_with_decision(self, result: SearchResult, decision: JevDecision) -> SearchResult:
        # copy + setattr: mirrors SearchResult.__post_init__ promotion without
        # re-running it (rebuilding would let metadata["score"] clobber .score).
        # __dict__ keeps mypy/ruff happy vs copied.jev / setattr(const).
        copied = copy.copy(result)
        jev_meta = {
            "p": decision.probability,
            "conf": decision.confidence,
            "keep": decision.keep,
            "model": self.model,
            "status": decision.status,
        }
        copied.metadata = {**result.metadata, "jev": jev_meta}
        copied.__dict__["jev"] = jev_meta  # dynamic attr; avoids mypy attr-defined + ruff B010
        return copied

    def supports_caching(self) -> bool:
        return False

    async def initialize(self) -> None:
        """No initialization is needed for the HTTP client."""

    async def drain(self, timeout: float | None = None) -> None:
        pending = set(self._pending)
        if pending:
            _, stragglers = await asyncio.wait(pending, timeout=timeout)
            for task in stragglers:
                task.cancel()
            await asyncio.gather(*stragglers, return_exceptions=True)
            self._pending.difference_update(pending)

    async def close(self) -> None:
        if self._closed:
            return
        await self.drain(timeout=self.deadline_seconds)
        if self._client is not None and self._owns_client:
            await self._client.aclose()
            self._client = None
        self._closed = True

    def get_stats(self) -> dict[str, Any]:
        return {**self.stats, "disabled_reason": self._disabled_reason}

    def get_recent_decisions(self) -> list[JevDecisionBatch]:
        return list(self._recent)
