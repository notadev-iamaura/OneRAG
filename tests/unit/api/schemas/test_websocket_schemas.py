"""
WebSocket 스키마 테스트

WebSocket 기반 실시간 스트리밍 통신을 위한 Pydantic 모델 테스트.
TDD 방식: 테스트를 먼저 작성하고 구현을 진행함.

테스트 대상 스키마:
- ClientMessage: 클라이언트 → 서버 메시지
- StreamStartEvent: 스트리밍 시작 이벤트
- StreamTokenEvent: 토큰 스트리밍 이벤트
- StreamSourcesEvent: 소스 전송 이벤트
- StreamEndEvent: 스트리밍 종료 이벤트
- StreamErrorEvent: 에러 이벤트
"""

import pytest
from pydantic import ValidationError


class TestClientMessage:
    """ClientMessage 스키마 테스트 - 클라이언트에서 서버로 전송되는 메시지"""

    def test_valid_client_message(self):
        """유효한 클라이언트 메시지 생성"""
        from app.api.schemas.websocket import ClientMessage

        msg = ClientMessage(
            message_id="msg-001",
            content="안녕하세요, 질문이 있습니다.",
            session_id="session-abc-123",
        )

        assert msg.type == "message"
        assert msg.message_id == "msg-001"
        assert msg.content == "안녕하세요, 질문이 있습니다."
        assert msg.session_id == "session-abc-123"

    def test_type_is_always_message(self):
        """type 필드는 항상 'message'"""
        from app.api.schemas.websocket import ClientMessage

        msg = ClientMessage(
            message_id="msg-002",
            content="테스트",
            session_id="session-123",
        )
        assert msg.type == "message"

    def test_missing_message_id_raises_error(self):
        """message_id 필수 필드 누락 시 ValidationError"""
        from app.api.schemas.websocket import ClientMessage

        with pytest.raises(ValidationError) as exc_info:
            ClientMessage(
                content="내용",
                session_id="session-123",
            )
        assert "message_id" in str(exc_info.value)

    def test_missing_content_raises_error(self):
        """content 필수 필드 누락 시 ValidationError"""
        from app.api.schemas.websocket import ClientMessage

        with pytest.raises(ValidationError) as exc_info:
            ClientMessage(
                message_id="msg-001",
                session_id="session-123",
            )
        assert "content" in str(exc_info.value)

    def test_missing_session_id_raises_error(self):
        """session_id 필수 필드 누락 시 ValidationError"""
        from app.api.schemas.websocket import ClientMessage

        with pytest.raises(ValidationError) as exc_info:
            ClientMessage(
                message_id="msg-001",
                content="내용",
            )
        assert "session_id" in str(exc_info.value)

    def test_empty_content_raises_error(self):
        """빈 content는 거부됨 (최소 1자)"""
        from app.api.schemas.websocket import ClientMessage

        with pytest.raises(ValidationError):
            ClientMessage(
                message_id="msg-001",
                content="",
                session_id="session-123",
            )

    def test_content_max_length(self):
        """content 최대 길이 검증 (10000자)"""
        from app.api.schemas.websocket import ClientMessage

        # 최대 길이는 허용됨
        msg = ClientMessage(
            message_id="msg-001",
            content="a" * 10000,
            session_id="session-123",
        )
        assert len(msg.content) == 10000

        # 최대 길이 초과는 거부됨
        with pytest.raises(ValidationError):
            ClientMessage(
                message_id="msg-001",
                content="a" * 10001,
                session_id="session-123",
            )

    def test_model_dump(self):
        """딕셔너리 변환 테스트"""
        from app.api.schemas.websocket import ClientMessage

        msg = ClientMessage(
            message_id="msg-001",
            content="테스트",
            session_id="session-123",
        )
        data = msg.model_dump()

        assert data["type"] == "message"
        assert data["message_id"] == "msg-001"
        assert isinstance(data, dict)


