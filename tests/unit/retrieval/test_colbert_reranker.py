"""
JinaColBERTReranker 단위 테스트

Jina ColBERT v2 API 기반 토큰 수준 리랭킹 검증.

테스트 케이스:
1. 정상적인 리랭킹 요청
2. API 응답 파싱 및 점수 매핑
3. 빈 결과 처리
4. API 오류 시 Graceful Fallback
5. 타임아웃 처리
6. top_n 제한
7. 캐싱 지원 여부

구현일: 2025-12-31
TDD Phase: RED (실패 테스트 작성)
"""

from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.modules.core.retrieval.interfaces import SearchResult

# TDD RED: 아직 존재하지 않는 모듈 임포트 (이 테스트는 실패해야 함)
from app.modules.core.retrieval.rerankers.colbert_reranker import (
    ColBERTRerankerConfig,
    JinaColBERTReranker,
)

# ========================================
# 테스트 픽스처
# ========================================


@pytest.fixture
def default_config() -> ColBERTRerankerConfig:
    """기본 설정"""
    return ColBERTRerankerConfig(
        enabled=True,
        api_key="test_api_key",
        model="jina-colbert-v2",
        endpoint="https://api.jina.ai/v1/rerank",
        timeout=10,
        max_documents=20,
    )


@pytest.fixture
def sample_search_results() -> list[SearchResult]:
    """테스트용 검색 결과"""
    return [
        SearchResult(
            id="doc_1",
            content="강남 레스토랑 A는 100명 수용 가능합니다. 주차 50대 가능.",
            score=0.85,
            metadata={"name": "레스토랑 A", "category": "restaurant"},
        ),
        SearchResult(
            id="doc_2",
            content="강남 레스토랑 B는 가격이 합리적입니다. 코스 요리 포함.",
            score=0.80,
            metadata={"name": "레스토랑 B", "category": "restaurant"},
        ),
        SearchResult(
            id="doc_3",
            content="강북 카페 C는 루프탑 테라스 전문입니다.",
            score=0.75,
            metadata={"name": "카페 C", "category": "cafe"},
        ),
    ]


@pytest.fixture
def mock_successful_response() -> dict[str, Any]:
    """성공적인 API 응답 목"""
    return {
        "model": "jina-colbert-v2",
        "usage": {"total_tokens": 150, "prompt_tokens": 100},
        "results": [
            {"index": 0, "relevance_score": 0.95},
            {"index": 1, "relevance_score": 0.88},
            {"index": 2, "relevance_score": 0.72},
        ],
    }


# ========================================
# 기본 동작 테스트
# ========================================


