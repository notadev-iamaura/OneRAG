"""
Jina Reranker 단위 테스트

현재 커버리지: 29.82%
목표 커버리지: 75-85%
"""

from unittest.mock import MagicMock, patch

import pytest

from app.modules.core.retrieval.interfaces import SearchResult


class TestJinaRerankerInitialization:
    """Jina 리랭커 초기화 테스트"""

    @pytest.fixture
    def sample_results(self) -> list[SearchResult]:
        """샘플 검색 결과"""
        return [
            SearchResult(
                id="doc1",
                content="Python is a programming language",
                score=0.7,
                metadata={"source": "doc1.txt"},
            ),
            SearchResult(
                id="doc2",
                content="JavaScript for web development",
                score=0.6,
                metadata={"source": "doc2.txt"},
            ),
            SearchResult(
                id="doc3",
                content="Machine learning AI field",
                score=0.5,
                metadata={"source": "doc3.txt"},
            ),
        ]

    def test_initialization_success(self) -> None:
        """
        Jina 리랭커 초기화 성공 테스트

        Given: 유효한 API 키와 설정
        When: JinaReranker 초기화
        Then: 초기화 성공
        """
        from app.modules.core.retrieval.rerankers.jina_reranker import JinaReranker

        reranker = JinaReranker(
            api_key="test-api-key",
            model="jina-reranker-v1-base-en",
        )

        assert reranker.api_key == "test-api-key"
        assert reranker.model == "jina-reranker-v1-base-en"
        assert reranker.endpoint == "https://api.jina.ai/v1/rerank"
        assert reranker.timeout == 30.0

    def test_initialization_custom_endpoint(self) -> None:
        """
        커스텀 엔드포인트로 초기화 테스트

        Given: 커스텀 엔드포인트 URL
        When: JinaReranker 초기화
        Then: 커스텀 엔드포인트 설정됨
        """
        from app.modules.core.retrieval.rerankers.jina_reranker import JinaReranker

        reranker = JinaReranker(
            api_key="test-api-key",
            endpoint="https://custom-endpoint.com/rerank",
            timeout=10.0,
        )

        assert reranker.endpoint == "https://custom-endpoint.com/rerank"
        assert reranker.timeout == 10.0

    @pytest.mark.asyncio
    async def test_initialize_method(self) -> None:
        """
        initialize() 메서드 테스트

        Given: JinaReranker 인스턴스
        When: initialize() 호출
        Then: 정상 완료 (HTTP API이므로 추가 작업 없음)
        """
        from app.modules.core.retrieval.rerankers.jina_reranker import JinaReranker

        reranker = JinaReranker(api_key="test-key")
        await reranker.initialize()

        # 에러 없이 완료되면 성공
        assert True

    @pytest.mark.asyncio
    async def test_close_method(self) -> None:
        """
        close() 메서드 테스트

        Given: JinaReranker 인스턴스
        When: close() 호출
        Then: 정상 완료
        """
        from app.modules.core.retrieval.rerankers.jina_reranker import JinaReranker

        reranker = JinaReranker(api_key="test-key")
        await reranker.close()

        # 에러 없이 완료되면 성공
        assert True


