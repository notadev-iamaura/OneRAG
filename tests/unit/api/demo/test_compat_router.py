"""
Compat Router 단위 테스트

프론트엔드 호환 채팅 API (POST /api/chat) 엔드포인트를 검증합니다.
FastAPI TestClient와 mock을 사용하여 스키마 변환 및 히스토리 기록을 테스트합니다.
"""

import time
from collections.abc import AsyncGenerator, Generator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.demo.demo_pipeline import DemoPipeline
from app.api.demo.demo_router import limiter, set_demo_services
from app.api.demo.session_manager import DemoSession, DemoSessionManager
from app.lib.errors.codes import ErrorCode

# =============================================================================
# 픽스처
# =============================================================================


@pytest.fixture
def mock_session() -> DemoSession:
    """테스트용 세션"""
    return DemoSession(
        session_id="test_session_id",
        collection_name="demo_testsess",
        created_at=time.time(),
        last_accessed=time.time(),
        document_count=1,
        document_names=["test.pdf"],
        total_chunks=5,
    )


@pytest.fixture
def mock_session_manager(mock_session: DemoSession) -> MagicMock:
    """Mock 세션 관리자"""
    manager = MagicMock(spec=DemoSessionManager)
    manager.create_session = AsyncMock(return_value=mock_session)
    manager.get_session = AsyncMock(return_value=mock_session)
    manager.check_and_increment_api_calls = AsyncMock(return_value=True)
    manager.get_session_info = AsyncMock(return_value={
        "session_id": "test_session_id",
        "created_at": "2026-03-11T00:00:00+00:00",
        "message_count": 0,
        "last_activity": "2026-03-11T00:00:00+00:00",
    })
    return manager


@pytest.fixture
def mock_pipeline() -> MagicMock:
    """Mock 파이프라인 — query() 반환값 설정"""
    pipeline = MagicMock(spec=DemoPipeline)
    pipeline.query = AsyncMock(
        return_value={
            "answer": "RAG는 검색 기반 생성 기술입니다.",
            "sources": [
                {"content": "소스 내용입니다. 이것은 테스트용 컨텐츠입니다.", "source": "test.pdf"},
            ],
            "chunks_used": 1,
        }
    )
    return pipeline


@pytest.fixture
def client(
    mock_session_manager: MagicMock, mock_pipeline: MagicMock
) -> Generator[TestClient, None, None]:
    """FastAPI TestClient (Rate Limiter 비활성화, 히스토리 격리)"""
    from app.api.demo.compat_router import _chat_history, compat_router

    # 테스트 격리: 전역 히스토리 초기화
    _chat_history.clear()

    app = FastAPI()
    limiter.enabled = False
    app.state.limiter = limiter
    app.include_router(compat_router)
    set_demo_services(mock_session_manager, mock_pipeline)

    with TestClient(app) as c:
        yield c

    # 테스트 정리
    _chat_history.clear()
    limiter.enabled = True


# =============================================================================
# 채팅 엔드포인트 테스트
# =============================================================================


