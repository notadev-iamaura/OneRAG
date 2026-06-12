"""
MongoDB Atlas 라이브 스모크 테스트 (주간 스케줄 CI 전용).

목적: MongoDB Atlas는 관리형 클라우드 서비스라 로컬 verify 스택으로 검증할 수
없다. 실 Atlas 클러스터에 대해 문서 관리 경로의 라운드트립을 실측한다.

스코프(명시): "문서 관리 경로만" 검증한다 —
  add_documents → fetch_objects(무필터/메타데이터 필터/단일 id) → delete_objects.
$vectorSearch 기반 search()는 사전 프로비저닝된 Atlas Vector Search 인덱스가
필요하므로 이 스모크의 범위에서 제외한다(인덱스 의존 없는 경로만 측정).

실행 조건(모두 충족해야 실행, 아니면 모듈 전체 깨끗한 skip):
  - ONERAG_RUN_LIVE_PROVIDER_TESTS=1
  - MONGODB_ATLAS_URI: Atlas 연결 문자열 (mongodb+srv://...)
  - MONGODB_ATLAS_DB: (선택) 데이터베이스 이름, 미설정 시 onerag_live_smoke

주의: 실 클러스터에 쓰기를 수행하므로 테스트 전용 클러스터/사용자를 권장한다.
테스트는 실행마다 고유(uuid) 컬렉션을 사용하고 종료 시 컬렉션을 drop 한다
(try/finally 보장).

의존성: pymongo (base 의존성), pytest, pytest-asyncio
"""

import logging
import os
import uuid
from collections.abc import Iterator
from typing import Any

import pytest

pytestmark = pytest.mark.integration

logger = logging.getLogger(__name__)

# 라이브 프로바이더 테스트 전역 게이트 환경 변수
LIVE_GATE_ENV = "ONERAG_RUN_LIVE_PROVIDER_TESTS"

# 게이트 1: 명시적 opt-in 없이는 절대 실행하지 않는다 (기본 게이트/로컬 verify 보호)
if os.getenv(LIVE_GATE_ENV) != "1":
    pytest.skip(
        f"라이브 MongoDB Atlas 스모크는 {LIVE_GATE_ENV}=1 일 때만 실행됩니다 "
        "(주간 스케줄 CI 전용 — 기본 게이트/로컬 verify에서는 실행하지 않음)",
        allow_module_level=True,
    )

_MONGODB_ATLAS_URI = os.getenv("MONGODB_ATLAS_URI", "")
# CI에서는 시크릿 부재 시 env가 "빈 문자열"로 주입되므로(os.getenv 기본값이
# 적용되지 않음) or 폴백으로 빈 값도 기본 DB 이름으로 대체한다
_MONGODB_ATLAS_DB = os.getenv("MONGODB_ATLAS_DB", "") or "onerag_live_smoke"

# 게이트 2: 시크릿 환경 변수 부재 시 명확한 사유와 함께 skip
if not _MONGODB_ATLAS_URI:
    pytest.skip(
        "MONGODB_ATLAS_URI 환경 변수가 없어 라이브 MongoDB Atlas 스모크를 "
        "건너뜁니다 (테스트 전용 Atlas 클러스터 연결 문자열 필요)",
        allow_module_level=True,
    )

# 게이트 통과 후에만 스토어를 import 한다 — 의존성 미설치 환경에서도
# 수집(collection) 에러 없이 깨끗하게 skip 되도록 보장하기 위함
from app.infrastructure.storage.vector.mongodb_atlas_store import (  # noqa: E402
    MongoDBAtlasStore,
)

# 실행(run)마다 고유한 컬렉션 — 동시 실행/이전 실행 잔여 데이터와 충돌 방지
_COLLECTION = f"live_smoke_{uuid.uuid4().hex[:12]}"

# 합성 시드 문서: 벡터 검색 인덱스가 필요 없는 소형 임베딩을 사용한다
_DOCUMENT_ID = "live-smoke-doc"
_SEED_DOCUMENTS: list[dict[str, Any]] = [
    {
        "id": "live-doc-1",
        "embedding": [0.1, 0.2, 0.3, 0.4],
        "content": "라이브 스모크 청크 1",
        "metadata": {"document_id": _DOCUMENT_ID, "chunk_index": 0},
    },
    {
        "id": "live-doc-2",
        "embedding": [0.2, 0.3, 0.4, 0.5],
        "content": "라이브 스모크 청크 2",
        "metadata": {"document_id": _DOCUMENT_ID, "chunk_index": 1},
    },
    {
        "id": "live-doc-3",
        "embedding": [0.3, 0.4, 0.5, 0.6],
        "content": "라이브 스모크 기타 청크",
        "metadata": {"document_id": "live-smoke-other", "chunk_index": 0},
    },
]


