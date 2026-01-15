"""
스트리밍 스키마 테스트

SSE(Server-Sent Events) 기반 스트리밍 응답을 위한 Pydantic 모델 테스트
TDD 방식: 먼저 테스트 작성 후 구현
"""

import pytest
from pydantic import ValidationError


class TestStreamChatRequest:
    """StreamChatRequest 스키마 테스트"""

    def test_valid_request_with_message_only(self):
        """메시지만 있는 유효한 요청"""
        from app.api.schemas.streaming import StreamChatRequest

        request = StreamChatRequest(message="테스트 질문입니다")

        assert request.message == "테스트 질문입니다"
        assert request.session_id is None
        assert request.options is None

    def test_valid_request_with_session_id(self):
        """세션 ID 포함 요청"""
        from app.api.schemas.streaming import StreamChatRequest

        request = StreamChatRequest(
            message="테스트 질문입니다",
            session_id="test-session-123",
        )

        assert request.message == "테스트 질문입니다"
        assert request.session_id == "test-session-123"

    def test_valid_request_with_options(self):
        """옵션 포함 요청"""
        from app.api.schemas.streaming import StreamChatRequest

        request = StreamChatRequest(
            message="테스트 질문입니다",
            options={"temperature": 0.7, "max_tokens": 1000},
        )

        assert request.options == {"temperature": 0.7, "max_tokens": 1000}

    def test_invalid_empty_message(self):
        """빈 메시지는 거부됨"""
        from app.api.schemas.streaming import StreamChatRequest

        with pytest.raises(ValidationError):
            StreamChatRequest(message="")

    def test_invalid_message_too_long(self):
        """너무 긴 메시지는 거부됨 (10000자 초과)"""
        from app.api.schemas.streaming import StreamChatRequest

        with pytest.raises(ValidationError):
            StreamChatRequest(message="a" * 10001)

    def test_valid_max_length_message(self):
        """최대 길이 메시지는 허용됨 (10000자)"""
        from app.api.schemas.streaming import StreamChatRequest

        request = StreamChatRequest(message="a" * 10000)
        assert len(request.message) == 10000


class TestStreamChunkEvent:
    """StreamChunkEvent 스키마 테스트"""

    def test_valid_chunk_event(self):
        """유효한 청크 이벤트 생성"""
        from app.api.schemas.streaming import StreamChunkEvent

        event = StreamChunkEvent(
            data="안녕하세요",
            chunk_index=0,
        )

        assert event.event == "chunk"
        assert event.data == "안녕하세요"
        assert event.chunk_index == 0

    def test_chunk_index_sequence(self):
        """청크 인덱스 순서 테스트"""
        from app.api.schemas.streaming import StreamChunkEvent

        events = [
            StreamChunkEvent(data="첫번째", chunk_index=0),
            StreamChunkEvent(data="두번째", chunk_index=1),
            StreamChunkEvent(data="세번째", chunk_index=2),
        ]

        for i, event in enumerate(events):
            assert event.chunk_index == i

    def test_invalid_negative_chunk_index(self):
        """음수 청크 인덱스는 거부됨"""
        from app.api.schemas.streaming import StreamChunkEvent

        with pytest.raises(ValidationError):
            StreamChunkEvent(data="테스트", chunk_index=-1)

    def test_event_type_is_chunk(self):
        """이벤트 타입은 항상 'chunk'"""
        from app.api.schemas.streaming import StreamChunkEvent

        event = StreamChunkEvent(data="테스트", chunk_index=0)
        assert event.event == "chunk"


