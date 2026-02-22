"""
Qdrant Retriever - 하이브리드 검색 (Dense + Sparse)

주요 기능:
- IRetriever 인터페이스 구현
- Dense 벡터 검색 지원
- 하이브리드 검색 지원 (Sparse Vector)
- BM25 전처리 모듈 통합 (동의어 확장, 불용어 제거, 사용자 사전)
- 쿼리 벡터화 → 유사도 검색 → SearchResult 변환

의존성:
- qdrant-client: pip install qdrant-client (선택적)
- app.infrastructure.storage.vector.qdrant_store: QdrantVectorStore
- app.modules.core.retrieval.interfaces: IRetriever, SearchResult

Note:
    Qdrant는 Full-Text 검색을 통한 하이브리드 검색을 지원합니다.
    hybrid_alpha 파라미터로 Dense/Sparse 가중치를 조절할 수 있습니다.
"""

from typing import Any, Protocol, runtime_checkable

from app.lib.logger import get_logger
from app.modules.core.retrieval.interfaces import SearchResult

logger = get_logger(__name__)


@runtime_checkable
class IEmbedder(Protocol):
    """임베딩 모델 인터페이스"""

    def embed_query(self, text: str) -> list[float]:
        """쿼리 텍스트를 벡터로 변환"""
        ...


