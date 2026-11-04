"""
Pinecone Retriever - 하이브리드 검색 (Dense + Sparse Vector)

주요 기능:
- IRetriever 인터페이스 구현
- Dense 벡터 검색 지원
- 하이브리드 검색 지원 (Sparse Vector)
- BM25 전처리 모듈 통합 (동의어 확장, 불용어 제거, 사용자 사전)
- 쿼리 벡터화 → 유사도 검색 → SearchResult 변환

의존성:
- pinecone: pip install pinecone (선택적)
- app.infrastructure.storage.vector.pinecone_store: PineconeVectorStore
- app.modules.core.retrieval.interfaces: IRetriever, SearchResult

Note:
    Pinecone은 Sparse Vector를 통한 하이브리드 검색을 지원합니다.
    hybrid_alpha 파라미터로 Dense/Sparse 가중치를 조절할 수 있습니다.
    공통 검색/문서 관리 흐름은 ``HybridVectorStoreRetrieverBase``에 있습니다.
"""

from typing import Any, ClassVar

from app.lib.logger import get_logger
from app.modules.core.retrieval.retrievers._vector_store_retriever_base import (
    HybridVectorStoreRetrieverBase,
    IEmbedder,
)
from app.modules.core.retrieval.retrievers._vector_store_retriever_base import (
    IHybridVectorStore as IVectorStore,
)

logger = get_logger(__name__)

__all__ = ["IEmbedder", "IVectorStore", "PineconeRetriever"]


class PineconeRetriever(HybridVectorStoreRetrieverBase):
    """
    Pinecone 벡터 DB를 사용하는 하이브리드 Retriever

    특징:
    - Dense 벡터 검색 지원
    - 하이브리드 검색 지원 (Sparse Vector via hybrid_alpha)
    - BM25 전처리 모듈 통합 (동의어, 불용어, 사용자 사전)
    - PineconeVectorStore를 통한 검색 수행
    - IRetriever Protocol 구현

    하이브리드 검색:
    - hybrid_alpha: 0.0 (Sparse만) ~ 1.0 (Dense만)
    - 기본값 0.6 = 60% Dense + 40% Sparse

    사용 예시:
        retriever = PineconeRetriever(
            embedder=gemini_embedder,
            store=pinecone_store,
            namespace="documents",
            top_k=10,
            hybrid_alpha=0.6,
        )
        results = await retriever.search("검색 쿼리")
    """

    _collection_attr: ClassVar[str] = "namespace"

    namespace: str

    def __init__(
        self,
        embedder: IEmbedder,
        store: IVectorStore,
        namespace: str = "default",
        top_k: int = 10,
        hybrid_alpha: float = 0.6,
        # BM25 전처리 모듈 (Optional)
        synonym_manager: Any | None = None,
        stopword_filter: Any | None = None,
        user_dictionary: Any | None = None,
    ) -> None:
        """
        PineconeRetriever 초기화

        Args:
            embedder: 쿼리 벡터화를 위한 임베딩 모델 (IEmbedder)
            store: PineconeVectorStore 인스턴스 (IVectorStore)
            namespace: Pinecone 네임스페이스 (기본값: "default")
            top_k: 기본 검색 결과 수 (기본값: 10)
            hybrid_alpha: 하이브리드 가중치 (기본값: 0.6)
                - 1.0: Dense만 사용
                - 0.0: Sparse만 사용
                - 0.6: 60% Dense + 40% Sparse (권장)
            synonym_manager: 동의어 관리자 (Optional, BM25 전처리용)
            stopword_filter: 불용어 필터 (Optional, BM25 전처리용)
            user_dictionary: 사용자 사전 (Optional, BM25 전처리용)

        Note:
            하이브리드 검색을 사용하려면 Pinecone 인덱스가
            Sparse-Dense 모드로 생성되어 있어야 합니다.
        """
        super().__init__(
            embedder=embedder,
            store=store,
            collection=namespace,
            top_k=top_k,
            hybrid_alpha=hybrid_alpha,
            synonym_manager=synonym_manager,
            stopword_filter=stopword_filter,
            user_dictionary=user_dictionary,
        )

    async def health_check(self) -> bool:
        """
        Pinecone 연결 상태 확인

        describe_index_stats를 호출하여 연결 상태를 확인합니다.

        Returns:
            정상 동작 여부 (True/False)
        """
        try:
            # describe_index_stats 호출로 연결 확인
            if hasattr(self.store, "describe_index_stats"):
                await self.store.describe_index_stats()

            logger.debug("PineconeRetriever health check 성공")
            return True

        except Exception as e:
            logger.warning(f"PineconeRetriever health check 실패: {e}")
            return False
