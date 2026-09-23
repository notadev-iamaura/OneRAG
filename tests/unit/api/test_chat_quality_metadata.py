"""
Chat API 품질 메타데이터 응답 테스트

Self-RAG 품질 게이트의 품질 점수가 API 응답에 제대로 노출되는지 검증합니다.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routers.chat_router import _get_confidence_level, router, set_chat_service
from app.api.schemas.chat_schemas import ChatResponse


@pytest.mark.unit
class TestChatQualityMetadata:
    """Chat API 품질 메타데이터 응답 테스트"""

    def test_chat_response_schema_includes_metadata_field(self):
        """
        ChatResponse 스키마에 metadata 필드 존재 검증

        Given: ChatResponse 스키마
        When: 인스턴스 생성
        Then: metadata 필드 존재 및 quality 객체 포함 가능
        """
        response = ChatResponse(
            answer="서울 강남구 맛집 3곳을 추천드립니다...",
            sources=[],
            session_id="test-session",
            message_id="msg-123",
            processing_time=2.5,
            tokens_used=150,
            timestamp="2026-01-06T10:00:00",
            metadata={
                "quality": {
                    "score": 0.87,
                    "confidence": "high",
                    "self_rag_applied": True,
                }
            }
        )

        assert "metadata" in response.model_dump()
        assert "quality" in response.metadata
        assert response.metadata["quality"]["score"] == 0.87
        assert response.metadata["quality"]["confidence"] == "high"

    def test_quality_metadata_structure(self):
        """
        품질 메타데이터 구조 검증

        Given: Self-RAG 품질 점수 데이터
        When: ChatResponse 생성
        Then: quality 객체에 score, confidence, self_rag_applied 포함
        """
        response = ChatResponse(
            answer="답변",
            sources=[],
            session_id="test",
            message_id="msg-1",
            processing_time=1.0,
            tokens_used=100,
            timestamp="2026-01-06T10:00:00",
            metadata={
                "quality": {
                    "score": 0.65,
                    "confidence": "medium",
                    "self_rag_applied": True,
                }
            }
        )

        quality = response.metadata["quality"]

        # 필수 필드 검증
        assert "score" in quality
        assert "confidence" in quality
        assert "self_rag_applied" in quality

        # 점수 범위 검증
        assert 0.0 <= quality["score"] <= 1.0

        # 신뢰도 레벨 검증
        assert quality["confidence"] in ["low", "medium", "high"]

    def test_quality_metadata_with_refusal(self):
        """
        저품질 거부 시 refusal_reason 포함 검증

        Given: 품질 점수 < 0.6 (저품질)
        When: ChatResponse 생성
        Then: quality 객체에 refusal_reason 포함
        """
        response = ChatResponse(
            answer="죄송합니다. 확실한 정보를 찾지 못했습니다.",
            sources=[],
            session_id="test",
            message_id="msg-2",
            processing_time=1.5,
            tokens_used=80,
            timestamp="2026-01-06T10:00:00",
            metadata={
                "quality": {
                    "score": 0.45,
                    "confidence": "low",
                    "self_rag_applied": True,
                    "refusal_reason": "quality_too_low",
                }
            }
        )

        quality = response.metadata["quality"]
        assert quality["score"] < 0.6
        assert quality["confidence"] == "low"
        assert quality["refusal_reason"] == "quality_too_low"

    def test_confidence_level_calculation(self):
        """
        신뢰도 레벨 계산 로직 검증

        Given: 다양한 품질 점수
        When: _get_confidence_level() 호출
        Then: 올바른 신뢰도 레벨 반환
        """
        # 테스트 케이스
        assert _get_confidence_level(0.95) == "high"
        assert _get_confidence_level(0.80) == "high"
        assert _get_confidence_level(0.75) == "medium"
        assert _get_confidence_level(0.60) == "medium"
        assert _get_confidence_level(0.55) == "low"
        assert _get_confidence_level(0.30) == "low"

    def test_metadata_field_default_empty_dict(self):
        """
        metadata 필드 기본값 검증

        Given: metadata 미지정
        When: ChatResponse 생성
        Then: 빈 딕셔너리 기본값
        """
        response = ChatResponse(
            answer="답변",
            sources=[],
            session_id="test",
            message_id="msg-3",
            processing_time=1.0,
            tokens_used=100,
            timestamp="2026-01-06T10:00:00",
            # metadata 미지정
        )

        assert response.metadata == {}

    def test_quality_metadata_optional_fields(self):
        """
        품질 메타데이터 선택 필드 검증

        Given: Self-RAG 비활성화 상태
        When: ChatResponse 생성
        Then: quality 필드 없어도 정상 동작
        """
        response = ChatResponse(
            answer="답변",
            sources=[],
            session_id="test",
            message_id="msg-4",
            processing_time=1.0,
            tokens_used=100,
            timestamp="2026-01-06T10:00:00",
            metadata={
                "total_time": 2.5,
                # quality 필드 없음 (Self-RAG 비활성화)
            }
        )

        assert "quality" not in response.metadata
        assert response.metadata["total_time"] == 2.5


@pytest.mark.unit
class TestGetConfidenceLevel:
    """_get_confidence_level() 함수 입력 검증 및 정확성 테스트"""

    # ==================== 입력 검증 테스트 ====================

    def test_confidence_level_invalid_score_negative(self) -> None:
        """음수 점수는 ValueError 발생"""
        with pytest.raises(ValueError, match=r"Invalid quality score.*Must be in \[0.0, 1.0\]"):
            _get_confidence_level(-0.1)

    def test_confidence_level_invalid_score_above_one(self) -> None:
        """1.0 초과 점수는 ValueError 발생"""
        with pytest.raises(ValueError, match=r"Invalid quality score.*Must be in \[0.0, 1.0\]"):
            _get_confidence_level(1.5)

    def test_confidence_level_invalid_score_way_below_zero(self) -> None:
        """매우 작은 음수 점수는 ValueError 발생"""
        with pytest.raises(ValueError, match=r"Invalid quality score.*Must be in \[0.0, 1.0\]"):
            _get_confidence_level(-999.0)

    def test_confidence_level_invalid_score_way_above_one(self) -> None:
        """매우 큰 점수는 ValueError 발생"""
        with pytest.raises(ValueError, match=r"Invalid quality score.*Must be in \[0.0, 1.0\]"):
            _get_confidence_level(100.0)

    # ==================== 유효한 입력 테스트 ====================

    def test_confidence_level_boundary_zero(self) -> None:
        """경계값 0.0은 low 반환"""
        assert _get_confidence_level(0.0) == "low"

    def test_confidence_level_boundary_one(self) -> None:
        """경계값 1.0은 high 반환"""
        assert _get_confidence_level(1.0) == "high"

    def test_confidence_level_low(self) -> None:
        """0.6 미만은 low 반환"""
        assert _get_confidence_level(0.5) == "low"
        assert _get_confidence_level(0.59) == "low"

    def test_confidence_level_medium(self) -> None:
        """0.6 이상 0.8 미만은 medium 반환"""
        assert _get_confidence_level(0.6) == "medium"
        assert _get_confidence_level(0.7) == "medium"
        assert _get_confidence_level(0.79) == "medium"

    def test_confidence_level_high(self) -> None:
        """0.8 이상은 high 반환"""
        assert _get_confidence_level(0.8) == "high"
        assert _get_confidence_level(0.9) == "high"
        assert _get_confidence_level(1.0) == "high"


@pytest.mark.unit
@pytest.mark.parametrize(
    ("applied", "outcome", "final_status", "rollback_reason"),
    [
        (True, "regenerated", "ok", None),
        (True, "rolled_back", "failed", "final_eval_failed"),
        (False, "skipped", None, None),
    ],
)
def test_chat_exposes_self_rag_status(
    applied: bool,
    outcome: str,
    final_status: str | None,
    rollback_reason: str | None,
) -> None:
    model_info = {
        "provider": "test",
        "model": "test-model",
        "self_rag_applied": applied,
        "self_rag_outcome": outcome,
        "self_rag_eval_status": "ok" if applied else None,
        "self_rag_final_eval_status": final_status,
        "self_rag_rollback_reason": rollback_reason,
        "self_rag_skip_reason": None if applied else "evaluator_unavailable",
    }
    rag_result = {
        "answer": "답변",
        "sources": [],
        "tokens_used": 10,
        "topic": "test",
        "model_info": model_info,
    }
    if applied:
        rag_result["quality_score"] = 0.8

    service = MagicMock()
    service.handle_session = AsyncMock(return_value={"success": True, "session_id": "session"})
    service.execute_rag_pipeline = AsyncMock(return_value=rag_result)
    service.add_conversation_to_session = AsyncMock()
    app = FastAPI()
    app.include_router(router)
    set_chat_service(service)
    try:
        response = TestClient(app).post("/chat", json={"message": "질문"})
    finally:
        set_chat_service(None)  # type: ignore[arg-type]

    assert response.status_code == 200
    payload = response.json()
    if applied:
        assert payload["self_rag_metadata"]["outcome"] == outcome
        assert payload["self_rag_metadata"]["eval_status"] == "ok"
        assert payload["self_rag_metadata"]["final_eval_status"] == final_status
        assert payload["self_rag_metadata"]["rollback_reason"] == rollback_reason
        assert payload["metadata"]["quality"]["status"] == outcome
    else:
        assert payload["self_rag_metadata"] is None
        assert payload["model_info"]["self_rag_skip_reason"] == "evaluator_unavailable"
