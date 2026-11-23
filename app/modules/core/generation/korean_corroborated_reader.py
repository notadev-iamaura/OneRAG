"""Read one original article, using the existing local QA and relevance encoders to corroborate source spans."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from .grounded_span import read_grounded_span
from .korean_corroborated_evidence import corroborate_misplaced_citation, select_supported_extent

Span = dict[str, Any]


class _RecordText:
    def __init__(self, model: Any):
        self.model = model
        self.raw: str | None = None

    async def generate_text(self, **options: Any) -> str:
        self.raw = await self.model.generate_text(**options)
        if not isinstance(self.raw, str):
            raise ValueError("The completed grounded reader requires a text response")
        return self.raw


async def read(
    model: Any, question: str, doc: Span,
    boundary: Callable[[], Awaitable[Span]], supported: Callable[[], Awaitable[bool]],
    rescue_span_threshold: float,
) -> Span | None:
    from ..agent.extractive_reader import refine_boundaries, supported_quantities

    captured = _RecordText(model)
    try:
        generated = await read_grounded_span(captured, question, [doc])
    except ValueError as error:
        if str(error) != "Answer is absent from the cited sentence" or not await supported():
            raise
        recovered = corroborate_misplaced_citation(doc, captured.raw, await boundary(), 1.)
        if recovered is None:
            raise
        return recovered
    if generated is None:
        if await supported():
            proposal = await boundary()
            if proposal["score"] > rescue_span_threshold and supported_quantities(question, proposal["quote"]):
                return select_supported_extent(question, doc, proposal, None, proposal)
        return None
    proposal = await boundary()
    initial = refine_boundaries(generated, proposal)
    return select_supported_extent(question, doc, initial, generated, proposal)
