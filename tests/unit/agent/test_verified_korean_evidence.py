from unittest.mock import AsyncMock

import pytest

from app.lib.llm_client import OllamaLLMClient
from app.modules.core.agent import extractive_reader as agent


def profile(**kwargs):
    values = {"implementation": "generative", "top_k": 1, "device": "cpu", "rescue_refusals": True,
              "sufficiency_model_dir": "/local/verifier", "boundary_model_dir": "/local/reader",
              "evidence_policy": "verified_korean_spans"}
    return agent.ExtractiveReaderConfig(**{**values, **kwargs})


@pytest.mark.parametrize("changes", [
    {"implementation": "en_generative"}, {"sufficiency_threshold": 0.2}, {"rescue_span_threshold": 0.},
    {"rescue_refusals": False}, {"top_k": 2}, {"evidence_policy": "unregistered"},
])
def test_verified_span_policy_requires_its_original_local_configuration(changes):
    with pytest.raises(ValueError):
        profile(**changes)


@pytest.mark.asyncio
async def test_verified_local_mode_uses_one_completed_response_and_original_offsets(monkeypatch):
    text = "도시 누리 개장. 동부 도시 누리 개장."
    model = AsyncMock(spec=OllamaLLMClient)
    model.base_url = "http://127.0.0.1:18759"
    model.generate_text.return_value = "[1.1] 누리"
    a = text.index("누리")
    proposal = {"source_id": "S1", "answer": "누리", "start": a, "end": a+2, "quote": text,
                "quote_start": 0, "quote_end": len(text), "score": 8.}
    monkeypatch.setattr(agent, "_boundary_proposal", lambda *args: proposal)
    result = await agent.extract_from_sources(profile(), model, "동부 도시 개장", {"S1": ({"title": "안내"}, text)})
    assert result is not None
    answer, source = result
    assert answer == "누리" and source["answer_start"] == text.rindex(answer)
    assert source["cited_sentences"] == ["동부 도시 누리 개장."]
    assert model.generate_text.await_args.kwargs["require_complete"] is True
    model.generate_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_unverified_transport_is_rejected_before_generation():
    model = AsyncMock()
    with pytest.raises(ValueError, match="completion status"):
        await agent.extract_from_sources(profile(), model, "질문?", {"S1": ({"title": "안내"}, "본문.")})
    model.generate_text.assert_not_awaited()


def test_existing_korean_passage_profile_uses_the_direct_decoder_with_compatible_token_ids(monkeypatch):
    from app.modules.core.generation.korean_reranked_passage_reader import (
        KoreanRerankedPassageReader,
    )
    from app.modules.core.generation.korean_span_reader import KoreanSpanReader
    from app.modules.core.generation.tydi_evidence_spans import KoreanEvidenceProposer

    monkeypatch.setattr(KoreanEvidenceProposer, "__init__", lambda self, root, device: None)
    reader = KoreanRerankedPassageReader.from_local("/models/qa", "/models/verifier", "cpu", 2.958441734313965)
    decoder = reader.span_provider()
    assert isinstance(decoder.__self__, KoreanEvidenceProposer)
    assert decoder.__func__ is KoreanSpanReader.predict_spans
