"""Mock-based tests for GrokAnswerProvider."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.lib.errors import ErrorCode
from app.modules.core.retrieval.grok_answer_provider import GrokAnswerProvider


@pytest.mark.asyncio
async def test_answer_uses_responses_file_search_payload() -> None:
    provider = GrokAnswerProvider(
        api_key="xai-api-key",
        collection_ids=["collection_1"],
        model="grok-4.20-reasoning",
        top_k=7,
    )

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "output_text": "Grok generated answer.",
        "model": "grok-4.20-reasoning",
        "citations": [
            "collections://collection_1/files/file_1",
        ],
        "usage": {"total_tokens": 42},
        "server_side_tool_usage": {"SERVER_SIDE_TOOL_COLLECTIONS_SEARCH": 1},
    }

    mock_client = AsyncMock()
    mock_client.is_closed = False
    mock_client.post.return_value = mock_response
    provider._client = mock_client

    result = await provider.answer(
        "무엇을 말하나요?",
        system_prompt="Cite sources.",
        include_code_interpreter=True,
    )

    assert result.answer == "Grok generated answer."
    assert result.model_used == "grok-4.20-reasoning"
    assert result.tokens_used == 42
    assert result.citations == ["collections://collection_1/files/file_1"]
    assert result.tool_usage == {"SERVER_SIDE_TOOL_COLLECTIONS_SEARCH": 1}

    call_kwargs = mock_client.post.call_args.kwargs
    assert mock_client.post.call_args.args[0] == "https://api.x.ai/v1/responses"
    assert call_kwargs["json"] == {
        "model": "grok-4.20-reasoning",
        "input": [
            {"role": "system", "content": "Cite sources."},
            {"role": "user", "content": "무엇을 말하나요?"},
        ],
        "tools": [
            {
                "type": "file_search",
                "vector_store_ids": ["collection_1"],
                "max_num_results": 7,
            },
            {"type": "code_interpreter"},
        ],
        "temperature": 0.0,
    }
    assert call_kwargs["headers"] == {
        "Authorization": "Bearer xai-api-key",
        "Content-Type": "application/json",
    }


@pytest.mark.asyncio
async def test_answer_requires_collection_ids() -> None:
    provider = GrokAnswerProvider(api_key="xai-api-key")

    with pytest.raises(Exception) as exc_info:
        await provider.answer("질문")

    assert exc_info.value.error_code == ErrorCode.GROK_003.value


@pytest.mark.asyncio
async def test_answer_auth_failure() -> None:
    provider = GrokAnswerProvider(
        api_key="bad-key",
        collection_ids=["collection_1"],
    )

    mock_response = MagicMock()
    mock_response.status_code = 401
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.is_closed = False
    mock_client.post.return_value = mock_response
    provider._client = mock_client

    with pytest.raises(Exception) as exc_info:
        await provider.answer("질문")

    assert exc_info.value.error_code == ErrorCode.GROK_001.value


def test_parse_output_content_and_annotations() -> None:
    answer, citations = GrokAnswerProvider._parse_answer_and_citations(
        {
            "output": [
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": "본문",
                            "annotations": [{"url": "collections://c/files/f"}],
                        },
                    ],
                },
            ],
        },
    )

    assert answer == "본문"
    assert citations == [{"url": "collections://c/files/f"}]
