"""Qdrant 실연결 통합 테스트 (verify 스택: QDRANT_URL=http://localhost:16333).

mock으로는 검증 불가했던 것:
- add_documents가 문자열 ID를 해시 정수 포인트 ID로 저장하고, fetch_objects의
  _id(해시 정수 문자열) → delete_objects(_coerce_point_id 역변환) 라운드트립이
  실제 Qdrant 포인트 ID 체계에서 일치하는지 — mock은 해시 정합성을 흉내만 낸다.
- _convert_filters의 FieldCondition/MatchValue 변환이 실엔진 페이로드 매칭
  (문자열·숫자 동등 비교)에서 실제로 동작하는지.
- fetch_objects의 scroll 페이지네이션(무필터 전수 조회)이 실제 scroll API
  offset 프로토콜과 호환되는지.
- search 결과의 cosine 점수 내림차순 정렬이 실엔진 계산 기준으로 보장되는지.

합성 8차원 고정 시드 벡터를 사용해 임베딩 API 없이 hermetic하게 실행한다.
qdrant-client 미설치 / QDRANT_URL 미설정 / 서비스 미접속 시 명확한 사유로 skip.
"""

import os
import random
import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest

# verify 스택(-m integration 수집)과 기본 CI(--ignore=tests/integration) 계약
pytestmark = pytest.mark.integration

pytest.importorskip(
    "qdrant_client",
    reason="qdrant-client 미설치 — Qdrant 실연결 테스트 skip (uv sync --extra qdrant)",
)

QDRANT_URL = os.getenv("QDRANT_URL", "").strip()
if not QDRANT_URL:
    pytest.skip(
        "QDRANT_URL 미설정 — Qdrant 실연결 테스트 skip "
        "(verify 스택: QDRANT_URL=http://localhost:16333)",
        allow_module_level=True,
    )

# 서비스 reachability 확인 — 수집/실행이 행 걸리지 않도록 2초 timeout
try:
    httpx.get(f"{QDRANT_URL.rstrip('/')}/readyz", timeout=2.0)
except httpx.HTTPError as exc:
    pytest.skip(
        f"Qdrant 서비스 미접속({QDRANT_URL}): {type(exc).__name__} — 실연결 테스트 skip",
        allow_module_level=True,
    )

from app.infrastructure.storage.vector.qdrant_store import QdrantVectorStore  # noqa: E402

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
async def seeded_store() -> AsyncIterator[tuple[QdrantVectorStore, str]]:
    """고유 이름 컬렉션을 생성하고 합성 문서를 적재한 스토어를 제공한다.

    스토어는 컬렉션을 직접 생성하지 않으므로(upsert 전제) 별도 관리용
    클라이언트로 8차원 cosine 컬렉션을 만들고, try/finally로 컬렉션 삭제와
    클라이언트 종료(teardown)를 보장한다. 스토어는 DI 없이 직접 인스턴스화.
    """
    from qdrant_client import QdrantClient
    from qdrant_client.models import Distance, VectorParams

    collection = f"vs_live_{uuid.uuid4().hex}"
    admin_client = QdrantClient(url=QDRANT_URL, timeout=10)
    try:
        admin_client.create_collection(
            collection_name=collection,
            vectors_config=VectorParams(size=DIMENSION, distance=Distance.COSINE),
        )
        try:
            store = QdrantVectorStore(url=QDRANT_URL, collection_name=collection)
            added = await store.add_documents(collection, _build_documents())
            assert added == 5
            yield store, collection
        finally:
            # teardown 보장: 공유 서비스에 테스트 컬렉션을 남기지 않는다
            admin_client.delete_collection(collection_name=collection)
    finally:
        admin_client.close()


async def test_add_and_search_roundtrip(
    seeded_store: tuple[QdrantVectorStore, str],
) -> None:
    """add_documents → search 라운드트립: 동일 벡터가 최상위, 점수 내림차순."""
    store, collection = seeded_store

    results = await store.search(collection, _synthetic_vector(0), top_k=3)

    assert len(results) == 3
    # 쿼리와 동일한 합성 벡터를 가진 문서가 최상위 (cosine 점수 ~1.0)
    # 포인트 ID는 해시 정수라 _id 대신 페이로드(page/content)로 원본을 식별한다
    assert results[0]["page"] == 0
    assert results[0]["content"] == "합성 문서 0"
    assert results[0]["_score"] == pytest.approx(1.0, abs=1e-3)
    # 실엔진의 유사도 점수 내림차순 정렬 검증
    scores = [item["_score"] for item in results]
    assert scores == sorted(scores, reverse=True)


async def test_fetch_objects_filters(
    seeded_store: tuple[QdrantVectorStore, str],
) -> None:
    """fetch_objects: 무필터 전수(scroll) / document_id 필터 / 숫자(page) 필터."""
    store, collection = seeded_store

    # 무필터 전수 조회 (scroll 페이지네이션 경로)
    all_items = await store.fetch_objects(collection)
    assert len(all_items) == 5

    # 문자열 필터 (document_id) — FieldCondition/MatchValue 실엔진 매칭
    doc_a_items = await store.fetch_objects(collection, filters={"document_id": "doc-a"})
    assert {item["page"] for item in doc_a_items} == {0, 1, 2}

    # 숫자 필터 (page) — MatchValue의 int 동등 비교 시맨틱 검증
    page_two = await store.fetch_objects(collection, filters={"page": 2})
    assert len(page_two) == 1
    assert page_two[0]["content"] == "합성 문서 2"
    assert page_two[0]["document_id"] == "doc-a"


async def test_delete_objects_roundtrip(
    seeded_store: tuple[QdrantVectorStore, str],
) -> None:
    """fetch_objects의 _id를 delete_objects에 그대로 사용하는 라운드트립 검증.

    add_documents가 저장한 해시 정수 포인트 ID가 fetch(_id 문자열) →
    delete(_coerce_point_id 역변환)에서 동일 포인트를 가리키는지 실엔진으로 확인.
    """
    store, collection = seeded_store

    targets = await store.fetch_objects(collection, filters={"document_id": "doc-b"})
    target_ids = [item["_id"] for item in targets]
    assert len(target_ids) == 2

    deleted = await store.delete_objects(collection, target_ids)
    assert deleted == 2

    # 삭제 반영 확인: 전수 3건 + doc-b 필터 0건
    remaining = await store.fetch_objects(collection)
    assert {item["page"] for item in remaining} == {0, 1, 2}
    assert await store.fetch_objects(collection, filters={"document_id": "doc-b"}) == []
