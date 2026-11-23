from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.modules.core.agent import extractive_reader
from app.modules.core.agent.factory import AgentFactory
from app.modules.core.agent.interfaces import AgentState, AgentStep, ToolResult
from app.modules.core.agent.synthesizer import AgentSynthesizer
from app.modules.core.generation.grounded_span import answer_offset


def config(**reader):
    return AgentFactory.create_config({"mcp": {"agent": {
        "require_evidence_quotes": True, "extractive_reader": reader,
    }}})


@pytest.mark.asyncio
@pytest.mark.parametrize(("response", "status"), [
    ("[2.2] 금요일", "verified_quotes"), ("NONE", "insufficient"),
    ("[1.2] 금요일", "error"), ("", "error"),
])
async def test_generative_span_agent(response, status):
    model = AsyncMock()
    model.generate_text.return_value = response
    synthesizer = AgentSynthesizer(model, config(implementation="generative"))
    docs = [{"id": "unrelated", "content": "광주에 있다."},
            {"id": "event", "content": "행사 공지.\n  접수는 금요일에 끝난다."}]
    state = AgentState("접수는 언제 끝나나?", steps=[AgentStep(1, "", [], [ToolResult("x", "search", True, data=docs)])])
    answer, sources = await synthesizer.synthesize(state)
    assert state.grounding_status == status
    if status == "verified_quotes":
        source, = sources
        body = docs[1]["content"]
        assert source["source_id"] == "event"
        assert body[source["answer_start"]:source["answer_end"]] == answer == "금요일"
        assert body[source["quote_start"]:source["quote_end"]] == source["cited_sentences"][0]
    else:
        assert not sources


@pytest.mark.asyncio
async def test_local_encoder_preserves_document_and_chunk_identity(monkeypatch, tmp_path):
    model = AsyncMock()
    profile = config(implementation="en_encoder", model_dir=str(tmp_path))

    def encode(profile, question, documents):
        assert [d["content"] for d in documents] == ["Denied.", "Allowed."]
        return SimpleNamespace(source_id=documents[1]["id"], start=0, end=7, answer="Allowed",
                               quote="Allowed.", quote_start=0, quote_end=8)

    monkeypatch.setattr(extractive_reader, "_encode", encode)
    docs = [{"id": str(n), "content": body, "metadata": {"document_id": "policy", "chunk": n}}
            for n, body in enumerate(("Denied.", "Allowed."))]
    state = AgentState("Which?", steps=[AgentStep(1, "", [], [ToolResult("x", "search", True, data=docs)])])
    answer, sources = await AgentSynthesizer(model, profile).synthesize(state)
    assert (answer, sources[0]["document_id"], sources[0]["source_id"], sources[0]["chunk"]) == (
        "Allowed", "policy", "1", 1
    )
    model.generate_text.assert_not_awaited()


def test_reader_cannot_be_silently_ignored():
    with pytest.raises(ValueError, match="require_evidence_quotes"):
        AgentFactory.create_config({"mcp": {"agent": {"extractive_reader": {"implementation": "generative"}}}})


@pytest.mark.asyncio
async def test_sufficiency_refusal_skips_generation(monkeypatch, tmp_path):
    model = AsyncMock()
    profile = config(implementation="generative", sufficiency_model_dir=str(tmp_path))
    verifier = SimpleNamespace(scores=lambda q, docs: [-1.] * len(docs))
    monkeypatch.setattr(extractive_reader, "_load_sufficiency", lambda path, device: verifier)
    doc = {"id": "a", "content": "신청 절차를 안내합니다."}
    state = AgentState("신청한 사람은?", steps=[AgentStep(1, "", [], [ToolResult("x", "search", True, data=[doc])])])
    assert await AgentSynthesizer(model, profile).synthesize(state) == ("근거 부족", [])
    assert state.grounding_status == "insufficient"
    model.generate_text.assert_not_awaited()


def test_duplicate_literal_uses_the_asked_year_in_a_compact_paragraph():
    quote = "협회(AA)는 다른 단체와 협약을 맺었다.AA는 2004년에 설립됐다."
    assert answer_offset("2004년 설립한 단체는?", quote, "AA") == quote.rfind("AA")


def test_boundary_expert_can_supply_a_shorter_phrase_with_its_own_supporting_clause():
    generated = {"source_id": "S1", "answer": "올해 납부한 법인세", "start": 100, "end": 110}
    expert = {"source_id": "S1", "answer": "법인세", "start": 80, "end": 83,
              "quote": "세목은 법인세였다.", "quote_start": 76, "quote_end": 86}
    assert extractive_reader.refine_boundaries(generated, expert)["quote"] == expert["quote"]
    assert extractive_reader.refine_boundaries(generated, {**expert, "source_id": "S2"}) == generated


def test_refusal_review_respects_explicit_numeric_constraints():
    assert not extractive_reader.supported_quantities("연회비의 5%를 넘으면?", "연회비의 10%를 넘으면 지급한다.")
    assert extractive_reader.supported_quantities("연회비의 5%를 넘으면?", "연회비의 5퍼센트를 넘으면 지급한다.")


@pytest.mark.asyncio
async def test_truncated_local_completion_is_an_error_even_if_the_prefix_appears_in_the_article():
    from app.lib.llm_client import OllamaLLMClient

    model = OllamaLLMClient({})
    client = MagicMock()
    response = MagicMock()
    response.choices = [SimpleNamespace(message=SimpleNamespace(content="[1.1] 동서"), finish_reason="length")]
    response.usage = None
    client.chat.completions.create = AsyncMock(return_value=response)
    model._client = client
    agent = AgentSynthesizer(model, config(implementation="generative"))
    docs = [{"id": "company", "content": "운영사는 동서주식회사다."}]
    state = AgentState("운영사는?", steps=[AgentStep(1, "", [], [ToolResult("x", "search", True, data=docs)])])
    _, sources = await agent.synthesize(state)
    assert state.grounding_status == "error" and not sources
