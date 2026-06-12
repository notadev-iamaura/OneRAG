"""
Pinecone 라이브 스모크 테스트 (주간 스케줄 CI 전용).

목적: 직전 사이클에서 "문서로만 확인"하고 실측하지 못한 Pinecone API 계약을
실제 API에 대해 검증한다.

  (a) $in 혼합 타입 필터 실측 — fetch_objects가 비문자열 메타데이터 값을
      {"$in": [value, str(value)]}로 변환해 전송하는 경로
      (pinecone_store._query_by_metadata_filter의 미실측 가정 1순위)
  (b) 단위 기저 벡터 + include_metadata=True + top_k=1000(PINECONE_QUERY_MAX_TOP_K)
      쿼리가 수용되는지
  (c) 문자열 document_id에 대한 $eq 필터 정상 매칭

실행 조건(모두 충족해야 실행, 아니면 모듈 전체 깨끗한 skip):
  - ONERAG_RUN_LIVE_PROVIDER_TESTS=1
  - PINECONE_API_KEY: Pinecone API 키
  - PINECONE_TEST_INDEX: 사전 프로비저닝된 "테스트 전용" 인덱스 이름
    (벡터 차원은 describe_index_stats로 자동 감지하므로 무관)

주의: 실 API 호출이므로 과금/쿼터에 영향이 있다. 반드시 테스트 전용 인덱스만
사용할 것. 테스트는 실행마다 고유(uuid) 네임스페이스를 사용하고 종료 시
네임스페이스 벡터를 전체 삭제한다(try/finally 보장).

의존성: pinecone (base 의존성), pytest, pytest-asyncio
"""

import asyncio
import logging
import os
import time
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
        f"라이브 Pinecone 스모크는 {LIVE_GATE_ENV}=1 일 때만 실행됩니다 "
        "(주간 스케줄 CI 전용 — 기본 게이트/로컬 verify에서는 실행하지 않음)",
        allow_module_level=True,
    )

_PINECONE_API_KEY = os.getenv("PINECONE_API_KEY", "")
_PINECONE_TEST_INDEX = os.getenv("PINECONE_TEST_INDEX", "")

# 게이트 2: 시크릿 환경 변수 부재 시 명확한 사유와 함께 skip
if not _PINECONE_API_KEY or not _PINECONE_TEST_INDEX:
    pytest.skip(
        "PINECONE_API_KEY / PINECONE_TEST_INDEX 환경 변수가 없어 라이브 Pinecone "
        "스모크를 건너뜁니다 (사전 프로비저닝된 테스트 전용 인덱스 이름 필요)",
        allow_module_level=True,
    )

# 게이트 통과 후에만 스토어를 import 한다 — 의존성 미설치 환경에서도
# 수집(collection) 에러 없이 깨끗하게 skip 되도록 보장하기 위함
from app.infrastructure.storage.vector.pinecone_store import (  # noqa: E402
    PINECONE_QUERY_MAX_TOP_K,
    PineconeVectorStore,
)

# 실행(run)마다 고유한 네임스페이스 — 동시 실행/이전 실행 잔여 데이터와 충돌 방지
_NAMESPACE = f"live-smoke-{uuid.uuid4().hex[:12]}"

# 합성 시드 문서 명세.
# page는 의도적으로 "숫자(int)" 메타데이터로 저장한다 — Pinecone은 숫자를
# float로 저장하므로(3 → 3.0), (a) 혼합 타입 $in([3, "3"]) 매칭을 실측할 수 있다.
_DOCUMENT_ID = "live-smoke-doc"
_SEED_SPECS: list[dict[str, Any]] = [
    {
        "id": "live-vec-1",
        "metadata": {
            "document_id": _DOCUMENT_ID,
            "page": 3,
            "content": "라이브 스모크 청크 1",
        },
    },
    {
        "id": "live-vec-2",
        "metadata": {
            "document_id": _DOCUMENT_ID,
            "page": 4,
            "content": "라이브 스모크 청크 2",
        },
    },
    {
        "id": "live-vec-3",
        "metadata": {
            "document_id": "live-smoke-other",
            "page": 5,
            "content": "라이브 스모크 청크 3",
        },
    },
]

# upsert 가시성 폴링 설정 — Pinecone은 eventual consistency라서
# upsert 직후 즉시 조회되지 않을 수 있다 (최대 ~30초 대기)
_VISIBILITY_TIMEOUT_SECONDS = 30.0
_VISIBILITY_POLL_INTERVAL_SECONDS = 2.0


