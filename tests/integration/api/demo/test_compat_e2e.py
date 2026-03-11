"""
프론트엔드 호환 라우터 E2E 통합 테스트

compat_router + demo_router를 함께 등록한 격리 앱에서
세션 생성 → 채팅 → 히스토리 → 세션 정보까지 전체 플로우를 검증합니다.

demo_main.py의 lifespan(ChromaDB, Gemini 등 외부 의존성)을 회피하기 위해
set_demo_services()로 Mock을 주입합니다.

시나리오:
1. 세션생성 → 채팅 → 히스토리 조회 전체 플로우
2. SSE 스트리밍 이벤트 시퀀스 + done 이벤트 보강
3. 다중 채팅 후 히스토리 누적
4. 채팅 후 세션 정보의 message_count 반영
5. API 예산 초과 시 429 (Rate Limit)
6. 미존재 세션 접근 시 404
"""

import json as _json
import time
from collections.abc import AsyncGenerator, Generator
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.demo.demo_pipeline import DemoPipeline
from app.api.demo.demo_router import limiter, set_demo_services
from app.api.demo.session_manager import DemoSession, DemoSessionManager
from app.lib.errors.codes import ErrorCode

# =============================================================================
# SSE 파싱 헬퍼
# =============================================================================


def _parse_sse(raw: str) -> list[dict]:
    """SSE 응답 텍스트를 이벤트 리스트로 파싱"""
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


# =============================================================================
# 픽스처
# =============================================================================


@pytest.fixture
def mock_session() -> DemoSession:
    """테스트용 데모 세션"""
    return DemoSession(
        session_id="e2e_test_session",
        collection_name="demo_e2e",
        created_at=time.time(),
        last_accessed=time.time(),
        document_count=1,
        document_names=["test.pdf"],
        total_chunks=5,
    )


@pytest.fixture
def mock_session_manager(mock_session: DemoSession) -> MagicMock:
    """Mock 세션 관리자 — 정상 동작 기본 설정"""
    manager = MagicMock(spec=DemoSessionManager)
    manager.create_session = AsyncMock(return_value=mock_session)
    manager.get_session = AsyncMock(return_value=mock_session)
    manager.delete_session = AsyncMock(return_value=True)
    manager.check_and_increment_api_calls = AsyncMock(return_value=True)
    manager.ttl_seconds = 600
    manager.max_docs_per_session = 5
    manager.max_file_size_mb = 10
    manager.get_session_info = AsyncMock(return_value={
        "session_id": "e2e_test_session",
        "created_at": "2026-03-11T00:00:00+00:00",
        "message_count": 0,
        "last_activity": "2026-03-11T00:00:00+00:00",
    })
    return manager


@pytest.fixture
def mock_pipeline() -> MagicMock:
    """Mock RAG 파이프라인 — query + stream_query 설정"""
    pipeline = MagicMock(spec=DemoPipeline)

    # 비스트리밍 채팅 응답
    pipeline.query = AsyncMock(
        return_value={
            "answer": "RAG는 검색 증강 생성 기술입니다.",
            "sources": [
                {"content": "RAG 관련 소스 내용", "source": "test.pdf"},
            ],
            "chunks_used": 1,
        }
    )

    # 스트리밍 채팅 응답
    async def mock_stream_query(
        session_id: str, question: str
    ) -> AsyncGenerator[dict, None]:
        """SSE 이벤트를 생성하는 mock 스트림"""
        yield {
            "event": "metadata",
            "data": {
                "session_id": session_id,
                "search_results": 1,
                "sources": [
                    {"content": "소스 내용", "source": "test.pdf"},
                ],
            },
        }
        yield {
            "event": "chunk",
            "data": {"token": "RAG는", "chunk_index": 0},
        }
        yield {
            "event": "chunk",
            "data": {"token": " 기술입니다.", "chunk_index": 1},
        }
        yield {
            "event": "done",
            "data": {"session_id": session_id, "total_chunks": 2},
        }

    pipeline.stream_query = mock_stream_query

    return pipeline


@pytest.fixture
def e2e_client(
    mock_session_manager: MagicMock,
    mock_pipeline: MagicMock,
) -> Generator[TestClient, None, None]:
    """
    E2E 격리 TestClient

    demo_router + compat_router를 모두 등록하고
    Mock 서비스를 주입한 독립 환경.
    """
    from app.api.demo.compat_router import _chat_history, compat_router
    from app.api.demo.demo_router import router as demo_router

    # 전역 히스토리 격리
    _chat_history.clear()

    app = FastAPI()
    limiter.enabled = False
    app.state.limiter = limiter

    # 두 라우터 모두 등록 (실제 demo_main.py와 동일 구조)
    app.include_router(demo_router, prefix="/api/demo")
    app.include_router(compat_router)

    # Mock 서비스 주입
    set_demo_services(mock_session_manager, mock_pipeline)

    with TestClient(app) as c:
        yield c

    # 정리
    _chat_history.clear()
    limiter.enabled = True


