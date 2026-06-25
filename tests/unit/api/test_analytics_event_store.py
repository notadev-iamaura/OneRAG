from datetime import datetime

from app.api.analytics_event_store import SQLiteAnalyticsEventStore


def test_analytics_store_hashes_ids_and_drops_raw_content(tmp_path) -> None:
    store = SQLiteAnalyticsEventStore(tmp_path / "analytics.sqlite3")

    stored = store.record_event(
        {
            "eventType": "answer_completed",
            "visitorId": "visitor-123",
            "sessionId": "session-123",
            "messageId": "message-123",
            "modelProvider": "google",
            "modelName": "gemini-2.0-flash",
            "totalTokens": 42,
            "referrerOrigin": "https://example.com/private?email=person@example.com",
            "metadata": {
                "route": "/bot",
                "email": "person@example.com",
                "rawQuestion": "Do not store this",
            },
        }
    )

    assert stored["visitor_id_hash"] != "visitor-123"
    assert stored["session_id_hash"] != "session-123"
    assert "person@example.com" not in str(stored)
    assert "Do not store this" not in str(stored)
    assert stored["referrer_origin"] == "https://example.com"
    assert stored["metadata"] == {"route": "/bot"}

    summary = store.summary(days=365)
    assert summary["answers"] == 1
    assert summary["totalTokens"] == 42


def test_analytics_timeseries_groups_monthly(tmp_path) -> None:
    store = SQLiteAnalyticsEventStore(tmp_path / "analytics.sqlite3")
    now = datetime.now().replace(microsecond=0)
    store.record_event(
        {
            "eventType": "question_submitted",
            "visitorId": "visitor-1",
            "sessionId": "session-1",
            "occurredAt": now.isoformat(),
        }
    )

    series = store.timeseries(months=12, grain="month")

    assert any(row["bucket"] == now.strftime("%Y-%m") and row["questions"] == 1 for row in series)


def test_analytics_store_drops_malformed_referrer(tmp_path) -> None:
    store = SQLiteAnalyticsEventStore(tmp_path / "analytics.sqlite3")

    stored = store.record_event(
        {
            "eventType": "page_view",
            "visitorId": "visitor-123",
            "referrerOrigin": "/private/path?email=person@example.com",
        }
    )

    assert stored["referrer_origin"] is None
    assert "person@example.com" not in str(stored)