def _resolve_index_dimension(store: PineconeVectorStore) -> int:
    """테스트 인덱스의 실제 벡터 차원을 describe_index_stats로 조회한다.

    합성 벡터/쿼리 벡터는 인덱스 차원과 일치해야 하므로 폴백 없이
    조회 실패 시 명확한 메시지로 테스트를 실패시킨다.
    """
    stats = store._index.describe_index_stats()
    dimension = getattr(stats, "dimension", None)
    if dimension is None and isinstance(stats, dict):
        dimension = stats.get("dimension")

    if (
        not isinstance(dimension, int | float)
        or isinstance(dimension, bool)
        or int(dimension) <= 0
    ):
        pytest.fail(
            f"PINECONE_TEST_INDEX({_PINECONE_TEST_INDEX})의 벡터 차원을 "
            f"describe_index_stats로 조회하지 못했습니다 (응답 dimension={dimension!r}). "
            "인덱스가 사전 프로비저닝되어 있는지 확인하세요."
        )
    return int(dimension)


def _namespace_vector_count(store: PineconeVectorStore, namespace: str) -> int:
    """describe_index_stats에서 특정 네임스페이스의 벡터 개수를 읽는다.

    SDK 버전별 응답 형태(객체/딕셔너리) 차이를 흡수한다.
    """
    stats = store._index.describe_index_stats()
    namespaces = getattr(stats, "namespaces", None)
    if namespaces is None and isinstance(stats, dict):
        namespaces = stats.get("namespaces")

    summary = (namespaces or {}).get(namespace)
    if summary is None:
        return 0

    count = getattr(summary, "vector_count", None)
    if count is None and isinstance(summary, dict):
        count = summary.get("vector_count")
    return int(count or 0)


def _wait_until_vectors_visible(
    store: PineconeVectorStore, namespace: str, expected_count: int
) -> None:
    """upsert한 벡터가 통계에 가시화될 때까지 재시도 폴링으로 대기한다.

    Pinecone upsert는 eventual consistency이므로 가시성 확인 없이 바로
    단언하면 위양성(flaky) 실패가 발생한다.
    """
    deadline = time.monotonic() + _VISIBILITY_TIMEOUT_SECONDS
    last_count = 0
    while time.monotonic() < deadline:
        last_count = _namespace_vector_count(store, namespace)
        if last_count >= expected_count:
            return
        time.sleep(_VISIBILITY_POLL_INTERVAL_SECONDS)

    pytest.fail(
        f"upsert한 벡터가 {_VISIBILITY_TIMEOUT_SECONDS:.0f}초 내에 가시화되지 "
        f"않았습니다 (기대 {expected_count}개, 현재 {last_count}개, "
        f"namespace={_NAMESPACE}). Pinecone 인덱스 상태를 확인하세요."
    )


@pytest.fixture(scope="module")
def seeded_store() -> Iterator[PineconeVectorStore]:
    """시드 벡터가 업서트된 라이브 스토어를 제공하는 모듈 픽스처.

    setup: 인덱스 차원 자동 감지 → 단위 기저 합성 벡터 upsert → 가시성 폴링.
    teardown: 테스트 성패와 무관하게 네임스페이스 벡터 전체 삭제(try/finally).

    Note:
        store 자체는 이벤트 루프에 묶이지 않으므로(동기 클라이언트를 호출
        시점에 asyncio.to_thread로 래핑) 동기 픽스처에서 asyncio.run으로
        시딩해도 이후 비동기 테스트에서 안전하게 재사용할 수 있다.
    """
    store = PineconeVectorStore(
        api_key=_PINECONE_API_KEY,
        index_name=_PINECONE_TEST_INDEX,
    )
    try:
        dimension = _resolve_index_dimension(store)
        documents = [
            {
                "id": spec["id"],
                # i번째 단위 기저 벡터 — 모든 메트릭(cosine/dotproduct/euclidean)
                # 에서 유효한 합성 벡터 (제로 벡터는 Pinecone이 거부)
                "vector": [1.0 if pos == i else 0.0 for pos in range(dimension)],
                "metadata": spec["metadata"],
            }
            for i, spec in enumerate(_SEED_SPECS)
        ]
        upserted = asyncio.run(store.add_documents(_NAMESPACE, documents))
        assert upserted == len(_SEED_SPECS), (
            f"시드 upsert 개수 불일치: 기대 {len(_SEED_SPECS)}개, 실제 {upserted}개"
        )
        _wait_until_vectors_visible(store, _NAMESPACE, len(_SEED_SPECS))
        yield store
    finally:
        # teardown 보장: 네임스페이스 벡터 전체 삭제 (setup 실패 시에도 실행)
        try:
            store._index.delete(delete_all=True, namespace=_NAMESPACE)
        except Exception as cleanup_error:
            # 정리 실패가 테스트 결과(원본 실패 원인)를 가리지 않도록 경고만
            # 남긴다. 고유 uuid 네임스페이스 + 테스트 전용 인덱스이므로 잔여
            # 데이터 영향은 제한적이다.
            logger.warning(
                "Pinecone 라이브 스모크: 네임스페이스 정리 실패 "
                f"(namespace={_NAMESPACE}): {cleanup_error}"
            )


