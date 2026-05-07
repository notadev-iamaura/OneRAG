"""Grok Collections API Retriever.

xAI의 `/v1/documents/search` API를 사용한 검색 전용 Retriever입니다.
관리형(Managed) 하이브리드 검색 서비스로, VectorStore 없이 직접 검색합니다.

주요 특징:
- xAI API를 통한 관리형 검색 (벡터 DB 운영 불필요)
- Collections 기반 keyword/semantic/hybrid 검색
- 검색 전용 (답변 생성은 OneRAG GenerationModule 또는 GrokAnswerProvider가 담당)

의존성:
- httpx: HTTP 비동기 클라이언트
- XAI_API_KEY 환경변수 필요

사용 예시:
    retriever = GrokRetriever(
        api_key="xai-...",
        collection_ids=["col_abc123"],
    )
    results = await retriever.search("OneRAG란 무엇인가?")
"""

import os
from typing import Any

from app.lib.errors import ErrorCode, RetrievalError
from app.lib.logger import get_logger
from app.modules.core.retrieval.interfaces import SearchResult

logger = get_logger(__name__)

# Grok API 설정
GROK_SEARCH_API_URL = "https://api.x.ai/v1/documents/search"
GROK_DEFAULT_MODEL = "grok-3"
GROK_DEFAULT_RETRIEVAL_MODE = "hybrid"


