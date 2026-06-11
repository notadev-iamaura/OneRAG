"""
Pinecone Vector Store Adapter

IVectorStore 인터페이스를 구현한 Pinecone 서버리스 어댑터입니다.
Pinecone은 완전 관리형 벡터 데이터베이스로, 하이브리드 검색(Dense + Sparse)을 지원합니다.

주요 기능:
- 서버리스 아키텍처 (자동 스케일링)
- Dense Vector 검색
- Sparse Vector를 통한 하이브리드 검색 (BM25 스타일)
- 네임스페이스 기반 멀티테넌시
- 동기 API를 asyncio.to_thread로 비동기 래핑

의존성:
- pinecone: pip install pinecone

Pinecone v7+ API 사용 (2024년 이후 신규 버전)
"""

import asyncio
from typing import Any

from pinecone import Pinecone

from app.core.interfaces.storage import IVectorStore
from app.lib.logger import get_logger

logger = get_logger(__name__)

# Pinecone query API의 top_k 상한 (include_metadata=True 기준).
# - top_k 자체의 절대 최대값은 10,000이지만(공식 문서
#   https://docs.pinecone.io/reference/api/database-limits "Max top_k value | 10,000"),
#   include_metadata=True 또는 include_values=True인 쿼리의 top_k 상한은 1,000이다
#   (Pinecone 공식 limits 문서: "The max value for top_k for queries with
#   include_metadata=True or include_data=True is 1,000").
# - 현행 문서(https://docs.pinecone.io/reference/quotas-and-limits)의 결과 크기
#   4MB 제한도 메타데이터 포함 시 실질 상한을 같은 수준으로 묶는다.
# 서버측 메타데이터 필터 조회(fetch_objects 필터 경로)는 include_metadata=True가
# 필수이므로 이 값을 1,000으로 유지해야 한다. 결과가 이 상한에 도달하면
# 잘림 가능성이 있으므로 전수 경로(list+fetch)로 폴백한다.
PINECONE_QUERY_MAX_TOP_K = 1000

# 메타데이터 필터 쿼리용 쿼리 벡터의 기본 차원.
# describe_index_stats로 실제 인덱스 차원을 조회하지 못한 경우의 폴백 값이며,
# config/features/pinecone.yaml의 index_guide.dimensions(=3072, Gemini
# embedding-001 기준)와 동일하게 유지한다.
DEFAULT_INDEX_DIMENSION = 3072


