# tests/integration/test_web_search_e2e.py
"""
웹 검색 E2E 테스트

실제 API를 호출하여 웹 검색 기능이 정상 동작하는지 검증합니다.
DuckDuckGo는 API 키 불필요하므로 항상 테스트 가능합니다.

주의: 이 테스트는 실제 네트워크 요청을 수행합니다.
"""
import pytest

from app.modules.core.tools.web_search import (
    DuckDuckGoProvider,
    WebSearchResponse,
    WebSearchService,
    web_search,
)


class TestWebSearchE2E:
    """웹 검색 E2E 테스트"""

    @pytest.mark.asyncio
    async def test_duckduckgo_real_search(self):
        """DuckDuckGo 실제 검색 테스트 (API 키 불필요)"""
        provider = DuckDuckGoProvider()

        # 실제 검색 수행
        response = await provider.search("Python programming", max_results=3)

        # 검증
        assert isinstance(response, WebSearchResponse)
        assert response.provider == "duckduckgo"
        assert len(response.results) >= 1  # 최소 1개 결과
        assert response.results[0].title  # 제목이 있어야 함
        assert response.results[0].url  # URL이 있어야 함

    @pytest.mark.asyncio
    async def test_web_search_service_fallback_to_duckduckgo(self):
        """WebSearchService가 DuckDuckGo로 Fallback하는지 테스트"""
        # API 키 없이 서비스 생성 (DuckDuckGo만 사용 가능)
        service = WebSearchService(
            tavily_api_key=None,
            brave_api_key=None,
        )

        # 실제 검색 수행
        response = await service.search("RAG system", max_results=3)

        # 검증 - DuckDuckGo로 Fallback되어야 함
        assert response.provider == "duckduckgo"
        assert len(response.results) >= 1

    @pytest.mark.asyncio
    async def test_web_search_tool_function(self):
        """web_search() 도구 함수 E2E 테스트"""
        arguments = {
            "query": "FastAPI tutorial",
            "max_results": 3,
        }
        global_config = {
            "web_search": {
                "tavily_api_key": None,
                "brave_api_key": None,
            }
        }

        # 실제 검색 수행
        results = await web_search(arguments, global_config)

        # 검증
        assert isinstance(results, list)
        assert len(results) >= 1
        assert "title" in results[0]
        assert "url" in results[0]
        assert "content" in results[0]

    @pytest.mark.asyncio
    async def test_korean_query_search(self):
        """한국어 검색 쿼리 테스트"""
        service = WebSearchService()

        # 한국어 검색
        response = await service.search("인공지능 뉴스", max_results=3)

        # 검증
        assert response.provider == "duckduckgo"
        assert len(response.results) >= 1

    @pytest.mark.asyncio
    async def test_empty_query_raises_error(self):
        """빈 쿼리 시 에러 발생 테스트"""
        service = WebSearchService()

        with pytest.raises(ValueError, match="검색 쿼리는 필수입니다"):
            await service.search("")

    @pytest.mark.asyncio
    async def test_whitespace_query_raises_error(self):
        """공백만 있는 쿼리 시 에러 발생 테스트"""
        service = WebSearchService()

        with pytest.raises(ValueError, match="검색 쿼리는 필수입니다"):
            await service.search("   ")


class TestProviderAvailability:
    """Provider 가용성 테스트"""

    def test_duckduckgo_always_available(self):
        """DuckDuckGo는 항상 사용 가능"""
        provider = DuckDuckGoProvider()
        assert provider.is_available() is True
        assert provider.name == "duckduckgo"

    def test_service_provider_order(self):
        """Provider 우선순위 확인"""
        # API 키 모두 제공
        service = WebSearchService(
            tavily_api_key="test-tavily",
            brave_api_key="test-brave",
        )

        # 순서 확인: Tavily -> Brave -> DuckDuckGo
        assert service.providers[0].name == "tavily"
        assert service.providers[1].name == "brave"
        assert service.providers[2].name == "duckduckgo"

    def test_service_without_paid_providers(self):
        """유료 Provider 없이도 동작"""
        service = WebSearchService()

        # DuckDuckGo만 사용 가능
        available_providers = [p for p in service.providers if p.is_available()]
        assert len(available_providers) == 1
        assert available_providers[0].name == "duckduckgo"
