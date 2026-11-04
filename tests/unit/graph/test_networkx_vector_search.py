
import numpy as np
import pytest

from app.modules.core.graph.models import Entity
from app.modules.core.graph.stores.networkx_store import NetworkXGraphStore


class MockEmbedder:
    async def embed_query(self, text: str):
        # 결정론적 벡터 (768차원)
        vec = np.zeros(768)
        if "삼성" in text or "SAMSUNG" in text:
            vec[0] = 1.0
        elif "애플" in text or "iPhone" in text:
            vec[0] = -1.0
        return vec.tolist()

    async def embed_documents(self, texts: list[str]):
        return [await self.embed_query(t) for t in texts]

@pytest.mark.asyncio
async def test_networkx_graph_vector_search():
    # 1. Setup
    store = NetworkXGraphStore()
    embedder = MockEmbedder()
    store.set_embedder(embedder) # 새로 구현할 메서드

    # 2. 데이터 준비
    samsung = Entity(
        id="corp_1",
        name="삼성전자",
        type="Organization",
        properties={"description": "대한민국 반도체 기업"}
    )
    apple = Entity(
        id="corp_2",
        name="애플",
        type="Organization",
        properties={"description": "미국 IT 기업"}
    )

    await store.add_entity(samsung)
    await store.add_entity(apple)

    # 3. 시나리오: 의미적 유사어 검색 ("SAMSUNG" -> "삼성전자")
    # 현재 구현은 "SAMSUNG"이 "삼성전자"에 포함되지 않으므로 실패함 (결과 0개 예상)
    # 하지만 고도화 후에는 1개가 나와야 함
    result = await store.search(query="SAMSUNG", top_k=1)

    assert len(result.entities) > 0
    assert result.entities[0].name == "삼성전자"
    # score 필드가 GraphSearchResult에 있으므로 점수 확인 가능
    assert result.score > 0.5


class SyncEmbedder:
    """운영 IEmbedder 구현체처럼 embed_query가 동기 함수인 임베더.

    과거 NetworkXGraphStore는 이 결과(list)를 await 해서 TypeError가 났고, 예외를 삼켜
    엔티티 임베딩이 생성되지 않았다. 이 테스트가 그 회귀를 막는다.
    """

    def __init__(self) -> None:
        self.calls = 0

    def embed_query(self, text: str) -> list[float]:
        self.calls += 1
        vec = np.zeros(8)
        vec[0] = 1.0 if "alpha" in text else -1.0
        return vec.tolist()

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self.embed_query(t) for t in texts]

    async def aembed_query(self, text: str) -> list[float]:
        return self.embed_query(text)

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        return self.embed_documents(texts)


class SyncOnlyEmbedder:
    """aembed_query 없이 동기 embed_query만 있는 최소 임베더(to_thread 경로)."""

    def embed_query(self, text: str) -> list[float]:
        vec = np.zeros(8)
        vec[0] = 1.0 if "alpha" in text else -1.0
        return vec.tolist()


@pytest.mark.asyncio
@pytest.mark.parametrize("embedder_cls", [SyncEmbedder, SyncOnlyEmbedder])
async def test_sync_embedder_produces_entity_embeddings(embedder_cls):
    """동기 IEmbedder가 주입돼도 엔티티 임베딩이 실제로 저장되고 벡터 검색이 동작해야 한다."""
    store = NetworkXGraphStore()
    store.set_embedder(embedder_cls())

    await store.add_entity(Entity(id="e1", name="alpha corp", type="ORG", properties={}))
    await store.add_entity(Entity(id="e2", name="beta inc", type="ORG", properties={}))

    # 임베딩이 노드에 저장됐는지(예전에는 await TypeError로 항상 None)
    node_data = dict(store._graph.nodes(data=True))
    assert node_data["e1"].get("embedding") is not None
    assert node_data["e2"].get("embedding") is not None

    result = await store.search(query="alpha", top_k=1)
    assert result.entities, "벡터 검색 결과가 비어 있으면 안 된다"
    assert result.entities[0].id == "e1"
