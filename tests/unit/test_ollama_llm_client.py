"""
OllamaLLMClient 단위 테스트

OllamaLLMClient의 핵심 기능을 Mock 기반으로 검증합니다.
실제 Ollama 서버 없이 테스트 가능합니다.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestOllamaLLMClientInit:
    """OllamaLLMClient 초기화 테스트"""

    def test_default_config(self) -> None:
        """기본 설정으로 초기화"""
        from app.lib.llm_client import OllamaLLMClient

        client = OllamaLLMClient(config={})
        assert client.base_url == "http://localhost:11434"
        assert client.model == "llama3.2"

    def test_custom_config(self) -> None:
        """커스텀 설정으로 초기화"""
        from app.lib.llm_client import OllamaLLMClient

        config = {
            "base_url": "http://myserver:11434",
            "model": "mistral",
        }
        client = OllamaLLMClient(config=config)
        assert client.base_url == "http://myserver:11434"
        assert client.model == "mistral"

    def test_provider_in_registry(self) -> None:
        """레지스트리에 ollama 등록 확인"""
        from app.lib.llm_client import LLMClientFactory

        assert "ollama" in LLMClientFactory._PROVIDER_REGISTRY

    def test_env_var_in_mapping(self) -> None:
        """환경변수 매핑에 ollama 등록 확인"""
        from app.lib.llm_client import LLMClientFactory

        assert "ollama" in LLMClientFactory._ENV_VAR_MAPPING
        assert LLMClientFactory._ENV_VAR_MAPPING["ollama"] == "OLLAMA_BASE_URL"


class TestOllamaLLMClientGenerate:
    """OllamaLLMClient 텍스트 생성 테스트"""

    @pytest.mark.asyncio
    async def test_generate_text(self) -> None:
        """generate_text 호출 검증"""
        from app.lib.llm_client import OllamaLLMClient

        client = OllamaLLMClient(config={})

        # OpenAI 클라이언트 Mock
        mock_openai = MagicMock()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content="테스트 응답"))]
        mock_response.usage = MagicMock(total_tokens=50)
        mock_openai.chat.completions.create.return_value = mock_response

        client._client = mock_openai

        result = await client.generate_text("안녕하세요")
        assert result == "테스트 응답"

    @pytest.mark.asyncio
    async def test_generate_text_with_system_prompt(self) -> None:
        """시스템 프롬프트 포함 생성"""
        from app.lib.llm_client import OllamaLLMClient

        client = OllamaLLMClient(config={})

        mock_openai = MagicMock()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content="응답"))]
        mock_response.usage = MagicMock(total_tokens=30)
        mock_openai.chat.completions.create.return_value = mock_response

        client._client = mock_openai

        result = await client.generate_text(
            "질문", system_prompt="당신은 AI입니다.",
        )

        # system prompt가 messages에 포함되었는지 확인
        call_args = mock_openai.chat.completions.create.call_args
        messages = call_args.kwargs.get("messages", call_args[1].get("messages", []))
        assert any(m["role"] == "system" for m in messages)


class TestOllamaLLMClientHealthCheck:
    """OllamaLLMClient 헬스 체크 테스트"""

    @pytest.mark.asyncio
    async def test_health_check_success(self) -> None:
        """헬스 체크 성공"""
        from app.lib.llm_client import OllamaLLMClient

        client = OllamaLLMClient(config={})

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"models": []}
            mock_client.get.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_class.return_value = mock_client

            result = await client.health_check()
            assert result is True

    @pytest.mark.asyncio
    async def test_health_check_failure(self) -> None:
        """헬스 체크 실패 (서버 미응답)"""
        from app.lib.llm_client import OllamaLLMClient

        client = OllamaLLMClient(config={})

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.get.side_effect = Exception("Connection refused")
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_class.return_value = mock_client

            result = await client.health_check()
            assert result is False


class TestOllamaLLMClientListModels:
    """OllamaLLMClient 모델 목록 테스트"""

    @pytest.mark.asyncio
    async def test_list_models(self) -> None:
        """설치된 모델 목록 반환"""
        from app.lib.llm_client import OllamaLLMClient

        client = OllamaLLMClient(config={})

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "models": [
                    {"name": "llama3.2"},
                    {"name": "mistral"},
                ],
            }
            mock_client.get.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_class.return_value = mock_client

            models = await client.list_models()
            assert "llama3.2" in models
            assert "mistral" in models
