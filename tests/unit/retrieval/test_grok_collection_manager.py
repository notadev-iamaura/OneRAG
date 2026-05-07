"""Mock-based tests for GrokCollectionManager."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.lib.errors import ErrorCode
from app.modules.core.retrieval.grok_collection_manager import (
    DOCUMENT_STATUS_PROCESSED,
    GrokCollectionManager,
)


@pytest.mark.asyncio
async def test_upload_document_uses_file_then_collection_attach() -> None:
    manager = GrokCollectionManager(
        api_key="xai-api-key",
        management_api_key="xai-management-key",
    )

    upload_response = MagicMock()
    upload_response.status_code = 200
    upload_response.raise_for_status = MagicMock()
    upload_response.json.return_value = {"id": "file_1", "filename": "doc.txt"}

    attach_response = MagicMock()
    attach_response.status_code = 200
    attach_response.content = b"{}"
    attach_response.raise_for_status = MagicMock()
    attach_response.json.return_value = {"status": DOCUMENT_STATUS_PROCESSED}

    api_client = AsyncMock()
    api_client.is_closed = False
    api_client.post.return_value = upload_response

    management_client = AsyncMock()
    management_client.is_closed = False
    management_client.post.return_value = attach_response

    manager._api_client = api_client
    manager._management_client = management_client

    result = await manager.upload_document(
        collection_id="collection_1",
        data=b"hello",
        filename="doc.txt",
        fields={"title": "Doc"},
        content_type="text/plain",
    )

    assert result["file_metadata"]["id"] == "file_1"
    assert result["document_metadata"]["status"] == DOCUMENT_STATUS_PROCESSED

    upload_call = api_client.post.call_args
    assert upload_call.args[0] == "https://api.x.ai/v1/files"
    assert upload_call.kwargs["data"] == {"purpose": "assistants"}
    assert upload_call.kwargs["files"] == {
        "file": ("doc.txt", b"hello", "text/plain"),
    }
    assert upload_call.kwargs["headers"] == {
        "Authorization": "Bearer xai-api-key",
    }

    attach_call = management_client.post.call_args
    assert (
        attach_call.args[0]
        == "https://management-api.x.ai/v1/collections/collection_1/documents/file_1"
    )
    assert attach_call.kwargs["json"] == {"fields": {"title": "Doc"}}
    assert attach_call.kwargs["headers"] == {
        "Authorization": "Bearer xai-management-key",
        "Content-Type": "application/json",
    }


@pytest.mark.asyncio
async def test_management_key_required_for_collection_create() -> None:
    manager = GrokCollectionManager(api_key="xai-api-key", management_api_key="")

    with pytest.raises(Exception) as exc_info:
        await manager.create_collection("docs")

    assert exc_info.value.error_code == ErrorCode.GROK_001.value


@pytest.mark.asyncio
async def test_wait_for_document_processed_polls_until_ready() -> None:
    manager = GrokCollectionManager(
        api_key="xai-api-key",
        management_api_key="xai-management-key",
    )
    manager.get_document = AsyncMock(
        side_effect=[
            {"status": "DOCUMENT_STATUS_PROCESSING"},
            {"status": DOCUMENT_STATUS_PROCESSED, "file_metadata": {"file_id": "file_1"}},
        ],
    )

    result = await manager.wait_for_document_processed(
        "collection_1",
        "file_1",
        timeout_seconds=1,
        poll_interval_seconds=0,
    )

    assert result["status"] == DOCUMENT_STATUS_PROCESSED
    assert manager.get_document.await_count == 2


@pytest.mark.asyncio
async def test_close_closes_both_clients() -> None:
    manager = GrokCollectionManager(
        api_key="xai-api-key",
        management_api_key="xai-management-key",
    )
    api_client = AsyncMock()
    api_client.is_closed = False
    management_client = AsyncMock()
    management_client.is_closed = False
    manager._api_client = api_client
    manager._management_client = management_client

    await manager.close()

    api_client.aclose.assert_awaited_once()
    management_client.aclose.assert_awaited_once()
    assert manager._api_client is None
    assert manager._management_client is None