async def test_in_filter_with_mixed_types_matches_numeric_metadata(
    seeded_store: PineconeVectorStore,
) -> None:
    """(a) 숫자 메타데이터에 대한 $in 혼합 타입([3, "3"]) 필터 실측.

    fetch_objects(filters={"page": 3})는 서버측에서
    {"page": {"$in": [3, "3"]}} 필터로 변환되어 전송된다(비문자열 값의
    타입 관용 매칭 의미론 보존 목적). 이 혼합 타입 $in 수용 여부가 코드의
    미실측 가정 1순위이며, Pinecone이 거부(4xx)하면 이 테스트가 명확한
    메시지로 실패해 코드 수정 필요성을 알린다.
    """
    try:
        results = await seeded_store.fetch_objects(_NAMESPACE, filters={"page": 3})
    except RuntimeError as error:
        pytest.fail(
            "Pinecone이 혼합 타입 $in 필터({'page': {'$in': [3, '3']}})를 "
            "거부했습니다. 문서 기반 가정이 실측에서 깨졌으므로 "
            "pinecone_store._query_by_metadata_filter의 비문자열 값 변환 로직"
            "({'$in': [value, str(value)]})을 단일 타입 필터로 수정해야 합니다. "
            f"원본 오류: {error}"
        )

    matched_ids = {item["_id"] for item in results}
    assert matched_ids == {"live-vec-1"}, (
        f"page=3 필터 매칭 결과 불일치 (실제: {matched_ids or '0건'}). "
        "Pinecone은 숫자 메타데이터를 float로 저장하므로(3 → 3.0) "
        "$in [3, '3'] 중 숫자 3이 3.0과 매칭되어야 한다는 가정이 깨졌을 수 "
        "있습니다. pinecone_store의 필터 변환/메모리 폴백 의미론을 재검토하세요."
    )


def test_unit_basis_vector_query_accepts_max_top_k_with_metadata(
    seeded_store: PineconeVectorStore,
) -> None:
    """(b) fetch_objects 필터 경로가 사용하는 쿼리 파라미터 계약 실측.

    단위 기저 벡터 + include_metadata=True + top_k=PINECONE_QUERY_MAX_TOP_K(1,000)
    조합이 수용되는지 raw 클라이언트로 격리 측정한다. (a)/(c)가 필터 "의미론"을
    검증한다면, 이 테스트는 쿼리 "파라미터 상한" 자체를 검증한다 —
    include_metadata=True 시 top_k 상한 1,000이라는 문서 기반 상수
    (PINECONE_QUERY_MAX_TOP_K)의 실측 근거가 된다.
    """
    dimension = _resolve_index_dimension(seeded_store)
    try:
        response = seeded_store._index.query(
            vector=[1.0] + [0.0] * (dimension - 1),
            top_k=PINECONE_QUERY_MAX_TOP_K,
            namespace=_NAMESPACE,
            include_metadata=True,
        )
    except Exception as error:
        pytest.fail(
            f"include_metadata=True + top_k={PINECONE_QUERY_MAX_TOP_K} 쿼리가 "
            "Pinecone에서 거부되었습니다. PINECONE_QUERY_MAX_TOP_K 상한 가정"
            "(1,000)이 실측에서 깨졌으므로 pinecone_store의 상수와 전수 폴백 "
            f"로직을 수정해야 합니다. 원본 오류: {error}"
        )

    # SDK 버전별 응답 형태(객체/딕셔너리) 차이 흡수
    matches = getattr(response, "matches", None)
    if matches is None and isinstance(response, dict):
        matches = response.get("matches")

    assert matches, (
        "시드 벡터가 가시화된 상태인데 단위 기저 벡터 쿼리 결과가 비어 있습니다. "
        "쿼리 벡터 차원 또는 네임스페이스 지정을 확인하세요."
    )
    assert len(matches) == len(_SEED_SPECS), (
        f"쿼리 결과 개수 불일치: 기대 {len(_SEED_SPECS)}개, 실제 {len(matches)}개"
    )


async def test_string_document_id_eq_filter_matches(
    seeded_store: PineconeVectorStore,
) -> None:
    """(c) 문자열 document_id $eq 필터 정상 매칭 실측.

    fetch_objects(filters={"document_id": <str>})는 서버측에서
    {"document_id": {"$eq": <str>}}로 변환된다. 문서 관리 경로
    (get_document_chunks/list_documents)의 핵심 필터이므로 실 API에서
    정확히 해당 문서의 청크만 반환되는지 검증한다.
    """
    results = await seeded_store.fetch_objects(
        _NAMESPACE, filters={"document_id": _DOCUMENT_ID}
    )

    matched_ids = {item["_id"] for item in results}
    assert matched_ids == {"live-vec-1", "live-vec-2"}, (
        f"document_id $eq 필터 매칭 결과 불일치 (실제: {matched_ids or '0건'}). "
        "문자열 $eq 동등 비교가 기대대로 동작하지 않습니다."
    )

    # 반환 계약 확인: 각 항목은 {"_id", "content", ...metadata} 형식
    for item in results:
        assert item["document_id"] == _DOCUMENT_ID
        assert isinstance(item["content"], str) and item["content"], (
            f"content 필드가 비어 있습니다: {item}"
        )
