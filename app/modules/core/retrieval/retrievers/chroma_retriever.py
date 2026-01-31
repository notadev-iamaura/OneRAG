"""
Chroma Retriever - Dense 및 하이브리드 벡터 검색

주요 기능:
- IRetriever 인터페이스 구현
- Dense 벡터 검색 기본 지원
- BM25 엔진 DI 주입 시 하이브리드 검색 지원 (Phase 1)
- ChromaVectorStore를 통한 검색 수행
- 쿼리 벡터화 → 유사도 검색 → (선택) BM25 병합 → SearchResult 변환

의존성:
- chromadb: pip install chromadb
- app.infrastructure.storage.vector.chroma_store: ChromaVectorStore
- app.modules.core.retrieval.interfaces: IRetriever, SearchResult
- (선택) kiwipiepy, rank-bm25: 하이브리드 검색 시 필요
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
    """벡터 스토어 인터페이스 (ChromaVectorStore용)"""

    async def search(
        self,
        collection: str,
        query_vector: list[float],
        top_k: int,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """벡터 유사도 검색"""
        ...


class ChromaRetriever:
    """
    Chroma 벡터 DB를 사용하는 Retriever (Dense + 선택적 하이브리드)

    특징:
    - Dense 벡터 검색 기본 지원
    - BM25 엔진 DI 주입 시 하이브리드 검색 자동 활성화
    - ChromaVectorStore를 통한 검색 수행
    - IRetriever Protocol 구현

    사용 예시:
        # Dense 전용 (기본)
        retriever = ChromaRetriever(embedder=embedder, store=store)

        # 하이브리드 검색 (BM25 엔진 DI 주입)
        retriever = ChromaRetriever(
            embedder=embedder, store=store,
            bm25_index=bm25_index, hybrid_merger=merger,
        )
    """

    def __init__(
        self,
        embedder: IEmbedder,
        store: IVectorStore,
        collection_name: str = "documents",
        top_k: int = 10,
        # Phase 1: BM25 엔진 DI 주입 (선택적)
        bm25_index: Any | None = None,
        hybrid_merger: Any | None = None,
    ) -> None:
        """
        ChromaRetriever 초기화

        Args:
            embedder: 쿼리 벡터화를 위한 임베딩 모델 (IEmbedder)
            store: ChromaVectorStore 인스턴스 (IVectorStore)
            collection_name: Chroma 컬렉션 이름 (기본값: "documents")
            top_k: 기본 검색 결과 수 (기본값: 10)
            bm25_index: BM25Index 인스턴스 (선택적, DI 주입)
            hybrid_merger: HybridMerger 인스턴스 (선택적, DI 주입)
        """
        self.embedder = embedder
        self.store = store
        self.collection_name = collection_name
        self.top_k = top_k

        # Phase 1: BM25 엔진 (선택적 DI)
        self._bm25_index = bm25_index
        self._hybrid_merger = hybrid_merger
        self._hybrid_enabled = bm25_index is not None and hybrid_merger is not None

        # 통계
        self._stats = {
            "total_searches": 0,
            "errors": 0,
        }

        logger.info(
            f"ChromaRetriever 초기화: collection={collection_name}, "
            f"top_k={top_k}, hybrid={'활성' if self._hybrid_enabled else '비활성'}"
        )

    async def search(
        self,
        query: str,
        top_k: int = 10,
        filters: dict[str, Any] | None = None,
    ) -> list[SearchResult]:
        """
        Dense 벡터 검색 수행

        검색 흐름:
        1. embedder로 쿼리 벡터화
        2. ChromaVectorStore에서 유사도 검색
        3. 결과를 SearchResult로 변환

        Args:
            query: 검색 쿼리 문자열
            top_k: 반환할 최대 결과 수
            filters: 메타데이터 필터링 조건 (예: {"file_type": "PDF"})

        Returns:
            검색 결과 리스트 (SearchResult)
                - id: 문서 ID
                - content: 문서 내용
                - score: 유사도 점수 (1 - distance)
                - metadata: 메타데이터 딕셔너리

        Raises:
            ValueError: 임베딩 생성 실패 시
            RuntimeError: 검색 실패 시
        """
        try:
            # 1. 쿼리 벡터화
            logger.debug(f"쿼리 임베딩 생성 중: '{query[:50]}...'")
            query_vector = self.embedder.embed_query(query)

            # 2. ChromaVectorStore에서 검색
            raw_results = await self.store.search(
                collection=self.collection_name,
                query_vector=query_vector,
                top_k=top_k,
                filters=filters,
            )

            # 3. SearchResult로 변환
            dense_results = self._convert_to_search_results(raw_results)

            # Phase 1: 하이브리드 검색 (BM25 엔진이 주입된 경우)
            if self._hybrid_enabled and self._bm25_index is not None and self._hybrid_merger is not None:
                bm25_results = self._bm25_index.search(query, top_k=top_k)
                merged: list[SearchResult] = self._hybrid_merger.merge(
                    dense_results=dense_results,
                    bm25_results=bm25_results,
                    top_k=top_k,
                )
                results = merged
            else:
                results = dense_results

            # 4. 통계 업데이트
            self._stats["total_searches"] += 1

            logger.info(
                f"ChromaRetriever 검색 완료: "
                f"{len(results)}개 결과 반환 "
                f"(query='{query[:30]}...', hybrid={self._hybrid_enabled})"
            )

            return results

        except Exception as e:
            self._stats["errors"] += 1
            logger.error(
                f"ChromaRetriever 검색 실패: {e}",
                extra={"query": query[:100]},
                exc_info=True,
            )
            raise

    async def health_check(self) -> bool:
        """
        Chroma 연결 상태 확인

        간단한 검색을 수행하여 store가 정상 동작하는지 확인합니다.

        Returns:
            정상 동작 여부 (True/False)
        """
        try:
            # 빈 벡터로 간단한 검색 시도
            # 실제 결과보다는 연결 확인이 목적
            dummy_vector = [0.0] * 768  # 기본 차원 (실제 차원과 다를 수 있음)

            await self.store.search(
                collection=self.collection_name,
                query_vector=dummy_vector,
                top_k=1,
            )

            logger.debug("ChromaRetriever health check 성공")
            return True

        except Exception as e:
            logger.warning(f"ChromaRetriever health check 실패: {e}")
            return False

    def _convert_to_search_results(
        self, raw_results: list[dict[str, Any]]
    ) -> list[SearchResult]:
        """
        ChromaVectorStore 결과를 SearchResult로 변환

        Chroma 결과 형식:
            {
                "_id": str,           # 문서 ID
                "_distance": float,   # 거리 (낮을수록 유사)
                "content": str,       # 문서 내용
                ...metadata...        # 기타 메타데이터
            }

        SearchResult 형식:
            - id: str              # 문서 ID
            - content: str         # 문서 내용
            - score: float         # 유사도 점수 (1 - distance)
            - metadata: dict       # 메타데이터

        Args:
            raw_results: ChromaVectorStore 검색 결과

        Returns:
            SearchResult 리스트
        """
        results: list[SearchResult] = []

        for item in raw_results:
            # ID 추출
            doc_id = str(item.get("_id", ""))

            # 콘텐츠 추출
            content = str(item.get("content", ""))

            # 거리를 점수로 변환 (1 - distance)
            # distance가 낮을수록 유사하므로 1에서 빼서 점수로 변환
            distance = float(item.get("_distance", 0.0))
            score = 1.0 - distance

            # 메타데이터 추출 (_id, _distance, content 제외)
            metadata: dict[str, Any] = {}
            for key, value in item.items():
                if key not in ("_id", "_distance", "content"):
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

    @property
    def stats(self) -> dict[str, int]:
        """검색 통계 반환"""
        return self._stats.copy()