class GrokRetriever:
    """
    Grok Collections API Retriever

    xAI의 관리형 검색 서비스를 통해 문서를 검색합니다.
    Grok의 documents search API를 사용하여 관리형 하이브리드 검색을
    수행합니다.

    특징:
    - IRetriever Protocol 구현 (search, health_check)
    - 검색 전용: add_documents, delete 메서드 미지원
    - 관리형 서비스: 벡터 DB 운영 불필요
    - 하이브리드 검색: xAI 서버에서 자동 처리

    제한사항:
    - 문서 추가/삭제는 GrokCollectionManager 또는 xAI 콘솔에서 관리
    - XAI_API_KEY 환경변수 필수
    - 네트워크 연결 필수 (로컬 모드 불가)
    """

    def __init__(
        self,
        api_key: str | None = None,
        collection_ids: list[str] | None = None,
        model: str = GROK_DEFAULT_MODEL,
        api_url: str = GROK_SEARCH_API_URL,
        timeout: int = 30,
        top_k: int = 10,
        retrieval_mode: str = GROK_DEFAULT_RETRIEVAL_MODE,
        **kwargs: Any,
    ):
        """
        GrokRetriever 초기화

        Args:
            api_key: xAI API 키 (없으면 환경변수 XAI_API_KEY 사용)
            collection_ids: 검색 대상 Collection ID 리스트
            model: 하위 호환용 Grok 모델 이름 (검색 API에서는 사용하지 않음)
            api_url: Grok documents search API 엔드포인트
            timeout: API 호출 타임아웃 (초)
            top_k: 기본 검색 결과 수
            retrieval_mode: keyword, semantic, hybrid 중 하나
            **kwargs: 추가 설정 (RetrieverFactory 호환)
        """
        self.api_key = api_key or os.getenv("XAI_API_KEY", "")
        self.collection_ids = collection_ids or []
        self.model = model
        self.api_url = api_url
        self.timeout = timeout
        self.top_k = top_k
        self.retrieval_mode = retrieval_mode

        if not self.api_key:
            logger.warning(
                "⚠️  XAI_API_KEY가 설정되지 않았습니다. "
                "Grok Collections 검색이 불가능합니다. "
                "API 키 발급: https://console.x.ai"
            )

        # httpx 비동기 클라이언트 (재사용)
        self._client: Any | None = None

        logger.info(
            f"✅ GrokRetriever 초기화: model={model}, collections={len(self.collection_ids)}개"
        )

    async def _get_client(self) -> Any:
        """httpx 비동기 클라이언트 반환 (재사용)"""
        if self._client is None or self._client.is_closed:
            import httpx

            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout, connect=10.0),
                limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
            )
        return self._client

    async def search(
        self,
        query: str,
        top_k: int = 10,
        filters: dict[str, Any] | None = None,
    ) -> list[SearchResult]:
        """
        Grok Collections API로 검색 수행

        xAI의 documents search API로 관리형 검색을 수행합니다.

        Args:
            query: 검색 쿼리
            top_k: 반환할 최대 결과 수
            filters: 메타데이터 필터 (현재 미지원)

        Returns:
            SearchResult 리스트

        Raises:
            RetrievalError: API 호출 실패 시
        """
        if not self.api_key:
            raise RetrievalError(
                message="xAI API 키가 설정되지 않았습니다.",
                error_code=ErrorCode.GROK_001,
                context={"query": query[:100]},
            )

        effective_top_k = top_k or self.top_k
        collection_ids = self._collection_ids_for_search(filters)
        if not collection_ids:
            raise RetrievalError(
                ErrorCode.GROK_003,
                reason="at least one xAI collection ID is required for Grok search",
                query=query[:100],
            )
        client = await self._get_client()

        payload = self._build_search_payload(
            query=query,
            collection_ids=collection_ids,
            top_k=effective_top_k,
            filters=filters,
        )

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        try:
            response = await client.post(
                self.api_url,
                json=payload,
                headers=headers,
            )

            # 속도 제한 (429)
            if response.status_code == 429:
                raise RetrievalError(
                    message="xAI API 속도 제한 초과. 잠시 후 다시 시도해주세요.",
                    error_code=ErrorCode.GROK_002,
                    context={"status_code": 429},
                )

            # 인증 실패 (401/403)
            if response.status_code in (401, 403):
                raise RetrievalError(
                    message="xAI API 인증 실패. XAI_API_KEY를 확인해주세요.",
                    error_code=ErrorCode.GROK_001,
                    context={"status_code": response.status_code},
                )

            response.raise_for_status()
            data = response.json()

            # 응답에서 검색 결과 추출
            results = self._parse_search_results(data, effective_top_k)

            logger.info(f"✅ Grok 검색 완료: query='{query[:50]}', results={len(results)}")

            return results

        except RetrievalError:
            raise
        except Exception as e:
            if e.__class__.__name__ == "TimeoutException":
                raise RetrievalError(
                    ErrorCode.GROK_003,
                    reason=f"xAI API timed out after {self.timeout} seconds",
                    timeout=self.timeout,
                    original_error=e,
                ) from e
            response = getattr(e, "response", None)
            if response is not None and hasattr(response, "status_code"):
                raise RetrievalError(
                    ErrorCode.GROK_003,
                    reason=f"xAI API request failed with status {response.status_code}",
                    status_code=response.status_code,
                    original_error=e,
                ) from e
            raise RetrievalError(
                ErrorCode.GROK_003,
                reason=f"Grok search failed: {e}",
                query=query[:100],
                original_error=e,
            ) from e

    def _collection_ids_for_search(
        self,
        filters: dict[str, Any] | None,
    ) -> list[str]:
        if filters and isinstance(filters.get("collection_ids"), list):
            return filters["collection_ids"]
        return self.collection_ids

    def _build_search_payload(
        self,
        query: str,
        collection_ids: list[str],
        top_k: int,
        filters: dict[str, Any] | None,
    ) -> dict[str, Any]:
        retrieval_mode = self.retrieval_mode
        if filters and filters.get("retrieval_mode"):
            retrieval_mode = filters["retrieval_mode"]

        retrieval_mode_payload = (
            retrieval_mode if isinstance(retrieval_mode, dict) else {"type": retrieval_mode}
        )

        return {
            "query": query,
            "source": {"collection_ids": collection_ids},
            "limit": top_k,
            "retrieval_mode": retrieval_mode_payload,
        }

    def _parse_search_results(
        self,
        response_data: dict[str, Any],
        top_k: int,
    ) -> list[SearchResult]:
        """
        Grok API 응답에서 검색 결과를 추출하여 SearchResult로 변환

        Grok documents search API는 `matches` 배열에 검색 결과를 포함합니다.

        Args:
            response_data: Grok API JSON 응답
            top_k: 최대 반환 수

        Returns:
            SearchResult 리스트
        """
        results: list[SearchResult] = []

        for i, match in enumerate(response_data.get("matches", [])[:top_k]):
            metadata = dict(match.get("metadata") or {})
            metadata["source"] = "grok_collections"
            for key in (
                "collection_id",
                "file_id",
                "document_id",
                "filename",
                "citation",
            ):
                if key in match and match[key] is not None:
                    metadata[key] = match[key]

            content = (
                match.get("content")
                or match.get("text")
                or match.get("chunk", {}).get("text")
                or ""
            )
            score = match.get("score", match.get("relevance_score", 1.0 - i * 0.01))
            result_id = (
                match.get("id") or match.get("document_id") or match.get("file_id") or f"grok-{i}"
            )

            results.append(
                SearchResult(
                    id=str(result_id),
                    content=str(content),
                    score=float(score),
                    metadata=metadata,
                )
            )

        return results

    async def health_check(self) -> bool:
        """
        Grok API 헬스 체크

        간단한 API 호출로 서비스 가용성을 확인합니다.

        Returns:
            서비스 정상 여부
        """
        if not self.api_key:
            return False
        if not self.collection_ids:
            return False

        try:
            client = await self._get_client()
            response = await client.post(
                self.api_url,
                json={
                    "query": "ping",
                    "source": {"collection_ids": self.collection_ids},
                    "limit": 1,
                    "retrieval_mode": {"type": self.retrieval_mode},
                },
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
            )
            return response.status_code == 200
        except Exception:
            return False

    async def close(self) -> None:
        """httpx 클라이언트 정리"""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None