class TestColBERTRerankerBasicOperations:
    """ColBERT 리랭커 기본 동작 테스트"""

    @pytest.mark.asyncio
    async def test_rerank_returns_sorted_results(
        self,
        default_config: ColBERTRerankerConfig,
        sample_search_results: list[SearchResult],
        mock_successful_response: dict[str, Any],
    ) -> None:
        """리랭킹 후 점수순으로 정렬된 결과 반환"""
        with patch("httpx.AsyncClient.post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = mock_successful_response
            mock_post.return_value = mock_response

            reranker = JinaColBERTReranker(config=default_config)
            result = await reranker.rerank(
                query="강남 맛집 추천",
                results=sample_search_results,
            )

            # 점수순 정렬 확인
            assert len(result) == 3
            assert result[0].score >= result[1].score >= result[2].score

    @pytest.mark.asyncio
    async def test_rerank_updates_scores_from_api(
        self,
        default_config: ColBERTRerankerConfig,
        sample_search_results: list[SearchResult],
        mock_successful_response: dict[str, Any],
    ) -> None:
        """API 응답의 점수로 SearchResult 점수 업데이트"""
        with patch("httpx.AsyncClient.post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = mock_successful_response
            mock_post.return_value = mock_response

            reranker = JinaColBERTReranker(config=default_config)
            result = await reranker.rerank(
                query="강남 맛집 추천",
                results=sample_search_results,
            )

            # API 응답 점수가 반영됨
            assert result[0].score == 0.95
            assert result[1].score == 0.88
            assert result[2].score == 0.72

    @pytest.mark.asyncio
    async def test_rerank_preserves_metadata(
        self,
        default_config: ColBERTRerankerConfig,
        sample_search_results: list[SearchResult],
        mock_successful_response: dict[str, Any],
    ) -> None:
        """리랭킹 후 원본 메타데이터 보존"""
        with patch("httpx.AsyncClient.post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = mock_successful_response
            mock_post.return_value = mock_response

            reranker = JinaColBERTReranker(config=default_config)
            result = await reranker.rerank(
                query="강남 맛집 추천",
                results=sample_search_results,
            )

            # 모든 결과가 원본 ID와 메타데이터 보존
            result_ids = {r.id for r in result}
            assert result_ids == {"doc_1", "doc_2", "doc_3"}

            for r in result:
                assert "name" in r.metadata
                assert "category" in r.metadata


# ========================================
# API 호출 테스트
# ========================================


class TestAPICall:
    """API 호출 관련 테스트"""

    @pytest.mark.asyncio
    async def test_correct_api_request_format(
        self,
        default_config: ColBERTRerankerConfig,
        sample_search_results: list[SearchResult],
    ) -> None:
        """올바른 API 요청 형식 확인"""
        with patch("httpx.AsyncClient.post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "results": [
                    {"index": 0, "relevance_score": 0.9},
                    {"index": 1, "relevance_score": 0.8},
                    {"index": 2, "relevance_score": 0.7},
                ]
            }
            mock_post.return_value = mock_response

            reranker = JinaColBERTReranker(config=default_config)
            await reranker.rerank(
                query="강남 맛집 추천",
                results=sample_search_results,
            )

            # API 호출 검증
            mock_post.assert_called_once()
            call_kwargs = mock_post.call_args

            # 헤더 검증 (Authorization Bearer 토큰)
            headers = call_kwargs.kwargs.get("headers", {})
            assert "Authorization" in headers
            assert "Bearer test_api_key" in headers["Authorization"]

            # 요청 바디 검증
            json_data = call_kwargs.kwargs.get("json", {})
            assert json_data.get("model") == "jina-colbert-v2"
            assert "query" in json_data
            assert "documents" in json_data
            assert len(json_data["documents"]) == 3

    @pytest.mark.asyncio
    async def test_api_endpoint_used(
        self,
        sample_search_results: list[SearchResult],
    ) -> None:
        """올바른 API 엔드포인트 사용 확인"""
        custom_endpoint = "https://custom.api.endpoint/rerank"
        config = ColBERTRerankerConfig(
            enabled=True,
            api_key="test_key",
            model="jina-colbert-v2",
            endpoint=custom_endpoint,
            timeout=10,
            max_documents=20,
        )

        # colbert_reranker 모듈에서 import한 httpx의 post 메서드를 패치
        with patch(
            "app.modules.core.retrieval.rerankers.colbert_reranker.httpx.AsyncClient.post"
        ) as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            # sample_search_results가 3개이므로 3개 결과 반환
            mock_response.json.return_value = {
                "results": [
                    {"index": 0, "relevance_score": 0.9},
                    {"index": 1, "relevance_score": 0.85},
                    {"index": 2, "relevance_score": 0.8},
                ]
            }
            mock_post.return_value = mock_response

            reranker = JinaColBERTReranker(config=config)
            # 2개 이상의 결과를 전달해야 API가 호출됨 (단일 결과는 스킵)
            await reranker.rerank(
                query="테스트",
                results=sample_search_results,
            )

            # 호출된 URL 확인
            assert mock_post.called
            call_args = mock_post.call_args
            # 첫 번째 위치 인자 또는 kwargs에서 URL 확인
            if call_args.args:
                assert call_args.args[0] == custom_endpoint
            else:
                # kwargs로 전달된 경우 url 키 확인
                assert call_args.kwargs.get("url") == custom_endpoint


# ========================================
# 에러 처리 테스트
# ========================================


class TestErrorHandling:
    """에러 처리 및 Graceful Fallback 테스트"""

    @pytest.mark.asyncio
    async def test_api_error_returns_original_results(
        self,
        default_config: ColBERTRerankerConfig,
        sample_search_results: list[SearchResult],
    ) -> None:
        """API 오류 시 원본 결과 반환 (Graceful Fallback)"""
        with patch("httpx.AsyncClient.post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 500
            mock_response.text = "Internal Server Error"
            mock_post.return_value = mock_response

            reranker = JinaColBERTReranker(config=default_config)
            result = await reranker.rerank(
                query="강남 맛집 추천",
                results=sample_search_results,
            )

            # 원본 결과 그대로 반환
            assert len(result) == 3
            assert result[0].id == sample_search_results[0].id
            assert result[0].score == sample_search_results[0].score

    @pytest.mark.asyncio
    async def test_timeout_returns_original_results(
        self,
        default_config: ColBERTRerankerConfig,
        sample_search_results: list[SearchResult],
    ) -> None:
        """타임아웃 시 원본 결과 반환"""
        with patch("httpx.AsyncClient.post") as mock_post:
            mock_post.side_effect = httpx.TimeoutException("Request timed out")

            reranker = JinaColBERTReranker(config=default_config)
            result = await reranker.rerank(
                query="강남 맛집 추천",
                results=sample_search_results,
            )

            # 원본 결과 반환
            assert len(result) == 3
            assert result[0].id == sample_search_results[0].id

    @pytest.mark.asyncio
    async def test_connection_error_returns_original_results(
        self,
        default_config: ColBERTRerankerConfig,
        sample_search_results: list[SearchResult],
    ) -> None:
        """네트워크 연결 오류 시 원본 결과 반환"""
        with patch("httpx.AsyncClient.post") as mock_post:
            mock_post.side_effect = httpx.ConnectError("Connection failed")

            reranker = JinaColBERTReranker(config=default_config)
            result = await reranker.rerank(
                query="강남 맛집 추천",
                results=sample_search_results,
            )

            # 원본 결과 반환
            assert len(result) == 3

    @pytest.mark.asyncio
    async def test_invalid_json_response_returns_original(
        self,
        default_config: ColBERTRerankerConfig,
        sample_search_results: list[SearchResult],
    ) -> None:
        """잘못된 JSON 응답 시 원본 결과 반환"""
        with patch("httpx.AsyncClient.post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.side_effect = ValueError("Invalid JSON")
            mock_post.return_value = mock_response

            reranker = JinaColBERTReranker(config=default_config)
            result = await reranker.rerank(
                query="테스트",
                results=sample_search_results,
            )

            # 원본 결과 반환
            assert len(result) == 3


# ========================================
# 빈 입력 처리 테스트
# ========================================


class TestEmptyInputHandling:
    """빈 입력 처리 테스트"""

    @pytest.mark.asyncio
    async def test_empty_results_returns_empty(
        self,
        default_config: ColBERTRerankerConfig,
    ) -> None:
        """빈 결과 리스트 입력 시 빈 리스트 반환"""
        reranker = JinaColBERTReranker(config=default_config)
        result = await reranker.rerank(
            query="강남 맛집 추천",
            results=[],
        )

        assert result == []

    @pytest.mark.asyncio
    async def test_single_result_returns_same(
        self,
        default_config: ColBERTRerankerConfig,
    ) -> None:
        """단일 결과는 그대로 반환 (API 호출 스킵)"""
        single_result = [
            SearchResult(
                id="doc_1",
                content="테스트 내용",
                score=0.9,
                metadata={},
            )
        ]

        with patch("httpx.AsyncClient.post") as mock_post:
            reranker = JinaColBERTReranker(config=default_config)
            result = await reranker.rerank(
                query="테스트",
                results=single_result,
            )

            # 단일 결과는 API 호출 없이 그대로 반환
            assert len(result) == 1
            assert result[0].id == "doc_1"
            # API 호출되지 않음 (최적화)
            mock_post.assert_not_called()


# ========================================
# top_n 제한 테스트
# ========================================


class TestTopNLimit:
    """top_n 결과 제한 테스트"""

    @pytest.mark.asyncio
    async def test_top_n_limits_results(
        self,
        default_config: ColBERTRerankerConfig,
        sample_search_results: list[SearchResult],
        mock_successful_response: dict[str, Any],
    ) -> None:
        """top_n 지정 시 상위 n개만 반환"""
        with patch("httpx.AsyncClient.post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = mock_successful_response
            mock_post.return_value = mock_response

            reranker = JinaColBERTReranker(config=default_config)
            result = await reranker.rerank(
                query="강남 맛집 추천",
                results=sample_search_results,
                top_n=2,  # 상위 2개만
            )

            assert len(result) == 2

    @pytest.mark.asyncio
    async def test_top_n_none_returns_all(
        self,
        default_config: ColBERTRerankerConfig,
        sample_search_results: list[SearchResult],
        mock_successful_response: dict[str, Any],
    ) -> None:
        """top_n이 None이면 전체 반환"""
        with patch("httpx.AsyncClient.post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = mock_successful_response
            mock_post.return_value = mock_response

            reranker = JinaColBERTReranker(config=default_config)
            result = await reranker.rerank(
                query="강남 맛집 추천",
                results=sample_search_results,
                top_n=None,
            )

            assert len(result) == 3


# ========================================
# 캐싱 지원 테스트
# ========================================


class TestCachingSupport:
    """캐싱 지원 여부 테스트"""

    def test_supports_caching_returns_true(
        self,
        default_config: ColBERTRerankerConfig,
    ) -> None:
        """ColBERT는 결정론적이므로 캐싱 지원"""
        reranker = JinaColBERTReranker(config=default_config)
        assert reranker.supports_caching() is True


# ========================================
# 통계 정보 테스트
# ========================================


class TestStatistics:
    """통계 정보 테스트"""

    @pytest.mark.asyncio
    async def test_get_stats_tracks_calls(
        self,
        default_config: ColBERTRerankerConfig,
        sample_search_results: list[SearchResult],
        mock_successful_response: dict[str, Any],
    ) -> None:
        """호출 통계 추적"""
        with patch("httpx.AsyncClient.post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = mock_successful_response
            mock_post.return_value = mock_response

            reranker = JinaColBERTReranker(config=default_config)

            # 성공 호출
            await reranker.rerank("쿼리1", sample_search_results)

            stats = reranker.get_stats()
            assert stats["total_calls"] == 1
            assert stats["successful_calls"] == 1
            assert stats["failed_calls"] == 0

    @pytest.mark.asyncio
    async def test_get_stats_tracks_failures(
        self,
        default_config: ColBERTRerankerConfig,
        sample_search_results: list[SearchResult],
    ) -> None:
        """실패 통계 추적"""
        with patch("httpx.AsyncClient.post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 500
            mock_post.return_value = mock_response

            reranker = JinaColBERTReranker(config=default_config)

            # 실패 호출
            await reranker.rerank("쿼리1", sample_search_results)

            stats = reranker.get_stats()
            assert stats["total_calls"] == 1
            assert stats["successful_calls"] == 0
            assert stats["failed_calls"] == 1


# ========================================
# 설정 검증 테스트
# ========================================


class TestConfigValidation:
    """설정 값 검증 테스트"""

    def test_missing_api_key_raises_error(self) -> None:
        """API 키 누락 시 에러"""
        with pytest.raises(ValueError, match="api_key"):
            ColBERTRerankerConfig(
                enabled=True,
                api_key="",  # 빈 문자열
                model="jina-colbert-v2",
                endpoint="https://api.jina.ai/v1/rerank",
                timeout=10,
                max_documents=20,
            )

    def test_invalid_timeout_raises_error(self) -> None:
        """유효하지 않은 타임아웃 에러"""
        with pytest.raises(ValueError, match="timeout"):
            ColBERTRerankerConfig(
                enabled=True,
                api_key="test_key",
                model="jina-colbert-v2",
                endpoint="https://api.jina.ai/v1/rerank",
                timeout=0,  # 0 이하
                max_documents=20,
            )

    def test_invalid_max_documents_raises_error(self) -> None:
        """유효하지 않은 max_documents 에러"""
        with pytest.raises(ValueError, match="max_documents"):
            ColBERTRerankerConfig(
                enabled=True,
                api_key="test_key",
                model="jina-colbert-v2",
                endpoint="https://api.jina.ai/v1/rerank",
                timeout=10,
                max_documents=0,  # 0 이하
            )

    def test_valid_config_creation(self) -> None:
        """유효한 설정 생성"""
        config = ColBERTRerankerConfig(
            enabled=True,
            api_key="valid_key",
            model="jina-colbert-v2",
            endpoint="https://api.jina.ai/v1/rerank",
            timeout=15,
            max_documents=50,
        )

        assert config.enabled is True
        assert config.api_key == "valid_key"
        assert config.model == "jina-colbert-v2"
        assert config.timeout == 15
        assert config.max_documents == 50


# ========================================
# 비활성화 상태 테스트
# ========================================


class TestDisabledState:
    """비활성화 상태 테스트"""

    @pytest.mark.asyncio
    async def test_disabled_reranker_returns_original(
        self,
        sample_search_results: list[SearchResult],
    ) -> None:
        """비활성화 시 원본 결과 반환"""
        config = ColBERTRerankerConfig(
            enabled=False,  # 비활성화
            api_key="test_key",
            model="jina-colbert-v2",
            endpoint="https://api.jina.ai/v1/rerank",
            timeout=10,
            max_documents=20,
        )

        with patch("httpx.AsyncClient.post") as mock_post:
            reranker = JinaColBERTReranker(config=config)
            result = await reranker.rerank(
                query="테스트",
                results=sample_search_results,
            )

            # 원본 그대로 반환
            assert len(result) == 3
            assert result[0].id == sample_search_results[0].id

            # API 호출 안 함
            mock_post.assert_not_called()
