"""pgvector 실연결 통합 테스트 (verify 스택 PostgreSQL: pgvector/pgvector:pg16).

mock으로는 검증 불가했던 것:
- 이번 캠페인의 SQL 주입 수정 실증: 파라미터화된 `metadata->>%s = %s` 절이
  실제 PostgreSQL 파서/JSONB 연산자에서 의도대로 매칭되는지. mock cursor는
  SQL 문자열을 실행하지 않으므로 placeholder 키 파라미터화가 진짜 PG에서
  동작한다는 보장을 줄 수 없었다 (특수문자 키/값 포함).
- 주입 페이로드가 리터럴 비교로만 처리되는지 (주입이 성립하면 전행 반환
  또는 DROP 실행 — 실 DB에서만 음성 검증 가능).
- fetch_objects가 asyncio.to_thread 경유로 실제 동기 psycopg 커서를
  블로킹 없이 수행하는지.
- `1 - (embedding <=> ...)` cosine 점수 계산과 내림차순 정렬이 실제
  pgvector 익스텐션 연산 결과로 보장되는지.

합성 8차원 고정 시드 벡터를 사용해 임베딩 API 없이 hermetic하게 실행한다.
psycopg(v3) 미설치 / DATABASE_URL 미설정 / DB 미접속 시 명확한 사유로 skip.
"""

import os
import random
import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest

# verify 스택(-m integration 수집)과 기본 CI(--ignore=tests/integration) 계약
pytestmark = pytest.mark.integration

psycopg = pytest.importorskip(
    "psycopg",
    reason="psycopg(v3) 미설치 — pgvector 실연결 테스트 skip (uv sync --extra pgvector)",
)

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
if not DATABASE_URL:
    pytest.skip(
        "DATABASE_URL 미설정 — pgvector 실연결 테스트 skip "
        "(verify 스택 PostgreSQL: localhost:55432/rag_db 재사용)",
        allow_module_level=True,
    )

# 서비스 reachability 확인 — 수집/실행이 행 걸리지 않도록 2초 timeout.
# 자격증명 노출 방지를 위해 skip 사유에 DATABASE_URL 원문은 포함하지 않는다.
try:
    _probe_connection = psycopg.connect(DATABASE_URL, connect_timeout=2)
    _probe_connection.close()
except psycopg.Error as exc:
    pytest.skip(
        f"PostgreSQL(DATABASE_URL) 미접속: {type(exc).__name__} — pgvector 실연결 테스트 skip",
        allow_module_level=True,
    )

from app.infrastructure.storage.vector.pgvector_store import PgVectorStore  # noqa: E402

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
async def seeded_store() -> AsyncIterator[PgVectorStore]:
    """고유 이름 테이블을 생성하고 합성 문서를 적재한 스토어를 제공한다.

    테이블/익스텐션 생성은 스토어 초기화 메서드(create_table_if_not_exists)가
    CREATE EXTENSION IF NOT EXISTS vector까지 포함해 처리함을 확인했으므로
    별도 사전 셋업 없이 그대로 사용한다. 스토어는 DI 없이 직접 인스턴스화하며,
    try/finally로 테이블 DROP과 연결 종료(teardown)를 보장한다.
    """
    table_name = f"vs_live_{uuid.uuid4().hex}"
    store = PgVectorStore(dsn=DATABASE_URL, table_name=table_name, vector_dimension=DIMENSION)
    try:
        await store.create_table_if_not_exists()

        # ivfflat은 근사(ANN) 인덱스라 빈 테이블에 생성 후 소량 데이터를 넣으면
        # probe 누락으로 검색 결과가 비결정적으로 빠질 수 있다. 여기서 검증하는
        # 계약(저장/필터/파라미터화)은 인덱스와 무관하므로 정확 스캔을 강제한다.
        with psycopg.connect(DATABASE_URL, connect_timeout=5) as setup_conn:
            with setup_conn.cursor() as cursor:
                cursor.execute(f'DROP INDEX IF EXISTS "{table_name}_embedding_idx"')
            setup_conn.commit()

        added = await store.add_documents(table_name, _build_documents())
        assert added == 5
        yield store
    finally:
        # teardown 보장: 공유 DB에 테스트 테이블을 남기지 않는다
        try:
            with psycopg.connect(DATABASE_URL, connect_timeout=5) as teardown_conn:
                with teardown_conn.cursor() as cursor:
                    cursor.execute(f'DROP TABLE IF EXISTS "{table_name}"')
                teardown_conn.commit()
        finally:
            store.close()


async def test_add_and_search_roundtrip(seeded_store: PgVectorStore) -> None:
    """add_documents → search 라운드트립: 동일 벡터가 최상위, 점수 내림차순."""
    table = seeded_store.table_name

    results = await seeded_store.search(table, _synthetic_vector(0), top_k=3)

    assert len(results) == 3
    # 쿼리와 동일한 합성 벡터를 가진 문서가 최상위 (cosine 점수 ~1.0)
    assert results[0]["_id"] == "doc-0"
    assert results[0]["content"] == "합성 문서 0"
    assert results[0]["_score"] == pytest.approx(1.0, abs=1e-6)
    # 실제 pgvector `<=>` 연산 기준 점수 내림차순 정렬 검증
    scores = [item["_score"] for item in results]
    assert scores == sorted(scores, reverse=True)


