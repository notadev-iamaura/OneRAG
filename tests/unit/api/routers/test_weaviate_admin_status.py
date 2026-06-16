"""Weaviate 관리 status 엔드포인트 도메인 범용화 회귀 테스트.

검증 목표:
- 샘플 문서 응답에 venue 도메인 키(entity_name/location/price/capacity/rating)를
  하드코딩하지 않는다(도메인 중립).
- 실제 존재하는 메타데이터(선언 프로퍼티 + metadata_json 파싱 결과)를
  동적으로 노출한다(데이터 무손실, 임의 도메인 호환).
"""

import json
from typing import Any
from unittest.mock import MagicMock

import pytest


def _build_mock_weaviate_client(sample_props: dict[str, Any]) -> MagicMock:
    """status 엔드포인트가 사용하는 weaviate 클라이언트를 모킹한다."""
    sample_obj = MagicMock()
    sample_obj.properties = sample_props

    sample_response = MagicMock()
    sample_response.objects = [sample_obj]

    collection = MagicMock()
    collection.aggregate.over_all = MagicMock(
        return_value=MagicMock(total_count=1)
    )
    collection.query.fetch_objects = MagicMock(return_value=sample_response)

    client = MagicMock()
    client.is_ready = MagicMock(return_value=True)
    client.collections.exists = MagicMock(return_value=True)
    client.collections.get = MagicMock(return_value=collection)

    wrapper = MagicMock()
    wrapper.client = client
    return wrapper


@pytest.mark.asyncio
async def test_status_sample_is_domain_neutral(monkeypatch: Any) -> None:
    """venue 도메인 키를 하드코딩하지 않고, 실제 메타데이터를 동적 노출한다."""
    import app.api.routers.weaviate_admin_router as router_mod

    # 임의 도메인 문서: 선언 프로퍼티(source_file/file_type) +
    # metadata_json에 보관된 도메인 메타데이터(author/topic)
    sample_props = {
        "content": "본문 내용입니다. " * 20,
        "source_file": "guide.md",
        "file_type": "md",
        "metadata_json": json.dumps(
            {"author": "홍길동", "topic": "온보딩"}, ensure_ascii=False
        ),
    }
    monkeypatch.setattr(
        router_mod,
        "get_weaviate_client",
        lambda: _build_mock_weaviate_client(sample_props),
    )

    result = await router_mod.check_weaviate_status()

    assert result["connected"] is True
    assert result["document_count"] == 1
    sample = result["sample_documents"][0]

    # 1) content_preview는 100자 미리보기 + "..."
    assert sample["content_preview"].endswith("...")
    assert len(sample["content_preview"]) <= 103

    # 2) venue 도메인 키를 최상위에 하드코딩하지 않는다.
    for venue_key in ("entity_name", "location", "price", "capacity", "rating"):
        assert venue_key not in sample

    # 3) 실제 메타데이터(선언 프로퍼티 + metadata_json 파싱)를 동적 노출한다.
    metadata = sample["metadata"]
    assert metadata["source_file"] == "guide.md"
    assert metadata["file_type"] == "md"
    assert metadata["author"] == "홍길동"
    assert metadata["topic"] == "온보딩"
    # content/metadata_json 원본 컬럼은 노출하지 않는다(중복/대용량 방지).
    assert "content" not in metadata
    assert "metadata_json" not in metadata


@pytest.mark.asyncio
async def test_status_sample_handles_invalid_metadata_json(
    monkeypatch: Any,
) -> None:
    """metadata_json 파싱 실패해도 예외 없이 선언 프로퍼티만 노출한다."""
    import app.api.routers.weaviate_admin_router as router_mod

    sample_props = {
        "content": "x",
        "source_file": "broken.txt",
        "metadata_json": "{not valid json",
    }
    monkeypatch.setattr(
        router_mod,
        "get_weaviate_client",
        lambda: _build_mock_weaviate_client(sample_props),
    )

    result = await router_mod.check_weaviate_status()
    sample = result["sample_documents"][0]

    assert sample["metadata"]["source_file"] == "broken.txt"
    # 깨진 metadata_json은 무시되고 키는 노출되지 않는다.
    assert "metadata_json" not in sample["metadata"]
