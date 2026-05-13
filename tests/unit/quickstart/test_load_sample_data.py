from quickstart import load_sample_data as loader


class FakeCollection:
    def __init__(self, existing_uuids: set[str] | None = None) -> None:
        self.data = FakeData(existing_uuids or set())
        self.batch = FakeBatch()


class FakeData:
    def __init__(self, existing_uuids: set[str]) -> None:
        self.existing_uuids = existing_uuids
        self.replaced: list[str] = []

    def exists(self, object_uuid: str) -> bool:
        return object_uuid in self.existing_uuids

    def replace(self, uuid: str, properties: dict, vector: list[float]) -> None:
        self.replaced.append(uuid)


class FakeBatch:
    def __init__(self) -> None:
        self.failed_objects: list[object] = []
        self.added: list[str] = []

    def dynamic(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None

    def add_object(self, uuid: str, properties: dict, vector: list[float]) -> None:
        self.added.append(uuid)


class FakeCollections:
    def __init__(self, exists: bool) -> None:
        self._exists = exists
        self.deleted: list[str] = []
        self.created: list[str] = []
        self.collection = FakeCollection()

    def exists(self, collection_name: str) -> bool:
        return self._exists

    def delete(self, collection_name: str) -> None:
        self.deleted.append(collection_name)
        self._exists = False

    def create(self, name: str, **kwargs) -> FakeCollection:
        self.created.append(name)
        self._exists = True
        return self.collection

    def get(self, collection_name: str) -> FakeCollection:
        return self.collection


class FakeClient:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class FakeConfig:
    def __init__(self, property_names: set[str]) -> None:
        self.property_names = property_names
        self.added: list[str] = []

    def get(self, simple: bool = True):
        return type("CollectionConfig", (), {"properties": dict.fromkeys(self.property_names)})()

    def add_property(self, prop) -> None:
        self.added.append(prop.name)
        self.property_names.add(prop.name)


def test_ensure_collection_reuses_existing_collection_without_reset(monkeypatch) -> None:
    collections = FakeCollections(exists=True)
    client = type("Client", (), {"collections": collections})()
    monkeypatch.setattr(
        loader,
        "create_documents_collection",
        lambda client, collection_name: collections.create(collection_name),
    )
    monkeypatch.setattr(loader, "ensure_quickstart_schema", lambda collection, name: 0)

    collection = loader.ensure_documents_collection(client, "Documents", reset=False)

    assert collection is collections.collection
    assert collections.deleted == []
    assert collections.created == []


def test_ensure_collection_deletes_only_when_reset_is_explicit(monkeypatch) -> None:
    collections = FakeCollections(exists=True)
    client = type("Client", (), {"collections": collections})()
    monkeypatch.setattr(
        loader,
        "create_documents_collection",
        lambda client, collection_name: collections.create(collection_name),
    )

    collection = loader.ensure_documents_collection(client, "Documents", reset=True)

    assert collection is collections.collection
    assert collections.deleted == ["Documents"]
    assert collections.created == ["Documents"]


def test_ensure_collection_creates_when_missing(monkeypatch) -> None:
    collections = FakeCollections(exists=False)
    client = type("Client", (), {"collections": collections})()
    monkeypatch.setattr(
        loader,
        "create_documents_collection",
        lambda client, collection_name: collections.create(collection_name),
    )

    collection = loader.ensure_documents_collection(client, "Documents", reset=False)

    assert collection is collections.collection
    assert collections.deleted == []
    assert collections.created == ["Documents"]


def test_ensure_quickstart_schema_adds_missing_properties() -> None:
    collection = FakeCollection()
    collection.config = FakeConfig({"content", "source"})

    added_count = loader.ensure_quickstart_schema(collection, "Documents")

    assert added_count == 3
    assert set(collection.config.added) == {"source_file", "file_type", "keywords"}


def test_sample_document_uuid_is_stable_and_collection_scoped() -> None:
    first = loader.sample_document_uuid("Documents", "faq-001")
    second = loader.sample_document_uuid("Documents", "faq-001")
    other_collection = loader.sample_document_uuid("Other", "faq-001")

    assert first == second
    assert first != other_collection


def test_load_sample_data_updates_existing_sample_documents(monkeypatch) -> None:
    existing_uuids = {
        loader.sample_document_uuid("Documents", doc["id"])
        for doc in loader.json.loads((loader.Path(loader.__file__).parent / "sample_data.json").read_text())[
            "documents"
        ]
    }
    fake_collection = FakeCollection(existing_uuids=existing_uuids)
    fake_client = FakeClient()

    class FakeEmbedder:
        def embed_documents(self, texts):
            return [[0.1, 0.2] for _ in texts]

    monkeypatch.setattr(loader, "wait_for_weaviate", lambda *args, **kwargs: True)
    monkeypatch.setattr(loader, "initialize_embedder", lambda: FakeEmbedder())
    monkeypatch.setattr(
        loader,
        "ensure_documents_collection",
        lambda client, collection_name, reset=False: fake_collection,
    )
    monkeypatch.setattr(loader, "env_flag_enabled", lambda value: False)
    monkeypatch.setattr("weaviate.connect_to_custom", lambda **kwargs: fake_client)

    loader.load_sample_data(reset=False, collection_name="Documents")

    assert fake_client.closed is True
    assert set(fake_collection.data.replaced) == existing_uuids
    assert fake_collection.batch.added == []


def test_load_sample_data_raises_when_batch_reports_failures(monkeypatch) -> None:
    fake_collection = FakeCollection(existing_uuids=set())
    fake_collection.batch.failed_objects = [type("FailedObject", (), {"original_uuid": "bad-id"})()]
    fake_client = FakeClient()

    class FakeEmbedder:
        def embed_documents(self, texts):
            return [[0.1, 0.2] for _ in texts]

    monkeypatch.setattr(loader, "wait_for_weaviate", lambda *args, **kwargs: True)
    monkeypatch.setattr(loader, "initialize_embedder", lambda: FakeEmbedder())
    monkeypatch.setattr(
        loader,
        "ensure_documents_collection",
        lambda client, collection_name, reset=False: fake_collection,
    )
    monkeypatch.setattr("weaviate.connect_to_custom", lambda **kwargs: fake_client)

    import pytest

    with pytest.raises(RuntimeError, match="Weaviate 배치 실패"):
        loader.load_sample_data(reset=False, collection_name="Documents")

    assert fake_client.closed is True


def test_main_passes_reset_and_collection(monkeypatch) -> None:
    calls: list[tuple[bool | None, str | None]] = []
    monkeypatch.setattr(
        loader,
        "load_sample_data",
        lambda reset=None, collection_name=None: calls.append((reset, collection_name)),
    )

    loader.main(["--reset", "--collection", "QuickstartSmoke"])

    assert calls == [(True, "QuickstartSmoke")]


def test_main_allows_env_reset_when_cli_reset_absent(monkeypatch) -> None:
    calls: list[tuple[bool | None, str | None]] = []
    monkeypatch.setattr(
        loader,
        "load_sample_data",
        lambda reset=None, collection_name=None: calls.append((reset, collection_name)),
    )

    loader.main(["--collection", "QuickstartSmoke"])

    assert calls == [(None, "QuickstartSmoke")]
