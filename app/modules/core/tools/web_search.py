# app/modules/core/tools/web_search.py
"""
웹 검색 서비스 모듈

Provider 기반의 웹 검색 서비스를 제공합니다.
Fallback 로직을 통해 여러 검색 Provider를 순차적으로 시도합니다.

Provider 우선순위: Tavily (유료) → Brave (유료) → DuckDuckGo (무료)

주요 컴포넌트:
- WebSearchProvider: 검색 Provider Protocol
- TavilyProvider: Tavily API 기반 검색
- BraveProvider: Brave Search API 기반 검색
- DuckDuckGoProvider: DuckDuckGo 무료 검색
- WebSearchService: Fallback 로직을 포함한 통합 검색 서비스
- web_search(): Agent 도구 함수
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

import httpx

from ....lib.logger import get_logger

logger = get_logger(__name__)


# ========================================
# 데이터 클래스
# ========================================
@dataclass
class WebSearchResult:
    """
    웹 검색 결과 단일 항목

    Args:
        title: 검색 결과 제목
        url: 검색 결과 URL
        content: 검색 결과 내용 (스니펫)
        score: 관련도 점수 (0.0 ~ 1.0)
    """

    title: str
    url: str
    content: str
    score: float = 0.0


@dataclass
class WebSearchResponse:
    """
    웹 검색 응답

    Args:
        results: 검색 결과 목록
        provider: 사용된 검색 Provider 이름
        query: 검색 쿼리
        total_results: 총 결과 수
        answer: AI 생성 답변 (Tavily 등 지원 시)
    """

    results: list[WebSearchResult] = field(default_factory=list)
    provider: str = ""
    query: str = ""
    total_results: int = 0
    answer: str = ""


# ========================================
# WebSearchProvider Protocol
# ========================================
@runtime_checkable
class WebSearchProvider(Protocol):
    """
    웹 검색 Provider Protocol

    모든 검색 Provider가 구현해야 하는 인터페이스를 정의합니다.
    """

    @property
    def name(self) -> str:
        """Provider 이름 반환"""
        ...

    def is_available(self) -> bool:
        """Provider 사용 가능 여부 반환"""
        ...

    async def search(self, query: str, max_results: int = 5) -> WebSearchResponse:
        """검색 수행"""
        ...


# ========================================
# TavilyProvider
# ========================================
class TavilyProvider:
    """
    Tavily 검색 Provider

    Tavily API를 사용한 웹 검색을 제공합니다.
    AI 기반의 고품질 검색 결과와 답변을 제공합니다.
    """

    def __init__(self, api_key: str | None = None) -> None:
        """
        TavilyProvider 초기화

        Args:
            api_key: Tavily API 키 (없으면 Provider 비활성화)
        """
        self._api_key = api_key
        self._client: Any = None

        # API 키가 있으면 클라이언트 초기화
        if api_key:
            try:
                from tavily import TavilyClient

                self._client = TavilyClient(api_key=api_key)
            except ImportError:
                logger.warning("tavily-python 패키지가 설치되지 않았습니다.")
            except Exception as e:
                logger.warning(f"Tavily 클라이언트 초기화 실패: {e}")

    @property
    def name(self) -> str:
        """Provider 이름 반환"""
        return "tavily"

    def is_available(self) -> bool:
        """API 키가 있고 클라이언트가 초기화되었으면 True"""
        return self._api_key is not None and self._client is not None

    async def _call_api(self, query: str, max_results: int) -> dict[str, Any]:
        """
        Tavily API 호출 (비동기 래퍼)

        Tavily의 동기 API를 asyncio executor에서 실행합니다.
        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            lambda: self._client.search(query=query, max_results=max_results),
        )

    async def search(self, query: str, max_results: int = 5) -> WebSearchResponse:
        """
        Tavily로 웹 검색 수행

        Args:
            query: 검색 쿼리
            max_results: 최대 결과 수

        Returns:
            WebSearchResponse: 검색 결과
        """
        if not self.is_available():
            raise RuntimeError("Tavily Provider가 사용 불가능합니다.")

        try:
            response = await self._call_api(query, max_results)
            results = [
                WebSearchResult(
                    title=r.get("title", ""),
                    url=r.get("url", ""),
                    content=r.get("content", ""),
                    score=r.get("score", 0.0),
                )
                for r in response.get("results", [])
            ]

            return WebSearchResponse(
                results=results,
                provider=self.name,
                query=query,
                total_results=len(results),
                answer=response.get("answer", ""),
            )

        except Exception as e:
            logger.error(f"Tavily 검색 실패: {e}")
            raise


