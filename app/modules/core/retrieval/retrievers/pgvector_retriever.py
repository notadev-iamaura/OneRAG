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
    공통 검색/문서 관리 흐름은 ``VectorStoreRetrieverBase``에 있습니다.
"""

from typing import ClassVar

from app.modules.core.retrieval.retrievers._vector_store_retriever_base import (
    IEmbedder,
    IVectorStore,
    VectorStoreRetrieverBase,
)

__all__ = ["IEmbedder", "IVectorStore", "PgVectorRetriever"]


class PgVectorRetriever(VectorStoreRetrieverBase):
    """
    pgvector를 사용하는 Dense Retriever

    특징:
    - Dense 벡터 검색 전용
    - PostgreSQL 기반 안정적인 검색
    - PgVectorStore를 통한 검색 수행
    - IRetriever Protocol 구현

    Note:
    - 하이브리드 검색 미지원 (Dense only). ``search(alpha=...)``는
      IRetriever 계약 호환용(#35)이며 무시된다.
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

    _collection_attr: ClassVar[str] = "table_name"
    _health_check_dimension: ClassVar[int] = 1024

    table_name: str

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
        super().__init__(embedder=embedder, store=store, collection=table_name, top_k=top_k)
        self._log_init("dense_only")
