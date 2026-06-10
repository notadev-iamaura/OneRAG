"""
ChatService 스트리밍 테스트

ChatService.stream_rag_pipeline() 메서드 구현을 위한 TDD 테스트.
비동기 제너레이터로 스트리밍 이벤트를 yield하는 메서드 테스트.

이벤트 타입:
- metadata: 검색 결과 메타데이터 (문서 수, 소스 등)
- chunk: LLM 응답 텍스트 청크
- done: 스트리밍 완료 이벤트
- error: 에러 이벤트
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest


class TestChatServiceStreaming:
    """ChatService 스트리밍 테스트"""

    @pytest.mark.asyncio
    async def test_stream_rag_pipeline_yields_chunks(self):
        """stream_rag_pipeline이 청크를 yield하는지 확인"""
        from app.api.services.chat_service import ChatService

        # Mock 세션 모듈 설정
        mock_session = MagicMock()
        mock_session.get_session = AsyncMock(return_value={"is_valid": True})
        mock_session.get_context_string = AsyncMock(return_value="")
        mock_session.create_session = AsyncMock(return_value={"session_id": "test-123"})

        # Mock 생성 모듈 설정 - 스트리밍 제너레이터 반환
        mock_generation = MagicMock()

        async def mock_stream(*args, **kwargs):
            """스트리밍 응답 시뮬레이터"""
            yield "안녕"
            yield "하세요"

        mock_generation.stream_answer = mock_stream

        # Mock 검색 모듈 설정
        mock_retrieval = MagicMock()
        mock_retrieval.search = AsyncMock(return_value=[])

        modules = {
            "session": mock_session,
            "generation": mock_generation,
            "retrieval": mock_retrieval,
        }

        service = ChatService(modules, {})

        # 스트리밍 호출
        chunks = []
        async for event in service.stream_rag_pipeline(
            message="테스트",
            session_id="test-123",
        ):
            chunks.append(event)

        # 최소 1개 이상의 청크가 있어야 함
        assert len(chunks) >= 2

    @pytest.mark.asyncio
    async def test_stream_rag_pipeline_event_types(self):
        """스트리밍 이벤트 타입 확인 (metadata, chunk, done)"""
        from app.api.services.chat_service import ChatService

        # Mock 세션 모듈
        mock_session = MagicMock()
        mock_session.get_session = AsyncMock(return_value={"is_valid": True})
        mock_session.get_context_string = AsyncMock(return_value="")
        mock_session.create_session = AsyncMock(return_value={"session_id": "test-123"})
        mock_session.add_conversation = AsyncMock()

        # Mock 생성 모듈 - 스트리밍
        mock_generation = MagicMock()

        async def mock_stream(*args, **kwargs):
            yield "테스트 응답입니다."

        mock_generation.stream_answer = mock_stream

        # Mock 검색 모듈 - 문서 반환
        mock_retrieval = MagicMock()
        mock_doc = MagicMock()
        mock_doc.metadata = {"source": "test.pdf", "score": 0.9}
        mock_doc.content = "테스트 컨텐츠"
        mock_doc.page_content = "테스트 컨텐츠"
        mock_retrieval.search = AsyncMock(return_value=[mock_doc])

        modules = {
            "session": mock_session,
            "generation": mock_generation,
            "retrieval": mock_retrieval,
        }

        service = ChatService(modules, {})

        # 스트리밍 호출
        events = []
        async for event in service.stream_rag_pipeline(
            message="테스트 질문",
            session_id="test-123",
        ):
            events.append(event)

        # 이벤트 타입 확인
        event_types = [e.get("event") for e in events if isinstance(e, dict)]

        # metadata 이벤트가 있어야 함
        assert "metadata" in event_types, f"metadata 이벤트가 없습니다. 실제 이벤트: {event_types}"

        # chunk 이벤트가 있어야 함
        assert "chunk" in event_types, f"chunk 이벤트가 없습니다. 실제 이벤트: {event_types}"

        # done 이벤트가 있어야 함
        assert "done" in event_types, f"done 이벤트가 없습니다. 실제 이벤트: {event_types}"

    @pytest.mark.asyncio
    async def test_stream_rag_pipeline_metadata_event_content(self):
        """metadata 이벤트에 검색 결과 정보가 포함되는지 확인"""
        from app.api.services.chat_service import ChatService

        # Mock 세션 모듈
        mock_session = MagicMock()
        mock_session.get_session = AsyncMock(return_value={"is_valid": True})
        mock_session.get_context_string = AsyncMock(return_value="")
        mock_session.create_session = AsyncMock(return_value={"session_id": "test-123"})

        # Mock 생성 모듈
        mock_generation = MagicMock()

        async def mock_stream(*args, **kwargs):
            yield "응답"

        mock_generation.stream_answer = mock_stream

        # Mock 검색 모듈 - 2개 문서
        mock_retrieval = MagicMock()
        mock_docs = []
        for i in range(2):
            doc = MagicMock()
            doc.metadata = {"source": f"doc{i}.pdf", "score": 0.9 - i * 0.1}
            doc.content = f"문서 {i} 내용"
            doc.page_content = f"문서 {i} 내용"
            mock_docs.append(doc)

        mock_retrieval.search = AsyncMock(return_value=mock_docs)

        modules = {
            "session": mock_session,
            "generation": mock_generation,
            "retrieval": mock_retrieval,
        }

        service = ChatService(modules, {})

        # 스트리밍 호출
        metadata_event = None
        async for event in service.stream_rag_pipeline(
            message="테스트",
            session_id="test-123",
        ):
            if isinstance(event, dict) and event.get("event") == "metadata":
                metadata_event = event
                break

        # metadata 이벤트 검증
        assert metadata_event is not None, "metadata 이벤트가 없습니다"
        assert "data" in metadata_event, "metadata 이벤트에 data가 없습니다"

        data = metadata_event["data"]
        assert "session_id" in data, "session_id가 없습니다"
        assert "search_results" in data, "search_results가 없습니다"
        assert data["search_results"] == 2, f"검색 결과 수가 2가 아닙니다: {data['search_results']}"

    @pytest.mark.asyncio
    async def test_stream_rag_pipeline_chunk_event_content(self):
        """chunk 이벤트에 텍스트와 인덱스가 포함되는지 확인"""
        from app.api.services.chat_service import ChatService

        # Mock 세션 모듈
        mock_session = MagicMock()
        mock_session.get_session = AsyncMock(return_value={"is_valid": True})
        mock_session.get_context_string = AsyncMock(return_value="")
        mock_session.create_session = AsyncMock(return_value={"session_id": "test-123"})

        # Mock 생성 모듈 - 여러 청크
        mock_generation = MagicMock()

        async def mock_stream(*args, **kwargs):
            yield "첫번째"
            yield "두번째"
            yield "세번째"

        mock_generation.stream_answer = mock_stream

        # Mock 검색 모듈
        mock_retrieval = MagicMock()
        mock_doc = MagicMock()
        mock_doc.metadata = {"source": "test.pdf"}
        mock_doc.content = "테스트"
        mock_doc.page_content = "테스트"
        mock_retrieval.search = AsyncMock(return_value=[mock_doc])

        modules = {
            "session": mock_session,
            "generation": mock_generation,
            "retrieval": mock_retrieval,
        }

        service = ChatService(modules, {})

        # 스트리밍 호출
        chunk_events = []
        async for event in service.stream_rag_pipeline(
            message="테스트",
            session_id="test-123",
        ):
            if isinstance(event, dict) and event.get("event") == "chunk":
                chunk_events.append(event)

        # 청크 이벤트 검증
        assert len(chunk_events) == 3, f"청크 수가 3이 아닙니다: {len(chunk_events)}"

        # 각 청크에 필수 필드 확인
        for i, chunk in enumerate(chunk_events):
            assert "data" in chunk, f"청크 {i}에 data가 없습니다"
            assert "chunk_index" in chunk, f"청크 {i}에 chunk_index가 없습니다"
            assert chunk["chunk_index"] == i, f"청크 인덱스가 잘못됨: {chunk['chunk_index']} != {i}"

    @pytest.mark.asyncio
    async def test_stream_rag_pipeline_done_event_content(self):
        """done 이벤트에 완료 정보가 포함되는지 확인"""
        from app.api.services.chat_service import ChatService

        # Mock 세션 모듈
        mock_session = MagicMock()
        mock_session.get_session = AsyncMock(return_value={"is_valid": True})
        mock_session.get_context_string = AsyncMock(return_value="")
        mock_session.create_session = AsyncMock(return_value={"session_id": "test-123"})

        # Mock 생성 모듈
        mock_generation = MagicMock()
        mock_generation.provider = "openrouter"
        mock_generation.default_model = "test/model"

        async def mock_stream(*args, **kwargs):
            yield "청크1"
            yield "청크2"

        mock_generation.stream_answer = mock_stream

        # Mock 검색 모듈
        mock_retrieval = MagicMock()
        mock_doc = MagicMock()
        mock_doc.metadata = {"source": "test.pdf", "score": 0.9}
        mock_doc.content = "테스트"
        mock_doc.page_content = "테스트"
        mock_retrieval.search = AsyncMock(return_value=[mock_doc])

        modules = {
            "session": mock_session,
            "generation": mock_generation,
            "retrieval": mock_retrieval,
        }

        service = ChatService(modules, {})

        # 스트리밍 호출
        done_event = None
        async for event in service.stream_rag_pipeline(
            message="테스트",
            session_id="test-123",
        ):
            if isinstance(event, dict) and event.get("event") == "done":
                done_event = event
                break

        # done 이벤트 검증
        assert done_event is not None, "done 이벤트가 없습니다"
        assert "data" in done_event, "done 이벤트에 data가 없습니다"

        data = done_event["data"]
        assert "session_id" in data, "session_id가 없습니다"
        assert "message_id" in data, "message_id가 없습니다"
        assert "total_chunks" in data, "total_chunks가 없습니다"
        assert "sources" in data, "sources가 없습니다"
        assert "model_info" in data, "model_info가 없습니다"
        assert data["total_chunks"] == 2, f"청크 수가 2가 아닙니다: {data['total_chunks']}"
        assert data["tokens_used"] > 0
        assert data["model_info"]["provider"] == "openrouter"
        mock_session.add_conversation.assert_called_once()

    @pytest.mark.asyncio
    async def test_stream_rag_pipeline_no_results_returns_graceful_done(self):
        """검색 0건은 error 대신 안내 chunk와 done 이벤트를 반환"""
        from app.api.services.chat_service import ChatService

        mock_session = MagicMock()
        mock_session.get_session = AsyncMock(return_value={"is_valid": True})
        mock_session.get_context_string = AsyncMock(return_value="")
        mock_session.create_session = AsyncMock(return_value={"session_id": "test-123"})
        mock_session.add_conversation = AsyncMock()

        mock_generation = MagicMock()
        mock_generation.stream_answer = MagicMock()

        mock_retrieval = MagicMock()
        mock_retrieval.search = AsyncMock(return_value=[])

        service = ChatService(
            {"session": mock_session, "generation": mock_generation, "retrieval": mock_retrieval},
            {},
        )

        events = [
            event
            async for event in service.stream_rag_pipeline(
                message="문서 없는 질문",
                session_id="test-123",
            )
        ]

        event_types = [event["event"] for event in events]
        assert event_types == ["metadata", "chunk", "done"]
        assert "관련 문서를 찾을 수 없습니다" in events[1]["data"]
        assert events[-1]["data"]["total_chunks"] == 1
        mock_generation.stream_answer.assert_not_called()

    @pytest.mark.asyncio
    async def test_stream_rag_pipeline_first_token_timeout_falls_back(self):
        """첫 청크 지연 시 비스트리밍 fallback 답변을 chunk로 반환"""
        from app.api.services.chat_service import ChatService
        from app.modules.core.generation.generator import GenerationResult

        mock_session = MagicMock()
        mock_session.get_session = AsyncMock(return_value={"is_valid": True})
        mock_session.get_context_string = AsyncMock(return_value="")
        mock_session.create_session = AsyncMock(return_value={"session_id": "test-123"})
        mock_session.add_conversation = AsyncMock()

        mock_generation = MagicMock()

        async def slow_stream(*args, **kwargs):
            await asyncio.sleep(1)
            yield "늦은 응답"

        mock_generation.stream_answer = slow_stream
        mock_generation.generate_answer = AsyncMock(
            return_value=GenerationResult(
                answer="비스트리밍 fallback 답변입니다.",
                text="비스트리밍 fallback 답변입니다.",
                tokens_used=17,
                model_used="fallback-model",
                provider="openrouter",
                generation_time=0.2,
            )
        )

        mock_doc = MagicMock()
        mock_doc.metadata = {"source": "test.pdf"}
        mock_doc.content = "테스트"
        mock_doc.page_content = "테스트"
        mock_retrieval = MagicMock()
        mock_retrieval.search = AsyncMock(return_value=[mock_doc])

        service = ChatService(
            {"session": mock_session, "generation": mock_generation, "retrieval": mock_retrieval},
            {},
        )

        events = [
            event
            async for event in service.stream_rag_pipeline(
                message="느린 질문",
                session_id="test-123",
                options={"first_token_timeout": 0.01},
            )
        ]

        assert [event["event"] for event in events] == ["metadata", "chunk", "done"]
        assert events[1]["data"] == "비스트리밍 fallback 답변입니다."
        assert events[-1]["data"]["tokens_used"] == 17
        assert events[-1]["data"]["model_info"]["model"] == "fallback-model"
        mock_generation.generate_answer.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_stream_rag_pipeline_error_handling(self):
        """에러 발생 시 error 이벤트가 yield되는지 확인"""
        from app.api.services.chat_service import ChatService

        # Mock 세션 모듈 - 에러 발생
        mock_session = MagicMock()
        mock_session.get_session = AsyncMock(side_effect=Exception("세션 에러"))
        mock_session.create_session = AsyncMock(return_value={"session_id": "test-123"})

        modules = {
            "session": mock_session,
            "generation": MagicMock(),
            "retrieval": MagicMock(),
        }

        service = ChatService(modules, {})

        # 스트리밍 호출 - 에러 이벤트 확인
        error_event = None
        async for event in service.stream_rag_pipeline(
            message="테스트",
            session_id="test-123",
        ):
            if isinstance(event, dict) and event.get("event") == "error":
                error_event = event
                break

        # error 이벤트 검증
        assert error_event is not None, "error 이벤트가 없습니다"
        assert "error_code" in error_event, "error_code가 없습니다"
        assert "message" in error_event, "message가 없습니다"

    @pytest.mark.asyncio
    async def test_stream_rag_pipeline_creates_session_if_needed(self):
        """세션이 없으면 새로 생성하는지 확인"""
        from app.api.services.chat_service import ChatService

        # Mock 세션 모듈 - 세션 없음 → 새로 생성
        mock_session = MagicMock()
        mock_session.get_session = AsyncMock(return_value={"is_valid": False})
        mock_session.create_session = AsyncMock(return_value={"session_id": "new-session-456"})
        mock_session.get_context_string = AsyncMock(return_value="")

        # Mock 생성 모듈
        mock_generation = MagicMock()

        async def mock_stream(*args, **kwargs):
            yield "응답"

        mock_generation.stream_answer = mock_stream

        # Mock 검색 모듈
        mock_retrieval = MagicMock()
        mock_retrieval.search = AsyncMock(return_value=[])

        modules = {
            "session": mock_session,
            "generation": mock_generation,
            "retrieval": mock_retrieval,
        }

        service = ChatService(modules, {})

        # 스트리밍 호출
        metadata_event = None
        async for event in service.stream_rag_pipeline(
            message="테스트",
            session_id=None,  # 세션 ID 없음
        ):
            if isinstance(event, dict) and event.get("event") == "metadata":
                metadata_event = event
                break

        # 새 세션 생성 확인
        mock_session.create_session.assert_called_once()

        # metadata에 새 세션 ID가 포함되어야 함
        assert metadata_event is not None
        assert metadata_event["data"]["session_id"] == "new-session-456"

    @pytest.mark.asyncio
    async def test_stream_rag_pipeline_with_options(self):
        """옵션이 올바르게 전달되는지 확인"""
        from app.api.services.chat_service import ChatService

        # Mock 세션 모듈
        mock_session = MagicMock()
        mock_session.get_session = AsyncMock(return_value={"is_valid": True})
        mock_session.get_context_string = AsyncMock(return_value="")
        mock_session.create_session = AsyncMock(return_value={"session_id": "test-123"})

        # Mock 생성 모듈 - 옵션 확인
        mock_generation = MagicMock()
        received_options = {}

        async def mock_stream(query, context_documents, options=None):
            nonlocal received_options
            received_options = options or {}
            yield "응답"

        mock_generation.stream_answer = mock_stream

        # Mock 검색 모듈
        mock_retrieval = MagicMock()
        mock_doc = MagicMock()
        mock_doc.metadata = {"source": "test.pdf"}
        mock_doc.content = "테스트"
        mock_doc.page_content = "테스트"
        mock_retrieval.search = AsyncMock(return_value=[mock_doc])

        modules = {
            "session": mock_session,
            "generation": mock_generation,
            "retrieval": mock_retrieval,
        }

        service = ChatService(modules, {})

        # 옵션과 함께 스트리밍 호출
        options = {
            "temperature": 0.7,
            "max_tokens": 1000,
            "model": "anthropic/claude-sonnet-4",
        }

        async for _ in service.stream_rag_pipeline(
            message="테스트",
            session_id="test-123",
            options=options,
        ):
            pass

        # 옵션이 전달되었는지 확인
        assert "temperature" in received_options
        assert received_options["temperature"] == 0.7

    @pytest.mark.asyncio
    async def test_stream_no_generation_module_emits_error(self):
        """생성 모듈이 스트리밍 미지원이면 안내문을 저장/성공집계하지 않고 error로 종료(#7)"""
        from app.api.services.chat_service import ChatService

        mock_session = MagicMock()
        mock_session.get_session = AsyncMock(return_value={"is_valid": True})
        mock_session.get_context_string = AsyncMock(return_value="")
        mock_session.create_session = AsyncMock(return_value={"session_id": "test-123"})
        mock_session.add_conversation = AsyncMock()

        # stream_answer가 없는 생성 모듈(else 분기 유도) + provider 메타데이터만 제공
        mock_generation = MagicMock(spec=["provider", "default_model"])
        mock_generation.provider = "openrouter"
        mock_generation.default_model = "test/model"

        # 검색은 문서를 반환해 no-docs 분기가 아닌 no-gen 분기로 진입시킨다.
        mock_doc = MagicMock()
        mock_doc.metadata = {"source": "test.pdf", "score": 0.9}
        mock_doc.content = "테스트"
        mock_doc.page_content = "테스트"
        mock_retrieval = MagicMock()
        mock_retrieval.search = AsyncMock(return_value=[mock_doc])

        service = ChatService(
            {"session": mock_session, "generation": mock_generation, "retrieval": mock_retrieval},
            {},
        )

        events = [
            event
            async for event in service.stream_rag_pipeline(
                message="테스트", session_id="test-123"
            )
        ]

        event_types = [e.get("event") for e in events if isinstance(e, dict)]
        assert "error" in event_types
        assert "done" not in event_types  # 실패는 done으로 종료하지 않는다
        assert events[-1]["event"] == "error"
        mock_session.add_conversation.assert_not_called()
        # 실패 턴은 성공 토큰으로 집계되지 않는다.
        assert service.get_stats()["total_tokens"] == 0

    @pytest.mark.asyncio
    async def test_stream_no_results_tokens_zero_and_not_persisted(self):
        """검색 0건 안내 응답은 tokens_used=0이고 저장/성공집계되지 않는다(#7/[28])"""
        from app.api.services.chat_service import ChatService

        mock_session = MagicMock()
        mock_session.get_session = AsyncMock(return_value={"is_valid": True})
        mock_session.get_context_string = AsyncMock(return_value="")
        mock_session.create_session = AsyncMock(return_value={"session_id": "test-123"})
        mock_session.add_conversation = AsyncMock()

        mock_generation = MagicMock()
        mock_generation.stream_answer = MagicMock()

        mock_retrieval = MagicMock()
        mock_retrieval.search = AsyncMock(return_value=[])

        service = ChatService(
            {"session": mock_session, "generation": mock_generation, "retrieval": mock_retrieval},
            {},
        )

        events = [
            event
            async for event in service.stream_rag_pipeline(
                message="문서 없는 질문", session_id="test-123"
            )
        ]

        assert [e["event"] for e in events] == ["metadata", "chunk", "done"]
        assert events[-1]["data"]["tokens_used"] == 0
        mock_session.add_conversation.assert_not_called()
        assert service.get_stats()["total_tokens"] == 0

    def test_format_stream_sources_preserves_zero_score(self):
        """관련도 0.0(유효값)이 falsy로 버려지지 않고 보존되는지 확인(#14)"""
        from app.api.services.chat_service import ChatService

        service = ChatService({}, {})

        zero_doc = MagicMock()
        zero_doc.score = 0.0
        zero_doc.metadata = {"score": 0.5, "source": "a.pdf"}
        zero_doc.page_content = "내용"

        none_doc = MagicMock()
        none_doc.score = None
        none_doc.metadata = {"score": 0.0, "source": "b.pdf"}
        none_doc.page_content = "내용"

        sources = service._format_stream_sources([zero_doc, none_doc])

        # document.score=0.0이 metadata score 0.5에 가려지지 않아야 한다.
        assert sources[0]["relevance"] == 0.0
        # document.score=None이면 metadata score 0.0이 그대로 보존돼야 한다.
        assert sources[1]["relevance"] == 0.0

    def test_format_stream_sources_excludes_context_expanded(self):
        """인접 청크 확장으로 추가된 이웃 청크는 스트리밍 소스에서 제외돼야 한다(#4)"""
        from app.api.services.chat_service import ChatService

        service = ChatService({}, {})

        hit = MagicMock()
        hit.score = 0.9
        hit.metadata = {"source": "real.md"}
        hit.page_content = "실제 히트"

        neighbor = MagicMock()
        neighbor.score = 0.86
        neighbor.metadata = {"source": "real.md", "context_expanded": True}
        neighbor.page_content = "이웃 청크"

        sources = service._format_stream_sources([hit, neighbor])

        assert len(sources) == 1
        assert sources[0]["document"] == "real.md"


class TestChatServiceStreamingTimeoutGuards:
    """스트리밍 타임아웃 가드(첫 청크 전 예외 폴백·중간 실패·inter-chunk) 테스트"""

    @staticmethod
    def _build_modules(stream_answer_fn, fallback_answer: str):
        """공통 mock 모듈 구성: session/retrieval/generation."""
        from app.modules.core.generation.generator import GenerationResult

        mock_session = MagicMock()
        mock_session.get_session = AsyncMock(return_value={"is_valid": True})
        mock_session.get_context_string = AsyncMock(return_value="")
        mock_session.create_session = AsyncMock(return_value={"session_id": "test-123"})
        mock_session.add_conversation = AsyncMock()

        mock_generation = MagicMock()
        mock_generation.stream_answer = stream_answer_fn
        mock_generation.generate_answer = AsyncMock(
            return_value=GenerationResult(
                answer=fallback_answer,
                text=fallback_answer,
                tokens_used=11,
                model_used="fallback-model",
                provider="openrouter",
                generation_time=0.1,
            )
        )

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
    async def test_stream_pre_first_chunk_exception_falls_back(self):
        """첫 청크 전 예외 발생 시에도 비스트리밍 폴백으로 답변을 보장한다."""
        from app.api.services.chat_service import ChatService

        async def raising_stream(*args, **kwargs):
            # 첫 청크를 yield하기 전에 예외 발생.
            raise RuntimeError("스트리밍 연결 실패")
            yield  # pragma: no cover - 도달하지 않음(제너레이터 표식)

        modules = self._build_modules(raising_stream, "예외 후 폴백 답변.")
        service = ChatService(modules, {})

        events = [
            event
            async for event in service.stream_rag_pipeline(
                message="테스트", session_id="test-123"
            )
        ]

        # 예외 → 폴백 generate_answer 호출.
        modules["generation"].generate_answer.assert_awaited_once()
        chunk_events = [e for e in events if e.get("event") == "chunk"]
        done_events = [e for e in events if e.get("event") == "done"]
        assert chunk_events, f"폴백 chunk 이벤트가 없습니다: {events}"
        assert done_events, f"done 이벤트가 없습니다: {events}"
        assert "".join(e["data"] for e in chunk_events) == "예외 후 폴백 답변."
        # 생성 실패 error는 발생하지 않아야 한다(폴백 성공).
        assert not [e for e in events if e.get("event") == "error"]

    @pytest.mark.asyncio
    async def test_stream_mid_stream_failure_does_not_fall_back(self):
        """청크 1개 이상 전송 후 실패 시 폴백하지 않고 에러 처리(중복 답변 방지)."""
        from app.api.services.chat_service import ChatService
        from app.lib.errors import ErrorCode

        async def fail_after_first(*args, **kwargs):
            yield "첫 청크"
            raise RuntimeError("중간 스트리밍 실패")

        modules = self._build_modules(fail_after_first, "이 폴백은 호출되면 안 됨.")
        service = ChatService(modules, {})

        events = [
            event
            async for event in service.stream_rag_pipeline(
                message="테스트", session_id="test-123"
            )
        ]

        # 이미 청크를 보냈으므로 폴백 generate_answer는 호출되지 않아야 한다.
        modules["generation"].generate_answer.assert_not_awaited()
        chunk_events = [e for e in events if e.get("event") == "chunk"]
        assert chunk_events, f"첫 청크가 없습니다: {events}"
        assert chunk_events[0]["data"] == "첫 청크"
        # 중간 실패는 기존 생성 실패 에러로 처리돼야 한다.
        error_events = [e for e in events if e.get("event") == "error"]
        assert error_events, f"error 이벤트가 없습니다: {events}"
        assert error_events[0]["error_code"] == ErrorCode.GENERATION_REQUEST_FAILED.value

    @pytest.mark.asyncio
    async def test_stream_inter_chunk_timeout_emits_stage_timeout_error(self):
        """청크 간(inter-chunk) 지연이 generate_answer 예산을 넘으면 PIPE-001 에러로 중단."""
        from app.api.services.chat_service import ChatService
        from app.lib.errors import ErrorCode

        async def stall_after_first(*args, **kwargs):
            yield "첫 청크"
            await asyncio.sleep(5)  # inter-chunk 예산(0.05초)보다 길게 멈춤
            yield "도달하지 않는 청크"

        modules = self._build_modules(stall_after_first, "이 폴백은 호출되면 안 됨.")
        # pipeline_timeout opt-in: generate_answer 예산을 매우 짧게 설정.
        config = {
            "rag": {
                "pipeline_timeout": {
                    "enabled": True,
                    "stages": {"generate_answer": 0.05},
                }
            }
        }
        service = ChatService(modules, config)

        events = [
            event
            async for event in service.stream_rag_pipeline(
                message="테스트", session_id="test-123"
            )
        ]

        # 첫 청크는 전송, 이후 중간 timeout으로 stage timeout 에러가 나야 한다.
        chunk_events = [e for e in events if e.get("event") == "chunk"]
        assert chunk_events and chunk_events[0]["data"] == "첫 청크"
        error_events = [e for e in events if e.get("event") == "error"]
        assert error_events, f"error 이벤트가 없습니다: {events}"
        assert error_events[0]["error_code"] == ErrorCode.PIPELINE_STAGE_TIMEOUT.value
        # 중복 답변 방지: 폴백 generate_answer는 호출되지 않아야 한다.
        modules["generation"].generate_answer.assert_not_awaited()
