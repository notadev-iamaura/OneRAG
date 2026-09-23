"""Self-RAG retry receives the main retrieval path's normalized options."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.api.services.rag_pipeline import RAGPipeline
from app.modules.core.generation.generator import GenerationResult
from app.modules.core.self_rag.orchestrator import SelfRAGOutcome, SelfRAGResult


def _pipeline(filter_mappings: dict[str, Any]) -> RAGPipeline:
    pipeline = RAGPipeline.__new__(RAGPipeline)
    pipeline.config = {
        "self_rag": {"enabled": True},
        "query_routing": {
            "data_source_routing": {"filter_mappings": filter_mappings}
        },
    }
    pipeline.min_score = 0.3
    result = SelfRAGResult(
        "original", False, MagicMock(score=0.2), None, None, False, 0.0,
        outcome=SelfRAGOutcome.OK,
    )
    pipeline.self_rag_module = MagicMock(
        verify_existing_answer=AsyncMock(return_value=result)
    )
    return pipeline


def _generation() -> GenerationResult:
    return GenerationResult("original", "original", 10, "model", "provider", 0.1)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("filter_mappings", "options", "expected_filters", "expected_min_score"),
    [
        (
            {"structured": {"doc_type": "table"}},
            {"data_source": "structured", "filters": {"lang": "ko"}},
            {"lang": "ko", "doc_type": "table"},
            0.3,
        ),
        (
            {"structured": {"doc_type": "table"}},
            {"data_source": "structured", "filters": {"lang": "ko"}, "min_score": 0.7},
            {"lang": "ko", "doc_type": "table"},
            0.7,
        ),
        ({}, {}, None, 0.3),
    ],
)
async def test_retry_receives_normalized_filters_and_min_score(
    filter_mappings: dict[str, Any],
    options: dict[str, Any],
    expected_filters: dict[str, Any] | None,
    expected_min_score: float,
) -> None:
    pipeline = _pipeline(filter_mappings)
    options = {**options, "_debug_trace_data": {}}
    original_options = dict(options)
    if "filters" in options:
        original_options["filters"] = dict(options["filters"])

    await pipeline.self_rag_verify("query", "session", _generation(), [], options)

    passed_options = pipeline.self_rag_module.verify_existing_answer.await_args.kwargs[
        "options"
    ]
    assert passed_options["filters"] == expected_filters
    assert passed_options["min_score"] == expected_min_score
    assert "_debug_trace_data" not in passed_options
    assert options == original_options
