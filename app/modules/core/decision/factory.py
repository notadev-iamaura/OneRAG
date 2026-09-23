"""Noul provider 생성. 모드 해석은 호출자에게 맡긴다."""

from collections.abc import Mapping
from typing import Any

from .interfaces import DecisionProvider
from .jev_provider import JevDecisionProvider
from .mock_provider import MockDecisionProvider


def create_decision_provider(settings: Mapping[str, Any]) -> DecisionProvider:
    """검증된 설정으로 Jev 또는 네트워크 없는 mock provider를 생성한다."""
    provider = settings.get("provider", "jev")
    if provider == "mock":
        return MockDecisionProvider()
    if provider == "jev":
        return JevDecisionProvider(
            api_key=settings.get("api_key"),
            api_base=settings.get("api_base", "https://api.typesafe.ai"),
            systemone_path=settings.get("systemone_path", "/v1/systemone"),
            model=settings.get("model", "jev-latest"),
        )
    raise ValueError("Unknown decision provider")
