"""
ChatService 단위 테스트

테스트 범위:
- 세션 관리 (생성, 조회, 검증)
- RAG 파이프라인 실행
- 토픽 추출
- 대화 저장
- 통계 수집 및 조회
- 세션 정보 조회
- 에러 핸들링
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.api.services.chat_service import ChatService
from app.lib.errors import ErrorCode, SessionError


# 공유 픽스처 (모든 테스트 클래스가 사용)
@pytest.fixture
def mock_modules() -> dict[str, Any]:
    """Mock 모듈들"""
    return {
        "session": AsyncMock(),
        "retrieval": AsyncMock(),
        "generation": AsyncMock(),
        "query_router": MagicMock(enabled=False),
        "query_expansion": None,
        "self_rag": None,
        "circuit_breaker_factory": MagicMock(),
        "cost_tracker": MagicMock(),
        "performance_metrics": MagicMock(),
        "sql_search_service": None,
    }


@pytest.fixture
def mock_config() -> dict[str, Any]:
    """Mock 설정"""
    return {
        "generation": {
            "default_provider": "openrouter",
            "temperature": 0.2,
        },
        "rag": {
            "top_k": 10,
            "rerank_top_k": 5,
        },
    }


@pytest.fixture
def service(mock_modules: dict[str, Any], mock_config: dict[str, Any]) -> ChatService:
    """ChatService 인스턴스 (재사용)"""
    return ChatService(modules=mock_modules, config=mock_config)


@pytest.fixture
def context() -> dict[str, Any]:
    """요청 컨텍스트 (재사용)"""
    return {"ip": "127.0.0.1", "user_agent": "test"}


class TestChatServiceInit:
    """ChatService 초기화 테스트"""

    def test_init_success(
        self,
        mock_modules: dict[str, Any],
        mock_config: dict[str, Any],
    ) -> None:
        """
        ChatService 정상 초기화 테스트

        Given: 유효한 modules와 config
        When: ChatService 생성
        Then: 필드가 올바르게 초기화됨
        """
        service = ChatService(modules=mock_modules, config=mock_config)

        assert service.modules is mock_modules
        assert service.config is mock_config
        assert service.stats["total_chats"] == 0
        assert service.stats["total_tokens"] == 0
        assert service.stats["errors"] == 0
        assert service.rag_pipeline is not None

    def test_init_stats_structure(
        self,
        mock_modules: dict[str, Any],
        mock_config: dict[str, Any],
    ) -> None:
        """
        통계 딕셔너리 구조 검증

        Given: ChatService 인스턴스
        When: 초기화 완료
        Then: stats 딕셔너리가 모든 필수 키를 포함
        """
        service = ChatService(modules=mock_modules, config=mock_config)

        assert "total_chats" in service.stats
        assert "total_tokens" in service.stats
        assert "average_latency" in service.stats
        assert "error_rate" in service.stats
        assert "errors" in service.stats


class TestHandleSession:
    """handle_session 메서드 테스트"""

    @pytest.mark.asyncio
    async def test_new_session_creation(
        self,
        service: ChatService,
        context: dict[str, Any],
    ) -> None:
        """
        새 세션 생성 테스트

        Given: session_id=None
        When: handle_session 호출
        Then: 새 세션 생성 성공
        """
        # Mock: get_session → 세션 없음
        service.modules["session"].get_session = AsyncMock(
            return_value={"is_valid": False, "reason": "not_found"}
        )

        # Mock: create_session → 새 세션 ID
        service.modules["session"].create_session = AsyncMock(
            return_value={"session_id": "new-session-123"}
        )

        result = await service.handle_session(session_id=None, context=context)

        # 검증
        assert result["success"] is True
        assert result["session_id"] == "new-session-123"
        assert result["is_new"] is True
        assert "새 대화 세션" in result["message"]
        service.modules["session"].create_session.assert_called_once()

    @pytest.mark.asyncio
    async def test_existing_session_validation_success(
        self,
        service: ChatService,
        context: dict[str, Any],
    ) -> None:
        """
        기존 세션 검증 성공 테스트

        Given: 유효한 session_id
        When: handle_session 호출
        Then: 기존 세션 사용
        """
        # Mock: get_session → 유효한 세션
        service.modules["session"].get_session = AsyncMock(
            return_value={"is_valid": True, "session_id": "existing-123"}
        )

        result = await service.handle_session(session_id="existing-123", context=context)

        # 검증
        assert result["success"] is True
        assert result["session_id"] == "existing-123"
        assert result["is_new"] is False
        assert result["validation_result"]["is_valid"] is True
        service.modules["session"].get_session.assert_called_once_with("existing-123", context)

    @pytest.mark.asyncio
    async def test_existing_session_expired_creates_new(
        self,
        service: ChatService,
        context: dict[str, Any],
    ) -> None:
        """
        만료된 세션 ID로 요청 시 새 세션 생성

        Given: 만료된 session_id
        When: handle_session 호출
        Then: 새 세션 생성
        """
        # Mock: get_session → 세션 만료
        service.modules["session"].get_session = AsyncMock(
            return_value={"is_valid": False, "reason": "expired"}
        )

        # Mock: create_session → 새 세션
        service.modules["session"].create_session = AsyncMock(
            return_value={"session_id": "renewed-session-456"}
        )

        result = await service.handle_session(session_id="expired-123", context=context)

        # 검증
        assert result["success"] is True
        assert result["session_id"] == "renewed-session-456"
        assert result["is_new"] is True

    @pytest.mark.asyncio
    async def test_session_module_not_available(
        self,
        mock_config: dict[str, Any],
        context: dict[str, Any],
    ) -> None:
        """
        세션 모듈 없음 에러 핸들링

        Given: session 모듈이 None
        When: handle_session 호출
        Then: 에러 응답 반환 (예외 발생하지 않음)
        """
        # session 모듈이 없는 ChatService
        service = ChatService(modules={}, config=mock_config)

        result = await service.handle_session(session_id=None, context=context)

        # 검증
        assert result["success"] is False
        assert "Session module not available" in result["message"]

    @pytest.mark.asyncio
    async def test_session_create_failure_raises_error(
        self,
        service: ChatService,
        context: dict[str, Any],
    ) -> None:
        """
        세션 생성 실패 시 SessionError 발생

        Given: create_session이 예외 발생
        When: handle_session 호출
        Then: SessionError 발생
        """
        # Mock: create_session → 예외 발생
        service.modules["session"].get_session = AsyncMock(
            return_value={"is_valid": False}
        )
        service.modules["session"].create_session = AsyncMock(
            side_effect=Exception("DB connection error")
        )

        with pytest.raises(SessionError) as exc_info:
            await service.handle_session(session_id=None, context=context)

        assert exc_info.value.error_code == ErrorCode.SESSION_CREATE_FAILED


class TestExtractTopic:
    """extract_topic 메서드 테스트"""

    def test_search_topic(self, service: ChatService) -> None:
        """
        검색 키워드 포함 시 'search' 토픽 반환

        Given: 검색 키워드가 포함된 메시지
        When: extract_topic 호출
        Then: 'search' 반환
        """
        topic = service.extract_topic("강남 맛집 검색해줘")
        assert topic == "search"

    def test_document_topic(self, service: ChatService) -> None:
        """
        문서 키워드 포함 시 'document' 토픽 반환

        Given: 문서 키워드가 포함된 메시지
        When: extract_topic 호출
        Then: 'document' 반환
        """
        topic = service.extract_topic("문서 자료 보여줘")
        assert topic == "document"

    def test_help_topic(self, service: ChatService) -> None:
        """
        도움 키워드 포함 시 'help' 토픽 반환

        Given: 도움 키워드가 포함된 메시지
        When: extract_topic 호출
        Then: 'help' 반환
        """
        topic = service.extract_topic("이것 좀 도와줘")
        assert topic == "help"

    def test_technical_topic(self, service: ChatService) -> None:
        """
        기술 키워드 포함 시 'technical' 토픽 반환

        Given: 기술 키워드가 포함된 메시지
        When: extract_topic 호출
        Then: 'technical' 반환
        """
        topic = service.extract_topic("Python 코드 개발 방법")
        assert topic == "technical"

    def test_greeting_topic(self, service: ChatService) -> None:
        """
        인사 키워드 포함 시 'greeting' 토픽 반환

        토픽 추출 단일 소스 통합으로 인사 키워드가 'greeting'으로 분류된다
        (과거 ChatService 전용 맵에는 인사 토픽이 없어 'general'로 떨어졌음).

        Given: 인사 키워드가 포함된 메시지
        When: extract_topic 호출
        Then: 'greeting' 반환
        """
        topic = service.extract_topic("안녕하세요")
        assert topic == "greeting"

    def test_general_topic_fallback(self, service: ChatService) -> None:
        """
        키워드 매칭 없을 때 'general' 토픽 반환

        Given: 어떤 키워드도 매칭되지 않는 메시지
        When: extract_topic 호출
        Then: 'general' 반환
        """
        topic = service.extract_topic("오늘 점심은 뭐였지")
        assert topic == "general"

    def test_empty_message_returns_general(self, service: ChatService) -> None:
        """
        빈 메시지 → 'general' 토픽

        Given: 빈 문자열
        When: extract_topic 호출
        Then: 'general' 반환
        """
        topic = service.extract_topic("")
        assert topic == "general"

    def test_list_message_conversion(self, service: ChatService) -> None:
        """
        리스트 메시지 → 문자열 변환 → 토픽 추출

        Given: 리스트 형태의 메시지
        When: extract_topic 호출
        Then: 문자열로 변환 후 토픽 반환
        """
        topic = service.extract_topic(["검색", "찾기"])
        assert topic == "search"


class TestExecuteRAGPipeline:
    """execute_rag_pipeline 메서드 테스트"""

    @pytest.mark.asyncio
    async def test_execute_rag_pipeline_success(
        self,
        service: ChatService,
    ) -> None:
        """
        RAG 파이프라인 정상 실행

        Given: 유효한 메시지와 세션
        When: execute_rag_pipeline 호출
        Then: RAGPipeline.execute() 결과 반환
        """
        # Mock: RAGPipeline.execute
        mock_result = {
            "answer": "테스트 답변",
            "sources": [{"title": "문서1"}],
            "tokens_used": 100,
            "topic": "search",
            "processing_time": 1.5,
        }
        service.rag_pipeline.execute = AsyncMock(return_value=mock_result)

        result = await service.execute_rag_pipeline(
            message="질문",
            session_id="test-session",
            options={"limit": 10},
        )

        # 검증
        assert result["answer"] == "테스트 답변"
        assert len(result["sources"]) == 1
        assert result["tokens_used"] == 100
        service.rag_pipeline.execute.assert_called_once_with(
            message="질문",
            session_id="test-session",
            options={"limit": 10},
        )

    @pytest.mark.asyncio
    async def test_execute_rag_pipeline_with_options(
        self,
        service: ChatService,
    ) -> None:
        """
        옵션 포함 RAG 파이프라인 실행

        Given: 추가 옵션 포함
        When: execute_rag_pipeline 호출
        Then: 옵션이 RAGPipeline에 전달됨
        """
        mock_result = {
            "answer": "옵션 포함 답변",
            "sources": [],
            "tokens_used": 50,
        }
        service.rag_pipeline.execute = AsyncMock(return_value=mock_result)

        options = {"limit": 20, "min_score": 0.7, "use_agent": True}
        result = await service.execute_rag_pipeline(
            message="복잡한 질문",
            session_id="test",
            options=options,
        )

        # 검증
        assert result["answer"] == "옵션 포함 답변"
        call_args = service.rag_pipeline.execute.call_args
        assert call_args[1]["options"] == options


class TestAddConversationToSession:
    """add_conversation_to_session 메서드 테스트"""

    @pytest.mark.asyncio
    async def test_add_conversation_success(
        self,
        service: ChatService,
    ) -> None:
        """
        대화 저장 성공

        Given: 유효한 세션 ID와 메시지
        When: add_conversation_to_session 호출
        Then: session_module.add_conversation 호출됨
        """
        service.modules["session"].add_conversation = AsyncMock()

        await service.add_conversation_to_session(
            session_id="test-session",
            user_message="질문",
            assistant_answer="답변",
            metadata={"tokens": 100},
        )

        service.modules["session"].add_conversation.assert_called_once_with(
            "test-session",
            "질문",
            "답변",
            {"tokens": 100},
        )

    @pytest.mark.asyncio
    async def test_add_conversation_no_session_module(
        self,
        mock_config: dict[str, Any],
    ) -> None:
        """
        세션 모듈 없을 때 대화 저장 스킵

        Given: session 모듈이 None
        When: add_conversation_to_session 호출
        Then: 아무 동작 안 함 (에러 발생 안 함)
        """
        service = ChatService(modules={}, config=mock_config)

        # 예외 없이 정상 실행되어야 함
        await service.add_conversation_to_session(
            session_id="test",
            user_message="질문",
            assistant_answer="답변",
            metadata={},
        )


class TestUpdateStats:
    """update_stats 메서드 테스트"""

    def test_update_stats_success(self, service: ChatService) -> None:
        """
        성공 케이스 통계 업데이트

        Given: success=True 데이터
        When: update_stats 호출
        Then: total_chats, total_tokens, average_latency 업데이트
        """
        data = {
            "success": True,
            "tokens_used": 100,
            "latency": 2.0,
        }

        service.update_stats(data)

        assert service.stats["total_chats"] == 1
        assert service.stats["total_tokens"] == 100
        assert service.stats["average_latency"] == 2.0
        assert service.stats["errors"] == 0

    def test_update_stats_multiple_calls(self, service: ChatService) -> None:
        """
        여러 번 호출 시 평균 레이턴시 계산

        Given: 여러 성공 요청
        When: update_stats 반복 호출
        Then: 평균 레이턴시가 정확하게 계산됨
        """
        service.update_stats({"success": True, "tokens_used": 100, "latency": 2.0})
        service.update_stats({"success": True, "tokens_used": 150, "latency": 3.0})

        assert service.stats["total_chats"] == 2
        assert service.stats["total_tokens"] == 250
        assert service.stats["average_latency"] == 2.5  # (2.0 + 3.0) / 2

    def test_update_stats_error_case(self, service: ChatService) -> None:
        """
        에러 케이스 통계 업데이트

        Given: success=False 데이터
        When: update_stats 호출
        Then: errors와 error_rate 증가
        """
        data = {"success": False}

        service.update_stats(data)

        assert service.stats["total_chats"] == 1
        assert service.stats["errors"] == 1
        assert service.stats["error_rate"] == 100.0  # 1/1 * 100

    def test_update_stats_mixed_success_and_errors(self, service: ChatService) -> None:
        """
        성공과 에러 혼합 시 통계

        Given: 성공 2회, 실패 1회
        When: update_stats 반복 호출
        Then: error_rate 계산 정확
        """
        service.update_stats({"success": True, "tokens_used": 100, "latency": 1.0})
        service.update_stats({"success": True, "tokens_used": 200, "latency": 2.0})
        service.update_stats({"success": False})

        assert service.stats["total_chats"] == 3
        assert service.stats["errors"] == 1
        assert service.stats["error_rate"] == pytest.approx(33.33, rel=0.01)  # 1/3 * 100


class TestGetStats:
    """get_stats 메서드 테스트"""

    def test_get_stats_returns_copy(self, service: ChatService) -> None:
        """
        통계 조회 시 복사본 반환

        Given: 업데이트된 통계
        When: get_stats 호출
        Then: stats 딕셔너리 복사본 반환 (원본 보호)
        """
        service.update_stats({"success": True, "tokens_used": 100})
        stats = service.get_stats()

        # 복사본 검증
        stats["total_chats"] = 999
        assert service.stats["total_chats"] == 1  # 원본 보호됨

    def test_get_stats_structure(self, service: ChatService) -> None:
        """
        통계 딕셔너리 구조 검증

        Given: ChatService 인스턴스
        When: get_stats 호출
        Then: 필수 키 모두 포함
        """
        stats = service.get_stats()

        assert "total_chats" in stats
        assert "total_tokens" in stats
        assert "average_latency" in stats
        assert "error_rate" in stats
        assert "errors" in stats


class TestGetSessionInfo:
    """get_session_info 메서드 테스트"""

    @pytest.mark.asyncio
    async def test_get_session_info_success(
        self,
        service: ChatService,
    ) -> None:
        """
        세션 정보 조회 성공

        Given: 유효한 세션 ID
        When: get_session_info 호출
        Then: 세션 통계 정보 반환
        """
        # Mock: get_session → 유효한 세션
        service.modules["session"].get_session = AsyncMock(
            return_value={"is_valid": True}
        )

        # Mock: get_chat_history → 대화 히스토리
        service.modules["session"].get_chat_history = AsyncMock(
            return_value={
                "messages": [
                    {
                        "type": "user",
                        "content": "질문1",
                    },
                    {
                        "type": "assistant",
                        "content": "답변1",
                        "tokens_used": 100,
                        "processing_time": 1.5,
                        "model_info": {"model": "gemini-flash"},
                    },
                    {
                        "type": "user",
                        "content": "질문2",
                    },
                    {
                        "type": "assistant",
                        "content": "답변2",
                        "tokens_used": 150,
                        "processing_time": 2.0,
                        "model_info": {"model": "gemini-flash"},
                    },
                ]
            }
        )

        info = await service.get_session_info("test-session")

        # 검증
        assert info["session_id"] == "test-session"
        assert info["message_count"] == 4  # user 2 + assistant 2
        assert info["tokens_used"] == 250  # 100 + 150
        assert info["processing_time"] == 3.5  # 1.5 + 2.0
        assert info["model_info"]["model"] == "gemini-flash"
        assert "timestamp" in info

    @pytest.mark.asyncio
    async def test_get_session_info_not_found(
        self,
        service: ChatService,
    ) -> None:
        """
        세션 정보 조회 실패 (세션 없음)

        Given: 존재하지 않는 세션 ID
        When: get_session_info 호출
        Then: Exception 발생
        """
        # Mock: get_session → 세션 없음
        service.modules["session"].get_session = AsyncMock(
            return_value={"is_valid": False}
        )

        with pytest.raises(Exception, match="Session not found"):
            await service.get_session_info("nonexistent-session")

    @pytest.mark.asyncio
    async def test_get_session_info_no_module(
        self,
        mock_config: dict[str, Any],
    ) -> None:
        """
        세션 모듈 없을 때 에러 발생

        Given: session 모듈이 None
        When: get_session_info 호출
        Then: Exception 발생
        """
        service = ChatService(modules={}, config=mock_config)

        with pytest.raises(Exception, match="Session module not available"):
            await service.get_session_info("test-session")

    @pytest.mark.asyncio
    async def test_get_session_info_empty_history(
        self,
        service: ChatService,
    ) -> None:
        """
        대화 히스토리가 없는 세션 정보 조회

        Given: 유효하지만 메시지가 없는 세션
        When: get_session_info 호출
        Then: 기본값 통계 반환
        """
        service.modules["session"].get_session = AsyncMock(
            return_value={"is_valid": True}
        )
        service.modules["session"].get_chat_history = AsyncMock(
            return_value={"messages": []}
        )

        info = await service.get_session_info("empty-session")

        assert info["message_count"] == 0
        assert info["tokens_used"] == 0
        assert info["processing_time"] == 0
        assert info["model_info"] is None
