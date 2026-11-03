"""
DI Container 평가 모듈 통합 테스트
AppContainer에 평가기가 올바르게 등록되었는지 검증
"""

from unittest.mock import AsyncMock, MagicMock

import pytest


class TestEvaluatorContainerRegistration:
    """평가기 DI Container 등록 테스트"""

    def test_evaluator_provider_exists_in_container(self):
        """AppContainer에 evaluator Provider가 있는지 확인"""
        from app.core.di_container import AppContainer

        container = AppContainer()
        assert hasattr(container, "evaluator")

    def test_evaluator_factory_helper_exists(self):
        """create_evaluator_instance 헬퍼 함수 존재 확인"""
        from app.core.di_container import create_evaluator_instance

        assert callable(create_evaluator_instance)


class TestCreateEvaluatorInstance:
    """create_evaluator_instance 헬퍼 함수 테스트"""

    @pytest.mark.asyncio
    async def test_create_evaluator_with_enabled_config(self):
        """평가 활성화 설정으로 평가기 생성"""
        from app.core.di_container import create_evaluator_instance

        config = {
            "evaluation": {
                "enabled": True,
                "provider": "internal",
                "internal": {
                    "model": "google/gemini-2.5-flash-lite",
                    "timeout": 10.0,
                },
            }
        }

        # Mock LLM Factory
        mock_llm_factory = MagicMock()
        mock_client = MagicMock()
        mock_client.generate = AsyncMock(return_value='{"faithfulness": 0.9, "relevance": 0.85}')
        mock_llm_factory.get_client.return_value = mock_client

        evaluator = await create_evaluator_instance(
            config=config,
            llm_factory=mock_llm_factory,
        )

        assert evaluator is not None
        assert evaluator.name == "internal"

    @pytest.mark.asyncio
    async def test_create_evaluator_with_disabled_config(self):
        """평가 비활성화 설정으로 None 반환"""
        from app.core.di_container import create_evaluator_instance

        config = {
            "evaluation": {
                "enabled": False,
            }
        }

        evaluator = await create_evaluator_instance(config=config)

        assert evaluator is None

    @pytest.mark.asyncio
    async def test_create_evaluator_without_config(self):
        """evaluation 설정이 없으면 None 반환 (기본 비활성화)"""
        from app.core.di_container import create_evaluator_instance

        config = {}

        evaluator = await create_evaluator_instance(config=config)

        assert evaluator is None

    @pytest.mark.asyncio
    async def test_create_evaluator_without_llm_factory(self):
        """LLM Factory 없이도 평가기 생성 가능 (is_available=False)"""
        from app.core.di_container import create_evaluator_instance

        config = {
            "evaluation": {
                "enabled": True,
                "provider": "internal",
            }
        }

        evaluator = await create_evaluator_instance(
            config=config,
            llm_factory=None,
        )

        # 평가기는 생성되지만 LLM 클라이언트가 없으므로 is_available=False
        assert evaluator is not None
        assert evaluator.name == "internal"
        assert evaluator.is_available() is False


class TestEvaluatorLLMClientWrapper:
    """평가기용 LLM 클라이언트 래퍼 테스트"""

    def test_evaluator_llm_client_exists(self):
        """_create_evaluator_llm_client 헬퍼 함수 존재 확인"""
        from app.core.di_container import _create_evaluator_llm_client

        assert callable(_create_evaluator_llm_client)

    def test_evaluator_llm_client_has_generate_method(self):
        """생성된 클라이언트가 generate 메서드를 가지는지 확인"""
        from app.core.di_container import _create_evaluator_llm_client

        mock_factory = MagicMock()
        eval_config = {
            "internal": {
                "model": "google/gemini-2.5-flash-lite",
            }
        }

        client = _create_evaluator_llm_client(mock_factory, eval_config)

        assert hasattr(client, "generate")
        assert callable(client.generate)

    @pytest.mark.asyncio
    async def test_evaluator_llm_client_generate_calls_factory(self):
        """generate 호출 시 LLM Factory를 사용하는지 확인"""
        from app.core.di_container import _create_evaluator_llm_client

        mock_factory = MagicMock()
        mock_llm_client = MagicMock()
        # BaseLLMClient 의 실제 API 는 generate_text 다(예전 테스트는 존재하지 않는 .generate 를
        # mock 해 래퍼의 버그를 가렸다).
        mock_llm_client.generate_text = AsyncMock(return_value='{"result": "ok"}')
        mock_factory.get_client.return_value = mock_llm_client

        eval_config = {
            "internal": {
                "model": "google/gemini-2.5-flash-lite",
            }
        }

        client = _create_evaluator_llm_client(mock_factory, eval_config)
        result = await client.generate("test prompt")

        mock_factory.get_client.assert_called_once_with(provider="openrouter")
        mock_llm_client.generate_text.assert_awaited_once_with(
            "test prompt", model="google/gemini-2.5-flash-lite"
        )
        assert result == '{"result": "ok"}'
