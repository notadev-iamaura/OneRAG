# tests/unit/modules/core/tools/test_web_search.py
"""
웹 검색 서비스 테스트

TDD Red 단계: 웹 검색 서비스의 인터페이스와 구현체를 테스트합니다.
- WebSearchProvider Protocol 테스트
- WebSearchResult, WebSearchResponse 데이터클래스 테스트
- Tavily, Brave, DuckDuckGo Provider 테스트
- WebSearchService Fallback 로직 테스트
- web_search() Agent 도구 함수 테스트

Provider 우선순위: Tavily (유료) → Brave (유료) → DuckDuckGo (무료)
"""
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ========================================
# 1. TestWebSearchProviderInterface
# ========================================
class TestWebSearchProviderInterface:
    """WebSearchProvider Protocol 및 데이터클래스 테스트"""

    def test_web_search_provider_protocol(self) -> None:
        """WebSearchProvider Protocol이 존재하는지 확인"""
        from app.modules.core.tools.web_search import WebSearchProvider

        # Protocol이 존재하고 필수 메서드를 정의하는지 확인
        assert WebSearchProvider is not None
        # Protocol은 runtime_checkable이어야 함
        assert hasattr(WebSearchProvider, "__protocol_attrs__") or hasattr(
            WebSearchProvider, "_is_protocol"
        )

    def test_web_search_result_dataclass(self) -> None:
        """WebSearchResult 데이터클래스가 올바른 필드를 가지는지 확인"""
        from app.modules.core.tools.web_search import WebSearchResult

        # 데이터클래스 인스턴스 생성
        result = WebSearchResult(
            title="테스트 제목",
            url="https://example.com",
            content="테스트 내용",
            score=0.95,
        )

        assert result.title == "테스트 제목"
        assert result.url == "https://example.com"
        assert result.content == "테스트 내용"
        assert result.score == 0.95

    def test_web_search_result_optional_fields(self) -> None:
        """WebSearchResult 선택적 필드 테스트"""
        from app.modules.core.tools.web_search import WebSearchResult

        # 최소 필드만으로 생성
        result = WebSearchResult(
            title="제목",
            url="https://test.com",
            content="내용",
        )

        # score는 선택적이며 기본값은 0.0이어야 함
        assert result.score == 0.0

    def test_web_search_response_dataclass(self) -> None:
        """WebSearchResponse 데이터클래스가 올바른 필드를 가지는지 확인"""
        from app.modules.core.tools.web_search import WebSearchResponse, WebSearchResult

        # 검색 결과 목록 생성
        results = [
            WebSearchResult(
                title="결과 1",
                url="https://example1.com",
                content="내용 1",
                score=0.9,
            ),
            WebSearchResult(
                title="결과 2",
                url="https://example2.com",
                content="내용 2",
                score=0.8,
            ),
        ]

        # WebSearchResponse 생성
        response = WebSearchResponse(
            results=results,
            provider="tavily",
            query="테스트 쿼리",
            total_results=2,
        )

        assert len(response.results) == 2
        assert response.provider == "tavily"
        assert response.query == "테스트 쿼리"
        assert response.total_results == 2


# ========================================
# 2. TestTavilyProvider
# ========================================
class TestTavilyProvider:
    """Tavily 검색 Provider 테스트"""

    @pytest.mark.asyncio
    async def test_tavily_search_success(self) -> None:
        """Mock으로 Tavily 검색 성공 테스트"""
        from app.modules.core.tools.web_search import TavilyProvider

        # Tavily API 응답 Mock
        mock_response = {
            "results": [
                {
                    "title": "Tavily 검색 결과",
                    "url": "https://tavily.com/result",
                    "content": "Tavily에서 검색된 내용입니다.",
                    "score": 0.95,
                }
            ]
        }

        with patch.object(
            TavilyProvider, "_call_api", new_callable=AsyncMock
        ) as mock_api:
            mock_api.return_value = mock_response

            provider = TavilyProvider(api_key="test-api-key")
            response = await provider.search("테스트 쿼리", max_results=5)

            assert len(response.results) == 1
            assert response.results[0].title == "Tavily 검색 결과"
            assert response.provider == "tavily"

    def test_tavily_not_available_without_key(self) -> None:
        """API 키가 없으면 is_available()이 False를 반환하는지 테스트"""
        from app.modules.core.tools.web_search import TavilyProvider

        # API 키 없이 생성
        provider = TavilyProvider(api_key=None)

        assert provider.is_available() is False

    def test_tavily_available_with_key(self) -> None:
        """API 키가 있으면 is_available()이 True를 반환하는지 테스트"""
        from app.modules.core.tools.web_search import TavilyProvider

        # API 키와 함께 생성
        provider = TavilyProvider(api_key="test-api-key")

        assert provider.is_available() is True

    def test_tavily_provider_name(self) -> None:
        """name 속성이 'tavily'를 반환하는지 테스트"""
        from app.modules.core.tools.web_search import TavilyProvider

        provider = TavilyProvider(api_key="test-key")

        assert provider.name == "tavily"


