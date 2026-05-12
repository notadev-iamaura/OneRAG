"""
Generation Module 폴백 체인 테스트

테스트 범위:
1. 단일 모델 실패 시 다음 모델로 폴백
2. 모든 모델 실패 시 GenerationError 발생
3. 폴백 체인 순서 검증 (sonnet → gemini → gpt → haiku)
"""
from unittest.mock import MagicMock, patch

import pytest

from app.lib.errors import ErrorCode, GenerationError
from app.modules.core.generation.generator import GenerationModule


@pytest.mark.unit
class TestGeneratorFallback:
    """Fallback 체인 테스트"""

    @pytest.fixture
    def generator(self):
        """Generator 인스턴스 생성"""
        config = {
            "generation": {
                "default_model": "anthropic/claude-sonnet-4.5",
                "fallback_models": ["google/gemini-2.5-flash", "openai/gpt-4.1", "anthropic/claude-3.5-haiku"],
                "timeout": 30.0,
            }
        }
        # Mock PromptManager
        mock_prompt_manager = MagicMock()
        return GenerationModule(config=config, prompt_manager=mock_prompt_manager)

    @pytest.mark.asyncio
    async def test_fallback_to_second_model_on_first_failure(self, generator):
        """
        첫 번째 모델 실패 시 두 번째 모델로 폴백

        Given: anthropic/claude-sonnet-4.5 모델이 실패
        When: generate_answer() 호출
        Then: google/gemini-2.5-flash로 폴백하여 성공
        """
        # Mock: 첫 번째 모델 실패, 두 번째 모델 성공
        with patch.object(generator, "_generate_with_model") as mock_gen:
            # 첫 번째 호출(claude) 실패
            mock_gen.side_effect = [
                GenerationError(ErrorCode.GENERATION_TIMEOUT),
                # 두 번째 호출(gemini) 성공
                MagicMock(answer="폴백 성공", model_used="google/gemini-2.5-flash"),
            ]

            result = await generator.generate_answer(
                query="테스트 쿼리",
                context_documents=[],
                options=None,
            )

            # 검증: gemini 모델로 성공
            assert result.answer == "폴백 성공"
            assert result.model_used == "google/gemini-2.5-flash"
            assert mock_gen.call_count == 2  # claude 실패 → gemini 성공

    @pytest.mark.asyncio
    async def test_all_models_fail_raises_generation_error(self, generator):
        """
        모든 모델 실패 시 GenerationError 발생

        Given: 모든 폴백 모델이 실패
        When: generate_answer() 호출
        Then: GenerationError 발생
        """
        with patch.object(generator, "_generate_with_model") as mock_gen:
            # 모든 모델 실패
            mock_gen.side_effect = [
                GenerationError(ErrorCode.GENERATION_TIMEOUT),
                GenerationError(ErrorCode.GENERATION_REQUEST_FAILED),
                GenerationError(ErrorCode.GENERATION_REQUEST_FAILED),
                GenerationError(ErrorCode.GENERATION_REQUEST_FAILED),
            ]

            with pytest.raises(RuntimeError) as exc_info:
                await generator.generate_answer(
                    query="테스트 쿼리",
                    context_documents=[],
                    options=None,
                )

            # 검증: 스펙에서 요구하는 에러 메시지 패턴
            error_msg = str(exc_info.value)
            assert "답변 생성 실패" in error_msg
            assert "해결 방법" in error_msg
            assert "API 키를 확인" in error_msg
            assert mock_gen.call_count == 4  # 4개 모델 모두 시도
