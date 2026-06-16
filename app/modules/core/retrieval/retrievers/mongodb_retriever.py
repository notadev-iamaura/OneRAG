"""
MongoDBRetriever - MongoDB 하이브리드 검색 (Dense + Sparse BM25, client-side RRF)

주요 기능:
- $vectorSearch(Dense)와 $search(Full-Text BM25)를 asyncio.gather로 병렬 실행
- Python client-side RRF(Reciprocal Rank Fusion)로 두 결과를 통합
  → Atlas tier 제약($rankFusion 미지원 tier) 없이 하이브리드 검색 제공
- dense_weight/sparse_weight 가중치로 융합 비중 조절
- 하이브리드 실패 시 vector-only fallback(Dense 검색만)으로 graceful degradation

설계 의도(OneRAG 차용 #4):
- 기존 mongodb 프로바이더(MongoDBAtlasRetriever)는 Dense 전용이다. 본 클래스는
  RetrieverFactory에 'mongodb_hybrid' 변형으로 등록되어, MongoDB 사용자가
  하이브리드 검색을 선택할 수 있게 한다(새 VectorStore가 아니라 Retriever 변형).

의존성:
- pymongo: MongoDB 공식 Python 드라이버(optional, uv sync --extra mongodb)
- app.lib.mongodb_client.MongoDBClient: ping()/get_collection() 제공 연결 클라이언트
- ..interfaces.SearchResult: 검색 결과 표준 형식
"""

from __future__ import annotations

import asyncio
from typing import Any

from pymongo.collection import Collection
from pymongo.errors import PyMongoError

from .....lib.logger import get_logger
from .....lib.mongodb_client import MongoDBClient
from ..interfaces import SearchResult

logger = get_logger(__name__)