# =============================================================================
# 시나리오 1: 세션생성 → 채팅 → 히스토리 전체 플로우
# =============================================================================


class TestFullChatFlow:
    """세션 생성 → 채팅 → 히스토리 조회 연쇄 E2E 테스트"""

    def test_세션생성_채팅_히스토리_플로우(self, e2e_client: TestClient) -> None:
        """전체 플로우: 세션 생성 → 채팅 → 히스토리 조회"""
        # 1단계: 세션 생성
        resp = e2e_client.post("/api/chat/session")
        assert resp.status_code == 200
        session_id = resp.json()["session_id"]
        assert session_id == "e2e_test_session"

        # 2단계: 채팅
        resp = e2e_client.post(
            "/api/chat",
            json={"message": "RAG란 무엇인가요?", "session_id": session_id},
        )
        assert resp.status_code == 200
        chat_data = resp.json()
        assert chat_data["answer"] == "RAG는 검색 증강 생성 기술입니다."
        assert chat_data["session_id"] == session_id

        # 3단계: 히스토리 조회 — 채팅 기록이 반영되어야 함
        resp = e2e_client.get(f"/api/chat/history/{session_id}")
        assert resp.status_code == 200
        history = resp.json()
        assert len(history["messages"]) == 1
        assert history["messages"][0]["question"] == "RAG란 무엇인가요?"
        assert history["messages"][0]["answer"] == "RAG는 검색 증강 생성 기술입니다."

    def test_채팅_응답_스키마_완전성(self, e2e_client: TestClient) -> None:
        """채팅 응답에 프론트엔드가 요구하는 모든 필드가 포함되어야 함"""
        resp = e2e_client.post(
            "/api/chat",
            json={"message": "스키마 테스트", "session_id": "e2e_test_session"},
        )
        assert resp.status_code == 200
        data = resp.json()

        # 필수 필드 검증
        required_fields = ["answer", "session_id", "sources", "processing_time",
                           "tokens_used", "timestamp"]
        for field in required_fields:
            assert field in data, f"필수 필드 누락: {field}"

        # sources 구조 검증
        assert len(data["sources"]) >= 1
        source = data["sources"][0]
        assert "id" in source
        assert "document" in source
        assert "content_preview" in source
        assert "relevance" in source


# =============================================================================
# 시나리오 2: SSE 스트리밍
# =============================================================================


class TestStreamingFlow:
    """SSE 스트리밍 채팅 E2E 테스트"""

    def test_스트리밍_이벤트_시퀀스(self, e2e_client: TestClient) -> None:
        """metadata → chunk(s) → done 순서 보장"""
        resp = e2e_client.post(
            "/api/chat/stream",
            json={"message": "스트리밍 테스트", "session_id": "e2e_test_session"},
        )
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers["content-type"]

        events = _parse_sse(resp.text)
        types = [e["event"] for e in events]

        # metadata는 첫 번째
        assert types[0] == "metadata"
        # done은 마지막
        assert types[-1] == "done"
        # chunk가 중간에 존재
        assert "chunk" in types

    def test_스트리밍_chunk_키_변환(self, e2e_client: TestClient) -> None:
        """chunk 이벤트에서 'token' → 'data' 키 변환 (핵심 변환 로직)"""
        resp = e2e_client.post(
            "/api/chat/stream",
            json={"message": "키 변환 확인", "session_id": "e2e_test_session"},
        )
        events = _parse_sse(resp.text)
        chunks = [e for e in events if e["event"] == "chunk"]

        assert len(chunks) >= 2
        for chunk in chunks:
            # 'token' 키는 없어야 하고 'data' 키가 있어야 함
            assert "token" not in chunk["data"]
            assert "data" in chunk["data"]

        # 실제 값 검증
        assert chunks[0]["data"]["data"] == "RAG는"
        assert chunks[1]["data"]["data"] == " 기술입니다."

    def test_스트리밍_done_이벤트_보강(self, e2e_client: TestClient) -> None:
        """done 이벤트에 message_id, processing_time, tokens_used, sources 포함"""
        resp = e2e_client.post(
            "/api/chat/stream",
            json={"message": "done 확인", "session_id": "e2e_test_session"},
        )
        events = _parse_sse(resp.text)
        done_events = [e for e in events if e["event"] == "done"]
        assert len(done_events) == 1

        done = done_events[0]["data"]
        # UUID v4 형식 (하이픈 포함 36자)
        assert "message_id" in done
        assert len(done["message_id"]) == 36
        # 처리 시간
        assert isinstance(done["processing_time"], float)
        assert done["processing_time"] >= 0.0
        # 토큰 수
        assert done["tokens_used"] == 0
        # sources 배열
        assert isinstance(done["sources"], list)
        assert len(done["sources"]) >= 1


