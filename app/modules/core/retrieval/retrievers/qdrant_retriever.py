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
    공통 검색/문서 관리 흐름은 ``HybridVectorStoreRetrieverBase``에 있습니다.
"""

from typing import Any, ClassVar

from app.modules.core.retrieval.retrievers._vector_store_retriever_base import (
    HybridVectorStoreRetrieverBase,
    IEmbedder,
)
from app.modules.core.retrieval.retrievers._vector_store_retriever_base import (
    IHybridVectorStore as IVectorStore,
)

__all__ = ["IEmbedder", "IVectorStore", "QdrantRetriever"]


class QdrantRetriever(HybridVectorStoreRetrieverBase):
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

    _collection_attr: ClassVar[str] = "collection_name"
    _health_check_dimension: ClassVar[int] = 768

    collection_name: str

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
        super().__init__(
            embedder=embedder,
            store=store,
            collection=collection_name,
            top_k=top_k,
            hybrid_alpha=hybrid_alpha,
            synonym_manager=synonym_manager,
            stopword_filter=stopword_filter,
            user_dictionary=user_dictionary,
        )