class TestJinaRerankerReranking:
    """Jina 리랭킹 기능 테스트"""

    @pytest.fixture
    def sample_results(self) -> list[SearchResult]:
        """샘플 검색 결과"""
        return [
            SearchResult(
                id="doc1",
                content="Python programming language",
                score=0.7,
                metadata={"source": "doc1.txt"},
            ),
            SearchResult(
                id="doc2",
                content="JavaScript for web development",
                score=0.6,
                metadata={"source": "doc2.txt"},
            ),
            SearchResult(
                id="doc3",
                content="Machine learning AI field",
                score=0.5,
                metadata={"source": "doc3.txt"},
            ),
        ]

    @pytest.mark.asyncio
    async def test_rerank_success(self, sample_results: list[SearchResult]) -> None:
        """
        Jina 리랭킹 성공 테스트

        Given: 쿼리와 문서 리스트
        When: Jina API 리랭킹 수행
        Then: 재정렬된 문서 반환
        """
        from app.modules.core.retrieval.rerankers.jina_reranker import JinaReranker

        with patch("httpx.AsyncClient.post") as mock_post:
            # Mock HTTP 응답
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "results": [
                    {"index": 2, "relevance_score": 0.95},
                    {"index": 0, "relevance_score": 0.85},
                    {"index": 1, "relevance_score": 0.75},
                ]
            }
            mock_post.return_value = mock_response

            reranker = JinaReranker(api_key="test-api-key")
            results = await reranker.rerank(
                query="Python programming",
                results=sample_results,
            )

            # 검증
            assert len(results) == 3
            assert results[0].score == 0.95  # 가장 높은 점수
            assert results[1].score == 0.85
            assert results[2].score == 0.75
            assert results[0].content == "Machine learning AI field"  # index 2

    @pytest.mark.asyncio
    async def test_rerank_with_top_n(self, sample_results: list[SearchResult]) -> None:
        """
        top_n 파라미터로 결과 제한 테스트

        Given: top_n=2 설정
        When: 리랭킹 수행
        Then: 상위 2개만 반환
        """
        from app.modules.core.retrieval.rerankers.jina_reranker import JinaReranker

        with patch("httpx.AsyncClient.post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "results": [
                    {"index": 0, "relevance_score": 0.95},
                    {"index": 1, "relevance_score": 0.85},
                ]
            }
            mock_post.return_value = mock_response

            reranker = JinaReranker(api_key="test-api-key")
            results = await reranker.rerank(
                query="test",
                results=sample_results,
                top_n=2,
            )

            # 검증: 2개만 반환됨
            assert len(results) == 2

    @pytest.mark.asyncio
    async def test_rerank_empty_results(self) -> None:
        """
        빈 결과 리스트 처리 테스트

        Given: 빈 결과 리스트
        When: 리랭킹 수행
        Then: 빈 리스트 반환
        """
        from app.modules.core.retrieval.rerankers.jina_reranker import JinaReranker

        reranker = JinaReranker(api_key="test-api-key")
        results = await reranker.rerank(query="test", results=[])

        assert results == []


class TestJinaRerankerErrorHandling:
    """Jina 리랭커 에러 핸들링 테스트"""

    @pytest.fixture
    def sample_results(self) -> list[SearchResult]:
        """샘플 검색 결과"""
        return [
            SearchResult(
                id="doc1",
                content="Python programming",
                score=0.7,
                metadata={"source": "doc1.txt"},
            ),
        ]

    @pytest.mark.asyncio
    async def test_http_error_fallback(
        self, sample_results: list[SearchResult]
    ) -> None:
        """
        HTTP 에러 시 폴백 테스트

        Given: Jina API 500 에러
        When: 리랭킹 수행
        Then: 원본 결과 반환
        """
        import httpx

        from app.modules.core.retrieval.rerankers.jina_reranker import JinaReranker

        with patch("httpx.AsyncClient.post") as mock_post:
            # HTTP 500 에러 시뮬레이션
            mock_response = MagicMock()
            mock_response.status_code = 500
            mock_response.text = "Internal Server Error"

            mock_post.side_effect = httpx.HTTPStatusError(
                "500 Server Error",
                request=MagicMock(),
                response=mock_response,
            )

            reranker = JinaReranker(api_key="test-api-key")
            results = await reranker.rerank(query="test", results=sample_results)

            # 검증: 원본 결과 반환 (폴백)
            assert results == sample_results
            assert len(results) == 1

    @pytest.mark.asyncio
    async def test_timeout_fallback(self, sample_results: list[SearchResult]) -> None:
        """
        타임아웃 시 폴백 테스트

        Given: Jina API 타임아웃
        When: 리랭킹 수행
        Then: 원본 결과 반환
        """
        import httpx

        from app.modules.core.retrieval.rerankers.jina_reranker import JinaReranker

        with patch("httpx.AsyncClient.post") as mock_post:
            # 타임아웃 시뮬레이션
            mock_post.side_effect = httpx.TimeoutException("Request timeout")

            reranker = JinaReranker(api_key="test-api-key", timeout=1.0)
            results = await reranker.rerank(query="test", results=sample_results)

            # 검증: 원본 결과 반환 (폴백)
            assert results == sample_results

    @pytest.mark.asyncio
    async def test_generic_exception_fallback(
        self, sample_results: list[SearchResult]
    ) -> None:
        """
        일반 예외 발생 시 폴백 테스트

        Given: Jina API 호출 중 예외 발생
        When: 리랭킹 수행
        Then: 원본 결과 반환
        """
        from app.modules.core.retrieval.rerankers.jina_reranker import JinaReranker

        with patch("httpx.AsyncClient.post") as mock_post:
            # 일반 예외 시뮬레이션
            mock_post.side_effect = ValueError("Invalid response format")

            reranker = JinaReranker(api_key="test-api-key")
            results = await reranker.rerank(query="test", results=sample_results)

            # 검증: 원본 결과 반환 (폴백)
            assert results == sample_results


