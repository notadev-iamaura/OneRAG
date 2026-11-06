"""
Weaviate 통합(integration) 식별 헤더

Weaviate 서버(1.38.0+)는 `X-Weaviate-Client-Integration: {name}/{version}` 요청 헤더로
트래픽을 보낸 통합을 식별합니다. 이 모듈은 OneRAG가 만드는 Weaviate 클라이언트에
`onerag/<버전>` 값을 등록합니다. 그 이전 버전의 서버는 헤더를 무시합니다.
"""

from __future__ import annotations

from typing import Any

from app.lib.logger import get_logger

logger = get_logger(__name__)

INTEGRATION_HEADER = "X-Weaviate-Client-Integration"
INTEGRATION_NAME = "onerag"


def integration_header_value() -> str:
    """`onerag/<버전>` 값을 반환합니다. 버전을 알 수 없으면 `onerag/unknown`."""
    try:
        from app import __version__

        version = str(__version__) or "unknown"
    except Exception:
        version = "unknown"
    return f"{INTEGRATION_NAME}/{version}"


def register_integration_header(client: Any) -> None:
    """
    Weaviate v4 클라이언트에 통합 식별 헤더를 등록합니다 (best-effort).

    `client.integrations.configure`는 REST와 gRPC 양쪽에 헤더를 적용합니다.
    `_IntegrationConfig`는 weaviate-client의 private API이므로 import와 서브클래스 정의를
    모두 try 안에 두어, API가 없거나 바뀌어도 연결을 깨뜨리지 않고 등록만 건너뜁니다.
    """
    try:
        from pydantic import Field
        from weaviate.connect.integrations import _IntegrationConfig

        value = integration_header_value()

        class _OneRAGIntegration(_IntegrationConfig):
            integration: str = Field(default=value, serialization_alias=INTEGRATION_HEADER)

        client.integrations.configure(_OneRAGIntegration())
    except Exception:  # 텔레메트리 실패가 Weaviate 연결을 깨뜨리면 안 된다
        logger.debug("Weaviate 통합 식별 헤더 등록 실패", exc_info=True)
