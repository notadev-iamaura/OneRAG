"""
DemoPipeline 단위 테스트

문서 인제스트, 벡터 검색, LLM 답변 생성을 검증합니다.
외부 API 호출은 모두 Mock으로 대체합니다.
"""

from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.api.demo.demo_pipeline import (
    ALLOWED_EXTENSIONS,
    DemoPipeline,
    extract_text_from_file,
)
from app.api.demo.session_manager import DemoSession, DemoSessionManager

# =============================================================================
# 픽스처
# =============================================================================


@pytest.fixture
def mock_session() -> DemoSession:
    """테스트용 세션"""
    import time

    return DemoSession(
        session_id="test_session_123",
        collection_name="demo_test1234",
        created_at=time.time(),
        last_accessed=time.time(),
    )


@pytest.fixture
def mock_session_manager(mock_session: DemoSession) -> MagicMock:
    """Mock 세션 관리자"""
    manager = MagicMock(spec=DemoSessionManager)
    manager.get_session = AsyncMock(return_value=mock_session)
    manager.increment_document_count = AsyncMock(return_value=True)
    manager.max_docs_per_session = 5
    return manager


@pytest.fixture
def mock_embedder() -> MagicMock:
    """Mock 임베딩 모델"""
    embedder = MagicMock()
    # embed_documents: 각 텍스트마다 3차원 벡터 반환
    embedder.embed_documents = MagicMock(
        side_effect=lambda texts: [[0.1, 0.2, 0.3]] * len(texts)
    )
    # embed_query: 단일 벡터 반환
    embedder.embed_query = MagicMock(return_value=[0.1, 0.2, 0.3])
    return embedder


@pytest.fixture
def mock_chroma_client() -> MagicMock:
    """Mock ChromaDB 클라이언트"""
    client = MagicMock()
    collection = MagicMock()
    collection.upsert = MagicMock()
    collection.query = MagicMock(return_value={
        "documents": [["RAG는 검색 기반 생성 기술입니다.", "벡터 DB를 사용합니다."]],
        "metadatas": [
            [
                {"source": "test.pdf", "content": "RAG는 검색 기반 생성 기술입니다."},
                {"source": "test.pdf", "content": "벡터 DB를 사용합니다."},
            ]
        ],
        "distances": [[0.1, 0.2]],
    })
    client.get_or_create_collection = MagicMock(return_value=collection)
    client.get_collection = MagicMock(return_value=collection)
    return client


@pytest.fixture
def mock_llm_client() -> MagicMock:
    """Mock LLM 클라이언트"""
    client = MagicMock()
    client.generate_text = AsyncMock(return_value="RAG는 Retrieval-Augmented Generation입니다.")

    async def mock_stream(*args: object, **kwargs: object) -> AsyncGenerator[str, None]:
        for token in ["RAG는 ", "검색 기반 ", "생성 기술입니다."]:
            yield token

    client.stream_text = mock_stream
    return client


@pytest.fixture
def pipeline(
    mock_session_manager: MagicMock,
    mock_embedder: MagicMock,
    mock_chroma_client: MagicMock,
    mock_llm_client: MagicMock,
) -> DemoPipeline:
    """테스트용 DemoPipeline"""
    return DemoPipeline(
        session_manager=mock_session_manager,
        embedder=mock_embedder,
        chroma_client=mock_chroma_client,
        llm_client=mock_llm_client,
    )


# =============================================================================
# 텍스트 추출 테스트
# =============================================================================


class TestTextExtraction:
    """텍스트 추출 관련 테스트"""

    @pytest.mark.asyncio
    async def test_텍스트_파일_추출(self, tmp_path: object) -> None:
        """TXT 파일에서 텍스트를 추출하는지 확인"""
        import pathlib

        tmp = pathlib.Path(str(tmp_path)) / "test.txt"
        tmp.write_text("안녕하세요, 테스트 문서입니다.", encoding="utf-8")

        result = await extract_text_from_file(str(tmp), "txt")
        assert "안녕하세요" in result
        assert "테스트 문서" in result

    @pytest.mark.asyncio
    async def test_마크다운_파일_추출(self, tmp_path: object) -> None:
        """MD 파일에서 텍스트를 추출하는지 확인"""
        import pathlib

        tmp = pathlib.Path(str(tmp_path)) / "test.md"
        tmp.write_text("# 제목\n\n내용입니다.", encoding="utf-8")

        result = await extract_text_from_file(str(tmp), "md")
        assert "제목" in result
        assert "내용" in result

    @pytest.mark.asyncio
    async def test_미지원_파일_형식(self) -> None:
        """지원하지 않는 파일 형식에서 ValueError 발생"""
        with pytest.raises(ValueError, match="지원하지 않는 파일 형식"):
            await extract_text_from_file("/tmp/test.xyz", "xyz")