class TestCompatChatEndpoint:
    """호환 채팅 엔드포인트 테스트"""

    def test_chat_success(
        self, client: TestClient, mock_pipeline: MagicMock
    ) -> None:
        """POST /api/chat → 정상 채팅 요청 시 변환된 응답 반환"""
        resp = client.post(
            "/api/chat",
            json={"message": "RAG란 무엇인가?", "session_id": "test_session_id"},
        )
        assert resp.status_code == 200

        data = resp.json()
        # pipeline.query()에 올바른 인자가 전달되었는지 확인
        mock_pipeline.query.assert_called_once_with(
            "test_session_id", question="RAG란 무엇인가?"
        )
        # 응답 answer가 pipeline 결과와 동일한지 확인
        assert data["answer"] == "RAG는 검색 기반 생성 기술입니다."
        assert data["session_id"] == "test_session_id"

    def test_chat_session_not_found(
        self, client: TestClient, mock_pipeline: MagicMock
    ) -> None:
        """POST /api/chat → 미존재 세션 시 pipeline.query가 ValueError → 404 반환"""
        mock_pipeline.query = AsyncMock(
            side_effect=ValueError("세션을 찾을 수 없습니다.")
        )
        resp = client.post(
            "/api/chat",
            json={"message": "질문", "session_id": "nonexistent_session"},
        )
        assert resp.status_code == 404
        assert resp.json()["detail"] == ErrorCode.DEMO_002.value

    def test_chat_response_schema(self, client: TestClient) -> None:
        """POST /api/chat → 응답에 모든 필수 필드가 포함되어야 함"""
        resp = client.post(
            "/api/chat",
            json={"message": "질문 테스트", "session_id": "test_session_id"},
        )
        assert resp.status_code == 200
        data = resp.json()

        # 필수 최상위 필드 확인
        assert "answer" in data
        assert "session_id" in data
        assert "sources" in data
        assert "processing_time" in data
        assert "tokens_used" in data
        assert "timestamp" in data

        # processing_time은 양수
        assert isinstance(data["processing_time"], float)
        assert data["processing_time"] >= 0.0

        # tokens_used는 정수
        assert isinstance(data["tokens_used"], int)

        # timestamp는 ISO 형식 문자열
        assert isinstance(data["timestamp"], str)

        # sources 구조 확인
        assert isinstance(data["sources"], list)
        assert len(data["sources"]) >= 1
        source = data["sources"][0]
        assert "id" in source
        assert "document" in source
        assert "content_preview" in source
        assert "relevance" in source

        # source.id는 0-based 인덱스
        assert source["id"] == 0
        # source.document는 pipeline source 필드
        assert source["document"] == "test.pdf"
        # content_preview는 최대 200자
        assert len(source["content_preview"]) <= 200
        # relevance는 float
        assert isinstance(source["relevance"], float)

    def test_chat_records_history(self, client: TestClient) -> None:
        """POST /api/chat → 채팅 후 인메모리 히스토리에 기록 확인"""
        from app.api.demo.compat_router import _chat_history

        session_id = "test_session_id"

        # 히스토리 초기화
        _chat_history.clear()

        # 첫 번째 채팅
        resp = client.post(
            "/api/chat",
            json={"message": "첫 번째 질문", "session_id": session_id},
        )
        assert resp.status_code == 200

        # 히스토리에 기록 확인
        assert session_id in _chat_history
        assert len(_chat_history[session_id]) == 1

        entry = _chat_history[session_id][0]
        assert entry["question"] == "첫 번째 질문"
        assert entry["answer"] == "RAG는 검색 기반 생성 기술입니다."

        # 두 번째 채팅 — 히스토리 누적 확인
        resp = client.post(
            "/api/chat",
            json={"message": "두 번째 질문", "session_id": session_id},
        )
        assert resp.status_code == 200
        assert len(_chat_history[session_id]) == 2

    def test_chat_history_size_limit(self, client: TestClient) -> None:
        """POST /api/chat → 히스토리 크기 제한 초과 시 오래된 항목 제거"""
        from app.api.demo.compat_router import (
            _MAX_HISTORY_PER_SESSION,
            _chat_history,
        )

        session_id = "test_session_id"
        _chat_history.clear()

        # 제한보다 많은 메시지 전송
        for i in range(_MAX_HISTORY_PER_SESSION + 5):
            client.post(
                "/api/chat",
                json={"message": f"질문 {i}", "session_id": session_id},
            )

        # 최대 크기를 초과하지 않아야 함
        assert len(_chat_history[session_id]) <= _MAX_HISTORY_PER_SESSION

    def test_chat_api_budget_exceeded(
        self, client: TestClient, mock_session_manager: MagicMock
    ) -> None:
        """POST /api/chat → API 예산 초과 시 429 반환"""
        mock_session_manager.check_and_increment_api_calls = AsyncMock(
            return_value=False
        )
        resp = client.post(
            "/api/chat",
            json={"message": "질문", "session_id": "test_session_id"},
        )
        assert resp.status_code == 429
        assert resp.json()["detail"] == ErrorCode.DEMO_008.value


# =============================================================================
# SSE 스트리밍 엔드포인트 테스트
# =============================================================================