class TestStreamStartEvent:
    """StreamStartEvent 스키마 테스트 - 스트리밍 시작 알림"""

    def test_valid_stream_start_event(self):
        """유효한 스트리밍 시작 이벤트 생성"""
        from app.api.schemas.websocket import StreamStartEvent

        event = StreamStartEvent(
            message_id="msg-001",
            session_id="session-abc-123",
            timestamp="2024-01-15T10:30:00Z",
        )

        assert event.type == "stream_start"
        assert event.message_id == "msg-001"
        assert event.session_id == "session-abc-123"
        assert event.timestamp == "2024-01-15T10:30:00Z"

    def test_type_is_always_stream_start(self):
        """type 필드는 항상 'stream_start'"""
        from app.api.schemas.websocket import StreamStartEvent

        event = StreamStartEvent(
            message_id="msg-001",
            session_id="session-123",
            timestamp="2024-01-15T10:30:00Z",
        )
        assert event.type == "stream_start"

    def test_missing_message_id_raises_error(self):
        """message_id 필수 필드 누락 시 ValidationError"""
        from app.api.schemas.websocket import StreamStartEvent

        with pytest.raises(ValidationError) as exc_info:
            StreamStartEvent(
                session_id="session-123",
                timestamp="2024-01-15T10:30:00Z",
            )
        assert "message_id" in str(exc_info.value)

    def test_missing_session_id_raises_error(self):
        """session_id 필수 필드 누락 시 ValidationError"""
        from app.api.schemas.websocket import StreamStartEvent

        with pytest.raises(ValidationError) as exc_info:
            StreamStartEvent(
                message_id="msg-001",
                timestamp="2024-01-15T10:30:00Z",
            )
        assert "session_id" in str(exc_info.value)

    def test_missing_timestamp_raises_error(self):
        """timestamp 필수 필드 누락 시 ValidationError"""
        from app.api.schemas.websocket import StreamStartEvent

        with pytest.raises(ValidationError) as exc_info:
            StreamStartEvent(
                message_id="msg-001",
                session_id="session-123",
            )
        assert "timestamp" in str(exc_info.value)


class TestStreamTokenEvent:
    """StreamTokenEvent 스키마 테스트 - 토큰 단위 스트리밍"""

    def test_valid_stream_token_event(self):
        """유효한 토큰 스트리밍 이벤트 생성"""
        from app.api.schemas.websocket import StreamTokenEvent

        event = StreamTokenEvent(
            message_id="msg-001",
            token="안녕",
            index=0,
        )

        assert event.type == "stream_token"
        assert event.message_id == "msg-001"
        assert event.token == "안녕"
        assert event.index == 0

    def test_type_is_always_stream_token(self):
        """type 필드는 항상 'stream_token'"""
        from app.api.schemas.websocket import StreamTokenEvent

        event = StreamTokenEvent(
            message_id="msg-001",
            token="테스트",
            index=5,
        )
        assert event.type == "stream_token"

    def test_token_sequence(self):
        """토큰 인덱스 순서 테스트"""
        from app.api.schemas.websocket import StreamTokenEvent

        tokens = ["안녕", "하세요", "!"]
        events = [
            StreamTokenEvent(message_id="msg-001", token=t, index=i)
            for i, t in enumerate(tokens)
        ]

        for i, event in enumerate(events):
            assert event.index == i
            assert event.token == tokens[i]

    def test_invalid_negative_index(self):
        """음수 index는 거부됨"""
        from app.api.schemas.websocket import StreamTokenEvent

        with pytest.raises(ValidationError):
            StreamTokenEvent(
                message_id="msg-001",
                token="테스트",
                index=-1,
            )

    def test_missing_token_raises_error(self):
        """token 필수 필드 누락 시 ValidationError"""
        from app.api.schemas.websocket import StreamTokenEvent

        with pytest.raises(ValidationError) as exc_info:
            StreamTokenEvent(
                message_id="msg-001",
                index=0,
            )
        assert "token" in str(exc_info.value)

    def test_empty_token_is_allowed(self):
        """빈 토큰은 허용됨 (공백 토큰 등)"""
        from app.api.schemas.websocket import StreamTokenEvent

        event = StreamTokenEvent(
            message_id="msg-001",
            token="",
            index=0,
        )
        assert event.token == ""


class TestStreamSourcesEvent:
    """StreamSourcesEvent 스키마 테스트 - 검색 소스 전송"""

    def test_valid_stream_sources_event(self):
        """유효한 소스 이벤트 생성"""
        from app.api.schemas.websocket import StreamSourcesEvent

        sources = [
            {"id": "doc-1", "title": "문서1", "score": 0.95},
            {"id": "doc-2", "title": "문서2", "score": 0.85},
        ]
        event = StreamSourcesEvent(
            message_id="msg-001",
            sources=sources,
        )

        assert event.type == "stream_sources"
        assert event.message_id == "msg-001"
        assert len(event.sources) == 2
        assert event.sources[0]["title"] == "문서1"

    def test_type_is_always_stream_sources(self):
        """type 필드는 항상 'stream_sources'"""
        from app.api.schemas.websocket import StreamSourcesEvent

        event = StreamSourcesEvent(
            message_id="msg-001",
            sources=[],
        )
        assert event.type == "stream_sources"

    def test_empty_sources_list_is_allowed(self):
        """빈 소스 리스트는 허용됨"""
        from app.api.schemas.websocket import StreamSourcesEvent

        event = StreamSourcesEvent(
            message_id="msg-001",
            sources=[],
        )
        assert event.sources == []

    def test_missing_sources_raises_error(self):
        """sources 필수 필드 누락 시 ValidationError"""
        from app.api.schemas.websocket import StreamSourcesEvent

        with pytest.raises(ValidationError) as exc_info:
            StreamSourcesEvent(
                message_id="msg-001",
            )
        assert "sources" in str(exc_info.value)

    def test_sources_with_various_structures(self):
        """다양한 구조의 소스 딕셔너리 허용"""
        from app.api.schemas.websocket import StreamSourcesEvent

        sources = [
            {"id": "1", "content": "내용"},
            {"document_id": "doc-1", "chunk_id": 0, "text": "텍스트", "metadata": {}},
            {"url": "http://example.com", "title": "제목"},
        ]
        event = StreamSourcesEvent(
            message_id="msg-001",
            sources=sources,
        )
        assert len(event.sources) == 3