class PineconeVectorStore(IVectorStore):
    """
    Pinecone 기반 벡터 스토어 구현체.

    IVectorStore 인터페이스를 구현하여 벡터 저장, 검색, 삭제 기능을 제공합니다.
    Pinecone의 동기 API를 asyncio.to_thread로 래핑하여 비동기로 사용 가능합니다.

    사용 예시:
        # 기본 사용
        store = PineconeVectorStore(api_key="your-api-key")

        # 커스텀 인덱스
        store = PineconeVectorStore(
            api_key="your-api-key",
            index_name="my-custom-index"
        )
    """

    def __init__(
        self,
        api_key: str,
        environment: str | None = None,  # 서버리스는 환경 설정 불필요
        index_name: str = "rag-documents",
        _client: Any = None,  # 테스트용 클라이언트 주입
    ) -> None:
        """
        PineconeVectorStore 초기화.

        Args:
            api_key: Pinecone API 키
            environment: Pinecone 환경 (서버리스에서는 불필요, 레거시 호환용)
            index_name: 사용할 인덱스 이름. 기본값 "rag-documents"
            _client: 테스트용 클라이언트 주입 (내부 사용)
        """
        self.api_key = api_key
        self.environment = environment
        self.index_name = index_name

        # 테스트용 클라이언트가 주입되었으면 사용, 아니면 새로 생성
        if _client is not None:
            self._client = _client
        else:
            self._client = Pinecone(api_key=api_key)

        # 인덱스 연결
        self._index = self._client.Index(index_name)

        # 인덱스 차원 캐시 (메타데이터 필터 쿼리의 쿼리 벡터 구성용, 지연 조회)
        self._index_dimension: int | None = None

        logger.info(
            f"PineconeVectorStore: 초기화 완료 (index={index_name})"
        )

    async def add_documents(
        self, collection: str, documents: list[dict[str, Any]]
    ) -> int:
        """
        문서(벡터 포함) 저장 (Upsert).

        동일 ID의 문서가 있으면 업데이트, 없으면 추가합니다.
        Pinecone에서 collection은 namespace로 매핑됩니다.

        Args:
            collection: 네임스페이스 이름 (Pinecone namespace)
            documents: 문서 리스트. 각 문서는 다음 형식:
                - id: str - 문서 ID
                - vector: list[float] - Dense 벡터
                - metadata: dict - 메타데이터
                - sparse_values: dict | None - Sparse 벡터 (선택)
                    - indices: list[int] - 토큰 인덱스
                    - values: list[float] - 토큰 가중치

        Returns:
            저장된 문서 개수
        """
        if not documents:
            return 0

        def _add_sync() -> int:
            # Pinecone 벡터 형식으로 변환
            vectors: list[dict[str, Any]] = []

            for doc in documents:
                doc_id = str(doc.get("id", ""))
                vector: list[float] = doc.get("vector", [])
                metadata: dict[str, Any] = doc.get("metadata", {})
                sparse_values = doc.get("sparse_values")

                if not doc_id:
                    continue

                # 기본 벡터 구조
                vec_data: dict[str, Any] = {
                    "id": doc_id,
                    "values": vector,
                    "metadata": metadata,
                }

                # Sparse Vector가 있으면 추가 (하이브리드 검색용)
                if sparse_values:
                    vec_data["sparse_values"] = sparse_values

                vectors.append(vec_data)

            if not vectors:
                return 0

            # Upsert 실행
            response = self._index.upsert(
                vectors=vectors,
                namespace=collection,
            )

            # upserted_count 반환
            return getattr(response, "upserted_count", len(vectors))

        try:
            count = await asyncio.to_thread(_add_sync)
            logger.debug(
                f"PineconeVectorStore: {count}개 문서 저장 완료 (namespace={collection})"
            )
            return count
        except Exception as e:
            logger.error(f"PineconeVectorStore: 문서 저장 실패 - {e}")
            raise RuntimeError(
                f"문서 저장 중 오류가 발생했습니다: {len(documents)}개 문서. "
                "해결 방법: 1) API 키가 유효한지 확인하세요. "
                "2) 인덱스 이름이 올바른지 확인하세요. "
                "3) 벡터 차원이 인덱스 설정과 일치하는지 확인하세요."
            ) from e

    async def search(
        self,
        collection: str,
        query_vector: list[float],
        top_k: int,
        filters: dict[str, Any] | None = None,
        sparse_vector: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """
        벡터 유사도 검색.

        Dense Vector 검색 또는 Sparse Vector를 포함한 하이브리드 검색을 수행합니다.

        Args:
            collection: 네임스페이스 이름 (Pinecone namespace)
            query_vector: 검색 쿼리의 Dense 벡터
            top_k: 반환할 최대 결과 수
            filters: 메타데이터 필터 (Pinecone filter 문법)
            sparse_vector: Sparse 벡터 (하이브리드 검색용)
                - indices: list[int] - 토큰 인덱스
                - values: list[float] - 토큰 가중치

        Returns:
            검색 결과 리스트. 각 결과는 다음 형식:
                - _id: str - 문서 ID
                - _score: float - 유사도 점수
                - ...metadata - 메타데이터 필드들
        """

        def _search_sync() -> list[dict[str, Any]]:
            # 검색 파라미터 구성
            query_params: dict[str, Any] = {
                "vector": query_vector,
                "top_k": top_k,
                "namespace": collection,
                "include_metadata": True,
            }

            # 메타데이터 필터
            if filters:
                query_params["filter"] = filters

            # Sparse Vector (하이브리드 검색)
            if sparse_vector:
                query_params["sparse_vector"] = sparse_vector

            # 검색 실행
            results = self._index.query(**query_params)

            # 결과 변환
            output: list[dict[str, Any]] = []

            if not results or not hasattr(results, "matches"):
                return output

            for match in results.matches:
                item: dict[str, Any] = {}

                # 메타데이터 복사
                if hasattr(match, "metadata") and match.metadata:
                    item.update(match.metadata)

                # 표준 필드 추가
                item["_id"] = match.id
                item["_score"] = match.score if hasattr(match, "score") else 0.0

                output.append(item)

            return output

        try:
            results = await asyncio.to_thread(_search_sync)
            logger.debug(
                f"PineconeVectorStore: {len(results)}개 결과 검색 완료 "
                f"(namespace={collection}, top_k={top_k})"
            )
            return results
        except Exception as e:
            logger.error(f"PineconeVectorStore: 검색 실패 - {e}")
            return []

    async def delete(
        self, collection: str, filters: dict[str, Any]
    ) -> int:
        """
        조건에 맞는 문서 삭제.

        Args:
            collection: 네임스페이스 이름 (Pinecone namespace)
            filters: 삭제 조건:
                - id: str - 단일 ID 삭제
                - ids: list[str] - 여러 ID 삭제
                - 그 외 필드: 메타데이터 필터 기반 삭제

        Returns:
            삭제된 문서 개수 (ID 기반 삭제 시 정확, 필터 기반은 추정치)
        """

        def _delete_sync() -> int:
            # ID 기반 삭제
            if "id" in filters:
                doc_id = str(filters["id"])
                self._index.delete(
                    ids=[doc_id],
                    namespace=collection,
                )
                return 1

            # 여러 ID 삭제
            if "ids" in filters:
                ids_to_delete = [str(id_) for id_ in filters["ids"]]
                if not ids_to_delete:
                    return 0

                self._index.delete(
                    ids=ids_to_delete,
                    namespace=collection,
                )
                return len(ids_to_delete)

            # 메타데이터 필터 기반 삭제
            # Pinecone은 filter 기반 삭제도 지원
            filter_conditions = {k: v for k, v in filters.items() if k not in ("id", "ids")}
            if filter_conditions:
                self._index.delete(
                    filter=filter_conditions,
                    namespace=collection,
                )
                # 필터 기반 삭제는 정확한 개수를 알 수 없음
                # -1 또는 0을 반환할 수 있으나, 일관성을 위해 1 반환
                return 1

            return 0

        try:
            count = await asyncio.to_thread(_delete_sync)
            logger.debug(
                f"PineconeVectorStore: {count}개 문서 삭제 완료 (namespace={collection})"
            )
            return count
        except Exception as e:
            logger.error(f"PineconeVectorStore: 삭제 실패 - {e}")
            raise RuntimeError(
                "문서 삭제 중 오류가 발생했습니다. "
                "해결 방법: 1) API 키가 유효한지 확인하세요. "
                "2) 인덱스 이름이 올바른지 확인하세요. "
                "3) 필터 형식을 확인하세요."
            ) from e

    async def fetch_objects(
        self,
        collection: str,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """컬렉션(네임스페이스) 객체를 조회한다(문서관리/인접청크 확장용).

        PineconeRetriever의 get_document_chunks/list_documents 등이 이 메서드에 위임한다
        (ChromaVectorStore 파리티 백포트). chroma_store와 동일하게 각 객체는
        {"_id": str, "content": str, ...metadata} 형태로 반환한다.

        조회 경로는 필터 종류에 따라 세 갈래로 나뉜다:
        1. id/ids 필터: fetch로 직접 조회 (나머지 메타데이터 조건은 메모리 필터링)
        2. 메타데이터 필터(id/ids 외): 서버측 필터 쿼리(query + filter)로 1회 조회
           — 전수 ID 스캔 후 순차 fetch하던 기존 방식(네임스페이스 크기에 비례한
           API 왕복)을 제거한다. 단, top_k 상한 도달 시 완전성 보장을 위해
           전수 경로(list_paginated + fetch)로 폴백한다.
        3. 필터 없음(전체 목록): list_paginated로 전체 ID 수집 후 fetch 배치 조회

        Args:
            collection: 네임스페이스 이름 (Pinecone namespace)
            filters: 메타데이터 필터.
                - id: str - 단일 ID 직접 조회
                - ids: list[str] - 여러 ID 직접 조회
                - 그 외 필드: 서버측 메타데이터 필터 쿼리 (top_k 상한
                  ``PINECONE_QUERY_MAX_TOP_K``, 도달 시 전수 경로 폴백)

        Returns:
            조회 결과 리스트. 각 항목은 {"_id": str, "content": str, ...metadata} 형식.
        """
        filters_value = filters or {}

        def _fetch_sync() -> list[dict[str, Any]]:
            # 메타데이터 조건 분리 (id/ids 제외)
            meta_filters = {
                key: value
                for key, value in filters_value.items()
                if key not in ("id", "ids")
            }

            # 1) 조회 대상 ID 목록 결정
            target_ids: list[str]
            if "id" in filters_value:
                target_ids = [str(filters_value["id"])]
            elif "ids" in filters_value:
                target_ids = [str(value) for value in filters_value["ids"]]
            elif meta_filters:
                # 메타데이터 필터 경로: 전수 스캔 대신 서버측 필터 쿼리 1회로 조회
                return self._query_by_metadata_filter(collection, meta_filters)
            else:
                # 필터 없음: 네임스페이스 전체 ID를 페이지네이션으로 수집
                target_ids = self._list_all_ids(collection)

            # 2) ID 배치 단위로 fetch + 메모리 필터링
            return self._fetch_ids_with_memory_filter(
                collection, target_ids, meta_filters
            )

        try:
            return await asyncio.to_thread(_fetch_sync)
        except Exception as e:
            logger.error(f"PineconeVectorStore: 객체 조회 실패 - {e}")
            raise RuntimeError(
                "객체 조회 중 오류가 발생했습니다. "
                "해결 방법: 1) API 키가 유효한지 확인하세요. "
                "2) 인덱스/네임스페이스 이름이 올바른지 확인하세요. "
                "3) Pinecone 로그를 확인하세요."
            ) from e

    async def delete_objects(self, collection: str, object_ids: list[str]) -> int:
        """ID 목록으로 객체를 삭제한다(문서관리용).

        fetch_objects가 반환한 _id(Pinecone 벡터 ID)를 그대로 사용한다.

        Args:
            collection: 네임스페이스 이름 (Pinecone namespace)
            object_ids: 삭제할 벡터 ID 목록

        Returns:
            삭제 요청한 객체 개수
        """
        if not object_ids:
            return 0
        return await self.delete(collection=collection, filters={"ids": object_ids})

    def _query_by_metadata_filter(
        self, namespace: str, meta_filters: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """메타데이터 필터를 서버측 query로 위임해 객체를 조회한다.

        기존 구현은 list_paginated로 네임스페이스 전체 ID를 수집한 뒤 100개씩
        순차 fetch하고 메모리에서 필터링했다(50k 벡터 기준 호출당 약 1,000회
        API 왕복). Pinecone query는 메타데이터 필터를 서버측에서 지원하므로
        정상 케이스(필터 일치 객체 < top_k 상한)는 쿼리 1회로 동일 결과를 얻는다.

        완전성 보장: 결과가 top_k 상한에 도달하면 필터 일치 객체가 더 존재할
        수 있으므로(잘림), 잘린 결과를 버리고 전수 경로(list_paginated + fetch
        + 메모리 필터)로 폴백해 완전한 결과를 반환한다. 부분 결과를 그대로
        반환하면 호출자(문서 삭제 등)에서 부분 삭제 사고로 이어지기 때문이다.

        Args:
            namespace: 네임스페이스 이름
            meta_filters: 메타데이터 필터 (id/ids 제외된 조건).
                - 값이 dict면 Pinecone 연산자 필터({"$in": ...} 등)로 그대로 전달
                - 문자열 값은 동등 비교({"$eq": value})로 변환
                - 비문자열 값은 {"$in": [value, str(value)]}로 변환 — 서버측
                  $eq는 타입 엄격 비교라서 숫자로 저장된 값을 문자열로 조회하면
                  (또는 그 반대) 조용히 0건이 된다. 기존 메모리 필터의
                  str(metadata) == str(value) 강제 변환 비교 의미론을 보존하기
                  위해 원본 타입과 문자열 표현 양쪽을 허용한다.

        Returns:
            조회 결과 리스트. 각 항목은 {"_id": str, "content": str, ...metadata} 형식
            (기존 fetch 경로와 동일한 반환 계약).
        """
        # Pinecone filter 문법으로 변환
        pinecone_filter: dict[str, Any] = {}
        for key, value in meta_filters.items():
            if isinstance(value, dict):
                # 연산자 필터({"$in": ...} 등)는 그대로 통과
                pinecone_filter[key] = value
            elif isinstance(value, str):
                pinecone_filter[key] = {"$eq": value}
            else:
                # 비문자열 값: 원본 타입/문자열 표현 양쪽 매칭 (의미론 보존)
                pinecone_filter[key] = {"$in": [value, str(value)]}

        # 순수 메타데이터 조회 목적이므로 유사도 순위는 무의미하다. 다만
        # Pinecone은 모든 값이 0인 dense 쿼리 벡터를 거부하므로("Dense vectors
        # must contain at least one non-zero value", error code 3 — 특히 cosine
        # 메트릭은 제로 벡터와의 유사도가 정의되지 않음) 단위 기저 벡터
        # [1, 0, 0, ...]를 사용한다. 어떤 메트릭(cosine/dotproduct/euclidean)
        # 에서도 유효하며, 필터 매칭 결과 집합은 쿼리 벡터와 무관하다(순위만
        # 영향을 받는데 이 경로에서는 순위를 사용하지 않음).
        # 차원은 인덱스 실제 차원과 일치해야 쿼리가 거부되지 않는다.
        dimension = self._get_index_dimension()
        response = self._index.query(
            vector=[1.0] + [0.0] * (dimension - 1),
            filter=pinecone_filter,
            top_k=PINECONE_QUERY_MAX_TOP_K,
            namespace=namespace,
            include_metadata=True,
        )

        # 응답에서 matches 추출 (SDK 버전별 형태 차이 흡수)
        matches = getattr(response, "matches", None)
        if matches is None and isinstance(response, dict):
            matches = response.get("matches")

        output: list[dict[str, Any]] = []
        for match in matches or []:
            match_id = getattr(match, "id", None)
            if match_id is None and isinstance(match, dict):
                match_id = match.get("id")
            metadata = self._extract_metadata(match)
            item: dict[str, Any] = dict(metadata)
            item["_id"] = str(match_id)
            item["content"] = str(metadata.get("content", ""))
            output.append(item)

        # top_k 상한 도달 시 결과가 잘렸을 수 있으므로 전수 경로로 폴백한다.
        # Pinecone query는 top_k를 넘는 결과를 반환하지 않으므로, 상한과 동일한
        # 개수가 반환되면 필터 일치 객체가 더 존재할 수 있다 — 잘린 부분 결과를
        # 사용하면 부분 삭제 위험이 있어 완전 열거로 전환한다(조용한 절단 금지).
        if len(output) >= PINECONE_QUERY_MAX_TOP_K:
            logger.info(
                f"PineconeVectorStore: 메타데이터 필터 조회 결과가 top_k 상한"
                f"({PINECONE_QUERY_MAX_TOP_K})에 도달해 전수 경로"
                f"(list+fetch)로 폴백합니다 "
                f"(namespace={namespace}, filter={pinecone_filter})"
            )
            return self._fetch_ids_with_memory_filter(
                namespace, self._list_all_ids(namespace), meta_filters
            )

        return output

    def _fetch_ids_with_memory_filter(
        self,
        namespace: str,
        target_ids: list[str],
        meta_filters: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """ID 목록을 배치 fetch하고 메타데이터 조건을 메모리에서 필터링한다.

        id/ids 직접 조회 경로와 메타데이터 필터 쿼리의 전수 폴백 경로가
        공유하는 헬퍼. 필터 의미론은 빠른 경로(서버측 query 필터)와 일치해야
        한다 — cap-hit 폴백 시 두 경로가 다른 결과를 내면 조용한 오결과가 된다.

        Args:
            namespace: 네임스페이스 이름
            target_ids: 조회할 벡터 ID 목록
            meta_filters: 메모리 필터링할 메타데이터 조건 (빈 dict면 필터 없음)

        Returns:
            조회 결과 리스트. 각 항목은 {"_id": str, "content": str, ...metadata} 형식.
        """
        if not target_ids:
            return []

        # ID 배치 단위로 fetch (Pinecone fetch 권장 배치 크기 100)
        output: list[dict[str, Any]] = []
        batch_size = 100
        for start in range(0, len(target_ids), batch_size):
            batch = target_ids[start : start + batch_size]
            response = self._index.fetch(ids=batch, namespace=namespace)
            vectors = self._extract_fetch_vectors(response)
            for vec_id, vec in vectors.items():
                metadata = self._extract_metadata(vec)
                # 메타데이터 필터 적용 (빠른 경로와 동일 의미론)
                if meta_filters and not all(
                    self._memory_filter_matches(metadata.get(key), value)
                    for key, value in meta_filters.items()
                ):
                    continue
                item: dict[str, Any] = dict(metadata)
                item["_id"] = str(vec_id)
                item["content"] = str(metadata.get("content", ""))
                output.append(item)
        return output

    @staticmethod
    def _memory_filter_values_equal(stored: Any, expected: Any) -> bool:
        """단일 값 동등 비교 — 빠른 경로의 관용적 의미론을 재현한다.

        Pinecone은 숫자 메타데이터를 float로 저장하므로(3 → 3.0),
        숫자 동등성(3 == 3.0 == "3")과 문자열 강제 변환 동등성을 함께 허용한다.
        """
        if str(stored) == str(expected):
            return True
        try:
            return float(stored) == float(expected)
        except (TypeError, ValueError):
            return False

    @classmethod
    def _memory_filter_matches(cls, stored: Any, condition: Any) -> bool:
        """메모리 폴백 필터 1개 조건 평가 — 서버측 query 필터와 의미론 일치.

        지원 연산자: ``$eq``, ``$in`` (빠른 경로가 생성·통과시키는 형태 전부).
        그 외 연산자(dict)는 메모리에서 재현할 수 없으므로 조용한 오결과 대신
        명시적 ValueError를 발생시킨다 (에러 숨김 금지).
        """
        if isinstance(condition, dict):
            if "$eq" in condition:
                return cls._memory_filter_values_equal(stored, condition["$eq"])
            if "$in" in condition:
                candidates = condition["$in"]
                return any(
                    cls._memory_filter_values_equal(stored, item) for item in candidates
                )
            raise ValueError(
                f"메모리 폴백이 지원하지 않는 필터 연산자입니다: {sorted(condition.keys())}. "
                "지원 연산자: $eq, $in"
            )
        return cls._memory_filter_values_equal(stored, condition)

    def _get_index_dimension(self) -> int:
        """인덱스 벡터 차원을 조회한다 (최초 1회 조회 후 캐시).

        메타데이터 필터 쿼리의 쿼리 벡터(단위 기저 벡터)는 인덱스 차원과
        일치해야 하므로 describe_index_stats에서 실제 차원을 읽는다. 조회 실패 또는 응답에
        유효한 차원이 없으면 ``DEFAULT_INDEX_DIMENSION``으로 폴백한다
        (차원 불일치 시 Pinecone이 쿼리를 거부하므로 오류가 은폐되지 않음).
        """
        if self._index_dimension is not None:
            return self._index_dimension

        dimension: Any = None
        try:
            stats = self._index.describe_index_stats()
            dimension = getattr(stats, "dimension", None)
            if dimension is None and isinstance(stats, dict):
                dimension = stats.get("dimension")
        except Exception as e:
            logger.warning(
                f"PineconeVectorStore: 인덱스 차원 조회 실패, 기본값 "
                f"{DEFAULT_INDEX_DIMENSION} 사용 - {e}"
            )

        # bool은 int의 서브클래스이므로 명시적으로 제외하고 정수 차원만 수용
        if (
            isinstance(dimension, int | float)
            and not isinstance(dimension, bool)
            and int(dimension) > 0
        ):
            self._index_dimension = int(dimension)
        else:
            self._index_dimension = DEFAULT_INDEX_DIMENSION

        return self._index_dimension

    def _list_all_ids(self, namespace: str) -> list[str]:
        """네임스페이스의 모든 벡터 ID를 list_paginated로 수집한다.

        Pinecone list_paginated는 한 페이지의 ID와 다음 페이지 토큰을 반환하므로
        pagination 토큰이 소진될 때까지 반복 호출한다.
        """
        all_ids: list[str] = []
        pagination_token: str | None = None
        while True:
            if pagination_token is not None:
                response = self._index.list_paginated(
                    namespace=namespace, pagination_token=pagination_token
                )
            else:
                response = self._index.list_paginated(namespace=namespace)

            # 응답에서 ID 추출 (SDK 버전별 형태 차이 흡수)
            vectors = getattr(response, "vectors", None)
            if vectors is None and isinstance(response, dict):
                vectors = response.get("vectors")
            for item in vectors or []:
                vec_id = getattr(item, "id", None)
                if vec_id is None and isinstance(item, dict):
                    vec_id = item.get("id")
                if vec_id is not None:
                    all_ids.append(str(vec_id))

            # 다음 페이지 토큰 추출
            pagination = getattr(response, "pagination", None)
            if pagination is None and isinstance(response, dict):
                pagination = response.get("pagination")
            next_token = getattr(pagination, "next", None)
            if next_token is None and isinstance(pagination, dict):
                next_token = pagination.get("next")
            if not next_token:
                break
            pagination_token = str(next_token)

        return all_ids

    @staticmethod
    def _extract_fetch_vectors(response: Any) -> dict[str, Any]:
        """fetch 응답에서 {id: Vector} 매핑을 추출한다(SDK 버전별 형태 차이 흡수)."""
        vectors = getattr(response, "vectors", None)
        if vectors is None and isinstance(response, dict):
            vectors = response.get("vectors")
        return dict(vectors) if vectors else {}

    @staticmethod
    def _extract_metadata(vector: Any) -> dict[str, Any]:
        """Vector 객체/딕셔너리에서 메타데이터 딕셔너리를 추출한다."""
        metadata = getattr(vector, "metadata", None)
        if metadata is None and isinstance(vector, dict):
            metadata = vector.get("metadata")
        return dict(metadata) if metadata else {}

    def close(self) -> None:
        """
        리소스 정리.

        Pinecone 클라이언트는 명시적 close가 필요하지 않지만
        일관성을 위해 메서드를 제공합니다.
        """
        logger.debug("PineconeVectorStore: 연결 종료")

    def __del__(self) -> None:
        """소멸자에서 리소스 정리."""
        self.close()
