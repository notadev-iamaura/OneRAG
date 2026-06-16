"""스트리밍 검색 0건 안내 메시지 외부화 테스트

목적:
    stream_rag_pipeline에서 검색 결과가 0건일 때 사용자에게 chunk로 내보내는
    안내 메시지를 rag.generation_fallback.no_documents_message로 외부화했는지,
    그리고 미설정 시 코드 내장 한국어 기본값으로 회귀 0을 보장하는지 검증한다.

회귀 안전판:
    config 미설정/null/공백이면 기존 한국어 하드코딩 문구와 byte 동치여야 한다.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.api.services.chat_service import (
    STREAM_NO_DOCUMENTS_MESSAGE,
    ChatService,
)

# 외부화 이전 코드에 하드코딩되어 있던 원본 한국어 문구(회귀 0 단언 기준).
LEGACY_KOREAN_MESSAGE = (
    "관련 문서를 찾을 수 없습니다. 문서를 업로드했는지 확인하거나 "
    "질문을 바꿔 다시 시도해주세요."
)


class TestStreamNoDocumentsMessageResolution:
    """초기화 시 안내 메시지 해소(config 우선, 미설정 시 기본값) 단위 검증"""

    def test_default_matches_legacy_korean(self) -> None:
        """코드 내장 기본 상수가 외부화 이전 하드코딩 문구와 byte 동치다(회귀 0)."""
        assert STREAM_NO_DOCUMENTS_MESSAGE == LEGACY_KOREAN_MESSAGE

    def test_unset_uses_korean_default(self) -> None:
        """config 미설정이면 한국어 기본 안내 문구를 사용한다(회귀 0)."""
        service = ChatService({}, {})
        assert service.stream_no_documents_message == LEGACY_KOREAN_MESSAGE

    def test_null_uses_korean_default(self) -> None:
        """no_documents_message가 null(None)이면 한국어 기본값으로 회귀한다."""
        config = {"rag": {"generation_fallback": {"no_documents_message": None}}}
        service = ChatService({}, config)
        assert service.stream_no_documents_message == LEGACY_KOREAN_MESSAGE

    def test_blank_uses_korean_default(self) -> None:
        """공백만 있는 값은 무효로 보아 한국어 기본값으로 회귀한다."""
        config = {"rag": {"generation_fallback": {"no_documents_message": "   "}}}
        service = ChatService({}, config)
        assert service.stream_no_documents_message == LEGACY_KOREAN_MESSAGE

    def test_non_dict_generation_fallback_uses_default(self) -> None:
        """generation_fallback이 dict가 아니어도 안전하게 기본값으로 회귀한다."""
        config = {"rag": {"generation_fallback": "broken"}}
        service = ChatService({}, config)
        assert service.stream_no_documents_message == LEGACY_KOREAN_MESSAGE

    def test_override_is_applied(self) -> None:
        """config 주입 시 해당 문구로 오버라이드된다(타 언어/도메인 전환)."""
        override = "No relevant documents found. Please upload documents or rephrase."
        config = {"rag": {"generation_fallback": {"no_documents_message": override}}}
        service = ChatService({}, config)
        assert service.stream_no_documents_message == override


class TestStreamNoDocumentsPipeline:
    """stream_rag_pipeline 검색 0건 분기에서 안내 메시지가 chunk로 방출되는지 통합 검증"""

    @staticmethod
    def _build_empty_retrieval_modules() -> dict[str, object]:
        """검색이 0건을 반환하도록 구성한 모듈 딕셔너리.

        retrieval.search가 빈 리스트를 반환하면 reranked_documents가 비어
        no-documents 안내 분기로 진입한다. generation 모듈은 의도적으로 제외해
        스트리밍 생성 분기로 새지 않게 한다.
        """
        mock_session = MagicMock()
        mock_session.get_session = AsyncMock(return_value={"is_valid": True})
        mock_session.get_context_string = AsyncMock(return_value="")
        mock_session.create_session = AsyncMock(return_value={"session_id": "test-123"})

        mock_retrieval = MagicMock()
        mock_retrieval.search = AsyncMock(return_value=[])

        return {
            "session": mock_session,
            "retrieval": mock_retrieval,
        }

    @pytest.mark.asyncio
    async def test_default_message_emitted_when_no_documents(self) -> None:
        """config 미설정 시 한국어 기본 안내 문구가 chunk로 방출된다(회귀 0)."""
        service = ChatService(self._build_empty_retrieval_modules(), {})

        events = [e async for e in service.stream_rag_pipeline("테스트", "test-123")]
        chunks = [e for e in events if e.get("event") == "chunk"]

        assert len(chunks) == 1
        assert chunks[0]["data"] == LEGACY_KOREAN_MESSAGE

    @pytest.mark.asyncio
    async def test_override_message_emitted_when_no_documents(self) -> None:
        """config 주입 시 오버라이드된 안내 문구가 chunk로 방출된다."""
        override = "No relevant documents found. Please upload documents or rephrase."
        config = {"rag": {"generation_fallback": {"no_documents_message": override}}}
        service = ChatService(self._build_empty_retrieval_modules(), config)

        events = [e async for e in service.stream_rag_pipeline("test", "test-123")]
        chunks = [e for e in events if e.get("event") == "chunk"]

        assert len(chunks) == 1
        assert chunks[0]["data"] == override