class TestStreamEndEvent:
    """StreamEndEvent 스키마 테스트 - 스트리밍 종료 알림"""

    def test_valid_stream_end_event(self):
        """유효한 스트리밍 종료 이벤트 생성"""
        from app.api.schemas.websocket import StreamEndEvent

        event = StreamEndEvent(
            message_id="msg-001",
            total_tokens=150,
            processing_time_ms=1234,
        )

        assert event.type == "stream_end"
        assert event.message_id == "msg-001"
        assert event.total_tokens == 150
        assert event.processing_time_ms == 1234

    def test_type_is_always_stream_end(self):
        """type 필드는 항상 'stream_end'"""
        from app.api.schemas.websocket import StreamEndEvent

        event = StreamEndEvent(
            message_id="msg-001",
            total_tokens=100,
            processing_time_ms=500,
        )
        assert event.type == "stream_end"

    def test_invalid_negative_total_tokens(self):
        """음수 total_tokens는 거부됨"""
        from app.api.schemas.websocket import StreamEndEvent

        with pytest.raises(ValidationError):
            StreamEndEvent(
                message_id="msg-001",
                total_tokens=-1,
                processing_time_ms=500,
            )

    def test_invalid_negative_processing_time(self):
        """음수 processing_time_ms는 거부됨"""
        from app.api.schemas.websocket import StreamEndEvent

        with pytest.raises(ValidationError):
            StreamEndEvent(
                message_id="msg-001",
                total_tokens=100,
                processing_time_ms=-1,
            )

    def test_zero_values_are_allowed(self):
        """0 값은 허용됨"""
        from app.api.schemas.websocket import StreamEndEvent

        event = StreamEndEvent(
            message_id="msg-001",
            total_tokens=0,
            processing_time_ms=0,
        )
        assert event.total_tokens == 0
        assert event.processing_time_ms == 0


class TestStreamErrorEvent:
    """StreamErrorEvent 스키마 테스트 - WebSocket 에러 이벤트"""

    def test_valid_stream_error_event(self):
        """유효한 에러 이벤트 생성"""
        from app.api.schemas.websocket import WSStreamErrorEvent

        event = WSStreamErrorEvent(
            message_id="msg-001",
            error_code="GEN-001",
            message="AI 모델 응답이 지연되고 있습니다.",
            solutions=["잠시 후 다시 시도해주세요.", "문제가 지속되면 관리자에게 문의하세요."],
        )

        assert event.type == "stream_error"
        assert event.message_id == "msg-001"
        assert event.error_code == "GEN-001"
        assert event.message == "AI 모델 응답이 지연되고 있습니다."
        assert len(event.solutions) == 2

    def test_type_is_always_stream_error(self):
        """type 필드는 항상 'stream_error'"""
        from app.api.schemas.websocket import WSStreamErrorEvent

        event = WSStreamErrorEvent(
            message_id="msg-001",
            error_code="TEST-001",
            message="테스트 에러",
            solutions=[],
        )
        assert event.type == "stream_error"

    def test_empty_solutions_list_is_allowed(self):
        """빈 solutions 리스트는 허용됨"""
        from app.api.schemas.websocket import WSStreamErrorEvent

        event = WSStreamErrorEvent(
            message_id="msg-001",
            error_code="TEST-001",
            message="에러 메시지",
            solutions=[],
        )
        assert event.solutions == []

    def test_missing_error_code_raises_error(self):
        """error_code 필수 필드 누락 시 ValidationError"""
        from app.api.schemas.websocket import WSStreamErrorEvent

        with pytest.raises(ValidationError) as exc_info:
            WSStreamErrorEvent(
                message_id="msg-001",
                message="에러 메시지",
                solutions=[],
            )
        assert "error_code" in str(exc_info.value)

    def test_missing_message_raises_error(self):
        """message 필수 필드 누락 시 ValidationError"""
        from app.api.schemas.websocket import WSStreamErrorEvent

        with pytest.raises(ValidationError) as exc_info:
            WSStreamErrorEvent(
                message_id="msg-001",
                error_code="TEST-001",
                solutions=[],
            )
        assert "message" in str(exc_info.value)

    def test_missing_solutions_raises_error(self):
        """solutions 필수 필드 누락 시 ValidationError"""
        from app.api.schemas.websocket import WSStreamErrorEvent

        with pytest.raises(ValidationError) as exc_info:
            WSStreamErrorEvent(
                message_id="msg-001",
                error_code="TEST-001",
                message="에러 메시지",
            )
        assert "solutions" in str(exc_info.value)


