"""Chroma 실연결 통합 테스트 (PersistentClient 기반, 별도 서비스 불필요).

mock으로는 검증 불가했던 것:
- 실제 chromadb 엔진(SQLite 백엔드)의 where 필터 시맨틱 — 숫자/문자열
  동등 비교가 진짜 저장 레이어에서 어떻게 매칭되는지는 mock이 재현하지 못한다.
- upsert → query 라운드트립에서 cosine 거리(_distance) 오름차순 정렬이
  실제 HNSW 인덱스 기준으로 보장되는지 — mock은 코드로 흉내 낸 정렬을
  되돌려줄 뿐 실엔진의 거리 계산을 검증하지 못한다.
- 메타데이터 기본 타입 제약(str/int/float/bool)과 content(documents) 저장이
  실제 클라이언트 직렬화 경로에서 손실 없이 왕복하는지.

합성 8차원 고정 시드 벡터를 사용해 임베딩 API 없이 hermetic하게 실행한다.
PersistentClient(tmp_path)를 사용하므로 env 기반 skip 없이 chromadb
importorskip만 적용한다 (기본 환경에서 실제로 통과해야 하는 파일).
"""

import random
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

# verify 스택(-m integration 수집)과 기본 CI(--ignore=tests/integration) 계약
pytestmark = pytest.mark.integration

pytest.importorskip("chromadb", reason="chromadb 미설치 — Chroma 실연결 테스트 skip")

from app.infrastructure.storage.vector.chroma_store import ChromaVectorStore  # noqa: E402

# 합성 벡터 차원 (임베딩 API 불필요 — 스토어 계약만 검증)
DIMENSION = 8


def _synthetic_vector(index: int) -> list[float]:
    """고정 시드 기반 합성 벡터 생성 (재현 가능, 문서별 서로 다른 방향)."""
    rng = random.Random(1000 + index)
    return [round(rng.uniform(-1.0, 1.0), 6) for _ in range(DIMENSION)]


def _build_documents() -> list[dict[str, Any]]:
    """공통 합성 문서 5건 (document_id: doc-a 3건 + doc-b 2건, page는 숫자)."""
    documents: list[dict[str, Any]] = []
    for index in range(5):
        documents.append(
            {
                "id": f"doc-{index}",
                "embedding": _synthetic_vector(index),
                "content": f"합성 문서 {index}",
                "metadata": {
                    "document_id": "doc-a" if index < 3 else "doc-b",
                    "page": index,
                    "category": "faq" if index < 3 else "notice",
                },
            }
        )
    return documents


@pytest.fixture()
def collection_name() -> str:
    """테스트 간 충돌을 막기 위한 고유 컬렉션 이름 (uuid 접미사)."""
    return f"vs_live_{uuid.uuid4().hex}"


@pytest.fixture()
async def seeded_store(
    tmp_path: Path, collection_name: str
) -> AsyncIterator[ChromaVectorStore]:
    """tmp_path 기반 PersistentClient 스토어를 만들고 합성 문서를 적재한다.

    teardown: 디스크 데이터는 pytest tmp_path가 정리하며, close()는
    try/finally로 보장한다 (DI 없이 직접 인스턴스화).
    """
    store = ChromaVectorStore(persist_directory=str(tmp_path / "chroma"))
    try:
        added = await store.add_documents(collection_name, _build_documents())
        assert added == 5
        yield store
    finally:
        store.close()


async def test_add_and_search_roundtrip(
    seeded_store: ChromaVectorStore, collection_name: str
) -> None:
    """add_documents → search 라운드트립: 동일 벡터가 최상위, 거리 오름차순."""
    results = await seeded_store.search(collection_name, _synthetic_vector(0), top_k=3)

    assert len(results) == 3
    # 쿼리와 동일한 합성 벡터를 가진 문서가 최상위 (cosine 거리 ~0)
    assert results[0]["_id"] == "doc-0"
    assert results[0]["content"] == "합성 문서 0"
    assert results[0]["_distance"] == pytest.approx(0.0, abs=1e-3)
    # 실제 HNSW 인덱스의 거리 정렬(오름차순 = 유사도 내림차순) 검증
    distances = [item["_distance"] for item in results]
    assert distances == sorted(distances)


async def test_search_with_metadata_filter(
    seeded_store: ChromaVectorStore, collection_name: str
) -> None:
    """search의 where 필터가 실엔진에서 해당 메타데이터 문서만 반환한다."""
    results = await seeded_store.search(
        collection_name, _synthetic_vector(3), top_k=10, filters={"category": "notice"}
    )
    assert {item["_id"] for item in results} == {"doc-3", "doc-4"}


async def test_fetch_objects_filters(
    seeded_store: ChromaVectorStore, collection_name: str
) -> None:
    """fetch_objects: 무필터 전수 / document_id 필터 / 숫자(page) 필터."""
    # 무필터 전수 조회
    all_items = await seeded_store.fetch_objects(collection_name)
    assert len(all_items) == 5

    # 문자열 필터 (document_id)
    doc_a_items = await seeded_store.fetch_objects(
        collection_name, filters={"document_id": "doc-a"}
    )
    assert {item["_id"] for item in doc_a_items} == {"doc-0", "doc-1", "doc-2"}

    # 숫자 필터 (page) — 실엔진의 int 동등 비교 시맨틱 검증
    page_two = await seeded_store.fetch_objects(collection_name, filters={"page": 2})
    assert [item["_id"] for item in page_two] == ["doc-2"]
    assert page_two[0]["content"] == "합성 문서 2"
    assert page_two[0]["page"] == 2


async def test_delete_objects_roundtrip(
    seeded_store: ChromaVectorStore, collection_name: str
) -> None:
    """delete_objects 후 삭제 반영을 fetch_objects로 확인한다."""
    targets = await seeded_store.fetch_objects(
        collection_name, filters={"document_id": "doc-b"}
    )
    target_ids = [item["_id"] for item in targets]
    assert sorted(target_ids) == ["doc-3", "doc-4"]

    deleted = await seeded_store.delete_objects(collection_name, target_ids)
    assert deleted == 2

    # 삭제 반영 확인: 전수 3건 + doc-b 필터 0건
    remaining = await seeded_store.fetch_objects(collection_name)
    assert {item["_id"] for item in remaining} == {"doc-0", "doc-1", "doc-2"}
    assert (
        await seeded_store.fetch_objects(collection_name, filters={"document_id": "doc-b"}) == []
    )
