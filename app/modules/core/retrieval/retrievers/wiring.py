"""설정 → Retriever 인스턴스 배선 (DI 컨테이너에서 분리).

provider별로 서로 다른 설정 키와 의존성(VectorStore, Weaviate 클라이언트, BM25 전처리기)을
RetrieverFactory.create 가 받는 형태로 변환한다. 순수 함수이며 컨테이너를 모른다.
app.core.di_container.create_retriever_via_factory 는 이 함수에 위임한다.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.lib.logger import get_logger

from .factory import RetrieverFactory

logger = get_logger(__name__)


def build_retriever_from_config(
    config: dict[str, Any],
    embedder: Any,
    *,
    vector_store: Any | None = None,
    vector_store_provider: Callable[[], Any] | None = None,
    vector_store_factory: Callable[[dict[str, Any]], Any] | None = None,
    weaviate_client: Any | None = None,
    weaviate_client_provider: Callable[[], Any] | None = None,
    synonym_manager: Any | None = None,
    stopword_filter: Any | None = None,
    user_dictionary: Any | None = None,
) -> Any:
    """앱 설정(dict)을 읽어 provider에 맞는 Retriever 를 생성한다.

    Args:
        config: 앱 전체 설정 딕셔너리
        embedder: 임베딩 모델 인스턴스
        vector_store: 이미 만들어진 VectorStore(있으면 우선 사용)
        vector_store_provider: VectorStore 지연 생성 함수
        vector_store_factory: 설정으로 VectorStore 를 만드는 함수(위 둘이 없을 때)
        weaviate_client: Weaviate 클라이언트(weaviate provider 전용)
        weaviate_client_provider: Weaviate 클라이언트 지연 생성 함수
        synonym_manager / stopword_filter / user_dictionary: BM25 전처리기

    Returns:
        IRetriever 구현체 인스턴스

    지원 provider: weaviate, chroma, pinecone, qdrant, pgvector, mongodb, grok
    """
    if vector_store_factory is None:
        def vector_store_factory(_config: dict[str, Any]) -> Any:
            raise RuntimeError(
                "vector_store 또는 vector_store_provider/vector_store_factory 가 필요합니다"
            )

    provider = config.get("vector_db", {}).get("provider", "weaviate")

    def resolve_vector_store() -> Any:
        if vector_store is not None:
            return vector_store
        if vector_store_provider is not None:
            return vector_store_provider()
        return vector_store_factory(config)

    def resolve_weaviate_client() -> Any:
        if weaviate_client is not None:
            return weaviate_client
        if weaviate_client_provider is not None:
            return weaviate_client_provider()
        return None

    # Provider별 설정 매핑
    retriever_config: dict[str, Any] = {}

    # BM25 전처리 모듈 (하이브리드 지원 provider용)
    bm25_preprocessors: dict[str, Any] | None = None
    if RetrieverFactory.supports_hybrid(provider):
        if provider == "weaviate":
            # Weaviate는 기존 전처리 모듈만 주입 (BM25 실행은 Weaviate 내장)
            bm25_preprocessors = {
                "synonym_manager": synonym_manager,
                "stopword_filter": stopword_filter,
                "user_dictionary": user_dictionary,
            }
        elif provider in ("chroma", "pgvector", "mongodb"):
            # BM25 엔진 기반 하이브리드 확장 (현재는 chroma에서 사용)
            try:
                from app.modules.core.retrieval.bm25_engine import (
                    BM25Index,
                    HybridMerger,
                    KoreanTokenizer,
                )
                from app.modules.core.retrieval.bm25_engine.tokenizer import (
                    WhitespaceTokenizer,
                )

                # 범용성: bm25.yaml의 tokenizer 설정으로 언어에 맞는 토크나이저 선택.
                # 기본 "korean"은 Kiwi 형태소 분석기, 그 외(예: "whitespace")는
                # 언어 중립 토크나이저로 비한국어 코퍼스를 지원한다.
                tokenizer_type = config.get("bm25", {}).get("tokenizer", "korean")
                tokenizer: object
                if tokenizer_type == "korean":
                    tokenizer = KoreanTokenizer(
                        stopword_filter=stopword_filter,
                        synonym_manager=synonym_manager,
                        user_dictionary=user_dictionary,
                    )
                else:
                    tokenizer = WhitespaceTokenizer()
                    logger.info(
                        f"BM25 언어 중립 토크나이저 사용 (tokenizer={tokenizer_type})"
                    )
                bm25_index = BM25Index(tokenizer=tokenizer)  # type: ignore[arg-type]
                hybrid_merger = HybridMerger(
                    alpha=config.get("hybrid_search", {}).get("default_alpha", 0.6)
                )

                bm25_preprocessors = {
                    "bm25_index": bm25_index,
                    "hybrid_merger": hybrid_merger,
                }
                logger.info(f"BM25 엔진 주입 완료 (provider={provider})")

            except ImportError:
                logger.warning(
                    f"BM25 엔진 의존성 미설치 - {provider}는 Dense 전용으로 동작합니다. "
                    "하이브리드 검색을 사용하려면: uv add kiwipiepy rank-bm25"
                )
                bm25_preprocessors = None
        else:
            # Pinecone, Qdrant 등은 기존 전처리 모듈 주입
            bm25_preprocessors = {
                "synonym_manager": synonym_manager,
                "stopword_filter": stopword_filter,
                "user_dictionary": user_dictionary,
            }

    if provider == "weaviate":
        resolved_weaviate_client = resolve_weaviate_client()
        # Weaviate: weaviate_client 사용 (store 대신)
        weaviate_config = config.get("weaviate", {})
        retriever_config = {
            "weaviate_client": resolved_weaviate_client,
            "collection_name": weaviate_config.get("collection_name", "Documents"),
            "alpha": weaviate_config.get("hybrid_search", {}).get("default_alpha", 0.6),
            "fusion_type": weaviate_config.get("hybrid_search", {}).get(
                "fusion_type", "ranked"
            ),
            "additional_collections": weaviate_config.get("additional_collections", []),
            "collection_properties": config.get("domain", {}).get("retrieval", {}).get(
                "collections", {}
            ),
            # 메타데이터 검색결과 source_file 표시 접미사를 config에서 파생한다.
            # 미설정(None) 시 생성자가 한국어 기본 " (메타데이터)"로 폴백(회귀 0).
            # 비한국어 운영자는 weaviate.metadata_source_suffix로 자국어/영어 라벨 주입.
            "metadata_source_suffix": weaviate_config.get("metadata_source_suffix"),
        }
    elif provider == "chroma":
        resolved_vector_store = resolve_vector_store()
        # Chroma: BM25 엔진이 있으면 하이브리드 검색 지원
        chroma_config = config.get("chroma", {})
        retriever_config = {
            "store": resolved_vector_store,
            "collection_name": chroma_config.get("collection_name", "documents"),
            "top_k": chroma_config.get("retrieval", {}).get("default_top_k", 10),
        }
    elif provider == "pinecone":
        resolved_vector_store = resolve_vector_store()
        # Pinecone: 하이브리드 지원
        pinecone_config = config.get("pinecone", {})
        retriever_config = {
            "store": resolved_vector_store,
            "namespace": pinecone_config.get("namespace", "default"),
            "top_k": pinecone_config.get("retrieval", {}).get("default_top_k", 10),
            "hybrid_alpha": pinecone_config.get("hybrid", {}).get("default_alpha", 0.6),
        }
    elif provider == "qdrant":
        resolved_vector_store = resolve_vector_store()
        # Qdrant: 하이브리드 지원
        qdrant_config = config.get("qdrant", {})
        retriever_config = {
            "store": resolved_vector_store,
            "collection_name": qdrant_config.get("collection_name", "documents"),
            "top_k": qdrant_config.get("retrieval", {}).get("default_top_k", 10),
            "hybrid_alpha": qdrant_config.get("hybrid_search", {}).get("default_alpha", 0.6),
        }
    elif provider == "pgvector":
        resolved_vector_store = resolve_vector_store()
        # pgvector: Dense 전용
        pgvector_config = config.get("pgvector", {})
        retriever_config = {
            "store": resolved_vector_store,
            "table_name": pgvector_config.get("table_name", "documents"),
            "top_k": pgvector_config.get("retrieval", {}).get("default_top_k", 10),
        }
    elif provider == "mongodb":
        resolved_vector_store = resolve_vector_store()
        # MongoDB Atlas: Dense 전용
        mongodb_config = config.get("mongodb", {}).get("vector_search", {})
        retriever_config = {
            "store": resolved_vector_store,
            "collection_name": mongodb_config.get("collection_name", "documents"),
            "top_k": mongodb_config.get("retrieval", {}).get("default_top_k", 10),
        }
    elif provider == "grok":
        # Grok Collections API: 검색 전용 (VectorStore 불필요)
        grok_config = config.get("grok", {})
        retriever_config = {
            "api_key": grok_config.get("api_key"),
            "collection_ids": grok_config.get("collection_ids", []),
            "model": grok_config.get("model", "grok-3"),
            "api_url": grok_config.get(
                "search_api_url", "https://api.x.ai/v1/documents/search"
            ),
            "timeout": grok_config.get("timeout", 30),
            "top_k": grok_config.get("top_k", 10),
            "retrieval_mode": grok_config.get("retrieval_mode", "hybrid"),
        }
        # Grok은 VectorStore 없이 동작하므로 BM25 전처리 불필요
        bm25_preprocessors = None

    logger.info(
        "Retriever 생성 시작",
        extra={
            "provider": provider,
            "hybrid_support": RetrieverFactory.supports_hybrid(provider),
        }
    )

    return RetrieverFactory.create(
        provider=provider,
        embedder=embedder,
        config=retriever_config,
        bm25_preprocessors=bm25_preprocessors,
    )


# ========================================
# AppContainer
# ========================================