# ========================================
# BraveProvider
# ========================================
class BraveProvider:
    """
    Brave Search Provider

    Brave Search API를 사용한 웹 검색을 제공합니다.
    프라이버시 중심의 검색 결과를 제공합니다.
    """

    # Brave Search API 엔드포인트
    _BASE_URL = "https://api.search.brave.com/res/v1/web/search"

    def __init__(self, api_key: str | None = None) -> None:
        """
        BraveProvider 초기화

        Args:
            api_key: Brave Search API 키 (없으면 Provider 비활성화)
        """
        self._api_key = api_key

    @property
    def name(self) -> str:
        """Provider 이름 반환"""
        return "brave"

    def is_available(self) -> bool:
        """API 키가 있으면 True"""
        return self._api_key is not None

    async def _call_api(self, query: str, max_results: int) -> dict[str, Any]:
        """
        Brave Search API 호출

        Args:
            query: 검색 쿼리
            max_results: 최대 결과 수

        Returns:
            API 응답 딕셔너리
        """
        headers = {
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
            "X-Subscription-Token": self._api_key,
        }
        params = {
            "q": query,
            "count": max_results,
        }

        async with httpx.AsyncClient() as client:
            response = await client.get(
                self._BASE_URL,
                headers=headers,
                params=params,
                timeout=30.0,
            )
            response.raise_for_status()
            return response.json()

    async def search(self, query: str, max_results: int = 5) -> WebSearchResponse:
        """
        Brave Search로 웹 검색 수행

        Args:
            query: 검색 쿼리
            max_results: 최대 결과 수

        Returns:
            WebSearchResponse: 검색 결과
        """
        if not self.is_available():
            raise RuntimeError("Brave Provider가 사용 불가능합니다.")

        try:
            response = await self._call_api(query, max_results)
            web_results = response.get("web", {}).get("results", [])

            results = [
                WebSearchResult(
                    title=r.get("title", ""),
                    url=r.get("url", ""),
                    content=r.get("description", ""),
                    score=0.0,  # Brave는 점수를 제공하지 않음
                )
                for r in web_results
            ]

            return WebSearchResponse(
                results=results,
                provider=self.name,
                query=query,
                total_results=len(results),
            )

        except Exception as e:
            logger.error(f"Brave Search 실패: {e}")
            raise


# ========================================
# DuckDuckGoProvider
# ========================================
class DuckDuckGoProvider:
    """
    DuckDuckGo 검색 Provider

    DuckDuckGo API를 사용한 무료 웹 검색을 제공합니다.
    API 키가 필요 없어 항상 사용 가능합니다.
    """

    def __init__(self) -> None:
        """DuckDuckGoProvider 초기화"""
        pass

    @property
    def name(self) -> str:
        """Provider 이름 반환"""
        return "duckduckgo"

    def is_available(self) -> bool:
        """항상 True (API 키 불필요)"""
        return True

    async def _search_ddg(self, query: str, max_results: int) -> list[dict[str, Any]]:
        """
        DuckDuckGo 검색 수행 (비동기 래퍼)

        DuckDuckGo의 동기 API를 asyncio executor에서 실행합니다.
        """
        from duckduckgo_search import DDGS

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            lambda: list(DDGS().text(keywords=query, max_results=max_results)),
        )

    async def search(self, query: str, max_results: int = 5) -> WebSearchResponse:
        """
        DuckDuckGo로 웹 검색 수행

        Args:
            query: 검색 쿼리
            max_results: 최대 결과 수

        Returns:
            WebSearchResponse: 검색 결과
        """
        try:
            ddg_results = await self._search_ddg(query, max_results)

            results = [
                WebSearchResult(
                    title=r.get("title", ""),
                    url=r.get("href", ""),
                    content=r.get("body", ""),
                    score=0.0,  # DuckDuckGo는 점수를 제공하지 않음
                )
                for r in ddg_results
            ]

            return WebSearchResponse(
                results=results,
                provider=self.name,
                query=query,
                total_results=len(results),
            )

        except Exception as e:
            logger.error(f"DuckDuckGo 검색 실패: {e}")
            raise


