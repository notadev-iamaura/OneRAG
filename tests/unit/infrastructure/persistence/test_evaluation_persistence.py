from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from app.infrastructure.persistence.evaluation_manager import EvaluationDataManager
from app.infrastructure.persistence.models import EvaluationModel
from app.models.evaluation import EvaluationResponse, EvaluationUpdate


def test_evaluation_model_to_dict_matches_response_schema():
    evaluation = EvaluationModel(
        evaluation_id="eval_123",
        session_id="session_123",
        message_id="message_123",
        query_score=4,
        response_score=5,
        overall_score=5,
        feedback="useful",
        evaluator_id="user_123",
        evaluation_type="human",
        query_text="What is OneRAG?",
        response_text="A RAG system.",
        extra_metadata={"source": "unit-test"},
        created_at=datetime(2026, 5, 11, tzinfo=UTC),
    )

    payload = evaluation.to_dict()
    response = EvaluationResponse(**payload)

    assert payload["query"] == "What is OneRAG?"
    assert payload["response"] == "A RAG system."
    assert payload["evaluator_type"] == "human"
    assert response.query == "What is OneRAG?"
    assert response.response == "A RAG system."
    assert response.evaluator_type == "human"
    assert response.metadata == {"source": "unit-test"}


@pytest.mark.asyncio
async def test_update_evaluation_persists_metadata_to_extra_metadata():
    evaluation = EvaluationModel(
        evaluation_id="eval_123",
        session_id="session_123",
        message_id="message_123",
        query_text="Original query",
        response_text="Original response",
        evaluation_type="human",
        extra_metadata={"before": True},
        created_at=datetime(2026, 5, 11, tzinfo=UTC),
    )
    session = _FakeSession(evaluation)
    manager = EvaluationDataManager()
    manager.db_manager = _FakeDbManager(session)

    result = await manager.update_evaluation(
        "eval_123", EvaluationUpdate(metadata={"after": True}, feedback="updated")
    )

    assert result is not None
    assert evaluation.extra_metadata == {"after": True}
    assert evaluation.feedback == "updated"
    assert result.metadata == {"after": True}
    session.commit.assert_awaited_once()
    session.refresh.assert_awaited_once_with(evaluation)


class _FakeResult:
    def __init__(self, evaluation):
        self._evaluation = evaluation

    def scalar_one_or_none(self):
        return self._evaluation


class _FakeSession:
    def __init__(self, evaluation):
        self._evaluation = evaluation
        self.commit = AsyncMock()
        self.refresh = AsyncMock()

    async def execute(self, _statement):
        return _FakeResult(self._evaluation)


class _FakeSessionContext:
    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeDbManager:
    def __init__(self, session):
        self._session = session

    def get_session(self):
        return _FakeSessionContext(self._session)
