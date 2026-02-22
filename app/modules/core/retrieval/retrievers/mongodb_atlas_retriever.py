"""
MongoDBAtlasRetriever - MongoDB Atlas 벡터 검색 Retriever

주요 기능:
- Dense 검색 전용 (MongoDB Atlas Vector Search 활용)
- 하이브리드 검색 미지원
- 클라우드 관리형 벡터 데이터베이스

Note:
    MongoDB Atlas는 기본적으로 Dense 전용 검색입니다.
    Sparse(BM25) 하이브리드 검색이 필요하면 Weaviate나 Qdrant를 권장합니다.
"""

from dataclasses import dataclass, field
from typing import Any, Protocol

from app.lib.logger import get_logger

logger = get_logger(__name__)


# ============================================================
# 프로토콜 정의 (의존성 역전)
# ============================================================


class IEmbedder(Protocol):
    """임베딩 모델 인터페이스"""

    def embed_query(self, text: str) -> list[float]:
        """텍스트를 벡터로 변환"""
        ...


class IMongoDBAtlasStore(Protocol):
    """MongoDB Atlas Store 인터페이스"""

    async def search(
        self,
        collection: str,
        query_vector: list[float],
        top_k: int,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """벡터 검색 수행"""
        ...


# ============================================================
# 검색 결과 데이터 클래스
# ============================================================


@dataclass
class SearchResult:
    """검색 결과 표준 형식"""

    id: str
    content: str
    score: float
    metadata: dict[str, Any] = field(default_factory=dict)


# ============================================================
# MongoDBAtlasRetriever 구현
# ============================================================


class MongoDBAtlasRetriever:
    """
    MongoDB Atlas 벡터 검색 Retriever

    MongoDB Atlas 특징:
    - 클라우드 관리형 벡터 데이터베이스
    - Atlas Vector Search로 ANN 검색
    - Dense 검색 전용 (하이브리드 미지원)

    사용 예시:
        retriever = MongoDBAtlasRetriever(
            embedder=embedding_model,
            store=mongodb_atlas_store,
            collection_name="documents",
            top_k=10
        )

        results = await retriever.search("검색 쿼리")
    """

    def __init__(
        self,
        embedder: IEmbedder,
        store: IMongoDBAtlasStore,
        collection_name: str = "documents",
        top_k: int = 10,
    ) -> None:
        """
        MongoDBAtlasRetriever 초기화

        Args:
            embedder: 임베딩 모델 인스턴스
            store: MongoDB Atlas Store 인스턴스
            collection_name: 검색할 컬렉션 이름 (기본값: "documents")
            top_k: 기본 반환 결과 수 (기본값: 10)
        """
        self._embedder = embedder
        self._store = store
        self._collection_name = collection_name
        self._top_k = top_k

        # 통계
        self._stats = {
            "total_searches": 0,
            "errors": 0,
        }

        logger.info(
            f"MongoDBAtlasRetriever 초기화: collection={collection_name}, "
            f"top_k={top_k}"
        )

    @property
    def collection_name(self) -> str:
        """컬렉션 이름 반환"""
        return self._collection_name

    @property
    def top_k(self) -> int:
        """기본 top_k 반환"""
        return self._top_k

    @property
    def stats(self) -> dict[str, int]:
        """통계 정보 반환"""
        return self._stats.copy()

    async def search(
        self,
        query: str,
        top_k: int | None = None,
        filters: dict[str, Any] | None = None,
    ) -> list[SearchResult]:
        """
        Dense 벡터 검색 수행

        MongoDB Atlas는 Dense 검색만 지원합니다.

        Args:
            query: 검색 쿼리 텍스트
            top_k: 반환할 결과 수 (None이면 기본값 사용)
            filters: 메타데이터 필터 조건 (선택)

        Returns:
            SearchResult 리스트 (score 내림차순)

        Raises:
            Exception: 검색 실패 시
        """
        effective_top_k = top_k or self._top_k

        try:
            # 1. 쿼리 임베딩
            query_vector = self._embedder.embed_query(query)

            # 2. MongoDB Atlas 검색 수행
            raw_results = await self._store.search(
                collection=self._collection_name,
                query_vector=query_vector,
                top_k=effective_top_k,
                filters=filters,
            )

            # 3. 결과 변환
            results = self._convert_to_search_results(raw_results)

            self._stats["total_searches"] += 1

            logger.debug(
                f"MongoDB Atlas 검색 완료: query='{query[:30]}...', "
                f"results={len(results)}"
            )

            return results

        except Exception as e:
            self._stats["errors"] += 1
            logger.error(f"MongoDB Atlas 검색 실패: {e}")
            raise

    async def health_check(self) -> bool:
        """
        MongoDB Atlas 연결 상태 확인

        Returns:
            연결 정상 여부 (True/False)
        """
        try:
            # 더미 검색으로 연결 테스트
            test_vector = self._embedder.embed_query("health check")
            await self._store.search(
                collection=self._collection_name,
                query_vector=test_vector,
                top_k=1,
            )
            return True

        except Exception as e:
            logger.warning(f"MongoDB Atlas health check 실패: {e}")
            return False

    # ============================================================
    # 문서 관리 메서드 (Store 위임, duck typing)
    # ============================================================

    async def get_document_chunks(self, document_id: str) -> list[dict[str, Any]]:
        """document_id로 모든 청크 조회"""
        if not hasattr(self._store, "fetch_objects"):
            raise NotImplementedError(
                f"{type(self).__name__}의 store는 fetch_objects를 지원하지 않습니다."
            )
        raw_results = await self._store.fetch_objects(
            collection=self._collection_name,
            filters={"document_id": document_id},
        )
        return [
            {
                "id": str(r.get("_id", "")),
                "content": r.get("content", ""),
                "metadata": {k: v for k, v in r.items() if k not in ("_id", "content")},
            }
            for r in raw_results
        ]

    async def delete_document(self, document_id: str) -> bool:
        """document_id의 모든 청크 삭제"""
        chunks = await self.get_document_chunks(document_id)
        if not chunks:
            return False
        object_ids = [c["id"] for c in chunks]
        if not hasattr(self._store, "delete_objects"):
            raise NotImplementedError(
                f"{type(self).__name__}의 store는 delete_objects를 지원하지 않습니다."
            )
        await self._store.delete_objects(
            collection=self._collection_name, object_ids=object_ids,
        )
        logger.info(f"문서 삭제 완료: document_id={document_id}, 청크 {len(object_ids)}개")
        return True

    async def list_documents(self, page: int = 1, page_size: int = 20) -> dict[str, Any]:
        """고유 문서 목록 페이지네이션 조회"""
        if not hasattr(self._store, "fetch_objects"):
            raise NotImplementedError(
                f"{type(self).__name__}의 store는 fetch_objects를 지원하지 않습니다."
            )
        raw_results = await self._store.fetch_objects(collection=self._collection_name)
        doc_map: dict[str, dict[str, Any]] = {}
        for r in raw_results:
            doc_id = r.get("document_id", r.get("_id", ""))
            if doc_id not in doc_map:
                doc_map[doc_id] = {
                    "id": doc_id,
                    "filename": r.get("source_file", ""),
                    "file_type": r.get("file_type", ""),
                    "created_at": r.get("created_at", ""),
                    "chunk_count": 0,
                }
            doc_map[doc_id]["chunk_count"] += 1
        all_docs = list(doc_map.values())
        total = len(all_docs)
        start = (page - 1) * page_size
        end = start + page_size
        return {"documents": all_docs[start:end], "total_count": total}

    async def get_document_details(self, document_id: str) -> dict[str, Any] | None:
        """문서 상세 정보 조회"""
        chunks = await self.get_document_chunks(document_id)
        if not chunks:
            return None
        first = chunks[0]["metadata"]
        total_size = sum(len(c.get("content", "").encode("utf-8")) for c in chunks)
        return {
            "id": document_id,
            "filename": first.get("source_file", ""),
            "file_type": first.get("file_type", ""),
            "file_size": total_size,
            "created_at": first.get("created_at", ""),
            "actual_chunk_count": len(chunks),
            "chunk_previews": [c["content"][:200] for c in chunks],
            "metadata": first,
        }

    async def get_document_stats(self) -> dict[str, Any]:
        """문서/벡터 수량 통계"""
        if not hasattr(self._store, "fetch_objects"):
            raise NotImplementedError(
                f"{type(self).__name__}의 store는 fetch_objects를 지원하지 않습니다."
            )
        raw_results = await self._store.fetch_objects(collection=self._collection_name)
        doc_ids = {r.get("document_id", r.get("_id", "")) for r in raw_results}
        return {"total_documents": len(doc_ids), "vector_count": len(raw_results)}

    async def get_collection_info(self) -> dict[str, Any]:
        """컬렉션 메타정보 반환"""
        if not hasattr(self._store, "fetch_objects"):
            raise NotImplementedError(
                f"{type(self).__name__}의 store는 fetch_objects를 지원하지 않습니다."
            )
        raw_results = await self._store.fetch_objects(collection=self._collection_name)
        dates = [r.get("created_at", "") for r in raw_results if r.get("created_at")]
        return {
            "collection_name": self._collection_name,
            "total_objects": len(raw_results),
            "oldest_document": min(dates) if dates else None,
            "newest_document": max(dates) if dates else None,
        }

    async def delete_all_documents(self) -> bool:
        """전체 문서 삭제"""
        if not hasattr(self._store, "fetch_objects") or not hasattr(self._store, "delete_objects"):
            raise NotImplementedError(
                f"{type(self).__name__}의 store는 전체 삭제를 지원하지 않습니다."
            )
        raw_results = await self._store.fetch_objects(collection=self._collection_name)
        if not raw_results:
            return True
        object_ids = [str(r.get("_id", "")) for r in raw_results]
        await self._store.delete_objects(
            collection=self._collection_name, object_ids=object_ids,
        )
        logger.warning(f"전체 문서 삭제 완료: {len(object_ids)}개 객체")
        return True

    async def recreate_collection(self) -> bool:
        """컬렉션 재생성"""
        await self.delete_all_documents()
        return True

    async def backup_metadata(self) -> list[dict[str, Any]]:
        """모든 문서의 메타데이터를 백업"""
        if not hasattr(self._store, "fetch_objects"):
            raise NotImplementedError(
                f"{type(self).__name__}의 store는 fetch_objects를 지원하지 않습니다."
            )
        raw_results = await self._store.fetch_objects(collection=self._collection_name)
        doc_map: dict[str, dict[str, Any]] = {}
        for r in raw_results:
            doc_id = r.get("document_id", r.get("_id", ""))
            if doc_id not in doc_map:
                doc_map[doc_id] = {
                    "id": doc_id,
                    "filename": r.get("source_file", ""),
                    "file_type": r.get("file_type", ""),
                    "created_at": r.get("created_at", ""),
                    "chunk_count": 0,
                }
            doc_map[doc_id]["chunk_count"] += 1
        return list(doc_map.values())

    def _convert_to_search_results(
        self, raw_results: list[dict[str, Any]]
    ) -> list[SearchResult]:
        """
        MongoDB Atlas 검색 결과를 SearchResult로 변환

        Args:
            raw_results: MongoDB Atlas 원본 검색 결과

        Returns:
            SearchResult 리스트
        """
        results = []

        for doc in raw_results:
            # ID 추출
            doc_id = str(doc.get("_id", ""))

            # 점수 추출
            score = float(doc.get("_score", 0.0))

            # 콘텐츠 추출
            content = doc.get("content", "")

            # 메타데이터 구성 (예약 필드 제외)
            metadata = {
                k: v
                for k, v in doc.items()
                if k not in ("_id", "_score", "content")
            }

            results.append(
                SearchResult(
                    id=doc_id,
                    content=content,
                    score=score,
                    metadata=metadata,
                )
            )

        return results
