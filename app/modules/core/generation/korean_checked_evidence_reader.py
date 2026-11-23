"""Select original Korean evidence using one completed generation and the configured QA and support encoders."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from functools import lru_cache
from typing import Any

from .grounded_span import read_grounded_span
from .korean_corroborated_evidence import select_supported_extent
from .korean_corroborated_reader import _RecordText
from .korean_evidence_safety import safe_extent, safe_mention, safe_recover
from .korean_mention_coverage import select as select_mention

Span = dict[str, Any]
_MISPLACED = "Answer is absent from the cited sentence"


@lru_cache(maxsize=1)
def _tokenizer() -> Any:
    from ..retrieval.bm25_engine.tokenizer import KoreanTokenizer
    return KoreanTokenizer()


def select_row(mode: str, question: str, doc: Span, support: float, proposal: Span, control_row: Span,
               generated: Span | None, raw: str | None) -> Span:
    """Apply the same source checks to recorded and live responses. A failed repair retains its original error."""
    if control_row["status"] == "error":
        if control_row.get("error", "").removeprefix("ValueError: ") != _MISPLACED:
            return control_row
        recovered = safe_recover(question, doc, raw, proposal, support)
        if recovered is None:
            return control_row
        chosen = {**{k: v for k, v in control_row.items() if k != "error"}, "status": "answered", **recovered}
    elif control_row["status"] == "answered":
        trimmed = select_supported_extent(question, doc, control_row, generated, proposal)
        chosen = safe_extent(question, control_row, trimmed)
    else:
        return control_row
    moved = select_mention(question, doc, chosen, lambda text: _tokenizer().tokenize(text))
    return safe_mention(doc, chosen, moved)


async def read(
    model: Any, question: str, doc: Span,
    boundary: Callable[[], Awaitable[Span]], supported: Callable[[], Awaitable[bool]],
) -> Span | None:
    from ..agent.extractive_reader import refine_boundaries, supported_quantities

    capture = _RecordText(model)
    try:
        generated = await read_grounded_span(capture, question, [doc])
    except ValueError as exc:
        if str(exc) != _MISPLACED or not await supported():
            raise
        proposal = await boundary()
        result = await asyncio.to_thread(select_row, "", question, doc, 1., proposal,
                                         {"status": "error", "error": _MISPLACED}, None, capture.raw)
        if result["status"] != "answered":
            raise
        return result
    if generated is None:
        if not await supported():
            return None
        proposal = await boundary()
        if proposal["score"] <= 4. or not supported_quantities(question, proposal["quote"]):
            return None
        initial = proposal
    else:
        proposal = await boundary()
        initial = refine_boundaries(generated, proposal)
    return await asyncio.to_thread(select_row, "", question, doc, 0., proposal,
                                   {"status": "answered", **initial}, generated, capture.raw)
