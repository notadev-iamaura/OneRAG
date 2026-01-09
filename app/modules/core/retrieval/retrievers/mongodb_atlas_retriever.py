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
