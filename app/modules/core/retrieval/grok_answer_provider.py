"""Grok managed RAG answer provider."""

import os
import time
from dataclasses import dataclass
from typing import Any

from app.lib.errors import ErrorCode, RetrievalError
from app.lib.langfuse_client import observe, record_generation

GROK_RESPONSES_API_URL = "https://api.x.ai/v1/responses"
GROK_DEFAULT_MODEL = "grok-3"


@dataclass
class GrokAnswerResult:
    """Normalized result from Grok's managed RAG answer path."""

    answer: str
    model_used: str
    provider: str
    citations: list[Any]
    tokens_used: int
    generation_time: float
    raw_response: dict[str, Any]
    tool_usage: dict[str, Any] | None = None


class GrokAnswerProvider:
    """Generate an answer with Grok using xAI Collections as the retrieval source."""

    def __init__(
        self,
        api_key: str | None = None,
        collection_ids: list[str] | None = None,
        model: str = GROK_DEFAULT_MODEL,
        api_url: str = GROK_RESPONSES_API_URL,
        timeout: int = 60,
        top_k: int = 10,
    ) -> None:
        self.api_key = api_key or os.getenv("XAI_API_KEY", "")
        self.collection_ids = collection_ids or []
        self.model = model
        self.api_url = api_url
        self.timeout = timeout
        self.top_k = top_k
        self._client: Any | None = None

    async def _get_client(self) -> Any:
        if self._client is None or self._client.is_closed:
            import httpx

            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout, connect=10.0),
                limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
            )
        return self._client

    def _headers(self) -> dict[str, str]:
        if not self.api_key:
            raise RetrievalError(
                ErrorCode.GROK_001,
                reason="XAI_API_KEY is required for Grok answer mode.",
            )
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    @observe(
        as_type="generation",
        name="Grok Answer Generation",
        capture_input=False,
        capture_output=False,
    )
    async def answer(
        self,
        question: str,
        collection_ids: list[str] | None = None,
        system_prompt: str | None = None,
        top_k: int | None = None,
        temperature: float = 0.0,
        include_code_interpreter: bool = False,
    ) -> GrokAnswerResult:
        """Ask Grok to search Collections and produce the final answer."""
        selected_collection_ids = collection_ids or self.collection_ids
        if not selected_collection_ids:
            raise RetrievalError(
                ErrorCode.GROK_003,
                reason="at least one xAI collection ID is required for Grok answer mode",
            )

        effective_top_k = top_k or self.top_k
        input_items: list[dict[str, str]] = []
        if system_prompt:
            input_items.append({"role": "system", "content": system_prompt})
        input_items.append({"role": "user", "content": question})

        tools: list[dict[str, Any]] = [
            {
                "type": "file_search",
                "vector_store_ids": selected_collection_ids,
                "max_num_results": effective_top_k,
            },
        ]
        if include_code_interpreter:
            tools.append({"type": "code_interpreter"})

        payload = {
            "model": self.model,
            "input": input_items,
            "tools": tools,
            "temperature": temperature,
        }

        start = time.perf_counter()
        client = await self._get_client()
        try:
            response = await client.post(
                self.api_url,
                json=payload,
                headers=self._headers(),
            )
            self._raise_for_status(response, "grok_answer")
            data = response.json()
        except RetrievalError:
            raise
        except Exception as exc:
            if exc.__class__.__name__ == "TimeoutException":
                raise RetrievalError(
                    ErrorCode.GROK_003,
                    reason=f"xAI Responses API timed out after {self.timeout} seconds",
                ) from exc
            raise RetrievalError(
                ErrorCode.GROK_003,
                reason=f"Grok answer request failed: {exc}",
            ) from exc

        generation_time = time.perf_counter() - start
        answer_text, citations = self._parse_answer_and_citations(data)
        usage = data.get("usage") or {}
        tokens_used = int(usage.get("total_tokens") or usage.get("output_tokens") or 0)

        # Grok 답변 생성 LLM 호출의 토큰/비용을 Langfuse generation으로 기록.
        # xAI Responses API는 input/output_tokens를 쓰며, prompt/completion_tokens 폴백을 둔다.
        record_generation(
            model=data.get("model", self.model),
            prompt_tokens=int(usage.get("input_tokens") or usage.get("prompt_tokens") or 0),
            completion_tokens=int(usage.get("output_tokens") or usage.get("completion_tokens") or 0),
            total_tokens=int(usage.get("total_tokens") or 0),
            model_parameters={"temperature": temperature},
        )

        return GrokAnswerResult(
            answer=answer_text,
            model_used=data.get("model", self.model),
            provider="grok",
            citations=citations,
            tokens_used=tokens_used,
            generation_time=generation_time,
            raw_response=data,
            tool_usage=(
                data.get("server_side_tool_usage") or data.get("tool_usage") or data.get("tools")
            ),
        )

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

    @staticmethod
    def _parse_answer_and_citations(
        response_data: dict[str, Any],
    ) -> tuple[str, list[Any]]:
        if response_data.get("output_text"):
            return str(response_data["output_text"]), response_data.get("citations", [])

        answer_parts: list[str] = []
        citations: list[Any] = list(response_data.get("citations", []))

        for output_item in response_data.get("output", []):
            for content_item in output_item.get("content", []):
                content_type = content_item.get("type")
                if content_type in {"output_text", "text"}:
                    text = content_item.get("text", "")
                    if text:
                        answer_parts.append(text)
                    annotations = content_item.get("annotations", [])
                    if annotations:
                        citations.extend(annotations)

        return "\n".join(answer_parts).strip(), citations

    async def health_check(self) -> bool:
        """Return whether the provider has enough local config to make requests."""
        return bool(self.api_key and self.collection_ids)

    async def close(self) -> None:
        """Close reusable HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
        self._client = None