# ========================================
# 3. TestBraveProvider
# ========================================
class TestBraveProvider:
    """Brave 검색 Provider 테스트"""

    @pytest.mark.asyncio
    async def test_brave_search_success(self) -> None:
        """Mock으로 Brave 검색 성공 테스트"""
        from app.modules.core.tools.web_search import BraveProvider

        # Brave API 응답 Mock
        mock_response = {
            "web": {
                "results": [
                    {
                        "title": "Brave 검색 결과",
                        "url": "https://brave.com/result",
                        "description": "Brave에서 검색된 내용입니다.",
                    }
                ]
            }
        }

        with patch.object(
            BraveProvider, "_call_api", new_callable=AsyncMock
        ) as mock_api:
            mock_api.return_value = mock_response

            provider = BraveProvider(api_key="test-api-key")
            response = await provider.search("테스트 쿼리", max_results=5)

            assert len(response.results) == 1
            assert response.results[0].title == "Brave 검색 결과"
            assert response.provider == "brave"

    def test_brave_not_available_without_key(self) -> None:
        """API 키가 없으면 is_available()이 False를 반환하는지 테스트"""
        from app.modules.core.tools.web_search import BraveProvider

        # API 키 없이 생성
        provider = BraveProvider(api_key=None)

        assert provider.is_available() is False

    def test_brave_available_with_key(self) -> None:
        """API 키가 있으면 is_available()이 True를 반환하는지 테스트"""
        from app.modules.core.tools.web_search import BraveProvider

        # API 키와 함께 생성
        provider = BraveProvider(api_key="test-api-key")

        assert provider.is_available() is True

    def test_brave_provider_name(self) -> None:
        """name 속성이 'brave'를 반환하는지 테스트"""
        from app.modules.core.tools.web_search import BraveProvider

        provider = BraveProvider(api_key="test-key")

        assert provider.name == "brave"


# ========================================
# 4. TestDuckDuckGoProvider
# ========================================
class TestDuckDuckGoProvider:
    """DuckDuckGo 검색 Provider 테스트"""

    @pytest.mark.asyncio
    async def test_duckduckgo_search_success(self) -> None:
        """Mock으로 DuckDuckGo 검색 성공 테스트"""
        from app.modules.core.tools.web_search import DuckDuckGoProvider

        # DuckDuckGo 검색 결과 Mock
        mock_results = [
            {
                "title": "DuckDuckGo 검색 결과",
                "href": "https://duckduckgo.com/result",
                "body": "DuckDuckGo에서 검색된 내용입니다.",
            }
        ]

        with patch.object(
            DuckDuckGoProvider, "_search_ddg", new_callable=AsyncMock
        ) as mock_search:
            mock_search.return_value = mock_results

            provider = DuckDuckGoProvider()
            response = await provider.search("테스트 쿼리", max_results=5)

            assert len(response.results) == 1
            assert response.results[0].title == "DuckDuckGo 검색 결과"
            assert response.provider == "duckduckgo"

    def test_duckduckgo_always_available(self) -> None:
        """API 키 없이도 항상 is_available()이 True를 반환하는지 테스트"""
        from app.modules.core.tools.web_search import DuckDuckGoProvider

        # API 키 없이 생성 (DuckDuckGo는 API 키 불필요)
        provider = DuckDuckGoProvider()

        # 항상 사용 가능
        assert provider.is_available() is True

    def test_duckduckgo_provider_name(self) -> None:
        """name 속성이 'duckduckgo'를 반환하는지 테스트"""
        from app.modules.core.tools.web_search import DuckDuckGoProvider

        provider = DuckDuckGoProvider()

        assert provider.name == "duckduckgo"