async def test_search_with_parameterized_metadata_filter(seeded_store: PgVectorStore) -> None:
    """search 경로의 `metadata->>%s = %s` 필터가 실 PG에서 매칭된다."""
    table = seeded_store.table_name

    results = await seeded_store.search(
        table, _synthetic_vector(3), top_k=10, filters={"category": "notice"}
    )
    assert {item["_id"] for item in results} == {"doc-3", "doc-4"}


async def test_fetch_objects_filters(seeded_store: PgVectorStore) -> None:
    """fetch_objects: 무필터 전수(to_thread 경유) / document_id 필터 / 숫자 필터."""
    table = seeded_store.table_name

    # 무필터 전수 조회 — asyncio.to_thread 경유 정상 동작 확인
    all_items = await seeded_store.fetch_objects(table)
    assert len(all_items) == 5

    # 문자열 필터 (document_id)
    doc_a_items = await seeded_store.fetch_objects(table, filters={"document_id": "doc-a"})
    assert {item["_id"] for item in doc_a_items} == {"doc-0", "doc-1", "doc-2"}

    # 숫자 필터 (page) — JSONB `->>` 텍스트 캐스팅 시맨틱을 실 PG로 검증
    page_two = await seeded_store.fetch_objects(table, filters={"page": 2})
    assert [item["_id"] for item in page_two] == ["doc-2"]
    assert page_two[0]["content"] == "합성 문서 2"


async def test_metadata_filter_parameterization_blocks_injection(
    seeded_store: PgVectorStore,
) -> None:
    """SQL 주입 수정의 실증: 특수문자 키/값이 파라미터로만 안전하게 처리된다.

    mock cursor는 SQL을 실행하지 않으므로, placeholder로 전달된 키가 실제
    PostgreSQL 파서에서 JSONB 키 텍스트로 취급되는지(주입 미성립)는 실 DB로만
    검증 가능하다.
    """
    table = seeded_store.table_name

    # 따옴표/세미콜론/주석 등 주입 페이로드 형태의 키와 값
    special_key = "key'with\"quotes; DROP TABLE other_table; --"
    special_value = "val'ue\" OR '1'='1"
    added = await seeded_store.add_documents(
        table,
        [
            {
                "id": "doc-special",
                "embedding": _synthetic_vector(99),
                "content": "특수문자 메타데이터 문서",
                "metadata": {special_key: special_value, "document_id": "doc-special"},
            }
        ],
    )
    assert added == 1

    # (a) 특수문자 키/값이 파라미터화된 필터로 정확히 1건 매칭된다
    matched = await seeded_store.fetch_objects(table, filters={special_key: special_value})
    assert [item["_id"] for item in matched] == ["doc-special"]

    # 주입 페이로드 값은 리터럴 비교로만 동작해야 한다 (주입 성립 시 전행 반환)
    injected = await seeded_store.fetch_objects(
        table, filters={"document_id": "doc-a' OR '1'='1"}
    )
    assert injected == []

    # search 경로의 filters도 동일하게 파라미터화되어 매칭된다
    search_matched = await seeded_store.search(
        table, _synthetic_vector(99), top_k=10, filters={special_key: special_value}
    )
    assert [item["_id"] for item in search_matched] == ["doc-special"]

    # 테이블이 손상되지 않았는지(DROP 미실행) 전수 조회로 확인
    all_items = await seeded_store.fetch_objects(table)
    assert len(all_items) == 6


async def test_non_string_filter_key_raises_value_error(seeded_store: PgVectorStore) -> None:
    """(c) 비-str 필터 키는 RuntimeError로 감싸지지 않고 ValueError로 거부된다."""
    table = seeded_store.table_name

    with pytest.raises(ValueError, match="문자열"):
        await seeded_store.fetch_objects(table, filters={1: "x"})

    with pytest.raises(ValueError, match="문자열"):
        await seeded_store.search(table, _synthetic_vector(0), top_k=3, filters={1: "x"})


async def test_delete_objects_roundtrip(seeded_store: PgVectorStore) -> None:
    """delete_objects 후 삭제 반영을 fetch_objects로 확인한다."""
    table = seeded_store.table_name

    targets = await seeded_store.fetch_objects(table, filters={"document_id": "doc-b"})
    target_ids = [item["_id"] for item in targets]
    assert sorted(target_ids) == ["doc-3", "doc-4"]

    deleted = await seeded_store.delete_objects(table, target_ids)
    assert deleted == 2

    # 삭제 반영 확인: 전수 3건 + doc-b 필터 0건
    remaining = await seeded_store.fetch_objects(table)
    assert {item["_id"] for item in remaining} == {"doc-0", "doc-1", "doc-2"}
    assert await seeded_store.fetch_objects(table, filters={"document_id": "doc-b"}) == []
