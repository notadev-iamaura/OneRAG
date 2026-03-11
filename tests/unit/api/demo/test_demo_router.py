"""
Demo API Router 단위 테스트

FastAPI TestClient를 사용하여 엔드포인트를 검증합니다.
"""

import io
import time
from collections.abc import AsyncGenerator, Generator
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.demo.demo_pipeline import DemoPipeline
from app.api.demo.demo_router import limiter, router, set_demo_services
from app.api.demo.session_manager import DemoSession, DemoSessionManager, DemoStats
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
    manager.delete_session = AsyncMock(return_value=True)
    manager.ttl_seconds = 600
    manager.max_docs_per_session = 5
    manager.max_file_size_mb = 10
    manager.check_and_increment_api_calls = AsyncMock(return_value=True)
    manager.get_stats = AsyncMock(
        return_value=DemoStats(
            active_sessions=2,
            max_sessions=50,
            ttl_seconds=600,
            total_sessions_created=10,
            total_sessions_expired=3,
            total_documents_uploaded=15,
            daily_api_calls=42,
            daily_api_limit=500,
        )
    )
    return manager


@pytest.fixture
def mock_pipeline() -> MagicMock:
    """Mock 파이프라인"""
    pipeline = MagicMock(spec=DemoPipeline)
    pipeline.ingest_document = AsyncMock(
        return_value={"chunks": 5, "filename": "test.txt", "collection": "demo_testsess"}
    )
    pipeline.query = AsyncMock(
        return_value={
            "answer": "RAG는 검색 기반 생성 기술입니다.",
            "sources": [{"content": "소스 내용", "source": "test.pdf"}],
            "chunks_used": 1,
        }
    )

    async def mock_stream(*args: object, **kwargs: object) -> AsyncGenerator[dict, None]:
        yield {"event": "metadata", "data": {"session_id": "test", "search_results": 1, "sources": []}}
        yield {"event": "chunk", "data": {"token": "안녕", "chunk_index": 0}}
        yield {"event": "done", "data": {"session_id": "test", "total_chunks": 1}}

    pipeline.stream_query = mock_stream
    return pipeline


@pytest.fixture
def client(
    mock_session_manager: MagicMock, mock_pipeline: MagicMock
) -> Generator[TestClient, None, None]:
    """FastAPI TestClient (Rate Limiter 비활성화)"""
    app = FastAPI()
    # 데코레이터에 사용된 limiter 인스턴스를 직접 비활성화
    limiter.enabled = False
    app.state.limiter = limiter
    app.include_router(router, prefix="/api/demo")
    set_demo_services(mock_session_manager, mock_pipeline)

    with TestClient(app) as c:
        yield c

    # 테스트 후 limiter 복원
    limiter.enabled = True


# =============================================================================
# 세션 엔드포인트 테스트
# =============================================================================


class TestSessionEndpoints:
    """세션 관련 엔드포인트 테스트"""

    def test_세션_생성(self, client: TestClient) -> None:
        """POST /sessions → 세션 생성 성공"""
        resp = client.post("/api/demo/sessions")
        assert resp.status_code == 200

        data = resp.json()
        assert "session_id" in data
        assert "collection_name" in data
        assert data["ttl_seconds"] == 600
        assert data["max_documents"] == 5

    def test_세션_삭제_성공(self, client: TestClient) -> None:
        """DELETE /sessions/{id} → 삭제 성공"""
        resp = client.delete("/api/demo/sessions/test_session_id")
        assert resp.status_code == 200
        assert "삭제" in resp.json()["message"]

    def test_세션_삭제_미존재(
        self, client: TestClient, mock_session_manager: MagicMock
    ) -> None:
        """DELETE /sessions/{id} → 404 (미존재)"""
        mock_session_manager.delete_session = AsyncMock(return_value=False)
        resp = client.delete("/api/demo/sessions/nonexistent")
        assert resp.status_code == 404


# =============================================================================
# 문서 업로드 엔드포인트 테스트
# =============================================================================


