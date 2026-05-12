"""
Generation Module 에러 처리 테스트

테스트 범위:
1. 타임아웃 에러 처리
2. Rate Limiting 에러 처리 및 재시도
3. Privacy 마스킹 실패 처리
"""
from unittest.mock import MagicMock, patch

import pytest

from app.lib.errors import ErrorCode, GenerationError
from app.modules.core.generation.generator import GenerationModule


@pytest.mark.unit
class TestGeneratorErrors:
    """에러 처리 테스트"""

    @pytest.fixture
    def generator(self):
        """Generator 인스턴스 생성"""
        config = {
            "generation": {
                "default_model": "anthropic/claude-sonnet-4.5",
                "fallback_models": ["google/gemini-2.5-flash", "openai/gpt-4.1", "anthropic/claude-3.5-haiku"],
                "timeout": 2.0,  # 짧은 타임아웃 (테스트용)
            }
        }
        # Mock PromptManager
        prompt_manager = MagicMock()
        return GenerationModule(config=config, prompt_manager=prompt_manager)

    @pytest.mark.asyncio
    async def test_timeout_error_handling(self, generator):
        """
        LLM API 타임아웃 에러 처리

        Given: LLM API가 타임아웃 초과
        When: generate_answer() 호출
        Then: 타임아웃 에러 발생 시 다음 모델로 폴백
        """
        with patch.object(generator, "_generate_with_model") as mock_gen:
            # Mock: 첫 번째 모델 타임아웃 → 두 번째 모델 성공
            mock_gen.side_effect = [
                GenerationError(ErrorCode.GENERATION_TIMEOUT, timeout_seconds=2),
                MagicMock(answer="타임아웃 후 폴백 성공", model_used="google/gemini-2.5-flash"),
            ]

            result = await generator.generate_answer(
                query="테스트 쿼리",
                context_documents=[],
                options=None,
            )

            # 검증: 타임아웃 후 폴백 성공
            assert result.answer == "타임아웃 후 폴백 성공"
            assert result.model_used == "google/gemini-2.5-flash"
            assert mock_gen.call_count == 2  # 타임아웃 → 폴백

    @pytest.mark.asyncio
    async def test_rate_limiting_error_handling(self, generator):
        """
        Rate Limiting 에러 처리

        Given: OpenRouter API가 429 에러 반환
        When: generate_answer() 호출
        Then: 재시도 후 성공
        """
        from openai import RateLimitError

        with patch.object(generator, "_generate_with_model") as mock_gen:
            # Mock: 첫 시도 429 에러 → 두 번째 시도 성공
            mock_gen.side_effect = [
                RateLimitError(
                    "Rate limit exceeded",
                    response=MagicMock(status_code=429),
                    body=None,
                ),
                MagicMock(answer="재시도 성공", model_used="anthropic/claude-sonnet-4.5"),
            ]

            result = await generator.generate_answer(
                query="테스트 쿼리",
                context_documents=[],
                options=None,
            )

            # 검증: 재시도 성공
            assert result.answer == "재시도 성공"
            assert mock_gen.call_count == 2  # 재시도 1회