class TestCompatStreamEndpoint:
    """호환 SSE 스트리밍 엔드포인트 테스트"""

    @pytest.fixture(autouse=True)
    def setup_stream_pipeline(self, mock_pipeline: MagicMock) -> None:
        """스트리밍용 mock 설정 — stream_query가 AsyncGenerator를 반환"""

        async def mock_stream_query(
            session_id: str, question: str
        ) -> AsyncGenerator[dict, None]:
            """stream_query 목(mock) 생성기"""
            yield {
                "event": "metadata",
                "data": {
                    "session_id": session_id,
                    "search_results": 1,
                    "sources": [
                        {"content": "테스트 소스 내용", "source": "test.pdf"}
                    ],
                },
            }
            yield {
                "event": "chunk",
                "data": {"token": "안녕", "chunk_index": 0},
            }
            yield {
                "event": "chunk",
                "data": {"token": "하세요", "chunk_index": 1},
            }
            yield {
                "event": "done",
                "data": {"session_id": session_id, "total_chunks": 2},
            }

        mock_pipeline.stream_query = mock_stream_query

    def _parse_sse_events(self, raw: str) -> list[dict]:
        """SSE 응답 텍스트를 파싱하여 이벤트 리스트 반환"""
        import json as _json

        events: list[dict] = []
        current_event: str | None = None
        current_data: str | None = None

        for line in raw.split("\n"):
            if line.startswith("event: "):
                current_event = line[len("event: "):]
            elif line.startswith("data: "):
                current_data = line[len("data: "):]
            elif line == "" and current_event is not None and current_data is not None:
                events.append({
                    "event": current_event,
                    "data": _json.loads(current_data),
                })
                current_event = None
                current_data = None

        return events

    def test_stream_chat_success(self, client: TestClient) -> None:
        """POST /api/chat/stream → text/event-stream 응답 반환"""
        resp = client.post(
            "/api/chat/stream",
            json={"message": "질문입니다", "session_id": "test_session_id"},
        )
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers["content-type"]

        # SSE 이벤트가 존재하는지 확인
        events = self._parse_sse_events(resp.text)
        assert len(events) >= 3  # metadata + chunk(s) + done
        event_types = [e["event"] for e in events]
        assert "metadata" in event_types
        assert "chunk" in event_types
        assert "done" in event_types

    def test_stream_chat_chunk_key_transformation(
        self, client: TestClient
    ) -> None:
        """POST /api/chat/stream → chunk 이벤트에서 "token" → "data" 키 변환 검증 (핵심!)"""
        resp = client.post(
            "/api/chat/stream",
            json={"message": "키 변환 테스트", "session_id": "test_session_id"},
        )
        assert resp.status_code == 200

        events = self._parse_sse_events(resp.text)
        chunk_events = [e for e in events if e["event"] == "chunk"]

        # chunk가 최소 2개여야 함 (mock에서 2개 yield)
        assert len(chunk_events) >= 2

        for chunk in chunk_events:
            chunk_data = chunk["data"]
            # "token" 키가 존재하면 안 됨 — "data"로 변환되어야 함
            assert "token" not in chunk_data, (
                f"chunk 이벤트에 'token' 키가 남아있음: {chunk_data}"
            )
            # "data" 키가 존재해야 함
            assert "data" in chunk_data, (
                f"chunk 이벤트에 'data' 키가 없음: {chunk_data}"
            )
            # chunk_index는 그대로 유지
            assert "chunk_index" in chunk_data

        # 실제 값 검증
        assert chunk_events[0]["data"]["data"] == "안녕"
        assert chunk_events[1]["data"]["data"] == "하세요"
        assert chunk_events[0]["data"]["chunk_index"] == 0
        assert chunk_events[1]["data"]["chunk_index"] == 1

    def test_stream_chat_done_event_enrichment(
        self, client: TestClient
    ) -> None:
        """POST /api/chat/stream → done 이벤트에 message_id, processing_time, sources 추가 검증"""
        resp = client.post(
            "/api/chat/stream",
            json={"message": "done 이벤트 테스트", "session_id": "test_session_id"},
        )
        assert resp.status_code == 200

        events = self._parse_sse_events(resp.text)
        done_events = [e for e in events if e["event"] == "done"]
        assert len(done_events) == 1

        done_data = done_events[0]["data"]

        # 기존 필드 유지 확인
        assert done_data["session_id"] == "test_session_id"
        assert done_data["total_chunks"] == 2

        # 추가 필드 확인
        assert "message_id" in done_data
        # message_id는 UUID v4 형식 (하이픈 포함 36자)
        assert len(done_data["message_id"]) == 36

        assert "processing_time" in done_data
        assert isinstance(done_data["processing_time"], float)
        assert done_data["processing_time"] >= 0.0

        assert "tokens_used" in done_data
        assert done_data["tokens_used"] == 0  # 데모 파이프라인은 토큰 카운트 미제공

        assert "sources" in done_data
        assert isinstance(done_data["sources"], list)
        assert len(done_data["sources"]) >= 1
        assert done_data["sources"][0]["source"] == "test.pdf"

    def test_stream_chat_session_not_found(
        self, client: TestClient, mock_pipeline: MagicMock
    ) -> None:
        """POST /api/chat/stream → 미존재 세션 시 스트림 에러 이벤트 반환"""
        # 스트리밍에서는 pipeline.stream_query가 ValueError를 발생시킴
        # 이벤트 제너레이터 내부에서 에러가 캡처되어 SSE error 이벤트로 반환됨
        async def failing_stream(*args: Any, **kwargs: Any) -> AsyncGenerator[dict[str, Any], None]:
            raise ValueError("세션을 찾을 수 없습니다.")
            yield  # type: ignore[misc]  # AsyncGenerator 타입 충족용

        mock_pipeline.stream_query = failing_stream
        resp = client.post(
            "/api/chat/stream",
            json={"message": "질문", "session_id": "nonexistent_session"},
        )
        # 스트리밍은 200으로 시작하고 에러 이벤트를 보내는 방식
        assert resp.status_code == 200
        assert "event: error" in resp.text

    def test_stream_chat_api_budget_exceeded(
        self, client: TestClient, mock_session_manager: MagicMock
    ) -> None:
        """POST /api/chat/stream → API 예산 초과 시 429 반환"""
        mock_session_manager.check_and_increment_api_calls = AsyncMock(
            return_value=False
        )
        resp = client.post(
            "/api/chat/stream",
            json={"message": "질문", "session_id": "test_session_id"},
        )
        assert resp.status_code == 429
        assert resp.json()["detail"] == ErrorCode.DEMO_008.value

    def test_stream_chat_error_event(
        self, client: TestClient, mock_pipeline: MagicMock
    ) -> None:
        """POST /api/chat/stream → 파이프라인 에러 시 error SSE 이벤트 반환"""

        async def mock_error_stream(
            session_id: str, question: str
        ) -> AsyncGenerator[dict, None]:
            """에러를 발생시키는 mock 스트림"""
            raise RuntimeError("파이프라인 내부 오류")
            # yield는 제너레이터 시그니처를 위해 필요
            yield {}  # type: ignore[misc]  # noqa: B901

        mock_pipeline.stream_query = mock_error_stream

        resp = client.post(
            "/api/chat/stream",
            json={"message": "에러 테스트", "session_id": "test_session_id"},
        )
        assert resp.status_code == 200  # SSE는 200으로 시작 후 error 이벤트 전송

        events = self._parse_sse_events(resp.text)
        error_events = [e for e in events if e["event"] == "error"]
        assert len(error_events) >= 1
        assert "error" in error_events[0]["data"]


