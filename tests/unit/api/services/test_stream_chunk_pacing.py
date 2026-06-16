"""서버사이드 SSE 청크 페이싱 테스트 (GAP #5)

목적:
    연속 LLM chunk burst가 SSE에 한꺼번에 flush되지 않도록
    `rag.streaming.chunk_min_interval_seconds`(기본 0.0=무동작)로
    최소 간격을 강제하는지 검증한다.

회귀 안전판:
    기본값(0.0)에서는 sleep 호출이 전혀 없어야 한다(opt-in, 회귀 0).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.api.services.chat_service import ChatService


class TestStreamChunkPacingConfig:
    """페이싱 설정 정규화 및 _pace_stream_chunk 단위 동작 테스트"""

    def test_default_min_interval_is_zero(self) -> None:
        """설정이 없으면 chunk_min_interval_seconds 기본값은 0.0(무동작)이다."""
        service = ChatService({}, {})
        assert service.stream_chunk_min_interval_seconds == 0.0

    def test_reads_min_interval_from_config(self) -> None:
        """rag.streaming.chunk_min_interval_seconds를 설정에서 읽는다."""
        config = {"rag": {"streaming": {"chunk_min_interval_seconds": 0.05}}}
        service = ChatService({}, config)
        assert service.stream_chunk_min_interval_seconds == pytest.approx(0.05)

    def test_negative_or_invalid_interval_coerced_to_zero(self) -> None:
        """음수/비정상 값은 0.0으로 정규화된다(회귀 안전판)."""
        for bad in (-1.0, "bad", None):
            config = {"rag": {"streaming": {"chunk_min_interval_seconds": bad}}}
            service = ChatService({}, config)
            assert service.stream_chunk_min_interval_seconds == 0.0

    @pytest.mark.asyncio
    async def test_pace_stream_chunk_no_sleep_when_interval_zero(self) -> None:
        """간격이 0이면 sleep 훅을 호출하지 않는다(opt-in 무동작)."""
        service = ChatService({}, {})
        service._sleep_for_stream_pacing = AsyncMock()  # type: ignore[method-assign]

        last = await service._pace_stream_chunk(None)
        last = await service._pace_stream_chunk(last)

        service._sleep_for_stream_pacing.assert_not_called()

    @pytest.mark.asyncio
    async def test_pace_stream_chunk_sleeps_when_interval_positive(self) -> None:
        """간격이 양수이고 직전 전송이 최근이면 차이만큼 sleep 한다."""
        config = {"rag": {"streaming": {"chunk_min_interval_seconds": 10.0}}}
        service = ChatService({}, config)
        service._sleep_for_stream_pacing = AsyncMock()  # type: ignore[method-assign]

        import time

        # 직전 전송이 방금(=elapsed≈0)이라면 거의 interval만큼 sleep 해야 한다.
        now = time.monotonic()
        await service._pace_stream_chunk(now)

        service._sleep_for_stream_pacing.assert_awaited_once()
        delay = service._sleep_for_stream_pacing.await_args.args[0]
        assert delay > 0

    @pytest.mark.asyncio
    async def test_pace_stream_chunk_first_chunk_no_sleep(self) -> None:
        """첫 청크(last_sent_at=None)는 간격이 양수여도 sleep 하지 않는다."""
        config = {"rag": {"streaming": {"chunk_min_interval_seconds": 10.0}}}
        service = ChatService({}, config)
        service._sleep_for_stream_pacing = AsyncMock()  # type: ignore[method-assign]

        await service._pace_stream_chunk(None)

        service._sleep_for_stream_pacing.assert_not_called()


class TestStreamPipelinePacingIntegration:
    """stream_rag_pipeline 토큰 방출 루프에서 페이싱이 적용되는지 통합 검증"""

    @staticmethod
    def _build_modules():
        mock_session = MagicMock()
        mock_session.get_session = AsyncMock(return_value={"is_valid": True})
        mock_session.get_context_string = AsyncMock(return_value="")
        mock_session.create_session = AsyncMock(return_value={"session_id": "test-123"})
        mock_session.add_conversation = AsyncMock()

        mock_generation = MagicMock()

        async def mock_stream(*args, **kwargs):
            yield "첫"
            yield "둘"
            yield "셋"

        mock_generation.stream_answer = mock_stream

        mock_doc = MagicMock()
        mock_doc.metadata = {"source": "test.pdf"}
        mock_doc.content = "테스트"
        mock_doc.page_content = "테스트"
        mock_retrieval = MagicMock()
        mock_retrieval.search = AsyncMock(return_value=[mock_doc])

        return {
            "session": mock_session,
            "generation": mock_generation,
            "retrieval": mock_retrieval,
        }

    @pytest.mark.asyncio
    async def test_pipeline_paces_each_chunk_when_enabled(self) -> None:
        """간격 활성화 시 각 청크 전송마다 페이서를 호출한다."""
        service = ChatService(
            self._build_modules(),
            {"rag": {"streaming": {"chunk_min_interval_seconds": 0.02}}},
        )
        # 실제 sleep 비용 없이 호출 횟수만 검증.
        service._sleep_for_stream_pacing = AsyncMock()  # type: ignore[method-assign]

        events = [
            e
            async for e in service.stream_rag_pipeline("테스트", "test-123")
        ]
        chunks = [e for e in events if e.get("event") == "chunk"]
        assert len(chunks) == 3
        # 첫 청크 제외 최소 2회 이상 sleep 호출(직전 전송이 최근이므로).
        assert service._sleep_for_stream_pacing.await_count >= 2

    @pytest.mark.asyncio
    async def test_pipeline_no_pacing_when_disabled(self) -> None:
        """기본값(0.0)에서는 sleep 훅이 전혀 호출되지 않는다(회귀 0)."""
        service = ChatService(self._build_modules(), {})
        service._sleep_for_stream_pacing = AsyncMock()  # type: ignore[method-assign]

        events = [
            e
            async for e in service.stream_rag_pipeline("테스트", "test-123")
        ]
        chunks = [e for e in events if e.get("event") == "chunk"]
        assert len(chunks) == 3
        service._sleep_for_stream_pacing.assert_not_called()
