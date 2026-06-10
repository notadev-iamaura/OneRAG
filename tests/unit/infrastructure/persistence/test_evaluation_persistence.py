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


@pytest.mark.asyncio
async def test_calculate_statistics_handles_timezone_aware_created_at():
    """timezone-aware created_at으로 통계 계산 시 TypeError가 발생하지 않아야 함.

    models.py의 created_at 컬럼은 DateTime(timezone=True)이므로
    PostgreSQL(asyncpg)에서 조회 시 aware datetime이 반환된다.
    경계값(today_start 등)을 naive datetime으로 생성하면
    'can't compare offset-naive and offset-aware datetimes' TypeError가 발생한다.
    """
    # Given: aware datetime created_at을 가진 평가 ORM 객체 2건
    now_aware = datetime.now(UTC)
    evaluations = [
        EvaluationModel(
            evaluation_id=f"eval_{i}",
            session_id=f"session_{i}",
            message_id=f"message_{i}",
            overall_score=5,
            evaluation_type="human",
            query_text="질문",
            response_text="답변",
            created_at=now_aware,
        )
        for i in range(2)
    ]

    manager = EvaluationDataManager()

    # When: 통계 계산 호출 (실DB 없이 ORM 객체 리스트 직접 전달)
    stats = await manager._calculate_statistics(evaluations)

    # Then: TypeError 없이 통계가 계산되고, 오늘 작성된 평가가 집계됨
    assert stats.total_evaluations == 2
    assert stats.evaluations_today == 2
    assert stats.evaluations_this_week == 2
    assert stats.evaluations_this_month == 2


@pytest.mark.asyncio
async def test_calculate_statistics_handles_naive_created_at_sqlite():
    """SQLite처럼 naive created_at이 반환되어도 통계 계산이 안전해야 함.

    SQLite는 DateTime(timezone=True)여도 tz 정보를 보존하지 않아 naive datetime을 반환한다.
    aware 경계값과 naive created_at을 비교할 때도 TypeError 없이 동작해야 한다.
    """
    # Given: tz 정보가 없는(naive) created_at을 가진 평가 ORM 객체
    now_naive = datetime.now(UTC).replace(tzinfo=None)
    evaluations = [
        EvaluationModel(
            evaluation_id="eval_naive",
            session_id="session_naive",
            message_id="message_naive",
            overall_score=4,
            evaluation_type="human",
            query_text="질문",
            response_text="답변",
            created_at=now_naive,
        )
    ]

    manager = EvaluationDataManager()

    # When
    stats = await manager._calculate_statistics(evaluations)

    # Then: naive 값도 UTC로 보정되어 정상 집계
    assert stats.total_evaluations == 1
    assert stats.evaluations_today == 1


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