# ========================================
# 5. TestWebSearchService
# ========================================
class TestWebSearchService:
    """WebSearchService Fallback 로직 테스트"""

    def test_provider_initialization_order(self) -> None:
        """Provider 초기화 순서 확인 (Tavily -> Brave -> DDG)"""
        from app.modules.core.tools.web_search import WebSearchService

        # 모든 API 키가 있는 경우
        service = WebSearchService(
            tavily_api_key="tavily-key",
            brave_api_key="brave-key",
        )

        # Provider 순서 확인
        provider_names = [p.name for p in service.providers]
        assert provider_names == ["tavily", "brave", "duckduckgo"]

    def test_provider_initialization_without_tavily(self) -> None:
        """Tavily 키 없을 때 Provider 순서 확인"""
        from app.modules.core.tools.web_search import WebSearchService

        service = WebSearchService(
            tavily_api_key=None,
            brave_api_key="brave-key",
        )

        # Tavily는 있지만 사용 불가
        available_providers = [p.name for p in service.providers if p.is_available()]
        assert "tavily" not in available_providers
        assert "brave" in available_providers
        assert "duckduckgo" in available_providers

    @pytest.mark.asyncio
    async def test_fallback_to_second_provider(self) -> None:
        """1순위 Provider 실패 시 2순위로 Fallback 테스트"""
        from app.modules.core.tools.web_search import (
            WebSearchResponse,
            WebSearchResult,
            WebSearchService,
        )

        service = WebSearchService(
            tavily_api_key="tavily-key",
            brave_api_key="brave-key",
        )

        # Tavily 실패, Brave 성공 Mock 설정
        mock_brave_response = WebSearchResponse(
            results=[
                WebSearchResult(
                    title="Brave 결과",
                    url="https://brave.com",
                    content="Brave 내용",
                )
            ],
            provider="brave",
            query="테스트",
            total_results=1,
        )

        with patch.object(
            service.providers[0], "search", side_effect=Exception("Tavily 실패")
        ), patch.object(
            service.providers[1],
            "search",
            new_callable=AsyncMock,
            return_value=mock_brave_response,
        ):
            response = await service.search("테스트 쿼리")

            # Brave로 Fallback 되어야 함
            assert response.provider == "brave"

    @pytest.mark.asyncio
    async def test_fallback_to_duckduckgo(self) -> None:
        """모든 유료 API 실패 시 DuckDuckGo로 Fallback 테스트"""
        from app.modules.core.tools.web_search import (
            WebSearchResponse,
            WebSearchResult,
            WebSearchService,
        )

        service = WebSearchService(
            tavily_api_key="tavily-key",
            brave_api_key="brave-key",
        )

        # DDG 응답 Mock
        mock_ddg_response = WebSearchResponse(
            results=[
                WebSearchResult(
                    title="DDG 결과",
                    url="https://duckduckgo.com",
                    content="DDG 내용",
                )
            ],
            provider="duckduckgo",
            query="테스트",
            total_results=1,
        )

        with patch.object(
            service.providers[0], "search", side_effect=Exception("Tavily 실패")
        ), patch.object(
            service.providers[1], "search", side_effect=Exception("Brave 실패")
        ), patch.object(
            service.providers[2],
            "search",
            new_callable=AsyncMock,
            return_value=mock_ddg_response,
        ):
            response = await service.search("테스트 쿼리")

            # DuckDuckGo로 Fallback 되어야 함
            assert response.provider == "duckduckgo"

    @pytest.mark.asyncio
    async def test_all_providers_fail(self) -> None:
        """모든 Provider 실패 시 예외 발생 테스트"""
        from app.modules.core.tools.web_search import WebSearchService

        service = WebSearchService(
            tavily_api_key="tavily-key",
            brave_api_key="brave-key",
        )

        # 모든 Provider 실패 Mock
        with patch.object(
            service.providers[0], "search", side_effect=Exception("Tavily 실패")
        ), patch.object(
            service.providers[1], "search", side_effect=Exception("Brave 실패")
        ), patch.object(
            service.providers[2], "search", side_effect=Exception("DDG 실패")
        ):
            with pytest.raises(Exception, match="모든 검색 Provider가 실패"):
                await service.search("테스트 쿼리")

    @pytest.mark.asyncio
    async def test_empty_query_raises_error(self) -> None:
        """빈 쿼리 시 ValueError 발생 테스트"""
        from app.modules.core.tools.web_search import WebSearchService

        service = WebSearchService()

        with pytest.raises(ValueError, match="검색 쿼리는 필수"):
            await service.search("")

    @pytest.mark.asyncio
    async def test_whitespace_query_raises_error(self) -> None:
        """공백만 있는 쿼리 시 ValueError 발생 테스트"""
        from app.modules.core.tools.web_search import WebSearchService

        service = WebSearchService()

        with pytest.raises(ValueError, match="검색 쿼리는 필수"):
            await service.search("   ")


