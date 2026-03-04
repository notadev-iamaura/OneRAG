"""
Grok Collections API Retriever

xAI의 Grok Collections API를 사용한 검색 전용 Retriever입니다.
관리형(Managed) 하이브리드 검색 서비스로, VectorStore 없이 직접 검색합니다.

주요 특징:
- xAI API를 통한 관리형 검색 (벡터 DB 운영 불필요)
- Collections 기반 자동 하이브리드 검색
- 검색 전용 (문서 추가/삭제는 xAI 콘솔에서 관리)

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

import httpx

from app.lib.errors import ErrorCode, RetrievalError
from app.lib.logger import get_logger
from app.modules.core.retrieval.interfaces import SearchResult

logger = get_logger(__name__)

# Grok API 설정
GROK_API_URL = "https://api.x.ai/v1/chat/completions"
GROK_DEFAULT_MODEL = "grok-3"


class GrokRetriever:
    """
    Grok Collections API Retriever

    xAI의 관리형 검색 서비스를 통해 문서를 검색합니다.
    Grok의 chat/completions API에 collections_search 도구를 사용하여
    관리형 하이브리드 검색을 수행합니다.

    특징:
    - IRetriever Protocol 구현 (search, health_check)
    - 검색 전용: add_documents, delete 메서드 미지원
    - 관리형 서비스: 벡터 DB 운영 불필요
    - 하이브리드 검색: xAI 서버에서 자동 처리

    제한사항:
    - 문서 추가/삭제는 xAI 콘솔에서 관리
    - XAI_API_KEY 환경변수 필수
    - 네트워크 연결 필수 (로컬 모드 불가)
    """

    def __init__(
        self,
        api_key: str | None = None,
        collection_ids: list[str] | None = None,
        model: str = GROK_DEFAULT_MODEL,
        api_url: str = GROK_API_URL,
        timeout: int = 30,
        top_k: int = 10,
        **kwargs: Any,
    ):
        """
        GrokRetriever 초기화

        Args:
            api_key: xAI API 키 (없으면 환경변수 XAI_API_KEY 사용)
            collection_ids: 검색 대상 Collection ID 리스트
            model: Grok 모델 이름 (기본: grok-3)
            api_url: Grok API 엔드포인트
            timeout: API 호출 타임아웃 (초)
            top_k: 기본 검색 결과 수
            **kwargs: 추가 설정 (RetrieverFactory 호환)
        """
        self.api_key = api_key or os.getenv("XAI_API_KEY", "")
        self.collection_ids = collection_ids or []
        self.model = model
        self.api_url = api_url
        self.timeout = timeout
        self.top_k = top_k

        if not self.api_key:
            logger.warning(
                "⚠️  XAI_API_KEY가 설정되지 않았습니다. "
                "Grok Collections 검색이 불가능합니다. "
                "API 키 발급: https://console.x.ai"
            )

        # httpx 비동기 클라이언트 (재사용)
        self._client: httpx.AsyncClient | None = None

        logger.info(
            f"✅ GrokRetriever 초기화: model={model}, "
            f"collections={len(self.collection_ids)}개"
        )

    async def _get_client(self) -> httpx.AsyncClient:
        """httpx 비동기 클라이언트 반환 (재사용)"""
        if self._client is None or self._client.is_closed:
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

        xAI의 chat/completions API에 collections_search 도구를 사용하여
        관리형 하이브리드 검색을 수행합니다.

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
        client = await self._get_client()

        # Grok Collections API 요청 구성
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "user", "content": query},
            ],
            "tools": [
                {
                    "type": "collections_search",
                    "collection_ids": self.collection_ids,
                },
            ],
            "temperature": 0.0,
        }

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

            logger.info(
                f"✅ Grok 검색 완료: query='{query[:50]}', "
                f"results={len(results)}"
            )

            return results

        except RetrievalError:
            raise
        except httpx.TimeoutException as e:
            raise RetrievalError(
                message=f"xAI API 타임아웃 ({self.timeout}초)",
                error_code=ErrorCode.GROK_003,
                context={"timeout": self.timeout},
                original_error=e,
            ) from e
        except httpx.HTTPStatusError as e:
            raise RetrievalError(
                message=f"xAI API 요청 실패: {e.response.status_code}",
                error_code=ErrorCode.GROK_003,
                context={"status_code": e.response.status_code},
                original_error=e,
            ) from e
        except Exception as e:
            raise RetrievalError(
                message=f"Grok 검색 중 오류 발생: {e}",
                error_code=ErrorCode.GROK_003,
                context={"query": query[:100]},
                original_error=e,
            ) from e

    def _parse_search_results(
        self, response_data: dict[str, Any], top_k: int,
    ) -> list[SearchResult]:
        """
        Grok API 응답에서 검색 결과를 추출하여 SearchResult로 변환

        Grok Collections API는 검색 결과를 tool_call 응답에 포함시킵니다.
        검색 결과가 없는 경우 LLM 응답에서 컨텍스트를 추출합니다.

        Args:
            response_data: Grok API JSON 응답
            top_k: 최대 반환 수

        Returns:
            SearchResult 리스트
        """
        results: list[SearchResult] = []

        choices = response_data.get("choices", [])
        if not choices:
            return results

        message = choices[0].get("message", {})

        # 1. tool_calls에서 검색 결과 추출
        tool_calls = message.get("tool_calls", [])
        for tool_call in tool_calls:
            if tool_call.get("type") == "collections_search":
                search_results = tool_call.get("results", [])
                for i, sr in enumerate(search_results[:top_k]):
                    # 원본 메타데이터에 grok 소스 정보 병합 (source 키 보장)
                    merged_metadata = {
                        **sr.get("metadata", {}),
                        "source": "grok_collections",
                        "collection_id": sr.get("collection_id", ""),
                    }
                    results.append(SearchResult(
                        id=sr.get("id", f"grok-{i}"),
                        content=sr.get("content", sr.get("text", "")),
                        score=float(sr.get("score", sr.get("relevance_score", 1.0 - i * 0.1))),
                        metadata=merged_metadata,
                    ))

        # 2. 검색 결과가 없으면 LLM 응답을 단일 결과로 반환
        if not results and message.get("content"):
            content = message["content"]
            if content.strip():
                results.append(SearchResult(
                    id="grok-llm-response",
                    content=content,
                    score=1.0,
                    metadata={
                        "source": "grok_llm",
                        "model": self.model,
                    },
                ))

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

        try:
            client = await self._get_client()
            # 간단한 완료 요청으로 API 가용성 확인
            response = await client.post(
                self.api_url,
                json={
                    "model": self.model,
                    "messages": [{"role": "user", "content": "ping"}],
                    "max_tokens": 1,
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