# =============================================================================
# 세션 생성 엔드포인트 테스트
# =============================================================================


class TestSessionCreateEndpoint:
    """POST /api/chat/session — 세션 생성 엔드포인트 테스트"""

    def test_create_session_success(
        self, client: TestClient, mock_session_manager: MagicMock
    ) -> None:
        """POST /api/chat/session → 정상 세션 생성"""
        resp = client.post("/api/chat/session")
        assert resp.status_code == 200

        data = resp.json()
        assert data["session_id"] == "test_session_id"
        assert data["message_count"] == 0
        assert "created_at" in data
        assert "last_activity" in data

        # create_session()이 호출되었는지 확인
        mock_session_manager.create_session.assert_called_once()

    def test_create_session_returns_iso_datetime(
        self, client: TestClient
    ) -> None:
        """POST /api/chat/session → created_at, last_activity가 ISO 형식"""
        resp = client.post("/api/chat/session")
        assert resp.status_code == 200

        data = resp.json()
        # ISO 형식 확인 (T 포함)
        assert "T" in data["created_at"]
        assert "T" in data["last_activity"]

    def test_create_session_internal_error(
        self, client: TestClient, mock_session_manager: MagicMock
    ) -> None:
        """POST /api/chat/session → 내부 에러 시 500 반환"""
        mock_session_manager.create_session = AsyncMock(
            side_effect=Exception("DB 연결 실패")
        )
        resp = client.post("/api/chat/session")
        assert resp.status_code == 500
        assert resp.json()["detail"] == ErrorCode.DEMO_005.value


# =============================================================================
# 채팅 히스토리 조회 엔드포인트 테스트
# =============================================================================