class TestStreamDoneEvent:
    """StreamDoneEvent 스키마 테스트"""

    def test_valid_done_event(self):
        """유효한 완료 이벤트 생성"""
        from app.api.schemas.streaming import StreamDoneEvent

        event = StreamDoneEvent(
            session_id="test-123",
            message_id="msg-456",
            total_chunks=10,
            tokens_used=150,
        )

        assert event.event == "done"
        assert event.session_id == "test-123"
        assert event.message_id == "msg-456"
        assert event.total_chunks == 10
        assert event.tokens_used == 150

    def test_done_event_with_all_fields(self):
        """모든 필드를 포함한 완료 이벤트"""
        from app.api.schemas.streaming import StreamDoneEvent

        event = StreamDoneEvent(
            session_id="test-123",
            message_id="msg-456",
            total_chunks=10,
            tokens_used=150,
            processing_time=1.5,
            sources=[{"id": 1, "document": "test.pdf"}],
        )

        assert event.processing_time == 1.5
        assert len(event.sources) == 1
        assert event.sources[0]["document"] == "test.pdf"

    def test_done_event_default_values(self):
        """기본값 테스트"""
        from app.api.schemas.streaming import StreamDoneEvent

        event = StreamDoneEvent(
            session_id="test-123",
            message_id="msg-456",
            total_chunks=5,
        )

        assert event.tokens_used == 0
        assert event.processing_time == 0.0
        assert event.sources == []

    def test_invalid_negative_total_chunks(self):
        """음수 총 청크 수는 거부됨"""
        from app.api.schemas.streaming import StreamDoneEvent

        with pytest.raises(ValidationError):
            StreamDoneEvent(
                session_id="test-123",
                message_id="msg-456",
                total_chunks=-1,
            )


class TestStreamErrorEvent:
    """StreamErrorEvent 스키마 테스트"""

    def test_valid_error_event(self):
        """유효한 에러 이벤트 생성"""
        from app.api.schemas.streaming import StreamErrorEvent

        event = StreamErrorEvent(
            error_code="GEN-001",
            message="AI 모델 응답이 지연되고 있습니다.",
        )

        assert event.event == "error"
        assert event.error_code == "GEN-001"
        assert event.message == "AI 모델 응답이 지연되고 있습니다."
        assert event.suggestion is None

    def test_error_event_with_suggestion(self):
        """해결 방법 포함 에러 이벤트"""
        from app.api.schemas.streaming import StreamErrorEvent

        event = StreamErrorEvent(
            error_code="SEARCH-003",
            message="검색 결과를 찾을 수 없습니다.",
            suggestion="검색어를 다시 확인해 주세요.",
        )

        assert event.suggestion == "검색어를 다시 확인해 주세요."

    def test_event_type_is_error(self):
        """이벤트 타입은 항상 'error'"""
        from app.api.schemas.streaming import StreamErrorEvent

        event = StreamErrorEvent(
            error_code="TEST-001",
            message="테스트 에러",
        )
        assert event.event == "error"


class TestStreamEventSerialization:
    """스트리밍 이벤트 직렬화 테스트"""

    def test_chunk_event_to_json(self):
        """청크 이벤트 JSON 직렬화"""
        from app.api.schemas.streaming import StreamChunkEvent

        event = StreamChunkEvent(data="안녕", chunk_index=0)
        json_str = event.model_dump_json()

        assert '"event":"chunk"' in json_str
        assert '"data":"안녕"' in json_str

    def test_done_event_to_dict(self):
        """완료 이벤트 딕셔너리 변환"""
        from app.api.schemas.streaming import StreamDoneEvent

        event = StreamDoneEvent(
            session_id="test-123",
            message_id="msg-456",
            total_chunks=5,
        )
        data = event.model_dump()

        assert data["event"] == "done"
        assert data["session_id"] == "test-123"
        assert isinstance(data, dict)

    def test_error_event_to_sse_format(self):
        """에러 이벤트 SSE 형식 변환"""
        from app.api.schemas.streaming import StreamErrorEvent

        event = StreamErrorEvent(
            error_code="TEST-001",
            message="테스트 에러",
        )
        # SSE 형식: data: {json}\n\n
        sse_line = f"data: {event.model_dump_json()}\n\n"

        assert sse_line.startswith("data: ")
        assert sse_line.endswith("\n\n")
