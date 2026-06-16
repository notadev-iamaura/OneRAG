"""Weaviate 스키마 도메인 범용화 회귀 테스트.

검증 목표:
- 코어 스키마는 도메인 무관 필드만(venue 도메인 필드 미정의 — 중립 기본)
- domain.yaml의 schema_fields로 도메인 필드를 정의하면 스키마/타입맵에 반영
- 임의 메타데이터는 metadata_json으로 보존(데이터 무손실)
"""

from typing import Any

import app.lib.weaviate_setup as weaviate_setup
from app.lib.weaviate_setup import (
    _document_schema_properties,
    document_property_types,
)

# venue(시설/예식/장소) 특정 도메인 필드 — OSS 기본 스키마에서 분리되어야 한다.
_VENUE_FIELDS = {"price", "capacity", "rating", "location", "entity_name", "numeric_value"}


def test_document_schema_contains_upload_and_management_contract_fields() -> None:
    property_names = {prop.name for prop in _document_schema_properties()}

    assert {
        "content",
        "embedding",
    } - property_names == {"embedding"}
    assert {
        "document_id",
        "source_file",
        "file_type",
        "file_size",
        "chunk_index",
        "total_chunks",
        "load_timestamp",
        "metadata_json",
        "page_number",
        "keys",
        "created_at",
    }.issubset(property_names)


def test_default_schema_is_domain_neutral_no_venue_fields() -> None:
    """(a) 기본(config 미정의)은 venue 도메인 필드를 스키마에 포함하지 않는다."""
    property_names = {prop.name for prop in _document_schema_properties()}

    assert _VENUE_FIELDS & property_names == set(), (
        "코어 스키마에 venue 도메인 필드가 누출되었습니다(도메인 중립 위반): "
        f"{_VENUE_FIELDS & property_names}"
    )
    # 임의 메타데이터 보존 컬럼은 항상 존재해야 데이터 무손실이 성립한다.
    assert "metadata_json" in property_names


def test_property_types_default_is_neutral() -> None:
    """단일 진실원천(document_property_types)도 기본은 venue 필드를 노출하지 않는다."""
    types = document_property_types()

    assert _VENUE_FIELDS & set(types) == set()
    # 코어 타입 분류가 올바른지 표본 검증
    assert types["content"] == "text"
    assert types["chunk_index"] == "int"
    assert types["load_timestamp"] == "number"
    assert types["keys"] == "text_array"


def _patch_domain_schema_fields(
    monkeypatch: Any, schema_fields: Any
) -> None:
    """domain.yaml 로드 결과를 schema_fields가 있는 config로 대체한다."""

    def _fake_load_config(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        return {"domain": {"metadata": {"schema_fields": schema_fields}}}

    # weaviate_setup이 지연 임포트하는 load_config를 패치한다.
    import app.lib.config_loader as config_loader

    monkeypatch.setattr(config_loader, "load_config", _fake_load_config)


def test_domain_schema_fields_reflected_in_schema_and_types(monkeypatch: Any) -> None:
    """(b) domain.yaml에 필드 정의 시 코드 변경 없이 스키마/타입맵에 반영된다."""
    _patch_domain_schema_fields(
        monkeypatch,
        [
            {"name": "price", "type": "text", "description": "가격/비용"},
            {"name": "capacity", "type": "int", "description": "수용 인원"},
            {"name": "score", "type": "number"},
        ],
    )

    property_names = {prop.name for prop in _document_schema_properties()}
    assert {"price", "capacity", "score"}.issubset(property_names)

    types = document_property_types()
    assert types["price"] == "text"
    assert types["capacity"] == "int"
    assert types["score"] == "number"


def test_domain_schema_fields_simple_mapping_form(monkeypatch: Any) -> None:
    """간단 매핑 형식({name: type})도 허용한다."""
    _patch_domain_schema_fields(monkeypatch, {"rating": "text", "amount": "int"})

    types = document_property_types()
    assert types["rating"] == "text"
    assert types["amount"] == "int"


def test_domain_schema_fields_cannot_override_core(monkeypatch: Any) -> None:
    """코어 필드와 충돌하는 도메인 정의는 무시되어 스키마 일관성을 보호한다."""
    _patch_domain_schema_fields(
        monkeypatch,
        [{"name": "content", "type": "int"}],  # 코어 content를 int로 덮어쓰려는 시도
    )

    types = document_property_types()
    # 코어 정의(text)가 보존되어야 한다.
    assert types["content"] == "text"


def test_domain_schema_fields_unsupported_type_demotes_to_text(
    monkeypatch: Any,
) -> None:
    """미지원 타입은 기본 text로 강등되어 스키마 생성이 깨지지 않는다."""
    _patch_domain_schema_fields(
        monkeypatch, [{"name": "weird", "type": "geocoordinates"}]
    )

    types = document_property_types()
    assert types["weird"] == "text"


def test_config_load_failure_falls_back_to_core(monkeypatch: Any) -> None:
    """config 로드 실패 시에도 코어 스키마로 graceful degradation 한다."""

    def _raise(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("config unavailable")

    import app.lib.config_loader as config_loader

    monkeypatch.setattr(config_loader, "load_config", _raise)

    # 예외 없이 코어 스키마만 생성되어야 한다.
    property_names = {prop.name for prop in _document_schema_properties()}
    assert "content" in property_names
    assert _VENUE_FIELDS & property_names == set()


def test_weaviate_setup_module_loaded() -> None:
    """모듈이 정상 임포트되는지 확인(스모크)."""
    assert hasattr(weaviate_setup, "_document_property_defs")
