"""A document citation can be published only after the provider completes the answer."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.api.services.chat_service import ChatService
from app.modules.core.generation.citations import AnswerCitations
from app.modules.core.generation.generator import GenerationModule
from app.modules.core.retrieval.interfaces import SearchResult

QUESTION = "마감일은? 정답만."
DOCUMENT = SearchResult("calendar", "금요일에 닫습니다.", 0.9, {"source": "calendar.txt"})
PARTIAL = "EVIDENCE: [S1.1]\nANSWER: 금"
COMPLETE = "EVIDENCE: [S1.1]\nANSWER: 금요일"


@pytest.fixture
def generation(monkeypatch: pytest.MonkeyPatch) -> tuple[GenerationModule, MagicMock]:
    monkeypatch.setattr(GenerationModule, "_load_admin_runtime_settings", lambda self: {})
    module = GenerationModule({"generation": {"fallback_models": []}}, MagicMock())
    provider = MagicMock()
    module.client = provider
    monkeypatch.setattr(module, "_build_prompt", AsyncMock(return_value=("system", "question")))
    return module, provider


def completed_response(text: str, reason: str | None) -> SimpleNamespace:
    choice = SimpleNamespace(message=SimpleNamespace(content=text), finish_reason=reason)
    return SimpleNamespace(choices=[choice], usage=None)


def delta(content: str | None, reason: str | None = None) -> SimpleNamespace:
    choice = SimpleNamespace(delta=SimpleNamespace(content=content), finish_reason=reason)
    return SimpleNamespace(choices=[choice])


def chat_service(module: GenerationModule) -> tuple[ChatService, AsyncMock]:
    session = AsyncMock()
    session.get_session.return_value = {"is_valid": True}
    session.get_context_string.return_value = ""
    retrieval = MagicMock(spec=["search"])
    retrieval.search = AsyncMock(return_value=[DOCUMENT])
    return ChatService({"generation": module, "session": session, "retrieval": retrieval}, {}), session


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", ["length", "content_filter", None])
async def test_document_generation_rejects_incomplete_response(generation, reason):
    module, provider = generation
    provider.chat.completions.create.return_value = completed_response(PARTIAL, reason)
    reader = AnswerCitations(QUESTION)
    with pytest.raises(RuntimeError, match="did not finish"):
        await module.generate_answer(QUESTION, [DOCUMENT], {"_answer_citations": reader})
    assert not reader.citations


@pytest.mark.asyncio
async def test_completed_second_model_verifies_only_its_own_answer(generation):
    module, provider = generation
    module.fallback_models = ["completed-model"]
    provider.chat.completions.create.side_effect = [
        completed_response(PARTIAL, "length"), completed_response(COMPLETE, "stop"),
    ]
    result = await module.generate_answer(QUESTION, [DOCUMENT], {"_answer_citations": AnswerCitations(QUESTION)})
    assert result.answer == "금요일"
    assert result.citation_status == "verified_quotes"
    assert [item.claim for item in result.citations] == ["금요일"]


@pytest.mark.asyncio
async def test_callers_without_document_citations_keep_provider_compatibility(generation):
    module, provider = generation
    provider.chat.completions.create.side_effect = [
        completed_response("기존 응답", None), iter([delta("기존 응답")]),
    ]
    result = await module.generate_answer(QUESTION, [DOCUMENT])
    assert result.answer == "기존 응답" and result.citations is None
    assert [part async for part in module.stream_answer(QUESTION, [DOCUMENT])] == ["기존 응답"]


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", ["length", "content_filter", None, "stop"])
async def test_document_stream_never_publishes_or_persists_unfinished_short_answer(generation, reason):
    module, provider = generation
    stream = [delta(COMPLETE if reason == "stop" else PARTIAL)]
    if reason is not None:
        stream.append(delta(None, reason))
    stream.append(SimpleNamespace(choices=[], usage=SimpleNamespace(total_tokens=9)))
    # The normal service retries a buffered answer once if nothing was visible.
    provider.chat.completions.create.side_effect = [iter(stream), completed_response(PARTIAL, "length")]
    service, session = chat_service(module)
    events = [event async for event in service.stream_rag_pipeline(QUESTION, "test-session")]
    visible = [e["data"] for e in events if e["event"] == "chunk"]
    if reason == "stop":
        assert visible == ["금요일"]
        assert events[-1]["data"]["grounding_status"] == "verified_quotes"
        assert events[-1]["data"]["cited_sources"]
        assert events[-1]["data"]["tokens_used"] == 9
        assert provider.chat.completions.create.call_count == 1
        session.add_conversation.assert_awaited_once()
    else:
        assert not visible
        assert [e["event"] for e in events] == ["metadata", "error"]
        assert provider.chat.completions.create.call_count == 2
        session.add_conversation.assert_not_awaited()


@pytest.mark.asyncio
async def test_prose_interrupted_after_visible_chunk_cannot_finish_or_persist(generation):
    module, provider = generation
    provider.chat.completions.create.return_value = iter([delta("공개된 문장"), delta("금", "length")])
    service, session = chat_service(module)
    events = [event async for event in service.stream_rag_pipeline("마감일을 설명해 주세요.", "test-session")]
    assert [e["event"] for e in events] == ["metadata", "chunk", "error"]
    assert events[1]["data"] == "공개된 문장"
    assert provider.chat.completions.create.call_count == 1
    session.add_conversation.assert_not_awaited()


@pytest.mark.asyncio
async def test_buffered_stream_recovers_only_with_a_completed_retry(generation):
    module, provider = generation
    provider.chat.completions.create.side_effect = [
        iter([delta(PARTIAL), delta(None, "length")]), completed_response(COMPLETE, "stop"),
    ]
    service, session = chat_service(module)
    events = [event async for event in service.stream_rag_pipeline(QUESTION, "test-session")]
    assert [event["event"] for event in events] == ["metadata", "chunk", "done"]
    assert events[1]["data"] == "금요일"
    assert events[-1]["data"]["grounding_status"] == "verified_quotes"
    assert events[-1]["data"]["cited_sources"][0]["additional_metadata"]["citations"][0]["claim"] == "금요일"
    assert session.add_conversation.await_args.args[2] == "금요일"
    assert provider.chat.completions.create.call_count == 2
