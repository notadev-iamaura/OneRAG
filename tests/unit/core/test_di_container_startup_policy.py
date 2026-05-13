from typing import Any

from app.core import di_container


def test_weaviate_retriever_does_not_resolve_vector_store_provider(monkeypatch) -> None:
    def fail_if_called() -> Any:
        raise AssertionError("vector_store_provider should be lazy for weaviate")

    created: dict[str, Any] = {}

    def fake_create(
        provider: str,
        embedder: Any,
        config: dict[str, Any],
        bm25_preprocessors: dict[str, Any] | None = None,
    ) -> str:
        created["provider"] = provider
        created["config"] = config
        created["bm25_preprocessors"] = bm25_preprocessors
        return "retriever"

    monkeypatch.setattr(di_container.RetrieverFactory, "create", fake_create)

    result = di_container.create_retriever_via_factory(
        config={
            "vector_db": {"provider": "weaviate"},
            "weaviate": {"collection_name": "Documents"},
            "domain": {"retrieval": {"collections": {}}},
        },
        embedder=object(),
        vector_store_provider=fail_if_called,
        weaviate_client=object(),
    )

    assert result == "retriever"
    assert created["provider"] == "weaviate"
    assert "weaviate_client" in created["config"]


def test_non_weaviate_retriever_does_not_resolve_weaviate_provider(monkeypatch) -> None:
    def fail_if_called() -> Any:
        raise AssertionError("weaviate_client_provider should be lazy for non-weaviate")

    created: dict[str, Any] = {}

    def fake_create(
        provider: str,
        embedder: Any,
        config: dict[str, Any],
        bm25_preprocessors: dict[str, Any] | None = None,
    ) -> str:
        created["provider"] = provider
        created["config"] = config
        return "retriever"

    monkeypatch.setattr(di_container.RetrieverFactory, "create", fake_create)

    result = di_container.create_retriever_via_factory(
        config={
            "vector_db": {"provider": "chroma"},
            "chroma": {"collection_name": "documents"},
            "hybrid_search": {"default_alpha": 0.6},
        },
        embedder=object(),
        vector_store=object(),
        weaviate_client_provider=fail_if_called,
    )

    assert result == "retriever"
    assert created["provider"] == "chroma"
    assert "store" in created["config"]