class MongoDBRetriever:
    """MongoDB 하이브리드 검색 구현(Dense + Sparse, client-side RRF).

    아키텍처:
    - vectorPipeline: $vectorSearch (Dense, cosine similarity)
    - fullTextPipeline: $search (Sparse, BM25)
    - _client_side_rank_fusion: 두 결과의 순위를 RRF로 통합

    IRetriever 계약(search/health_check)을 만족하며, dense-only 구현체와 달리
    실제 BM25 분기를 병렬 수행한다.
    """

    def __init__(
        self,
        embedder: Any,
        mongodb_client: MongoDBClient,
        collection_name: str = "documents",
        dense_weight: float = 0.6,
        sparse_weight: float = 0.4,
        vector_index_name: str = "vector_index",
        fulltext_index_name: str = "default",
    ) -> None:
        """MongoDBRetriever 초기화.

        Args:
            embedder: Dense embedding 모델(embed_query 제공).
            mongodb_client: MongoDB 연결 클라이언트(ping/get_collection 제공).
            collection_name: 검색할 컬렉션 이름(기본: "documents").
            dense_weight: Dense 벡터 RRF 가중치(기본: 0.6).
            sparse_weight: BM25 RRF 가중치(기본: 0.4).
            vector_index_name: Atlas Vector Search 인덱스 이름.
            fulltext_index_name: Atlas Full-Text Search 인덱스 이름.

        Note:
            가중치 합은 1.0이 아니어도 된다(RRF 점수의 상대 비중만 결정).
        """
        self.embedder = embedder
        self.collection_name = collection_name
        self.dense_weight = dense_weight
        self.sparse_weight = sparse_weight

        self.mongodb_client = mongodb_client
        self.collection: Collection | None = None

        self.vector_index_name = vector_index_name
        self.fulltext_index_name = fulltext_index_name

        # 통계(관측용)
        self.stats: dict[str, int] = {
            "total_searches": 0,
            "hybrid_searches": 0,
            "vector_searches": 0,
            "fulltext_searches": 0,
        }

        logger.info(
            "MongoDBRetriever 초기화: collection=%s, weights=(dense=%s, sparse=%s)",
            collection_name,
            dense_weight,
            sparse_weight,
        )

    async def initialize(self) -> None:
        """MongoDB 연결 및 컬렉션 접근을 확인한다.

        Raises:
            RuntimeError: 연결 비활성 또는 컬렉션 접근 실패 시.
            PyMongoError: MongoDB 드라이버 오류 시.
        """
        try:
            logger.debug("MongoDBRetriever 초기화 시작...")

            if not self.mongodb_client.ping():
                raise RuntimeError("MongoDB 연결이 활성화되지 않았습니다.")

            self.collection = self.mongodb_client.get_collection(self.collection_name)
            if self.collection is None:
                raise RuntimeError(
                    f"MongoDB 컬렉션을 가져올 수 없습니다: {self.collection_name}"
                )

            doc_count = await asyncio.to_thread(self.collection.count_documents, {})
            logger.info(
                "MongoDBRetriever 초기화 완료: collection=%s, documents=%s",
                self.collection_name,
                doc_count,
            )
        except PyMongoError as e:
            logger.error(
                "MongoDB 연결 오류: %s",
                str(e),
                extra={"collection": self.collection_name, "error_type": type(e).__name__},
            )
            raise
        except Exception as e:
            logger.error(
                "MongoDBRetriever 초기화 실패: %s",
                str(e),
                extra={"collection": self.collection_name},
            )
            raise

    async def health_check(self) -> bool:
        """MongoDB 연결 및 컬렉션 상태를 확인한다.

        Returns:
            정상 동작 여부(True/False). 예외는 False로 흡수한다.
        """
        try:
            if self.collection is None:
                logger.warning("MongoDB health check 실패: 컬렉션 미초기화")
                return False
            if not self.mongodb_client.ping():
                logger.warning("MongoDB health check 실패: 연결 끊김")
                return False
            await asyncio.to_thread(self.collection.count_documents, {}, limit=1)
            logger.debug("MongoDB health check 성공")
            return True
        except PyMongoError as e:
            logger.error(
                "MongoDB health check 실패: %s", str(e), extra={"error_type": type(e).__name__}
            )
            return False
        except Exception as e:
            logger.error("MongoDB health check 예상치 못한 오류: %s", str(e))
            return False

    async def search(
        self,
        query: str,
        top_k: int = 10,
        filters: dict[str, Any] | None = None,
        alpha: float | None = None,  # IRetriever 계약 호환(미사용; 가중치는 생성자 설정)
    ) -> list[SearchResult]:
        """하이브리드 검색 수행(Dense + Sparse, client-side RRF).

        절차:
        1. 쿼리 임베딩 생성
        2. $vectorSearch와 $search를 asyncio.gather로 병렬 실행(분기 예외는 흡수)
        3. _client_side_rank_fusion으로 통합(Atlas tier 제약 없음)

        Args:
            query: 검색 쿼리 문자열.
            top_k: 반환할 최대 결과 수.
            filters: 메타데이터 필터링 조건(선택).
            alpha: IRetriever 계약 호환용. 본 구현은 생성자 가중치를 사용한다.

        Returns:
            통합·정렬된 검색 결과 리스트(SearchResult).

        Raises:
            Exception: 임베딩 등 비-PyMongo 치명적 오류는 상위로 전파한다.
        """
        try:
            if self.collection is None:
                raise RuntimeError("MongoDB 컬렉션이 초기화되지 않았습니다.")

            query_embedding = await asyncio.to_thread(self.embedder.embed_query, query)
            if not isinstance(query_embedding, list):
                raise ValueError(
                    f"Embedding은 list 타입이어야 합니다. 받은 타입: {type(query_embedding)}"
                )

            # 더 많은 후보를 가져와 RRF로 통합(재현율 보강)
            candidate_k = top_k * 2

            vector_task = self._vector_search_only(
                query_embedding=query_embedding, top_k=candidate_k, filters=filters
            )
            fulltext_task = self._fulltext_search_only(
                query=query, top_k=candidate_k, filters=filters
            )

            results_tuple = await asyncio.gather(
                vector_task, fulltext_task, return_exceptions=True
            )
            vector_raw, fulltext_raw = results_tuple

            vector_results: list[dict[str, Any]]
            if isinstance(vector_raw, BaseException):
                logger.warning("Vector search 실패: %s", vector_raw)
                vector_results = []
            else:
                vector_results = vector_raw

            fulltext_results: list[dict[str, Any]]
            if isinstance(fulltext_raw, BaseException):
                logger.warning("Full-text search 실패: %s", fulltext_raw)
                fulltext_results = []
            else:
                fulltext_results = fulltext_raw

            results = self._client_side_rank_fusion(
                vector_results=vector_results,
                fulltext_results=fulltext_results,
                top_k=top_k,
            )

            self.stats["total_searches"] += 1
            self.stats["hybrid_searches"] += 1
            logger.info("MongoDB 하이브리드 검색 완료(client-side RRF): %s개 결과", len(results))
            return results

        except PyMongoError as e:
            logger.error(
                "MongoDB 검색 오류: %s",
                str(e),
                extra={"query": query[:100], "error_type": type(e).__name__},
            )
            # Fallback: Dense 검색만 시도
            return await self._vector_search_fallback(query, top_k, filters)
        except Exception as e:
            logger.error(
                "MongoDB 검색 예상치 못한 오류: %s", str(e), extra={"query": query[:100]}
            )
            raise

    async def _vector_search_only(
        self,
        query_embedding: list[float],
        top_k: int,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """$vectorSearch 단독 실행(Dense)."""
        pipeline: list[dict[str, Any]] = [
            {
                "$vectorSearch": {
                    "index": self.vector_index_name,
                    "path": "embedding",
                    "queryVector": query_embedding,
                    "numCandidates": top_k * 10,
                    "limit": top_k,
                }
            },
            {
                "$project": {
                    "_id": 1,
                    "content": 1,
                    "metadata": 1,
                    "score": {"$meta": "vectorSearchScore"},
                }
            },
        ]
        if filters:
            pipeline.insert(1, self._build_match_stage(filters))

        if self.collection is None:
            logger.error("Collection이 초기화되지 않음")
            return []

        cursor = await asyncio.to_thread(self.collection.aggregate, pipeline)
        results: list[dict[str, Any]] = await asyncio.to_thread(list, cursor)
        self.stats["vector_searches"] += 1
        return results

    async def _fulltext_search_only(
        self,
        query: str,
        top_k: int,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """$search 단독 실행(Sparse, BM25 full-text)."""
        pipeline: list[dict[str, Any]] = [
            {
                "$search": {
                    "index": self.fulltext_index_name,
                    "text": {"query": query, "path": "content"},
                }
            },
            {"$limit": top_k},
            {
                "$project": {
                    "_id": 1,
                    "content": 1,
                    "metadata": 1,
                    "score": {"$meta": "searchScore"},
                }
            },
        ]
        if filters:
            pipeline.insert(1, self._build_match_stage(filters))

        if self.collection is None:
            logger.error("Collection이 초기화되지 않음")
            return []

        cursor = await asyncio.to_thread(self.collection.aggregate, pipeline)
        results: list[dict[str, Any]] = await asyncio.to_thread(list, cursor)
        self.stats["fulltext_searches"] += 1
        return results

    @staticmethod
    def _build_match_stage(filters: dict[str, Any]) -> dict[str, Any]:
        """필터 dict를 중첩 메타데이터 경로 기반 $match 스테이지로 변환한다."""
        match: dict[str, Any] = {"$match": {}}
        for key, value in filters.items():
            match["$match"][f"metadata.metadata.{key}"] = value
        return match

    def _client_side_rank_fusion(
        self,
        vector_results: list[dict[str, Any]],
        fulltext_results: list[dict[str, Any]],
        top_k: int,
        k: int = 60,
    ) -> list[SearchResult]:
        """Client-side RRF(Reciprocal Rank Fusion)로 두 검색 결과를 통합한다.

        RRF 점수: score(doc) = Σ(weight_i / (k + rank_i))
        - 여러 검색에서 상위에 든 문서가 최종 상위로 올라간다.
        - dense_weight/sparse_weight가 각 분기의 기여도를 결정한다.

        Args:
            vector_results: $vectorSearch 결과.
            fulltext_results: $search 결과.
            top_k: 최종 반환 결과 수.
            k: RRF 상수(논문 기본값 60).

        Returns:
            RRF 점수 내림차순으로 정렬된 SearchResult 리스트.
        """
        doc_scores: dict[str, float] = {}
        doc_data: dict[str, dict[str, Any]] = {}

        for rank, doc in enumerate(vector_results, start=1):
            doc_id = str(doc["_id"])
            doc_scores[doc_id] = doc_scores.get(doc_id, 0.0) + self.dense_weight / (k + rank)
            doc_data[doc_id] = doc

        for rank, doc in enumerate(fulltext_results, start=1):
            doc_id = str(doc["_id"])
            doc_scores[doc_id] = doc_scores.get(doc_id, 0.0) + self.sparse_weight / (k + rank)
            doc_data.setdefault(doc_id, doc)

        sorted_doc_ids = sorted(doc_scores.items(), key=lambda x: x[1], reverse=True)[:top_k]

        results: list[SearchResult] = []
        for doc_id, score in sorted_doc_ids:
            doc = doc_data[doc_id]
            results.append(
                SearchResult(
                    id=doc_id,
                    content=doc.get("content", ""),
                    score=score,
                    metadata=doc.get("metadata", {}) or {},
                )
            )
        return results

    async def _vector_search_fallback(
        self,
        query: str,
        top_k: int,
        filters: dict[str, Any] | None = None,
    ) -> list[SearchResult]:
        """하이브리드 실패 시 Dense 검색만 수행하는 fallback.

        Returns:
            Dense 검색 결과 리스트. fallback 자체가 실패하면 빈 리스트.
        """
        try:
            logger.warning("Fallback: Vector search만 수행")
            query_embedding = await asyncio.to_thread(self.embedder.embed_query, query)
            raw_results = await self._vector_search_only(
                query_embedding=query_embedding, top_k=top_k, filters=filters
            )
            results = [
                SearchResult(
                    id=str(doc["_id"]),
                    content=doc.get("content", ""),
                    score=float(doc.get("score", 0.0)),
                    metadata=doc.get("metadata", {}) or {},
                )
                for doc in raw_results
            ]
            logger.info("Fallback vector search 완료: %s개 결과", len(results))
            return results
        except Exception as e:
            logger.error("Fallback vector search 실패: %s", str(e))
            return []