@runtime_checkable
class IVectorStore(Protocol):
    """벡터 스토어 인터페이스 (QdrantVectorStore용)"""

    async def search(
        self,
        collection: str,
        query_vector: list[float],
        top_k: int,
        filters: dict[str, Any] | None = None,
        sparse_vector: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """벡터 유사도 검색"""
        ...


class QdrantRetriever:
    """
    Qdrant 벡터 DB를 사용하는 하이브리드 Retriever

    특징:
    - Dense 벡터 검색 지원
    - 하이브리드 검색 지원 (Sparse Vector via hybrid_alpha)
    - BM25 전처리 모듈 통합 (동의어, 불용어, 사용자 사전)
    - QdrantVectorStore를 통한 검색 수행
    - IRetriever Protocol 구현

    하이브리드 검색:
    - hybrid_alpha: 0.0 (Sparse만) ~ 1.0 (Dense만)
    - 기본값 0.6 = 60% Dense + 40% Sparse

    사용 예시:
        retriever = QdrantRetriever(
            embedder=gemini_embedder,
            store=qdrant_store,
            collection_name="documents",
            top_k=10,
            hybrid_alpha=0.6,
        )
        results = await retriever.search("검색 쿼리")
    """

    def __init__(
        self,
        embedder: IEmbedder,
        store: IVectorStore,
        collection_name: str = "documents",
        top_k: int = 10,
        hybrid_alpha: float = 0.6,
        # BM25 전처리 모듈 (Optional)
        synonym_manager: Any | None = None,
        stopword_filter: Any | None = None,
        user_dictionary: Any | None = None,
    ) -> None:
        """
        QdrantRetriever 초기화

        Args:
            embedder: 쿼리 벡터화를 위한 임베딩 모델 (IEmbedder)
            store: QdrantVectorStore 인스턴스 (IVectorStore)
            collection_name: Qdrant 컬렉션 이름 (기본값: "documents")
            top_k: 기본 검색 결과 수 (기본값: 10)
            hybrid_alpha: 하이브리드 가중치 (기본값: 0.6)
                - 1.0: Dense만 사용
                - 0.0: Sparse만 사용
                - 0.6: 60% Dense + 40% Sparse (권장)
            synonym_manager: 동의어 관리자 (Optional, BM25 전처리용)
            stopword_filter: 불용어 필터 (Optional, BM25 전처리용)
            user_dictionary: 사용자 사전 (Optional, BM25 전처리용)

        Note:
            하이브리드 검색을 사용하려면 Qdrant 컬렉션이
            Full-Text 인덱스로 설정되어 있어야 합니다.
        """
        self.embedder = embedder
        self.store = store
        self.collection_name = collection_name
        self.top_k = top_k
        self.hybrid_alpha = hybrid_alpha

        # BM25 전처리 모듈
        self.synonym_manager = synonym_manager
        self.stopword_filter = stopword_filter
        self.user_dictionary = user_dictionary

        # BM25 전처리 활성화 여부
        self._bm25_preprocessing_enabled = any(
            [synonym_manager is not None, stopword_filter is not None, user_dictionary is not None]
        )

        # Sparse 인코더 (하이브리드 검색용, 지연 초기화)
        self._sparse_encoder: Any | None = None

        # 통계
        self._stats = {
            "total_searches": 0,
            "hybrid_searches": 0,
            "errors": 0,
            "bm25_preprocessed": 0,
        }

        # 로그 메시지 구성
        bm25_status = "enabled" if self._bm25_preprocessing_enabled else "disabled"
        search_mode = "hybrid" if hybrid_alpha < 1.0 else "dense_only"
        logger.info(
            f"QdrantRetriever 초기화: collection={collection_name}, "
            f"top_k={top_k}, alpha={hybrid_alpha}, mode={search_mode}, "
            f"bm25_preprocessing={bm25_status}"
        )

    @property
    def stats(self) -> dict[str, int]:
        """검색 통계 반환"""
        return self._stats.copy()

    async def search(
        self,
        query: str,
        top_k: int = 10,
        filters: dict[str, Any] | None = None,
    ) -> list[SearchResult]:
        """
        하이브리드/Dense 검색 수행

        검색 흐름:
        1. embedder로 쿼리 벡터화 (Dense)
        2. BM25 전처리 후 Sparse 벡터 생성 (하이브리드 모드 시)
        3. QdrantVectorStore에서 검색
        4. 결과를 SearchResult로 변환

        Args:
            query: 검색 쿼리 문자열
            top_k: 반환할 최대 결과 수
            filters: 메타데이터 필터링 조건 (예: {"file_type": "PDF"})

        Returns:
            검색 결과 리스트 (SearchResult)
                - id: 문서 ID
                - content: 문서 내용
                - score: 유사도 점수
                - metadata: 메타데이터 딕셔너리

        Raises:
            ValueError: 임베딩 생성 실패 시
            RuntimeError: 검색 실패 시
        """
        try:
            # 1. Dense 쿼리 벡터화 (원본 쿼리 - 의미 보존)
            logger.debug(f"쿼리 임베딩 생성 중: '{query[:50]}...'")
            query_vector = self.embedder.embed_query(query)

            # 2. Sparse 벡터 생성 (하이브리드 모드)
            sparse_vector = None
            if self.hybrid_alpha < 1.0 and self._sparse_encoder is not None:
                # BM25 전처리 적용
                processed_query = self._preprocess_query(query)
                sparse_vector = self._sparse_encoder.encode(processed_query)
                self._stats["hybrid_searches"] += 1

            # 3. QdrantVectorStore에서 검색
            raw_results = await self.store.search(
                collection=self.collection_name,
                query_vector=query_vector,
                top_k=top_k,
                filters=filters,
                sparse_vector=sparse_vector,
            )

            # 4. SearchResult로 변환
            results = self._convert_to_search_results(raw_results)

            # 5. 통계 업데이트
            self._stats["total_searches"] += 1

            logger.info(
                f"QdrantRetriever 검색 완료: "
                f"{len(results)}개 결과 반환 (query='{query[:30]}...')"
            )

            return results

        except Exception as e:
            self._stats["errors"] += 1
            logger.error(
                f"QdrantRetriever 검색 실패: {e}",
                extra={"query": query[:100]},
                exc_info=True,
            )
            raise

    async def health_check(self) -> bool:
        """
        Qdrant 연결 상태 확인

        간단한 검색을 수행하여 store가 정상 동작하는지 확인합니다.

        Returns:
            정상 동작 여부 (True/False)
        """
        try:
            # 빈 벡터로 간단한 검색 시도
            dummy_vector = [0.0] * 768  # 기본 차원

            await self.store.search(
                collection=self.collection_name,
                query_vector=dummy_vector,
                top_k=1,
            )

            logger.debug("QdrantRetriever health check 성공")
            return True

        except Exception as e:
            logger.warning(f"QdrantRetriever health check 실패: {e}")
            return False

    def _preprocess_query(self, query: str) -> str:
        """
        BM25 검색을 위한 쿼리 전처리

        전처리 파이프라인:
        1. 사용자 사전 - 합성어 보호 (분리 방지)
        2. 동의어 확장 (축약어 → 표준어)
        3. 불용어 제거
        4. 사용자 사전 - 합성어 복원

        Args:
            query: 원본 검색 쿼리

        Returns:
            전처리된 쿼리 (Sparse 벡터 생성용)

        Note:
            - Dense embedding은 원본 쿼리 사용 (의미 보존)
            - Sparse 벡터만 전처리된 쿼리 사용 (키워드 매칭 향상)
        """
        if not self._bm25_preprocessing_enabled:
            return query

        processed = query
        restore_map: dict[str, str] = {}

        try:
            # Step 1: 사용자 사전 - 합성어 보호
            if self.user_dictionary is not None:
                processed, restore_map = self.user_dictionary.protect_entries(processed)

            # Step 2: 동의어 확장
            if self.synonym_manager is not None:
                processed = self.synonym_manager.expand_query(processed)

            # Step 3: 불용어 제거
            if self.stopword_filter is not None:
                processed = self.stopword_filter.filter_text(processed)

            # Step 4: 사용자 사전 - 합성어 복원
            if self.user_dictionary is not None and restore_map:
                processed = self.user_dictionary.restore_entries(processed, restore_map)

            # 전처리 결과 로깅 (변경 시에만)
            if processed != query:
                self._stats["bm25_preprocessed"] += 1
                logger.debug(f"BM25 쿼리 전처리: '{query}' → '{processed}'")

        except Exception as e:
            # 전처리 실패 시 원본 쿼리 사용 (Graceful Degradation)
            logger.warning(
                f"BM25 쿼리 전처리 실패, 원본 사용: {str(e)}", extra={"query": query[:100]}
            )
            return query

        return processed

    # ============================================================
    # 문서 관리 메서드 (Store 위임, duck typing)
    # ============================================================

    async def get_document_chunks(self, document_id: str) -> list[dict[str, Any]]:
        """document_id로 모든 청크 조회"""
        if not hasattr(self.store, "fetch_objects"):
            raise NotImplementedError(
                f"{type(self).__name__}의 store는 fetch_objects를 지원하지 않습니다."
            )
        raw_results = await self.store.fetch_objects(
            collection=self.collection_name,
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
        if not hasattr(self.store, "delete_objects"):
            raise NotImplementedError(
                f"{type(self).__name__}의 store는 delete_objects를 지원하지 않습니다."
            )
        await self.store.delete_objects(
            collection=self.collection_name, object_ids=object_ids,
        )
        logger.info(f"문서 삭제 완료: document_id={document_id}, 청크 {len(object_ids)}개")
        return True

    async def list_documents(self, page: int = 1, page_size: int = 20) -> dict[str, Any]:
        """고유 문서 목록 페이지네이션 조회"""
        if not hasattr(self.store, "fetch_objects"):
            raise NotImplementedError(
                f"{type(self).__name__}의 store는 fetch_objects를 지원하지 않습니다."
            )
        raw_results = await self.store.fetch_objects(collection=self.collection_name)
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
        if not hasattr(self.store, "fetch_objects"):
            raise NotImplementedError(
                f"{type(self).__name__}의 store는 fetch_objects를 지원하지 않습니다."
            )
        raw_results = await self.store.fetch_objects(collection=self.collection_name)
        doc_ids = {r.get("document_id", r.get("_id", "")) for r in raw_results}
        return {"total_documents": len(doc_ids), "vector_count": len(raw_results)}

    async def get_collection_info(self) -> dict[str, Any]:
        """컬렉션 메타정보 반환"""
        if not hasattr(self.store, "fetch_objects"):
            raise NotImplementedError(
                f"{type(self).__name__}의 store는 fetch_objects를 지원하지 않습니다."
            )
        raw_results = await self.store.fetch_objects(collection=self.collection_name)
        dates = [r.get("created_at", "") for r in raw_results if r.get("created_at")]
        return {
            "collection_name": self.collection_name,
            "total_objects": len(raw_results),
            "oldest_document": min(dates) if dates else None,
            "newest_document": max(dates) if dates else None,
        }

    async def delete_all_documents(self) -> bool:
        """전체 문서 삭제"""
        if not hasattr(self.store, "fetch_objects") or not hasattr(self.store, "delete_objects"):
            raise NotImplementedError(
                f"{type(self).__name__}의 store는 전체 삭제를 지원하지 않습니다."
            )
        raw_results = await self.store.fetch_objects(collection=self.collection_name)
        if not raw_results:
            return True
        object_ids = [str(r.get("_id", "")) for r in raw_results]
        await self.store.delete_objects(collection=self.collection_name, object_ids=object_ids)
        logger.warning(f"전체 문서 삭제 완료: {len(object_ids)}개 객체")
        return True

    async def recreate_collection(self) -> bool:
        """컬렉션 재생성"""
        await self.delete_all_documents()
        return True

    async def backup_metadata(self) -> list[dict[str, Any]]:
        """모든 문서의 메타데이터를 백업"""
        if not hasattr(self.store, "fetch_objects"):
            raise NotImplementedError(
                f"{type(self).__name__}의 store는 fetch_objects를 지원하지 않습니다."
            )
        raw_results = await self.store.fetch_objects(collection=self.collection_name)
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
        Qdrant 결과를 SearchResult로 변환

        Qdrant 결과 형식:
            {
                "_id": str,           # 벡터 ID
                "_score": float,      # 유사도 점수
                "content": str,       # 문서 내용
                ...metadata...        # 기타 메타데이터
            }

        SearchResult 형식:
            - id: str              # 문서 ID
            - content: str         # 문서 내용
            - score: float         # 유사도 점수
            - metadata: dict       # 메타데이터

        Args:
            raw_results: QdrantVectorStore 검색 결과

        Returns:
            SearchResult 리스트
        """
        results: list[SearchResult] = []

        for item in raw_results:
            # ID 추출
            doc_id = str(item.get("_id", ""))

            # 콘텐츠 추출
            content = str(item.get("content", ""))

            # 점수 추출
            score = float(item.get("_score", 0.0))

            # 메타데이터 추출 (_id, _score, content 제외)
            metadata: dict[str, Any] = {}
            for key, value in item.items():
                if key not in ("_id", "_score", "content"):
                    metadata[key] = value

            results.append(
                SearchResult(
                    id=doc_id,
                    content=content,
                    score=score,
                    metadata=metadata,
                )
            )

        return results