@pytest.fixture(scope="module")
def live_store() -> Iterator[MongoDBAtlasStore]:
    """라이브 Atlas 스토어를 제공하는 모듈 픽스처.

    teardown: 테스트 성패와 무관하게 고유 컬렉션 drop + 연결 종료를 보장한다
    (try/finally). MongoDB의 문서 CRUD는 강한 일관성이므로 별도 가시성 폴링은
    필요하지 않다.
    """
    store = MongoDBAtlasStore(
        connection_string=_MONGODB_ATLAS_URI,
        database_name=_MONGODB_ATLAS_DB,
        collection_name=_COLLECTION,
    )
    try:
        yield store
    finally:
        # teardown 보장: 고유 컬렉션 전체 제거 후 연결 종료
        try:
            store._get_collection(_COLLECTION).drop()
        except Exception as cleanup_error:
            # 정리 실패가 테스트 결과(원본 실패 원인)를 가리지 않도록 경고만
            # 남긴다. 고유 uuid 컬렉션이므로 잔여 데이터 영향은 제한적이다.
            logger.warning(
                "MongoDB Atlas 라이브 스모크: 컬렉션 정리 실패 "
                f"(db={_MONGODB_ATLAS_DB}, collection={_COLLECTION}): {cleanup_error}"
            )
        finally:
            store.close()


async def test_document_management_roundtrip(live_store: MongoDBAtlasStore) -> None:
    """문서 관리 경로 라운드트립 실측: 삽입 → 조회(3가지 필터) → 삭제.

    단계별로 의존하는 시나리오이므로 하나의 테스트로 묶어 순서를 보장한다.
    """
    # 1) 삽입 (upsert)
    added = await live_store.add_documents(_COLLECTION, _SEED_DOCUMENTS)
    assert added == len(_SEED_DOCUMENTS), (
        f"삽입 개수 불일치: 기대 {len(_SEED_DOCUMENTS)}개, 실제 {added}개"
    )

    # 2) 무필터 전체 조회 — 반환 계약 {"_id", "content", ...metadata} 확인
    all_objects = await live_store.fetch_objects(_COLLECTION)
    assert {item["_id"] for item in all_objects} == {
        "live-doc-1",
        "live-doc-2",
        "live-doc-3",
    }, f"무필터 조회 결과 불일치: {[item['_id'] for item in all_objects]}"
    for item in all_objects:
        assert isinstance(item["content"], str) and item["content"], (
            f"content 필드가 비어 있습니다: {item}"
        )

    # 3) document_id 메타데이터 필터 조회 (metadata.document_id 일치 조건)
    filtered = await live_store.fetch_objects(
        _COLLECTION, filters={"document_id": _DOCUMENT_ID}
    )
    assert {item["_id"] for item in filtered} == {"live-doc-1", "live-doc-2"}, (
        f"document_id 필터 조회 결과 불일치: {[item['_id'] for item in filtered]}"
    )
    for item in filtered:
        assert item["document_id"] == _DOCUMENT_ID

    # 4) 단일 id 직접 조회
    single = await live_store.fetch_objects(_COLLECTION, filters={"id": "live-doc-3"})
    assert [item["_id"] for item in single] == ["live-doc-3"], (
        f"단일 id 조회 결과 불일치: {[item['_id'] for item in single]}"
    )

    # 5) 일부 삭제 후 잔여 확인
    deleted = await live_store.delete_objects(
        _COLLECTION, ["live-doc-1", "live-doc-2"]
    )
    assert deleted == 2, f"삭제 개수 불일치: 기대 2개, 실제 {deleted}개"

    remaining = await live_store.fetch_objects(_COLLECTION)
    assert {item["_id"] for item in remaining} == {"live-doc-3"}, (
        f"삭제 후 잔여 문서 불일치: {[item['_id'] for item in remaining]}"
    )

    # 6) 전체 삭제 라운드트립 마무리
    deleted_rest = await live_store.delete_objects(_COLLECTION, ["live-doc-3"])
    assert deleted_rest == 1, f"잔여 삭제 개수 불일치: 기대 1개, 실제 {deleted_rest}개"
    assert await live_store.fetch_objects(_COLLECTION) == [], (
        "전체 삭제 후에도 문서가 남아 있습니다"
    )