class TestChatHistoryEndpoint:
    """GET /api/chat/history/{session_id} — 채팅 히스토리 조회 테스트"""

    def test_get_history_empty(self, client: TestClient) -> None:
        """GET /api/chat/history/{session_id} → 빈 히스토리 반환"""
        from app.api.demo.compat_router import _chat_history

        _chat_history.clear()

        resp = client.get("/api/chat/history/test_session_id")
        assert resp.status_code == 200

        data = resp.json()
        assert data["session_id"] == "test_session_id"
        assert data["messages"] == []

    def test_get_history_with_messages(self, client: TestClient) -> None:
        """GET /api/chat/history/{session_id} → 기존 히스토리 반환"""
        from app.api.demo.compat_router import _chat_history

        _chat_history.clear()
        _chat_history["test_session_id"] = [
            {"question": "질문1", "answer": "답변1"},
            {"question": "질문2", "answer": "답변2"},
        ]

        resp = client.get("/api/chat/history/test_session_id")
        assert resp.status_code == 200

        data = resp.json()
        assert data["session_id"] == "test_session_id"
        assert len(data["messages"]) == 2
        assert data["messages"][0]["question"] == "질문1"
        assert data["messages"][1]["answer"] == "답변2"

    def test_get_history_session_not_found(
        self, client: TestClient, mock_session_manager: MagicMock
    ) -> None:
        """GET /api/chat/history/{session_id} → 미존재 세션 시 404 반환"""
        mock_session_manager.get_session = AsyncMock(return_value=None)

        resp = client.get("/api/chat/history/nonexistent")
        assert resp.status_code == 404
        assert resp.json()["detail"] == ErrorCode.DEMO_002.value


# =============================================================================
# 세션 정보 엔드포인트 테스트
# =============================================================================


class TestSessionInfoEndpoint:
    """GET /api/chat/session/{session_id}/info — 세션 정보 조회 테스트"""

    def test_get_session_info_success(
        self, client: TestClient, mock_session_manager: MagicMock
    ) -> None:
        """GET /api/chat/session/{session_id}/info → 정상 세션 정보 반환"""
        resp = client.get("/api/chat/session/test_session_id/info")
        assert resp.status_code == 200

        data = resp.json()
        assert data["session_id"] == "test_session_id"
        assert data["message_count"] == 0
        assert "created_at" in data
        assert "last_activity" in data

        # get_session_info()가 올바른 session_id로 호출되었는지 확인
        mock_session_manager.get_session_info.assert_called_once_with(
            "test_session_id"
        )

    def test_get_session_info_not_found(
        self, client: TestClient, mock_session_manager: MagicMock
    ) -> None:
        """GET /api/chat/session/{session_id}/info → 미존재 세션 시 404 반환"""
        mock_session_manager.get_session_info = AsyncMock(return_value=None)

        resp = client.get("/api/chat/session/nonexistent/info")
        assert resp.status_code == 404
        assert resp.json()["detail"] == ErrorCode.DEMO_002.value

    def test_get_session_info_message_count_reflects_history(
        self, client: TestClient
    ) -> None:
        """GET /api/chat/session/{id}/info → message_count가 실제 히스토리 길이를 반영"""
        from app.api.demo.compat_router import _chat_history

        # 히스토리에 2건 기록
        _chat_history["test_session_id"] = [
            {"question": "질문1", "answer": "답변1"},
            {"question": "질문2", "answer": "답변2"},
        ]

        resp = client.get("/api/chat/session/test_session_id/info")
        assert resp.status_code == 200
        assert resp.json()["message_count"] == 2


# =============================================================================
# 히스토리 정리 함수 테스트
# =============================================================================


class TestCleanupSessionHistory:
    """cleanup_session_history() — 세션 삭제 시 히스토리 정리 검증"""

    def test_cleanup_removes_history(self) -> None:
        """cleanup_session_history() → 해당 세션 히스토리 제거"""
        from app.api.demo.compat_router import (
            _chat_history,
            cleanup_session_history,
        )

        _chat_history["sess-to-delete"] = [
            {"question": "Q1", "answer": "A1"},
        ]
        _chat_history["sess-to-keep"] = [
            {"question": "Q2", "answer": "A2"},
        ]

        cleanup_session_history("sess-to-delete")

        assert "sess-to-delete" not in _chat_history
        assert "sess-to-keep" in _chat_history

        # 정리
        _chat_history.clear()

    def test_cleanup_nonexistent_session_noop(self) -> None:
        """cleanup_session_history() → 미존재 세션 시 에러 없이 무시"""
        from app.api.demo.compat_router import (
            _chat_history,
            cleanup_session_history,
        )

        _chat_history.clear()
        # 존재하지 않는 세션 정리 시도 — 예외 발생하지 않아야 함
        cleanup_session_history("nonexistent-session")


