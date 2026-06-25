from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import admin, analytics, analytics_event_store
from app.api.analytics_event_store import SQLiteAnalyticsEventStore
from app.lib.auth import get_api_key


@pytest.fixture()
def tracking_client(monkeypatch, tmp_path) -> TestClient:
    monkeypatch.setenv("ONERAG_ANALYTICS_DB", str(tmp_path / "analytics.sqlite3"))
    monkeypatch.setattr(analytics_event_store, "_STORE", None)

    test_app = FastAPI()
    test_app.include_router(analytics.router, prefix="/api")
    test_app.include_router(admin.router)
    test_app.dependency_overrides[get_api_key] = lambda: "test-admin-key"

    try:
        yield TestClient(test_app)
    finally:
        monkeypatch.setattr(analytics_event_store, "_STORE", None)


def _record_backend_event(
    store: SQLiteAnalyticsEventStore,
    payload: dict[str, object],
) -> None:
    stored = store.record_event(payload)
    assert stored["event_id"]


def test_admin_tracking_endpoints_aggregate_mock_backend_events(
    tracking_client: TestClient,
) -> None:
    now = datetime.now(UTC).replace(microsecond=0).isoformat()
    mock_events = [
        {
            "eventType": "page_view",
            "visitorId": "visitor-a",
            "sessionId": "session-a",
            "occurredAt": now,
            "route": "/bot",
        },
        {
            "eventType": "question_submitted",
            "visitorId": "visitor-a",
            "sessionId": "session-a",
            "occurredAt": now,
            "messageId": "msg-a",
        },
        {
            "eventType": "answer_completed",
            "visitorId": "visitor-a",
            "sessionId": "session-a",
            "occurredAt": now,
            "messageId": "msg-a",
            "modelProvider": "google",
            "modelName": "gemini-2.0-flash",
            "totalTokens": 120,
            "estimatedCostUsd": 0.0073,
            "latencyMs": 1250,
        },
        {
            "eventType": "question_submitted",
            "visitorId": "visitor-b",
            "sessionId": "session-b",
            "occurredAt": now,
            "messageId": "msg-b",
        },
        {
            "eventType": "answer_completed",
            "visitorId": "visitor-b",
            "sessionId": "session-b",
            "occurredAt": now,
            "messageId": "msg-b",
            "modelProvider": "openai",
            "modelName": "gpt-4o",
            "totalTokens": 80,
            "estimatedCostUsd": 0.005,
            "latencyMs": 750,
        },
    ]
    for event in mock_events:
        _record_backend_event(analytics_event_store.get_analytics_event_store(), event)

    headers = {"X-API-Key": "test-admin-key"}
    summary = tracking_client.get(
        "/api/admin/analytics/summary?days=365",
        headers=headers,
    )
    assert summary.status_code == 200
    summary_payload = summary.json()["summary"]
    assert summary_payload["visitors"] == 2
    assert summary_payload["sessions"] == 2
    assert summary_payload["questions"] == 2
    assert summary_payload["answers"] == 2
    assert summary_payload["totalTokens"] == 200
    assert summary_payload["estimatedCostUsd"] == pytest.approx(0.0123)
    assert summary_payload["avgLatencyMs"] == pytest.approx(1000)

    timeseries = tracking_client.get(
        "/api/admin/analytics/timeseries?months=12&grain=month",
        headers=headers,
    )
    assert timeseries.status_code == 200
    current_bucket = now[:7]
    month_row = next(
        row for row in timeseries.json()["series"] if row["bucket"] == current_bucket
    )
    assert month_row["visitors"] == 2
    assert month_row["questions"] == 2
    assert month_row["answers"] == 2
    assert month_row["totalTokens"] == 200

    models = tracking_client.get(
        "/api/admin/analytics/models?days=365",
        headers=headers,
    )
    assert models.status_code == 200
    by_model = {
        (row["provider"], row["model"]): row
        for row in models.json()["models"]
    }
    assert by_model[("google", "gemini-2.0-flash")]["answers"] == 1
    assert by_model[("google", "gemini-2.0-flash")]["totalTokens"] == 120
    assert by_model[("openai", "gpt-4o")]["answers"] == 1
    assert by_model[("openai", "gpt-4o")]["totalTokens"] == 80

    legacy_metrics = tracking_client.get("/api/admin/metrics?period=7d", headers=headers)
    assert legacy_metrics.status_code == 200
    assert legacy_metrics.json()["totalSessions"] == 2
    assert legacy_metrics.json()["totalQueries"] == 2