# =============================================================================
# 시나리오 3: 히스토리 누적
# =============================================================================


class TestHistoryAccumulation:
    """다중 채팅 후 히스토리 누적 E2E 테스트"""

    def test_다중_채팅_히스토리_누적(self, e2e_client: TestClient) -> None:
        """3회 채팅 후 히스토리에 3건 기록"""
        session_id = "e2e_test_session"
        questions = ["첫 번째 질문", "두 번째 질문", "세 번째 질문"]

        for q in questions:
            resp = e2e_client.post(
                "/api/chat",
                json={"message": q, "session_id": session_id},
            )
            assert resp.status_code == 200

        resp = e2e_client.get(f"/api/chat/history/{session_id}")
        assert resp.status_code == 200
        messages = resp.json()["messages"]
        assert len(messages) == 3

        # 순서 보장 확인
        for i, q in enumerate(questions):
            assert messages[i]["question"] == q


# =============================================================================
# 시나리오 4: 세션 정보 message_count 반영
# =============================================================================


class TestSessionInfoFlow:
    """세션 정보의 message_count가 히스토리를 반영하는지 E2E 테스트"""

    def test_채팅_후_message_count_반영(self, e2e_client: TestClient) -> None:
        """2회 채팅 후 session info의 message_count가 2"""
        session_id = "e2e_test_session"

        # 2회 채팅
        for _ in range(2):
            resp = e2e_client.post(
                "/api/chat",
                json={"message": "질문", "session_id": session_id},
            )
            assert resp.status_code == 200

        # 세션 정보 조회
        resp = e2e_client.get(f"/api/chat/session/{session_id}/info")
        assert resp.status_code == 200
        assert resp.json()["message_count"] == 2


# =============================================================================
# 시나리오 5: Rate Limit (API 예산 초과)
# =============================================================================


class TestRateLimitFlow:
    """API 예산 초과 시 429 반환 E2E 테스트"""

    def test_채팅_api_예산_초과_429(
        self,
        e2e_client: TestClient,
        mock_session_manager: MagicMock,
    ) -> None:
        """check_and_increment_api_calls가 False 반환 시 429"""
        mock_session_manager.check_and_increment_api_calls = AsyncMock(
            return_value=False
        )
        resp = e2e_client.post(
            "/api/chat",
            json={"message": "예산 초과", "session_id": "e2e_test_session"},
        )
        assert resp.status_code == 429
        assert resp.json()["detail"] == ErrorCode.DEMO_008.value

    def test_스트리밍_api_예산_초과_429(
        self,
        e2e_client: TestClient,
        mock_session_manager: MagicMock,
    ) -> None:
        """스트리밍에서도 API 예산 초과 시 429"""
        mock_session_manager.check_and_increment_api_calls = AsyncMock(
            return_value=False
        )
        resp = e2e_client.post(
            "/api/chat/stream",
            json={"message": "예산 초과", "session_id": "e2e_test_session"},
        )
        assert resp.status_code == 429
        assert resp.json()["detail"] == ErrorCode.DEMO_008.value


# =============================================================================
# 시나리오 6: 404 미존재 세션
# =============================================================================


class TestNotFoundFlow:
    """미존재 세션 접근 시 404 반환 E2E 테스트"""

    def test_채팅_미존재_세션_404(
        self,
        e2e_client: TestClient,
        mock_session_manager: MagicMock,
    ) -> None:
        """존재하지 않는 session_id로 채팅 시 404"""
        mock_session_manager.get_session = AsyncMock(return_value=None)
        resp = e2e_client.post(
            "/api/chat",
            json={"message": "질문", "session_id": "nonexistent"},
        )
        assert resp.status_code == 404
        assert resp.json()["detail"] == ErrorCode.DEMO_002.value

    def test_히스토리_미존재_세션_404(
        self,
        e2e_client: TestClient,
        mock_session_manager: MagicMock,
    ) -> None:
        """존재하지 않는 session_id로 히스토리 조회 시 404"""
        mock_session_manager.get_session = AsyncMock(return_value=None)
        resp = e2e_client.get("/api/chat/history/nonexistent")
        assert resp.status_code == 404
        assert resp.json()["detail"] == ErrorCode.DEMO_002.value

    def test_세션정보_미존재_세션_404(
        self,
        e2e_client: TestClient,
        mock_session_manager: MagicMock,
    ) -> None:
        """존재하지 않는 session_id로 세션 정보 조회 시 404"""
        mock_session_manager.get_session_info = AsyncMock(return_value=None)
        resp = e2e_client.get("/api/chat/session/nonexistent/info")
        assert resp.status_code == 404
        assert resp.json()["detail"] == ErrorCode.DEMO_002.value
