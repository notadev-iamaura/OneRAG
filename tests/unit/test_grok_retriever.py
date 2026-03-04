"""
GrokRetriever 단위 테스트

GrokRetriever의 초기화, 검색, 헬스 체크를 Mock 기반으로 검증합니다.
실제 xAI API 호출 없이 테스트 가능합니다.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.lib.errors import ErrorCode


class TestGrokRetrieverInit:
    """GrokRetriever 초기화 테스트"""

    def test_default_config(self) -> None:
        """기본 설정으로 초기화"""
        from app.modules.core.retrieval.retrievers.grok_retriever import GrokRetriever

        retriever = GrokRetriever(api_key="test-key")
        assert retriever.model == "grok-3"
        assert retriever.timeout == 30
        assert retriever.top_k == 10

    def test_custom_config(self) -> None:
        """커스텀 설정으로 초기화"""
        from app.modules.core.retrieval.retrievers.grok_retriever import GrokRetriever

        retriever = GrokRetriever(
            api_key="test-key",
            collection_ids=["col_1", "col_2"],
            model="grok-3-mini",
            timeout=60,
        )
        assert retriever.collection_ids == ["col_1", "col_2"]
        assert retriever.model == "grok-3-mini"
        assert retriever.timeout == 60

    def test_env_var_api_key(self) -> None:
        """환경변수에서 API 키 로드"""
        from app.modules.core.retrieval.retrievers.grok_retriever import GrokRetriever

        with patch.dict("os.environ", {"XAI_API_KEY": "env-key"}):
            retriever = GrokRetriever()
            assert retriever.api_key == "env-key"

    def test_factory_registration(self) -> None:
        """RetrieverFactory에 grok 등록 확인"""
        from app.modules.core.retrieval.retrievers.factory import RetrieverFactory

        assert "grok" in RetrieverFactory.get_available_providers()
        info = RetrieverFactory.get_provider_info("grok")
        assert info is not None
        assert info["hybrid_support"] is True

    def test_error_codes_exist(self) -> None:
        """GROK ErrorCode 존재 확인"""
        assert ErrorCode.GROK_001.value == "GROK-001"
        assert ErrorCode.GROK_002.value == "GROK-002"
        assert ErrorCode.GROK_003.value == "GROK-003"


class TestGrokRetrieverSearch:
    """GrokRetriever 검색 테스트"""

    @pytest.mark.asyncio
    async def test_search_no_api_key(self) -> None:
        """API 키 없이 검색 시 에러"""
        from app.modules.core.retrieval.retrievers.grok_retriever import GrokRetriever

        retriever = GrokRetriever(api_key="")

        with pytest.raises(Exception) as exc_info:
            await retriever.search("테스트 쿼리")
        assert "API 키" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_search_success(self) -> None:
        """성공적인 검색 응답 파싱"""
        from app.modules.core.retrieval.retrievers.grok_retriever import GrokRetriever

        retriever = GrokRetriever(
            api_key="test-key",
            collection_ids=["col_1"],
        )

        # Mock httpx 응답
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": "검색 결과 기반 응답",
                        "tool_calls": [
                            {
                                "type": "collections_search",
                                "results": [
                                    {
                                        "id": "doc-1",
                                        "content": "문서 내용 1",
                                        "score": 0.95,
                                        "collection_id": "col_1",
                                        "metadata": {"source": "test"},
                                    },
                                    {
                                        "id": "doc-2",
                                        "content": "문서 내용 2",
                                        "score": 0.85,
                                        "collection_id": "col_1",
                                        "metadata": {},
                                    },
                                ],
                            },
                        ],
                    },
                },
            ],
        }

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.is_closed = False
        retriever._client = mock_client

        results = await retriever.search("테스트")
        assert len(results) == 2
        assert results[0].id == "doc-1"
        assert results[0].score == 0.95
        assert results[0].content == "문서 내용 1"
        assert results[0].metadata["source"] == "grok_collections"

    @pytest.mark.asyncio
    async def test_search_fallback_to_llm_response(self) -> None:
        """검색 결과 없을 때 LLM 응답으로 폴백"""
        from app.modules.core.retrieval.retrievers.grok_retriever import GrokRetriever

        retriever = GrokRetriever(api_key="test-key")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": "LLM이 생성한 답변입니다.",
                    },
                },
            ],
        }

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.is_closed = False
        retriever._client = mock_client

        results = await retriever.search("테스트")
        assert len(results) == 1
        assert results[0].id == "grok-llm-response"
        assert results[0].metadata["source"] == "grok_llm"

    @pytest.mark.asyncio
    async def test_search_rate_limit(self) -> None:
        """속도 제한 (429) 에러 처리"""
        from app.modules.core.retrieval.retrievers.grok_retriever import GrokRetriever

        retriever = GrokRetriever(api_key="test-key")

        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.is_closed = False
        retriever._client = mock_client

        with pytest.raises(Exception) as exc_info:
            await retriever.search("테스트")
        assert "속도 제한" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_search_auth_failure(self) -> None:
        """인증 실패 (401) 에러 처리"""
        from app.modules.core.retrieval.retrievers.grok_retriever import GrokRetriever

        retriever = GrokRetriever(api_key="invalid-key")

        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.is_closed = False
        retriever._client = mock_client

        with pytest.raises(Exception) as exc_info:
            await retriever.search("테스트")
        assert "인증" in str(exc_info.value)


class TestGrokRetrieverHealthCheck:
    """GrokRetriever 헬스 체크 테스트"""

    @pytest.mark.asyncio
    async def test_health_check_no_api_key(self) -> None:
        """API 키 없으면 헬스 체크 실패"""
        from app.modules.core.retrieval.retrievers.grok_retriever import GrokRetriever

        retriever = GrokRetriever(api_key="")
        result = await retriever.health_check()
        assert result is False

    @pytest.mark.asyncio
    async def test_health_check_success(self) -> None:
        """헬스 체크 성공"""
        from app.modules.core.retrieval.retrievers.grok_retriever import GrokRetriever

        retriever = GrokRetriever(api_key="test-key")

        mock_response = MagicMock()
        mock_response.status_code = 200

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.is_closed = False
        retriever._client = mock_client

        result = await retriever.health_check()
        assert result is True

    @pytest.mark.asyncio
    async def test_health_check_failure(self) -> None:
        """헬스 체크 실패 (서버 오류)"""
        from app.modules.core.retrieval.retrievers.grok_retriever import GrokRetriever

        retriever = GrokRetriever(api_key="test-key")

        mock_client = AsyncMock()
        mock_client.post.side_effect = Exception("Connection error")
        mock_client.is_closed = False
        retriever._client = mock_client

        result = await retriever.health_check()
        assert result is False
