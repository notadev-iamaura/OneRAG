"""
VectorStore 기반 Retriever 공용 베이스
========================================
기능: Qdrant / Pinecone / pgvector Retriever가 공유하던 동일 흐름을 한 곳에 모은다.

- ``VectorStoreRetrieverBase``: Dense 검색 공통 흐름
  (``asyncio.to_thread`` 임베딩 → store.search → SearchResult 변환 → 통계),
  health check, 문서 관리 메서드(store 위임, duck typing)
- ``HybridVectorStoreRetrieverBase``: 위 베이스에 Sparse 벡터(하이브리드) 검색과
  BM25 전처리(동의어/불용어/사용자 사전)를 추가

설계 의도:
- 각 구현체는 provider별로 다른 것(컬렉션 속성 이름, health check 방식,
  health check 더미 벡터 차원)만 선언한다. 공개 클래스 이름·생성자 시그니처·
  동작은 이전과 동일하게 유지한다(회귀 0).
- 컬렉션 속성 이름은 provider마다 다르므로(``collection_name`` / ``namespace`` /
  ``table_name``) ``_collection_attr``로 선언하고 ``_collection`` 프로퍼티로 읽는다.
  속성 자체는 서브클래스 인스턴스에 그대로 존재하므로 외부에서 읽고 바꿀 수 있다.
"""