# ========================================
# 6. TestWebSearchToolFunction
# ========================================
class TestWebSearchToolFunction:
    """Agent용 web_search() 도구 함수 테스트"""

    @pytest.mark.asyncio
    async def test_web_search_tool_function(self) -> None:
        """web_search() 함수가 올바르게 동작하는지 테스트"""
        from app.modules.core.tools.web_search import (
            WebSearchResponse,
            WebSearchResult,
            web_search,
        )

        # Mock 검색 응답
        mock_response = WebSearchResponse(
            results=[
                WebSearchResult(
                    title="검색 결과",
                    url="https://example.com",
                    content="검색 내용",
                    score=0.9,
                )
            ],
            provider="tavily",
            query="AI 뉴스",
            total_results=1,
        )

        # WebSearchService Mock
        with patch(
            "app.modules.core.tools.web_search.WebSearchService"
        ) as MockService:
            mock_service_instance = MagicMock()
            mock_service_instance.search = AsyncMock(return_value=mock_response)
            MockService.return_value = mock_service_instance

            # 도구 함수 호출
            arguments = {"query": "AI 뉴스", "max_results": 5}
            global_config: dict[str, Any] = {
                "web_search": {
                    "tavily_api_key": "test-tavily-key",
                    "brave_api_key": "test-brave-key",
                }
            }

            result = await web_search(arguments, global_config)

            # 결과 검증
            assert isinstance(result, list)
            assert len(result) == 1
            assert result[0]["title"] == "검색 결과"
            assert result[0]["url"] == "https://example.com"
            assert result[0]["content"] == "검색 내용"

    @pytest.mark.asyncio
    async def test_web_search_tool_empty_query(self) -> None:
        """빈 쿼리로 web_search() 호출 시 예외 테스트"""
        from app.modules.core.tools.web_search import web_search

        arguments: dict[str, Any] = {"query": ""}
        global_config: dict[str, Any] = {}

        with pytest.raises(ValueError, match="query는 필수"):
            await web_search(arguments, global_config)

    @pytest.mark.asyncio
    async def test_web_search_tool_missing_query(self) -> None:
        """query 파라미터 누락 시 예외 테스트"""
        from app.modules.core.tools.web_search import web_search

        arguments: dict[str, Any] = {"max_results": 5}
        global_config: dict[str, Any] = {}

        with pytest.raises(ValueError, match="query는 필수"):
            await web_search(arguments, global_config)

    @pytest.mark.asyncio
    async def test_web_search_tool_default_max_results(self) -> None:
        """max_results 미지정 시 기본값 사용 테스트"""
        from app.modules.core.tools.web_search import (
            WebSearchResponse,
            WebSearchResult,
            web_search,
        )

        mock_response = WebSearchResponse(
            results=[
                WebSearchResult(
                    title="결과",
                    url="https://test.com",
                    content="내용",
                )
            ],
            provider="duckduckgo",
            query="테스트",
            total_results=1,
        )

        with patch(
            "app.modules.core.tools.web_search.WebSearchService"
        ) as MockService:
            mock_service_instance = MagicMock()
            mock_service_instance.search = AsyncMock(return_value=mock_response)
            MockService.return_value = mock_service_instance

            arguments = {"query": "테스트"}
            global_config: dict[str, Any] = {}

            await web_search(arguments, global_config)

            # 기본 max_results(10)로 호출되었는지 확인
            mock_service_instance.search.assert_called_once()
            call_args = mock_service_instance.search.call_args
            assert call_args.kwargs.get("max_results", 10) == 10 or (
                len(call_args.args) >= 2 and call_args.args[1] == 10
            )


# ========================================
# 7. TestWebSearchModuleExports
# ========================================
class TestWebSearchModuleExports:
    """web_search 모듈 export 테스트"""

    def test_exports_from_web_search_module(self) -> None:
        """web_search 모듈에서 필수 클래스와 함수가 export 되는지 테스트"""
        from app.modules.core.tools.web_search import (
            BraveProvider,
            DuckDuckGoProvider,
            TavilyProvider,
            WebSearchProvider,
            WebSearchResponse,
            WebSearchResult,
            WebSearchService,
            web_search,
        )

        # 모든 export가 존재하는지 확인
        assert WebSearchProvider is not None
        assert WebSearchResult is not None
        assert WebSearchResponse is not None
        assert TavilyProvider is not None
        assert BraveProvider is not None
        assert DuckDuckGoProvider is not None
        assert WebSearchService is not None
        assert web_search is not None
        assert callable(web_search)

    def test_exports_from_tools_module(self) -> None:
        """tools 모듈의 __init__.py에서 web_search가 export 되는지 테스트"""
        from app.modules.core.tools import web_search

        assert web_search is not None
        assert callable(web_search)
