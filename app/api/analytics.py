"""Public analytics event intake.

This endpoint accepts low-trust frontend events such as page views and chat
opens. Raw questions, answers, secrets, IPs, and direct personal identifiers
are not accepted into the durable analytics store.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from ..lib.logger import get_logger
from .analytics_event_store import get_analytics_event_store

logger = get_logger(__name__)
router = APIRouter(prefix="/analytics", tags=["Analytics"])


class AnalyticsEventRequest(BaseModel):
    eventType: str = Field(..., min_length=1, max_length=64)
    visitorId: str | None = Field(default=None, max_length=256)
    sessionId: str | None = Field(default=None, max_length=256)
    messageId: str | None = Field(default=None, max_length=256)
    channel: str | None = Field(default="web", max_length=64)
    route: str | None = Field(default=None, max_length=256)
    referrerOrigin: str | None = Field(default=None, max_length=256)
    metadata: dict[str, Any] | None = Field(default_factory=dict)


@router.post("/event")
async def record_analytics_event(payload: AnalyticsEventRequest, request: Request):
    """Record a privacy-scoped frontend analytics event."""
    try:
        event = payload.dict()
        if not event.get("referrerOrigin"):
            event["referrerOrigin"] = request.headers.get("origin") or request.headers.get("referer")
        stored = get_analytics_event_store().record_event(event)
        return {
            "ok": True,
            "eventId": stored["event_id"],
            "eventType": stored["event_type"],
        }
    except Exception as error:
        # Analytics intake must not break user-facing pages.
        logger.warning(
            "analytics event recording failed",
            extra={"error": str(error), "error_type": type(error).__name__},
        )
        return {"ok": False}