class TestUploadEndpoint:
    """문서 업로드 관련 테스트"""

    def test_문서_업로드_성공(self, client: TestClient) -> None:
        """POST /sessions/{id}/upload → 업로드 성공"""
        file_content = b"Test document content"
        resp = client.post(
            "/api/demo/sessions/test_session_id/upload",
            files={"file": ("test.txt", io.BytesIO(file_content), "text/plain")},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["filename"] == "test.txt"
        assert data["chunks"] == 5

    def test_세션_미존재시_404(
        self, client: TestClient, mock_session_manager: MagicMock
    ) -> None:
        """세션이 없으면 404"""
        mock_session_manager.get_session = AsyncMock(return_value=None)
        resp = client.post(
            "/api/demo/sessions/nonexistent/upload",
            files={"file": ("test.txt", io.BytesIO(b"test"), "text/plain")},
        )
        assert resp.status_code == 404

    def test_파일_크기_초과(
        self, client: TestClient, mock_session_manager: MagicMock
    ) -> None:
        """파일 크기 초과 시 400"""
        mock_session_manager.max_file_size_mb = 0  # 0MB 제한
        large_content = b"x" * (1024 * 1024 + 1)  # 1MB+
        resp = client.post(
            "/api/demo/sessions/test_session_id/upload",
            files={"file": ("large.txt", io.BytesIO(large_content), "text/plain")},
        )
        assert resp.status_code == 400
        assert resp.json()["detail"] == ErrorCode.DEMO_003.value


# =============================================================================
# 문서 목록 엔드포인트 테스트
# =============================================================================


class TestDocumentListEndpoint:
    """문서 목록 관련 테스트"""

    def test_문서_목록_조회(self, client: TestClient) -> None:
        """GET /sessions/{id}/documents → 목록 반환"""
        resp = client.get("/api/demo/sessions/test_session_id/documents")
        assert resp.status_code == 200

        data = resp.json()
        assert data["total"] == 1
        assert len(data["documents"]) == 1
        assert data["documents"][0]["filename"] == "test.pdf"

    def test_세션_미존재시_404(
        self, client: TestClient, mock_session_manager: MagicMock
    ) -> None:
        """세션이 없으면 404"""
        mock_session_manager.get_session = AsyncMock(return_value=None)
        resp = client.get("/api/demo/sessions/nonexistent/documents")
        assert resp.status_code == 404


# =============================================================================
# 채팅 엔드포인트 테스트
# =============================================================================


class TestChatEndpoint:
    """채팅 관련 테스트"""

    def test_채팅_질문_성공(self, client: TestClient) -> None:
        """POST /sessions/{id}/chat → 답변 반환"""
        resp = client.post(
            "/api/demo/sessions/test_session_id/chat",
            json={"question": "RAG란 무엇인가?"},
        )
        assert resp.status_code == 200

        data = resp.json()
        assert "answer" in data
        assert "sources" in data
        assert data["chunks_used"] == 1

    def test_빈_질문_에러(self, client: TestClient) -> None:
        """빈 질문 시 422 (Pydantic 검증 실패)"""
        resp = client.post(
            "/api/demo/sessions/test_session_id/chat",
            json={"question": ""},
        )
        assert resp.status_code == 422

    def test_세션_미존재시_404(
        self, client: TestClient, mock_pipeline: MagicMock
    ) -> None:
        """세션이 없으면 404"""
        mock_pipeline.query = AsyncMock(
            side_effect=ValueError("세션을 찾을 수 없습니다")
        )
        resp = client.post(
            "/api/demo/sessions/nonexistent/chat",
            json={"question": "질문"},
        )
        assert resp.status_code == 404


# =============================================================================
# 스트리밍 채팅 엔드포인트 테스트
# =============================================================================


class TestStreamChatEndpoint:
    """스트리밍 채팅 관련 테스트"""

    def test_스트리밍_응답_형식(self, client: TestClient) -> None:
        """POST /sessions/{id}/chat/stream → SSE 형식 응답"""
        resp = client.post(
            "/api/demo/sessions/test_session_id/chat/stream",
            json={"question": "RAG란?"},
        )
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers["content-type"]

        # SSE 이벤트 파싱
        content = resp.text
        assert "event: metadata" in content
        assert "event: chunk" in content
        assert "event: done" in content

    def test_세션_미존재시_404(
        self, client: TestClient, mock_session_manager: MagicMock
    ) -> None:
        """세션이 없으면 404"""
        mock_session_manager.get_session = AsyncMock(return_value=None)
        resp = client.post(
            "/api/demo/sessions/nonexistent/chat/stream",
            json={"question": "질문"},
        )
        assert resp.status_code == 404


# =============================================================================
# 통계 엔드포인트 테스트
# =============================================================================


class TestStatsEndpoint:
    """통계 관련 테스트"""

    def test_통계_조회(self, client: TestClient) -> None:
        """GET /stats → 통계 반환"""
        resp = client.get("/api/demo/stats")
        assert resp.status_code == 200

        data = resp.json()
        assert data["active_sessions"] == 2
        assert data["max_sessions"] == 50
        assert data["ttl_seconds"] == 600
        assert data["total_sessions_created"] == 10
        assert data["daily_api_calls"] == 42
        assert data["daily_api_limit"] == 500
        assert "allowed_file_types" in data
        assert "pdf" in data["allowed_file_types"]


# =============================================================================
# Path 파라미터 검증 테스트
# =============================================================================


class TestPathValidation:
    """Path 파라미터 검증 테스트 — min_length=1, max_length=200"""

    def test_삭제_장문_session_id_422(self, client: TestClient) -> None:
        """201자 session_id로 세션 삭제 시 422 반환"""
        long_id = "a" * 201
        resp = client.delete(f"/api/demo/sessions/{long_id}")
        assert resp.status_code == 422

    def test_문서목록_장문_session_id_422(self, client: TestClient) -> None:
        """201자 session_id로 문서 목록 조회 시 422 반환"""
        long_id = "b" * 201
        resp = client.get(f"/api/demo/sessions/{long_id}/documents")
        assert resp.status_code == 422

    def test_채팅_장문_session_id_422(self, client: TestClient) -> None:
        """201자 session_id로 채팅 시 422 반환"""
        long_id = "c" * 201
        resp = client.post(
            f"/api/demo/sessions/{long_id}/chat",
            json={"question": "테스트"},
        )
        assert resp.status_code == 422

    def test_스트리밍_장문_session_id_422(self, client: TestClient) -> None:
        """201자 session_id로 스트리밍 시 422 반환"""
        long_id = "d" * 201
        resp = client.post(
            f"/api/demo/sessions/{long_id}/chat/stream",
            json={"question": "테스트"},
        )
        assert resp.status_code == 422

    def test_정상_session_id_통과(self, client: TestClient) -> None:
        """200자 session_id는 Path 검증을 통과 (Mock 세션 반환으로 200)"""
        valid_id = "a" * 200
        resp = client.get(f"/api/demo/sessions/{valid_id}/documents")
        # Path 검증이 통과하여 Mock 세션 관리자가 응답 → 422가 아님
        assert resp.status_code != 422