class TestJinaRerankerUtilities:
    """Jina 리랭커 유틸리티 기능 테스트"""

    def test_supports_caching(self) -> None:
        """
        캐싱 지원 여부 테스트

        Given: JinaReranker 인스턴스
        When: supports_caching() 호출
        Then: True 반환 (Jina는 결정론적)
        """
        from app.modules.core.retrieval.rerankers.jina_reranker import JinaReranker

        reranker = JinaReranker(api_key="test-api-key")
        assert reranker.supports_caching() is True

    def test_get_stats_initial(self) -> None:
        """
        초기 통계 조회 테스트

        Given: 새로 생성된 JinaReranker
        When: get_stats() 호출
        Then: 초기 통계 반환 (요청 0건)
        """
        from app.modules.core.retrieval.rerankers.jina_reranker import JinaReranker

        reranker = JinaReranker(api_key="test-api-key", model="jina-reranker-v2")
        stats = reranker.get_stats()

        assert stats["total_requests"] == 0
        assert stats["successful_requests"] == 0
        assert stats["failed_requests"] == 0
        assert stats["success_rate"] == 0.0
        assert stats["model"] == "jina-reranker-v2"
        assert stats["endpoint"] == "https://api.jina.ai/v1/rerank"

    @pytest.mark.asyncio
    async def test_get_stats_after_success(self) -> None:
        """
        성공 후 통계 조회 테스트

        Given: 리랭킹 성공 후
        When: get_stats() 호출
        Then: 통계 업데이트됨
        """
        from app.modules.core.retrieval.interfaces import SearchResult
        from app.modules.core.retrieval.rerankers.jina_reranker import JinaReranker

        sample_results = [
            SearchResult(id="test-doc", content="test", score=0.5, metadata={}),
        ]

        with patch("httpx.AsyncClient.post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "results": [{"index": 0, "relevance_score": 0.9}]
            }
            mock_post.return_value = mock_response

            reranker = JinaReranker(api_key="test-api-key")
            await reranker.rerank(query="test", results=sample_results)

            stats = reranker.get_stats()
            assert stats["total_requests"] == 1
            assert stats["successful_requests"] == 1
            assert stats["failed_requests"] == 0
            assert stats["success_rate"] == 100.0

    @pytest.mark.asyncio
    async def test_get_stats_after_failure(self) -> None:
        """
        실패 후 통계 조회 테스트

        Given: 리랭킹 실패 후
        When: get_stats() 호출
        Then: 실패 통계 업데이트됨
        """
        import httpx

        from app.modules.core.retrieval.interfaces import SearchResult
        from app.modules.core.retrieval.rerankers.jina_reranker import JinaReranker

        sample_results = [
            SearchResult(id="test-doc", content="test", score=0.5, metadata={}),
        ]

        with patch("httpx.AsyncClient.post") as mock_post:
            # 타임아웃 시뮬레이션
            mock_post.side_effect = httpx.TimeoutException("Timeout")

            reranker = JinaReranker(api_key="test-api-key")
            await reranker.rerank(query="test", results=sample_results)

            stats = reranker.get_stats()
            assert stats["total_requests"] == 1
            assert stats["successful_requests"] == 0
            assert stats["failed_requests"] == 1
            assert stats["success_rate"] == 0.0