class TestWebSocketEventSerialization:
    """WebSocket 이벤트 직렬화 테스트"""

    def test_client_message_to_json(self):
        """클라이언트 메시지 JSON 직렬화"""
        from app.api.schemas.websocket import ClientMessage

        msg = ClientMessage(
            message_id="msg-001",
            content="테스트",
            session_id="session-123",
        )
        json_str = msg.model_dump_json()

        assert '"type":"message"' in json_str
        assert '"message_id":"msg-001"' in json_str

    def test_stream_start_event_to_dict(self):
        """스트림 시작 이벤트 딕셔너리 변환"""
        from app.api.schemas.websocket import StreamStartEvent

        event = StreamStartEvent(
            message_id="msg-001",
            session_id="session-123",
            timestamp="2024-01-15T10:30:00Z",
        )
        data = event.model_dump()

        assert data["type"] == "stream_start"
        assert isinstance(data, dict)

    def test_stream_token_event_serialization(self):
        """토큰 이벤트 직렬화"""
        from app.api.schemas.websocket import StreamTokenEvent

        event = StreamTokenEvent(
            message_id="msg-001",
            token="안녕",
            index=0,
        )
        json_str = event.model_dump_json()

        assert '"type":"stream_token"' in json_str
        assert '"token":"안녕"' in json_str
        assert '"index":0' in json_str

    def test_stream_sources_event_serialization(self):
        """소스 이벤트 직렬화"""
        from app.api.schemas.websocket import StreamSourcesEvent

        event = StreamSourcesEvent(
            message_id="msg-001",
            sources=[{"id": "doc-1", "title": "문서"}],
        )
        data = event.model_dump()

        assert data["type"] == "stream_sources"
        assert len(data["sources"]) == 1

    def test_stream_end_event_serialization(self):
        """종료 이벤트 직렬화"""
        from app.api.schemas.websocket import StreamEndEvent

        event = StreamEndEvent(
            message_id="msg-001",
            total_tokens=100,
            processing_time_ms=500,
        )
        json_str = event.model_dump_json()

        assert '"type":"stream_end"' in json_str
        assert '"total_tokens":100' in json_str

    def test_stream_error_event_serialization(self):
        """에러 이벤트 직렬화"""
        from app.api.schemas.websocket import WSStreamErrorEvent

        event = WSStreamErrorEvent(
            message_id="msg-001",
            error_code="GEN-001",
            message="에러 발생",
            solutions=["해결 방법 1"],
        )
        data = event.model_dump()

        assert data["type"] == "stream_error"
        assert data["error_code"] == "GEN-001"
        assert len(data["solutions"]) == 1


class TestLiteralTypeValidation:
    """Literal 타입 검증 테스트 - type 필드가 올바른 값인지 확인"""

    def test_client_message_type_literal(self):
        """ClientMessage type 필드는 'message' Literal"""
        from app.api.schemas.websocket import ClientMessage

        # Literal 타입이므로 다른 값으로 설정 불가
        msg = ClientMessage(
            message_id="msg-001",
            content="테스트",
            session_id="session-123",
        )
        # type은 항상 "message"
        assert msg.type == "message"

    def test_all_event_types_are_correct(self):
        """모든 이벤트의 type 필드가 올바른 Literal 값인지 확인"""
        from app.api.schemas.websocket import (
            ClientMessage,
            StreamEndEvent,
            StreamSourcesEvent,
            StreamStartEvent,
            StreamTokenEvent,
            WSStreamErrorEvent,
        )

        # 각 스키마 생성 시 type 필드가 자동으로 올바른 값
        assert ClientMessage(
            message_id="1", content="c", session_id="s"
        ).type == "message"
        assert StreamStartEvent(
            message_id="1", session_id="s", timestamp="t"
        ).type == "stream_start"
        assert StreamTokenEvent(
            message_id="1", token="t", index=0
        ).type == "stream_token"
        assert StreamSourcesEvent(
            message_id="1", sources=[]
        ).type == "stream_sources"
        assert StreamEndEvent(
            message_id="1", total_tokens=0, processing_time_ms=0
        ).type == "stream_end"
        assert WSStreamErrorEvent(
            message_id="1", error_code="E", message="m", solutions=[]
        ).type == "stream_error"