# =============================================================================
# 문서 인제스트 테스트
# =============================================================================


class TestIngestDocument:
    """문서 인제스트 관련 테스트"""

    @pytest.mark.asyncio
    async def test_텍스트_문서_인제스트_성공(
        self, pipeline: DemoPipeline
    ) -> None:
        """텍스트 파일 인제스트가 정상 동작하는지 확인"""
        file_bytes = "RAG 시스템은 검색과 생성을 결합합니다.".encode()

        result = await pipeline.ingest_document(
            session_id="test_session_123",
            file_bytes=file_bytes,
            filename="test.txt",
        )

        assert result["filename"] == "test.txt"
        assert result["chunks"] >= 1
        assert result["collection"] == "demo_test1234"

    @pytest.mark.asyncio
    async def test_세션_미존재시_에러(
        self, pipeline: DemoPipeline, mock_session_manager: MagicMock
    ) -> None:
        """존재하지 않는 세션에 인제스트 시 ValueError"""
        mock_session_manager.get_session = AsyncMock(return_value=None)

        with pytest.raises(ValueError, match="세션을 찾을 수 없습니다"):
            await pipeline.ingest_document(
                session_id="nonexistent",
                file_bytes=b"test",
                filename="test.txt",
            )

    @pytest.mark.asyncio
    async def test_미지원_파일_형식_에러(
        self, pipeline: DemoPipeline
    ) -> None:
        """미지원 파일 형식 시 ValueError"""
        with pytest.raises(ValueError, match="지원하지 않는 파일 형식"):
            await pipeline.ingest_document(
                session_id="test_session_123",
                file_bytes=b"test",
                filename="test.py",
            )

    @pytest.mark.asyncio
    async def test_빈_파일_에러(self, pipeline: DemoPipeline) -> None:
        """빈 파일 시 ValueError"""
        with pytest.raises(ValueError, match="텍스트를 추출할 수 없습니다"):
            await pipeline.ingest_document(
                session_id="test_session_123",
                file_bytes=b"",
                filename="empty.txt",
            )

    @pytest.mark.asyncio
    async def test_문서_수_제한_초과_에러(
        self, pipeline: DemoPipeline, mock_session_manager: MagicMock
    ) -> None:
        """세션당 문서 수 제한 초과 시 ValueError"""
        mock_session_manager.increment_document_count = AsyncMock(
            return_value=False
        )

        with pytest.raises(ValueError, match="최대"):
            await pipeline.ingest_document(
                session_id="test_session_123",
                file_bytes="테스트 내용".encode(),
                filename="extra.txt",
            )


# =============================================================================
# 샘플 데이터 인제스트 테스트
# =============================================================================


class TestIngestSampleData:
    """샘플 데이터 인제스트 관련 테스트"""

    @pytest.mark.asyncio
    async def test_샘플_데이터_인제스트_성공(
        self, pipeline: DemoPipeline
    ) -> None:
        """샘플 데이터가 정상적으로 인제스트되는지 확인"""
        docs = [
            {
                "id": "faq-001",
                "title": "RAG란?",
                "content": "RAG는 Retrieval-Augmented Generation입니다.",
                "metadata": {"category": "기술"},
            },
            {
                "id": "faq-002",
                "title": "벡터 DB란?",
                "content": "벡터 DB는 임베딩 벡터를 저장하는 데이터베이스입니다.",
                "metadata": {"category": "기술"},
            },
        ]

        count = await pipeline.ingest_sample_data("test_session_123", docs)
        assert count == 2

    @pytest.mark.asyncio
    async def test_빈_샘플_데이터(self, pipeline: DemoPipeline) -> None:
        """빈 샘플 데이터는 0 반환"""
        count = await pipeline.ingest_sample_data("test_session_123", [])
        assert count == 0

    @pytest.mark.asyncio
    async def test_세션_미존재시_에러(
        self, pipeline: DemoPipeline, mock_session_manager: MagicMock
    ) -> None:
        """존재하지 않는 세션에 인제스트 시 ValueError"""
        mock_session_manager.get_session = AsyncMock(return_value=None)

        with pytest.raises(ValueError, match="세션을 찾을 수 없습니다"):
            await pipeline.ingest_sample_data("nonexistent", [{"id": "1", "content": "test"}])