import asyncio
from typing import Any, ClassVar, Protocol, runtime_checkable

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
    """벡터 스토어 인터페이스 (Dense 검색용)"""

    async def search(
        self,
        collection: str,
        query_vector: list[float],
        top_k: int,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """벡터 유사도 검색"""
        ...


@runtime_checkable
class IHybridVectorStore(Protocol):
    """벡터 스토어 인터페이스 (Dense + Sparse 하이브리드 검색용)"""

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


class VectorStoreRetrieverBase:
    """
    VectorStore 기반 Dense Retriever 공용 베이스

    서브클래스는 다음을 선언한다:
    - ``_collection_attr``: 컬렉션 이름을 담는 인스턴스 속성 이름
    - ``_health_check_dimension``: health check 더미 벡터 차원 (기본 768)

    결과 변환은 ``{"_id", "_score", "content", ...metadata}`` 형식의 store 결과를
    ``SearchResult``로 바꾸는 공통 규약을 따른다.
    """

    # 컬렉션 이름을 담는 인스턴스 속성 이름 (provider별로 다름)
    _collection_attr: ClassVar[str] = "collection_name"
    # health check 더미 벡터 차원
    _health_check_dimension: ClassVar[int] = 768

    def __init__(
        self,
        embedder: IEmbedder,
        store: IVectorStore,
        collection: str,
        top_k: int,
    ) -> None:
        self.embedder = embedder
        self.store = store
        setattr(self, self._collection_attr, collection)
        self.top_k = top_k

        # 통계
        self._stats: dict[str, int] = {
            "total_searches": 0,
            "errors": 0,
        }

    @property
    def _collection(self) -> str:
        """store에 전달할 컬렉션/네임스페이스/테이블 이름"""
        return str(getattr(self, self._collection_attr))

    @property
    def stats(self) -> dict[str, int]:
        """검색 통계 반환"""
        return self._stats.copy()

    def _log_init(self, mode: str, **extra: Any) -> None:
        """초기화 로그 (provider 공통 포맷)"""
        suffix = "".join(f", {key}={value}" for key, value in extra.items())
        logger.info(
            f"{type(self).__name__} 초기화: {self._collection_attr}={self._collection}, "
            f"top_k={self.top_k}, mode={mode}{suffix}"
        )

    def _hybrid_search_kwargs(self, query: str, alpha: float | None) -> dict[str, Any]:
        """store.search에 추가로 전달할 하이브리드 인자 (Dense 전용은 없음)"""
        return {}

    async def search(
        self,
        query: str,
        top_k: int = 10,
        filters: dict[str, Any] | None = None,
        alpha: float | None = None,
    ) -> list[SearchResult]:
        """
        검색 수행

        검색 흐름:
        1. embedder로 쿼리 벡터화 (Dense, 원본 쿼리 - 의미 보존)
        2. (하이브리드) BM25 전처리 후 Sparse 벡터 생성
        3. VectorStore에서 검색
        4. 결과를 SearchResult로 변환

        Args:
            query: 검색 쿼리 문자열
            top_k: 반환할 최대 결과 수
            filters: 메타데이터 필터링 조건 (예: {"file_type": "PDF"})
            alpha: 하이브리드 가중치 동적 오버라이드(#35). Dense 전용 provider는 무시한다.

        Returns:
            검색 결과 리스트 (SearchResult)

        Raises:
            ValueError: 임베딩 생성 실패 시
            RuntimeError: 검색 실패 시
        """
        name = type(self).__name__
        try:
            # 1. Dense 쿼리 벡터화 (원본 쿼리 - 의미 보존)
            logger.debug(f"쿼리 임베딩 생성 중: '{query[:50]}...'")
            # 동기 임베딩(HTTP/CPU)을 to_thread로 오프로딩해 이벤트 루프 블로킹을 막는다.
            query_vector = await asyncio.to_thread(self.embedder.embed_query, query)

            # 2. (하이브리드) Sparse 벡터 생성
            extra_kwargs = self._hybrid_search_kwargs(query, alpha)

            # 3. VectorStore에서 검색
            raw_results = await self.store.search(
                collection=self._collection,
                query_vector=query_vector,
                top_k=top_k,
                filters=filters,
                **extra_kwargs,
            )

            # 4. SearchResult로 변환
            results = self._convert_to_search_results(raw_results)

            # 5. 통계 업데이트
            self._stats["total_searches"] += 1

            logger.info(
                f"{name} 검색 완료: {len(results)}개 결과 반환 (query='{query[:30]}...')"
            )

            return results

        except Exception as e:
            self._stats["errors"] += 1
            logger.error(
                f"{name} 검색 실패: {e}",
                extra={"query": query[:100]},
                exc_info=True,
            )
            raise

    async def health_check(self) -> bool:
        """
        연결 상태 확인

        더미 벡터로 간단한 검색을 수행하여 store가 정상 동작하는지 확인합니다.

        Returns:
            정상 동작 여부 (True/False)
        """
        name = type(self).__name__
        try:
            # 빈 벡터로 간단한 검색 시도
            dummy_vector = [0.0] * self._health_check_dimension

            await self.store.search(
                collection=self._collection,
                query_vector=dummy_vector,
                top_k=1,
            )

            logger.debug(f"{name} health check 성공")
            return True

        except Exception as e:
            logger.warning(f"{name} health check 실패: {e}")
            return False

    # ============================================================
    # 문서 관리 메서드 (Store 위임, duck typing)
    # ============================================================

    def _unsupported(self, method_name: str) -> NotImplementedError:
        """store가 필요한 메서드를 지원하지 않을 때의 예외 생성"""
        return NotImplementedError(
            f"{type(self).__name__}의 store는 {method_name}를 지원하지 않습니다."
        )

    async def _fetch_all_objects(self) -> list[dict[str, Any]]:
        """컬렉션의 모든 객체 조회 (store.fetch_objects 위임)"""
        if not hasattr(self.store, "fetch_objects"):
            raise self._unsupported("fetch_objects")
        result: list[dict[str, Any]] = await self.store.fetch_objects(collection=self._collection)
        return result

    @staticmethod
    def _build_document_map(raw_results: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        """청크 목록을 document_id 기준 문서 요약 맵으로 집계"""
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
        return doc_map

    async def get_document_chunks(self, document_id: str) -> list[dict[str, Any]]:
        """document_id로 모든 청크 조회"""
        if not hasattr(self.store, "fetch_objects"):
            raise self._unsupported("fetch_objects")
        raw_results = await self.store.fetch_objects(
            collection=self._collection,
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
            raise self._unsupported("delete_objects")
        await self.store.delete_objects(
            collection=self._collection, object_ids=object_ids,
        )
        logger.info(f"문서 삭제 완료: document_id={document_id}, 청크 {len(object_ids)}개")
        return True

    async def list_documents(self, page: int = 1, page_size: int = 20) -> dict[str, Any]:
        """고유 문서 목록 페이지네이션 조회"""
        raw_results = await self._fetch_all_objects()
        all_docs = list(self._build_document_map(raw_results).values())
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
        raw_results = await self._fetch_all_objects()
        doc_ids = {r.get("document_id", r.get("_id", "")) for r in raw_results}
        return {"total_documents": len(doc_ids), "vector_count": len(raw_results)}

    async def get_collection_info(self) -> dict[str, Any]:
        """컬렉션 메타정보 반환"""
        raw_results = await self._fetch_all_objects()
        dates = [r.get("created_at", "") for r in raw_results if r.get("created_at")]
        return {
            "collection_name": self._collection,
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
        raw_results = await self.store.fetch_objects(collection=self._collection)
        if not raw_results:
            return True
        object_ids = [str(r.get("_id", "")) for r in raw_results]
        await self.store.delete_objects(collection=self._collection, object_ids=object_ids)
        logger.warning(f"전체 문서 삭제 완료: {len(object_ids)}개 객체")
        return True

    async def recreate_collection(self) -> bool:
        """컬렉션 재생성"""
        await self.delete_all_documents()
        return True

    async def backup_metadata(self) -> list[dict[str, Any]]:
        """모든 문서의 메타데이터를 백업"""
        raw_results = await self._fetch_all_objects()
        return list(self._build_document_map(raw_results).values())

    def _convert_to_search_results(
        self, raw_results: list[dict[str, Any]]
    ) -> list[SearchResult]:
        """
        store 결과를 SearchResult로 변환

        store 결과 형식:
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
            - metadata: dict       # 메타데이터 (_id, _score, content 제외)

        Args:
            raw_results: VectorStore 검색 결과

        Returns:
            SearchResult 리스트
        """
        results: list[SearchResult] = []

        for item in raw_results:
            doc_id = str(item.get("_id", ""))
            content = str(item.get("content", ""))
            score = float(item.get("_score", 0.0))

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


class HybridVectorStoreRetrieverBase(VectorStoreRetrieverBase):
    """
    VectorStore 기반 하이브리드(Dense + Sparse) Retriever 공용 베이스

    하이브리드 검색:
    - hybrid_alpha: 0.0 (Sparse만) ~ 1.0 (Dense만)
    - alpha < 1.0 이고 Sparse 인코더가 준비된 경우에만 Sparse 벡터를 생성한다.
    - Sparse 벡터 생성 전에 BM25 전처리(사용자 사전 보호 → 동의어 확장 →
      불용어 제거 → 사용자 사전 복원)를 적용한다. Dense 임베딩은 원본 쿼리를 쓴다.
    """

    store: IHybridVectorStore

    def __init__(
        self,
        embedder: IEmbedder,
        store: IHybridVectorStore,
        collection: str,
        top_k: int,
        hybrid_alpha: float,
        synonym_manager: Any | None,
        stopword_filter: Any | None,
        user_dictionary: Any | None,
    ) -> None:
        super().__init__(embedder=embedder, store=store, collection=collection, top_k=top_k)
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

        # 하이브리드 통계 항목 추가
        self._stats.update({"hybrid_searches": 0, "bm25_preprocessed": 0})

        bm25_status = "enabled" if self._bm25_preprocessing_enabled else "disabled"
        search_mode = "hybrid" if hybrid_alpha < 1.0 else "dense_only"
        self._log_init(search_mode, alpha=hybrid_alpha, bm25_preprocessing=bm25_status)

    def _hybrid_search_kwargs(self, query: str, alpha: float | None) -> dict[str, Any]:
        """
        Sparse 벡터 생성 (하이브리드 모드)

        alpha 오버라이드(#35)가 없으면 인스턴스 기본 hybrid_alpha를 사용한다.
        alpha<1.0이면 Sparse(BM25) 벡터를 생성해 하이브리드 검색을 수행한다
        (lexical 질의에서 낮은 alpha → BM25 강화).
        """
        effective_alpha = alpha if alpha is not None else self.hybrid_alpha

        sparse_vector = None
        if effective_alpha < 1.0 and self._sparse_encoder is not None:
            # BM25 전처리 적용
            processed_query = self._preprocess_query(query)
            sparse_vector = self._sparse_encoder.encode(processed_query)
            self._stats["hybrid_searches"] += 1

        return {"sparse_vector": sparse_vector}

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
