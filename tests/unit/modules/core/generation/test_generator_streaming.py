"""
GenerationModule 스트리밍 기능 테스트

TDD 방식으로 stream_answer 메서드 구현을 위한 테스트.
기존 generate_answer()와 유사하지만, 청크 단위로 응답을 yield하는 방식.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestGenerationModuleStreaming:
    """GenerationModule 스트리밍 테스트"""

    @pytest.mark.asyncio
    async def test_stream_answer_yields_chunks(self):
        """stream_answer가 청크를 yield하는지 확인"""
        from app.modules.core.generation.generator import GenerationModule

        # Mock PromptManager
        mock_prompt_manager = MagicMock()
        mock_prompt_manager.get_prompt_content = AsyncMock(
            return_value="당신은 도움이 되는 AI 어시스턴트입니다."
        )

        # GenerationModule 생성 (최소 설정)
        config = {
            "generation": {
                "openrouter": {
                    "api_key": "test-key",
                    "default_model": "test/model",
                },
            }
        }
        generator = GenerationModule(
            config=config,
            prompt_manager=mock_prompt_manager,
        )

        # Mock OpenAI 클라이언트 - 스트리밍 응답
        mock_client = MagicMock()
        generator.client = mock_client

        # 스트리밍 응답 시뮬레이션
        async def mock_stream_response():
            """스트리밍 응답 시뮬레이터"""
            chunks = ["안녕", "하세요", "!"]
            for chunk_text in chunks:
                # OpenAI Streaming 형식 모방
                mock_choice = MagicMock()
                mock_choice.delta = MagicMock()
                mock_choice.delta.content = chunk_text
                mock_choice.finish_reason = None

                mock_chunk = MagicMock()
                mock_chunk.choices = [mock_choice]
                yield mock_chunk

            # 마지막 청크 (finish_reason 포함)
            mock_final_choice = MagicMock()
            mock_final_choice.delta = MagicMock()
            mock_final_choice.delta.content = None
            mock_final_choice.finish_reason = "stop"

            mock_final_chunk = MagicMock()
            mock_final_chunk.choices = [mock_final_choice]
            yield mock_final_chunk

        # stream 메서드 패치
        mock_stream = MagicMock()
        mock_stream.__aiter__ = lambda self: mock_stream_response()
        mock_client.chat.completions.create.return_value = mock_stream

        # 스트리밍 호출
        chunks = []
        async for chunk in generator.stream_answer(
            query="테스트 질문",
            context_documents=[{"content": "테스트 컨텍스트"}],
        ):
            chunks.append(chunk)

        # 검증
        assert chunks == ["안녕", "하세요", "!"]

    @pytest.mark.asyncio
    async def test_stream_answer_handles_empty_context(self):
        """빈 컨텍스트로 스트리밍 시 에러 처리 확인"""
        from app.modules.core.generation.generator import GenerationModule

        # Mock PromptManager
        mock_prompt_manager = MagicMock()
        mock_prompt_manager.get_prompt_content = AsyncMock(
            return_value="당신은 도움이 되는 AI 어시스턴트입니다."
        )

        # GenerationModule 생성
        config = {
            "generation": {
                "openrouter": {
                    "api_key": "test-key",
                },
            }
        }
        generator = GenerationModule(
            config=config,
            prompt_manager=mock_prompt_manager,
        )
        generator.client = MagicMock()

        # 빈 컨텍스트로 호출 시 ValueError 예상
        with pytest.raises(ValueError, match="검색된 문서가 없습니다"):
            async for _ in generator.stream_answer(
                query="테스트 질문",
                context_documents=[],
            ):
                pass

    @pytest.mark.asyncio
    async def test_stream_answer_without_client_raises_error(self):
        """클라이언트 초기화 없이 스트리밍 시 RuntimeError 발생 확인"""
        from app.modules.core.generation.generator import GenerationModule

        # Mock PromptManager
        mock_prompt_manager = MagicMock()

        # GenerationModule 생성 (클라이언트 없음)
        config = {"generation": {}}
        generator = GenerationModule(
            config=config,
            prompt_manager=mock_prompt_manager,
        )

        # 클라이언트 없이 호출 시 RuntimeError 예상
        with pytest.raises(RuntimeError, match="클라이언트가 초기화되지 않았습니다"):
            async for _ in generator.stream_answer(
                query="테스트",
                context_documents=[{"content": "컨텍스트"}],
            ):
                pass

    @pytest.mark.asyncio
    async def test_stream_answer_applies_privacy_masking(self):
        """스트리밍 시 개인정보 마스킹 적용 확인"""
        from app.modules.core.generation.generator import GenerationModule

        # Mock PromptManager
        mock_prompt_manager = MagicMock()
        mock_prompt_manager.get_prompt_content = AsyncMock(
            return_value="시스템 프롬프트"
        )

        # Mock PrivacyMasker
        mock_privacy_masker = MagicMock()

        def mask_chunk(text):
            """청크에서 전화번호 마스킹"""
            if "010-1234-5678" in text:
                return text.replace("010-1234-5678", "010-****-5678")
            return text

        mock_privacy_masker.mask_text = mask_chunk

        # GenerationModule 생성 (개인정보 마스커 포함)
        config = {
            "generation": {
                "openrouter": {
                    "api_key": "test-key",
                },
            }
        }
        generator = GenerationModule(
            config=config,
            prompt_manager=mock_prompt_manager,
            privacy_masker=mock_privacy_masker,
        )

        # Mock 클라이언트
        mock_client = MagicMock()
        generator.client = mock_client

        # 전화번호가 포함된 스트리밍 응답
        async def mock_stream_with_phone():
            chunks = ["전화번호는 ", "010-1234-5678", "입니다."]
            for chunk_text in chunks:
                mock_choice = MagicMock()
                mock_choice.delta = MagicMock()
                mock_choice.delta.content = chunk_text
                mock_choice.finish_reason = None

                mock_chunk = MagicMock()
                mock_chunk.choices = [mock_choice]
                yield mock_chunk

            # 마지막
            mock_final_choice = MagicMock()
            mock_final_choice.delta.content = None
            mock_final_choice.finish_reason = "stop"
            mock_final = MagicMock()
            mock_final.choices = [mock_final_choice]
            yield mock_final

        mock_stream = MagicMock()
        mock_stream.__aiter__ = lambda self: mock_stream_with_phone()
        mock_client.chat.completions.create.return_value = mock_stream

        # 스트리밍 호출
        chunks = []
        async for chunk in generator.stream_answer(
            query="전화번호 알려줘",
            context_documents=[{"content": "연락처: 010-1234-5678"}],
        ):
            chunks.append(chunk)

        # 마스킹 확인 (전화번호가 포함된 청크가 마스킹됨)
        full_response = "".join(chunks)
        assert "010-****-5678" in full_response or "010-1234-5678" not in full_response

    @pytest.mark.asyncio
    async def test_stream_answer_with_options(self):
        """옵션이 스트리밍에 올바르게 전달되는지 확인"""
        from app.modules.core.generation.generator import GenerationModule

        # Mock PromptManager
        mock_prompt_manager = MagicMock()
        mock_prompt_manager.get_prompt_content = AsyncMock(
            return_value="시스템 프롬프트"
        )

        # GenerationModule 생성
        config = {
            "generation": {
                "openrouter": {
                    "api_key": "test-key",
                },
            }
        }
        generator = GenerationModule(
            config=config,
            prompt_manager=mock_prompt_manager,
        )

        # Mock 클라이언트
        mock_client = MagicMock()
        generator.client = mock_client

        # 스트리밍 응답
        async def mock_stream():
            mock_choice = MagicMock()
            mock_choice.delta.content = "응답"
            mock_choice.finish_reason = None

            mock_chunk = MagicMock()
            mock_chunk.choices = [mock_choice]
            yield mock_chunk

            # 종료
            mock_final_choice = MagicMock()
            mock_final_choice.delta.content = None
            mock_final_choice.finish_reason = "stop"
            mock_final = MagicMock()
            mock_final.choices = [mock_final_choice]
            yield mock_final

        mock_stream_obj = MagicMock()
        mock_stream_obj.__aiter__ = lambda self: mock_stream()
        mock_client.chat.completions.create.return_value = mock_stream_obj

        # 옵션과 함께 호출
        options = {
            "model": "anthropic/claude-sonnet-4",
            "temperature": 0.5,
            "max_tokens": 1000,
        }

        chunks = []
        async for chunk in generator.stream_answer(
            query="테스트",
            context_documents=[{"content": "컨텍스트"}],
            options=options,
        ):
            chunks.append(chunk)

        # API 호출 확인
        mock_client.chat.completions.create.assert_called_once()
        call_kwargs = mock_client.chat.completions.create.call_args[1]

        # stream=True 확인
        assert call_kwargs.get("stream") is True
        # 모델 확인
        assert call_kwargs.get("model") == "anthropic/claude-sonnet-4"