# ========================================
# WebSearchService
# ========================================
class WebSearchService:
    """
    웹 검색 서비스

    여러 검색 Provider를 관리하고 Fallback 로직을 제공합니다.
    Provider 우선순위: Tavily → Brave → DuckDuckGo
    """

    def __init__(
        self,
        tavily_api_key: str | None = None,
        brave_api_key: str | None = None,
    ) -> None:
        """
        WebSearchService 초기화

        Args:
            tavily_api_key: Tavily API 키
            brave_api_key: Brave Search API 키
        """
        self._tavily_api_key = tavily_api_key
        self._brave_api_key = brave_api_key
        self._providers: list[TavilyProvider | BraveProvider | DuckDuckGoProvider] = []
        self._init_providers()

    def _init_providers(self) -> None:
        """우선순위별 Provider 초기화"""
        # 우선순위 순서로 Provider 추가
        self._providers = [
            TavilyProvider(api_key=self._tavily_api_key),
            BraveProvider(api_key=self._brave_api_key),
            DuckDuckGoProvider(),
        ]

    @property
    def providers(
        self,
    ) -> list[TavilyProvider | BraveProvider | DuckDuckGoProvider]:
        """등록된 Provider 목록 반환"""
        return self._providers

    async def search(self, query: str, max_results: int = 10) -> WebSearchResponse:
        """
        웹 검색 수행 (Fallback 로직 적용)

        가용한 Provider를 순차적으로 시도하여 검색을 수행합니다.
        모든 Provider가 실패하면 예외를 발생시킵니다.

        Args:
            query: 검색 쿼리 (빈 문자열 불가)
            max_results: 최대 결과 수 (기본값: 10)

        Returns:
            WebSearchResponse: 검색 결과

        Raises:
            ValueError: 쿼리가 비어있는 경우
            Exception: 모든 Provider가 실패한 경우
        """
        # 쿼리 유효성 검사
        if not query or not query.strip():
            raise ValueError("검색 쿼리는 필수입니다.")

        errors: list[str] = []

        # 가용한 Provider를 순차적으로 시도
        for provider in self._providers:
            if not provider.is_available():
                logger.debug(f"{provider.name} Provider가 비활성화되어 있습니다.")
                continue

            try:
                logger.info(f"{provider.name}으로 검색 시도: {query}")
                response = await provider.search(query, max_results)
                logger.info(f"{provider.name} 검색 성공: {len(response.results)}개 결과")
                return response

            except Exception as e:
                error_msg = f"{provider.name} 검색 실패: {e}"
                logger.warning(error_msg)
                errors.append(error_msg)
                continue

        # 모든 Provider가 실패한 경우
        error_details = "\n".join(errors)
        raise Exception(f"모든 검색 Provider가 실패했습니다.\n{error_details}")


# ========================================
# web_search() 도구 함수
# ========================================
async def web_search(
    arguments: dict[str, Any],
    global_config: dict[str, Any],
) -> list[dict[str, Any]]:
    """
    Agent용 웹 검색 도구 함수

    LLM Agent가 Tool Use로 호출하는 웹 검색 함수입니다.

    Args:
        arguments: 도구 인자
            - query (str, 필수): 검색 쿼리
            - max_results (int, 선택): 최대 결과 수 (기본값: 10)
        global_config: 전역 설정
            - web_search.tavily_api_key: Tavily API 키
            - web_search.brave_api_key: Brave Search API 키

    Returns:
        list[dict]: 검색 결과 목록
            각 항목: {"title": str, "url": str, "content": str, "score": float}

    Raises:
        ValueError: query 파라미터가 누락되거나 비어있는 경우

    Example:
        >>> result = await web_search(
        ...     {"query": "AI 뉴스", "max_results": 5},
        ...     {"web_search": {"tavily_api_key": "..."}}
        ... )
    """
    # query 파라미터 검증
    query = arguments.get("query", "")
    if not query or not query.strip():
        raise ValueError("query는 필수 파라미터입니다.")

    # max_results 파라미터 (기본값: 10)
    max_results = arguments.get("max_results", 10)

    # 설정에서 API 키 추출
    web_search_config = global_config.get("web_search", {})
    tavily_api_key = web_search_config.get("tavily_api_key")
    brave_api_key = web_search_config.get("brave_api_key")

    # WebSearchService 생성 및 검색 수행
    service = WebSearchService(
        tavily_api_key=tavily_api_key,
        brave_api_key=brave_api_key,
    )
    response = await service.search(query, max_results=max_results)

    # 결과를 딕셔너리 형식으로 변환
    return [
        {
            "title": result.title,
            "url": result.url,
            "content": result.content,
            "score": result.score,
        }
        for result in response.results
    ]


# ========================================
# Module Exports
# ========================================
__all__ = [
    # 데이터 클래스
    "WebSearchResult",
    "WebSearchResponse",
    # Protocol
    "WebSearchProvider",
    # Provider 구현체
    "TavilyProvider",
    "BraveProvider",
    "DuckDuckGoProvider",
    # 서비스
    "WebSearchService",
    # 도구 함수
    "web_search",
]
