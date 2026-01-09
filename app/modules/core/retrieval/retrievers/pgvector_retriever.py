"""
pgvector Retriever - Dense 벡터 검색

주요 기능:
- IRetriever 인터페이스 구현
- Dense 벡터 검색 전용 (하이브리드 미지원)
- PostgreSQL 기반 안정적인 벡터 검색
- 쿼리 벡터화 → 유사도 검색 → SearchResult 변환

의존성:
- psycopg[binary]: pip install "psycopg[binary]" (선택적)
- app.infrastructure.storage.vector.pgvector_store: PgVectorStore
- app.modules.core.retrieval.interfaces: IRetriever, SearchResult

Note:
    pgvector는 기본적으로 Dense 벡터 검색만 지원합니다.
    하이브리드 검색이 필요한 경우 Weaviate, Pinecone, Qdrant를 사용하세요.
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
    """벡터 스토어 인터페이스 (PgVectorStore용)"""

    async def search(
        self,
        collection: str,
        query_vector: list[float],
        top_k: int,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """벡터 유사도 검색"""
        ...


class PgVectorRetriever:
    """
    pgvector를 사용하는 Dense Retriever

    특징:
    - Dense 벡터 검색 전용
    - PostgreSQL 기반 안정적인 검색
    - PgVectorStore를 통한 검색 수행
    - IRetriever Protocol 구현

    Note:
    - 하이브리드 검색 미지원 (Dense only)
    - 하이브리드 필요 시 Weaviate, Pinecone, Qdrant 사용 권장

    사용 예시:
        retriever = PgVectorRetriever(
            embedder=gemini_embedder,
            store=pgvector_store,
            table_name="documents",
            top_k=10,
        )
        results = await retriever.search("검색 쿼리")
    """

    def __init__(
        self,
        embedder: IEmbedder,
        store: IVectorStore,
        table_name: str = "documents",
        top_k: int = 10,
    ) -> None:
        """
        PgVectorRetriever 초기화

        Args:
            embedder: 쿼리 벡터화를 위한 임베딩 모델 (IEmbedder)
            store: PgVectorStore 인스턴스 (IVectorStore)
            table_name: PostgreSQL 테이블 이름 (기본값: "documents")
            top_k: 기본 검색 결과 수 (기본값: 10)

        Note:
            pgvector는 Dense 검색만 지원합니다.
        """
        self.embedder = embedder
        self.store = store
        self.table_name = table_name
        self.top_k = top_k

        # 통계
        self._stats = {
            "total_searches": 0,
            "errors": 0,
        }

        logger.info(
            f"PgVectorRetriever 초기화: table={table_name}, "
            f"top_k={top_k}, mode=dense_only"
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
        Dense 벡터 검색 수행

        검색 흐름:
        1. embedder로 쿼리 벡터화
        2. PgVectorStore에서 검색
        3. 결과를 SearchResult로 변환

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
            # 1. Dense 쿼리 벡터화
            logger.debug(f"쿼리 임베딩 생성 중: '{query[:50]}...'")
            query_vector = self.embedder.embed_query(query)

            # 2. PgVectorStore에서 검색
            raw_results = await self.store.search(
                collection=self.table_name,
                query_vector=query_vector,
                top_k=top_k,
                filters=filters,
            )

            # 3. SearchResult로 변환
            results = self._convert_to_search_results(raw_results)

            # 4. 통계 업데이트
            self._stats["total_searches"] += 1

            logger.info(
                f"PgVectorRetriever 검색 완료: "
                f"{len(results)}개 결과 반환 (query='{query[:30]}...')"
            )

            return results

        except Exception as e:
            self._stats["errors"] += 1
            logger.error(
                f"PgVectorRetriever 검색 실패: {e}",
                extra={"query": query[:100]},
                exc_info=True,
            )
            raise

    async def health_check(self) -> bool:
        """
        pgvector 연결 상태 확인

        간단한 검색을 수행하여 store가 정상 동작하는지 확인합니다.

        Returns:
            정상 동작 여부 (True/False)
        """
        try:
            # 빈 벡터로 간단한 검색 시도
            dummy_vector = [0.0] * 1024  # 기본 차원

            await self.store.search(
                collection=self.table_name,
                query_vector=dummy_vector,
                top_k=1,
            )

            logger.debug("PgVectorRetriever health check 성공")
            return True

        except Exception as e:
            logger.warning(f"PgVectorRetriever health check 실패: {e}")
            return False

    def _convert_to_search_results(
        self, raw_results: list[dict[str, Any]]
    ) -> list[SearchResult]:
        """
        pgvector 결과를 SearchResult로 변환

        pgvector 결과 형식:
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
            raw_results: PgVectorStore 검색 결과

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
