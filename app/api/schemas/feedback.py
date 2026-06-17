"""
피드백 API 스키마
사용자 피드백 요청/응답 Pydantic 모델
"""

from typing import Literal

from pydantic import BaseModel, Field


class FeedbackRequest(BaseModel):
    """
    피드백 요청 스키마

    사용자가 답변에 대한 피드백을 제출할 때 사용
    """

    session_id: str = Field(
        ...,
        description="세션 ID",
        examples=["session-123"],
    )
    message_id: str = Field(
        ...,
        description="메시지 ID (피드백 대상)",
        examples=["msg-456"],
    )
    rating: Literal[1, -1] = Field(
        ...,
        description="평점: 1 (좋아요), -1 (싫어요)",
        examples=[1, -1],
    )
    comment: str | None = Field(
        default=None,
        description="추가 코멘트 (선택)",
        examples=["답변이 정확하고 도움이 되었습니다"],
    )
    query: str | None = Field(
        default=None,
        description="원본 질문 (Golden Dataset 후보 등록용)",
        examples=["What is RAG?"],
    )
    response: str | None = Field(
        default=None,
        description="원본 답변 (Golden Dataset 후보 등록용)",
        examples=[
            "RAG combines retrieval and generation to ground LLM answers in documents."
        ],
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "session_id": "session-123",
                    "message_id": "msg-456",
                    "rating": 1,
                    "comment": "정확하고 유용한 답변이었습니다",
                }
            ]
        }
    }


class FeedbackResponse(BaseModel):
    """
    피드백 응답 스키마

    피드백 저장 결과를 반환
    """

    success: bool = Field(
        ...,
        description="피드백 저장 성공 여부",
    )
    feedback_id: str | None = Field(
        default=None,
        description="저장된 피드백 ID (실패 시 None)",
        examples=["fb-789"],
    )
    message: str = Field(
        ...,
        description="결과 메시지",
        examples=["피드백이 저장되었습니다"],
    )
    golden_candidate: bool = Field(
        default=False,
        description="Golden Dataset 후보 등록 여부",
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "success": True,
                    "feedback_id": "fb-789",
                    "message": "피드백이 저장되었습니다",
                    "golden_candidate": False,
                }
            ]
        }
    }
