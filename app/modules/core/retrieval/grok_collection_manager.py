"""xAI Collection lifecycle helper for Grok managed RAG."""

import asyncio
import os
from typing import Any

from app.lib.errors import ErrorCode, RetrievalError

GROK_API_BASE_URL = "https://api.x.ai/v1"
GROK_MANAGEMENT_API_BASE_URL = "https://management-api.x.ai/v1"
DOCUMENT_STATUS_PROCESSED = "DOCUMENT_STATUS_PROCESSED"
DOCUMENT_STATUS_FAILED = "DOCUMENT_STATUS_FAILED"


class GrokCollectionManager:
    """Manage xAI Collections without registering Grok as a VectorStore."""

    def __init__(
        self,
        api_key: str | None = None,
        management_api_key: str | None = None,
        api_base_url: str = GROK_API_BASE_URL,
        management_api_base_url: str = GROK_MANAGEMENT_API_BASE_URL,
        timeout: int = 30,
    ) -> None:
        self.api_key = api_key or os.getenv("XAI_API_KEY", "")
        self.management_api_key = management_api_key or os.getenv("XAI_MANAGEMENT_API_KEY", "")
        self.api_base_url = api_base_url.rstrip("/")
        self.management_api_base_url = management_api_base_url.rstrip("/")
        self.timeout = timeout
        self._api_client: Any | None = None
        self._management_client: Any | None = None

    async def _get_api_client(self) -> Any:
        if self._api_client is None or self._api_client.is_closed:
            import httpx

            self._api_client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout, connect=10.0),
                limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
            )
        return self._api_client

    async def _get_management_client(self) -> Any:
        if self._management_client is None or self._management_client.is_closed:
            import httpx

            self._management_client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout, connect=10.0),
                limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
            )
        return self._management_client

    def _api_headers(self) -> dict[str, str]:
        if not self.api_key:
            raise RetrievalError(
                ErrorCode.GROK_001,
                reason="XAI_API_KEY is required for xAI file upload/search calls.",
            )
        return {"Authorization": f"Bearer {self.api_key}"}

    def _management_headers(self) -> dict[str, str]:
        if not self.management_api_key:
            raise RetrievalError(
                ErrorCode.GROK_001,
                reason=("XAI_MANAGEMENT_API_KEY is required for xAI Collection management calls."),
            )
        return {"Authorization": f"Bearer {self.management_api_key}"}

    @staticmethod
    def _raise_for_status(response: Any, operation: str) -> None:
        if response.status_code in (401, 403):
            raise RetrievalError(
                ErrorCode.GROK_001,
                reason=f"{operation} authentication failed.",
                status_code=response.status_code,
            )
        if response.status_code == 429:
            raise RetrievalError(
                ErrorCode.GROK_002,
                reason=f"{operation} rate limited.",
                status_code=429,
            )
        try:
            response.raise_for_status()
        except Exception as exc:
            raise RetrievalError(
                ErrorCode.GROK_003,
                reason=f"{operation} failed with status {response.status_code}.",
                status_code=response.status_code,
            ) from exc

    async def create_collection(
        self,
        collection_name: str,
        collection_description: str | None = None,
        index_configuration: dict[str, Any] | None = None,
        field_definitions: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Create an xAI Collection through the Management API."""
        payload: dict[str, Any] = {"collection_name": collection_name}
        if collection_description:
            payload["collection_description"] = collection_description
        if index_configuration is not None:
            payload["index_configuration"] = index_configuration
        if field_definitions is not None:
            payload["field_definitions"] = field_definitions

        headers = {**self._management_headers(), "Content-Type": "application/json"}
        client = await self._get_management_client()
        response = await client.post(
            f"{self.management_api_base_url}/collections",
            json=payload,
            headers=headers,
        )
        self._raise_for_status(response, "create_collection")
        return response.json()

    async def list_collections(
        self,
        limit: int = 100,
        order: str | None = None,
        pagination_token: str | None = None,
        filter_expression: str | None = None,
    ) -> dict[str, Any]:
        """List xAI Collections visible to the management key."""
        params: dict[str, Any] = {"limit": limit}
        if order:
            params["order"] = order
        if pagination_token:
            params["pagination_token"] = pagination_token
        if filter_expression:
            params["filter"] = filter_expression

        headers = self._management_headers()
        client = await self._get_management_client()
        response = await client.get(
            f"{self.management_api_base_url}/collections",
            params=params,
            headers=headers,
        )
        self._raise_for_status(response, "list_collections")
        return response.json()

    async def get_collection(self, collection_id: str) -> dict[str, Any]:
        """Get metadata for one xAI Collection."""
        headers = self._management_headers()
        client = await self._get_management_client()
        response = await client.get(
            f"{self.management_api_base_url}/collections/{collection_id}",
            headers=headers,
        )
        self._raise_for_status(response, "get_collection")
        return response.json()

    async def delete_collection(self, collection_id: str) -> dict[str, Any]:
        """Delete an xAI Collection."""
        headers = self._management_headers()
        client = await self._get_management_client()
        response = await client.delete(
            f"{self.management_api_base_url}/collections/{collection_id}",
            headers=headers,
        )
        self._raise_for_status(response, "delete_collection")
        return response.json() if response.content else {"deleted": True}

    async def upload_file(
        self,
        data: bytes,
        filename: str,
        purpose: str = "assistants",
        content_type: str = "application/octet-stream",
    ) -> dict[str, Any]:
        """Upload a file to xAI Files API and return its metadata."""
        headers = self._api_headers()
        client = await self._get_api_client()
        response = await client.post(
            f"{self.api_base_url}/files",
            data={"purpose": purpose},
            files={"file": (filename, data, content_type)},
            headers=headers,
        )
        self._raise_for_status(response, "upload_file")
        return response.json()

    async def add_file_to_collection(
        self,
        collection_id: str,
        file_id: str,
        fields: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Attach an existing xAI file to a Collection."""
        headers = self._management_headers()
        kwargs: dict[str, Any] = {
            "headers": headers,
        }
        if fields is not None:
            kwargs["json"] = {"fields": fields}
            kwargs["headers"] = {
                **kwargs["headers"],
                "Content-Type": "application/json",
            }

        client = await self._get_management_client()
        response = await client.post(
            (f"{self.management_api_base_url}/collections/{collection_id}/documents/{file_id}"),
            **kwargs,
        )
        self._raise_for_status(response, "add_file_to_collection")
        return response.json() if response.content else {"file_id": file_id}

    async def upload_document(
        self,
        collection_id: str,
        data: bytes,
        filename: str,
        fields: dict[str, Any] | None = None,
        content_type: str = "application/octet-stream",
    ) -> dict[str, Any]:
        """Upload a file, then attach it to a Collection."""
        file_metadata = await self.upload_file(
            data=data,
            filename=filename,
            content_type=content_type,
        )
        file_id = file_metadata["id"]
        document_metadata = await self.add_file_to_collection(
            collection_id=collection_id,
            file_id=file_id,
            fields=fields,
        )
        return {
            "file_metadata": file_metadata,
            "document_metadata": document_metadata,
        }

    async def list_documents(
        self,
        collection_id: str,
        limit: int = 100,
        order: str | None = None,
        pagination_token: str | None = None,
    ) -> dict[str, Any]:
        """List documents attached to a Collection."""
        params: dict[str, Any] = {"limit": limit}
        if order:
            params["order"] = order
        if pagination_token:
            params["pagination_token"] = pagination_token

        headers = self._management_headers()
        client = await self._get_management_client()
        response = await client.get(
            f"{self.management_api_base_url}/collections/{collection_id}/documents",
            params=params,
            headers=headers,
        )
        self._raise_for_status(response, "list_documents")
        return response.json()

    async def get_document(
        self,
        collection_id: str,
        file_id: str,
    ) -> dict[str, Any]:
        """Get metadata for one Collection document."""
        headers = self._management_headers()
        client = await self._get_management_client()
        response = await client.get(
            (f"{self.management_api_base_url}/collections/{collection_id}/documents/{file_id}"),
            headers=headers,
        )
        self._raise_for_status(response, "get_document")
        return response.json()

    async def remove_document(
        self,
        collection_id: str,
        file_id: str,
    ) -> dict[str, Any]:
        """Remove a document from a Collection."""
        headers = self._management_headers()
        client = await self._get_management_client()
        response = await client.delete(
            (f"{self.management_api_base_url}/collections/{collection_id}/documents/{file_id}"),
            headers=headers,
        )
        self._raise_for_status(response, "remove_document")
        return response.json() if response.content else {"removed": True, "id": file_id}

    async def wait_for_document_processed(
        self,
        collection_id: str,
        file_id: str,
        timeout_seconds: int = 120,
        poll_interval_seconds: float = 3.0,
    ) -> dict[str, Any]:
        """Poll a Collection document until it is processed or failed."""
        deadline = asyncio.get_running_loop().time() + timeout_seconds
        while True:
            document = await self.get_document(collection_id, file_id)
            status = document.get("status")
            if status == DOCUMENT_STATUS_PROCESSED:
                return document
            if status == DOCUMENT_STATUS_FAILED:
                raise RetrievalError(
                    ErrorCode.GROK_003,
                    reason=document.get("error_message", "document processing failed"),
                    collection_id=collection_id,
                    file_id=file_id,
                )
            if asyncio.get_running_loop().time() >= deadline:
                raise RetrievalError(
                    ErrorCode.GROK_003,
                    reason="timed out waiting for xAI document processing",
                    collection_id=collection_id,
                    file_id=file_id,
                    status=status,
                )
            await asyncio.sleep(poll_interval_seconds)

    async def close(self) -> None:
        """Close reusable HTTP clients."""
        if self._api_client and not self._api_client.is_closed:
            await self._api_client.aclose()
        if self._management_client and not self._management_client.is_closed:
            await self._management_client.aclose()
        self._api_client = None
        self._management_client = None