# =============================================================================
# RAG 검색 + 답변 테스트
# =============================================================================


class TestQuery:
    """RAG 질문 답변 관련 테스트"""

    @pytest.mark.asyncio
    async def test_질문_답변_성공(self, pipeline: DemoPipeline) -> None:
        """RAG 파이프라인으로 답변을 생성하는지 확인"""
        result = await pipeline.query("test_session_123", "RAG란 무엇인가?")

        assert "answer" in result
        assert "sources" in result
        assert "chunks_used" in result
        assert result["chunks_used"] == 2
        assert len(result["sources"]) == 2

    @pytest.mark.asyncio
    async def test_세션_미존재시_에러(
        self, pipeline: DemoPipeline, mock_session_manager: MagicMock
    ) -> None:
        """존재하지 않는 세션에서 질문 시 ValueError"""
        mock_session_manager.get_session = AsyncMock(return_value=None)

        with pytest.raises(ValueError, match="세션을 찾을 수 없습니다"):
            await pipeline.query("nonexistent", "질문")

    @pytest.mark.asyncio
    async def test_컬렉션_없을때_빈_답변(
        self,
        pipeline: DemoPipeline,
        mock_chroma_client: MagicMock,
    ) -> None:
        """컬렉션이 없으면 빈 소스로 답변 생성"""
        mock_chroma_client.get_collection = MagicMock(
            side_effect=Exception("Collection not found")
        )

        result = await pipeline.query("test_session_123", "질문")
        assert result["chunks_used"] == 0


# =============================================================================
# 스트리밍 답변 테스트
# =============================================================================


class TestStreamQuery:
    """스트리밍 답변 관련 테스트"""

    @pytest.mark.asyncio
    async def test_스트리밍_답변_성공(self, pipeline: DemoPipeline) -> None:
        """스트리밍 답변이 올바른 이벤트 순서로 생성되는지 확인"""
        events = []
        async for event in pipeline.stream_query(
            "test_session_123", "RAG란?"
        ):
            events.append(event)

        # 첫 이벤트: metadata
        assert events[0]["event"] == "metadata"
        assert "sources" in events[0]["data"]

        # 중간 이벤트: chunk
        chunk_events = [e for e in events if e["event"] == "chunk"]
        assert len(chunk_events) == 3  # "RAG는 ", "검색 기반 ", "생성 기술입니다."
        assert chunk_events[0]["data"]["chunk_index"] == 0

        # 마지막 이벤트: done
        assert events[-1]["event"] == "done"
        assert events[-1]["data"]["total_chunks"] == 3

    @pytest.mark.asyncio
    async def test_스트리밍_세션_미존재시_에러(
        self, pipeline: DemoPipeline, mock_session_manager: MagicMock
    ) -> None:
        """존재하지 않는 세션에서 스트리밍 시 ValueError"""
        mock_session_manager.get_session = AsyncMock(return_value=None)

        with pytest.raises(ValueError, match="세션을 찾을 수 없습니다"):
            async for _ in pipeline.stream_query("nonexistent", "질문"):
                pass


# =============================================================================
# 허용 파일 확장자 테스트
# =============================================================================


class TestAllowedExtensions:
    """파일 확장자 관련 테스트"""

    def test_허용_확장자_목록(self) -> None:
        """허용된 확장자가 올바른지 확인"""
        assert "pdf" in ALLOWED_EXTENSIONS
        assert "txt" in ALLOWED_EXTENSIONS
        assert "md" in ALLOWED_EXTENSIONS
        assert "csv" in ALLOWED_EXTENSIONS
        assert "docx" in ALLOWED_EXTENSIONS
        # 보안상 코드 파일 제외
        assert "py" not in ALLOWED_EXTENSIONS
        assert "js" not in ALLOWED_EXTENSIONS
