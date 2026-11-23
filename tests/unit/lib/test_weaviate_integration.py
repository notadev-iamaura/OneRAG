"""Weaviate 통합 식별 헤더(X-Weaviate-Client-Integration) 등록 테스트."""

from typing import Any

import weaviate
from weaviate.connect import ConnectionParams

from app import __version__
from app.lib.weaviate_integration import (
    INTEGRATION_HEADER,
    integration_header_value,
    register_integration_header,
)


class _RecordingIntegrations:
    def __init__(self) -> None:
        self.headers: dict[str, str] = {}

    def configure(self, config: Any) -> None:
        self.headers.update(config._to_header())


class _FakeClient:
    def __init__(self) -> None:
        self.integrations = _RecordingIntegrations()


def test_header_value_uses_app_version() -> None:
    assert integration_header_value() == f"onerag/{__version__}"


def test_register_sends_onerag_header() -> None:
    client = _FakeClient()

    register_integration_header(client)

    assert client.integrations.headers == {INTEGRATION_HEADER: f"onerag/{__version__}"}


def test_register_applies_header_to_real_client_connection() -> None:
    client = weaviate.WeaviateClient(
        connection_params=ConnectionParams.from_url("http://localhost:8080", 50051),
        skip_init_checks=True,
    )
    try:
        register_integration_header(client)

        assert client._connection.additional_headers[INTEGRATION_HEADER] == (
            f"onerag/{__version__}"
        )
    finally:
        client.close()


def test_register_never_raises() -> None:
    class _BrokenIntegrations:
        def configure(self, config: Any) -> None:
            raise RuntimeError("boom")

    class _BrokenClient:
        integrations = _BrokenIntegrations()

    register_integration_header(_BrokenClient())
    register_integration_header(object())
