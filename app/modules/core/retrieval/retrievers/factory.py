"""
RetrieverFactory - 설정 기반 Retriever 생성 팩토리

다양한 벡터 데이터베이스(Weaviate, Pinecone, Qdrant 등)의 Retriever를
설정에 따라 동적으로 선택하고 인스턴스화하는 팩토리 클래스입니다.

주요 기능:
- 지연 로딩(Lazy Import)으로 불필요한 의존성 방지
- 런타임에 새 provider 등록 가능
- 하이브리드 검색 지원 여부 관리
- BM25 전처리 모듈 자동 주입 지원
- 친절한 에러 메시지로 설치 가이드 제공

VectorStoreFactory 패턴 준수:
- 동일한 API 구조 (get_available_providers, register_provider, create)
- TypedDict 기반 provider 정보 관리
- 지연 로딩을 통한 의존성 최적화

사용 예시:
    # 기본 사용
    retriever = RetrieverFactory.create(
        provider="weaviate",
        embedder=gemini_embedder,
        config={"weaviate_client": client, "alpha": 0.7}
    )

    # BM25 전처리 모듈과 함께
    retriever = RetrieverFactory.create(
        provider="weaviate",
        embedder=embedder,
        config=config,
        bm25_preprocessors={
            "synonym_manager": SynonymManager(),
            "stopword_filter": StopwordFilter(),
        }
    )
"""

from importlib import import_module
from typing import Any, Protocol, TypedDict, runtime_checkable

from app.lib.logger import get_logger

logger = get_logger(__name__)


@runtime_checkable
class IEmbedder(Protocol):
    """
    Embedder 인터페이스 (Protocol 기반)

    Retriever 생성 시 의존성으로 주입되는 임베딩 모델.
    """

    def embed_query(self, text: str) -> list[float]:
        """쿼리 텍스트를 벡터로 변환"""
        ...

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """문서 리스트를 벡터 리스트로 변환"""
        ...


class RetrieverProviderInfo(TypedDict):
    """Retriever Provider 정보를 담는 타입"""
    class_path: str  # 클래스의 전체 경로
    hybrid_support: bool  # 하이브리드 검색 지원 여부
    description: str  # Provider 설명


# 기본 등록된 Retriever provider 레지스트리
_DEFAULT_PROVIDERS: dict[str, RetrieverProviderInfo] = {
    "weaviate": {
        "class_path": "app.modules.core.retrieval.retrievers.weaviate_retriever.WeaviateRetriever",
        "hybrid_support": True,
        "description": "Weaviate 하이브리드 Retriever - Dense + BM25 검색 지원",
    },
    "chroma": {
        "class_path": "app.modules.core.retrieval.retrievers.chroma_retriever.ChromaRetriever",
        "hybrid_support": False,
        "description": "Chroma Dense 전용 Retriever - 벡터 검색만 지원 (하이브리드 미지원)",
    },
    "pinecone": {
        "class_path": "app.modules.core.retrieval.retrievers.pinecone_retriever.PineconeRetriever",
        "hybrid_support": True,
        "description": "Pinecone 하이브리드 Retriever - Dense + Sparse Vector 검색 지원",
    },
    "qdrant": {
        "class_path": "app.modules.core.retrieval.retrievers.qdrant_retriever.QdrantRetriever",
        "hybrid_support": True,
        "description": "Qdrant 하이브리드 Retriever - Dense + Full-Text 검색 지원",
    },
    "pgvector": {
        "class_path": "app.modules.core.retrieval.retrievers.pgvector_retriever.PgVectorRetriever",
        "hybrid_support": False,
        "description": "pgvector Dense Retriever - PostgreSQL 기반 벡터 검색 (하이브리드 미지원)",
    },
    "mongodb": {
        "class_path": "app.modules.core.retrieval.retrievers.mongodb_atlas_retriever.MongoDBAtlasRetriever",
        "hybrid_support": False,
        "description": "MongoDB Atlas Dense Retriever - 클라우드 관리형 벡터 검색 (하이브리드 미지원)",
    },
}


class RetrieverFactory:
    """
    Retriever 팩토리 클래스

    설정 기반으로 다양한 Retriever 인스턴스를 생성합니다.
    지연 로딩(Lazy Import)을 사용하여 실제 사용 시에만 의존성을 로드합니다.

    특징:
    - VectorStoreFactory 패턴 준수
    - 하이브리드 검색 지원 여부 관리
    - BM25 전처리 모듈 자동 주입
    - IEmbedder 의존성 주입 필수

    사용 예시:
        # 기본 사용
        retriever = RetrieverFactory.create("weaviate", embedder, config)

        # 하이브리드 지원 확인
        if RetrieverFactory.supports_hybrid("weaviate"):
            retriever = RetrieverFactory.create(
                "weaviate", embedder, config, bm25_preprocessors
            )
    """

    # 클래스 레벨 provider 레지스트리 (런타임 수정 가능)
    _providers: dict[str, RetrieverProviderInfo] = _DEFAULT_PROVIDERS.copy()

    @classmethod
    def get_available_providers(cls) -> list[str]:
        """
        등록된 provider 목록을 반환합니다.

        Returns:
            list[str]: 사용 가능한 provider 이름 리스트

        사용 예시:
            providers = RetrieverFactory.get_available_providers()
            # ['weaviate', 'pinecone', 'qdrant', ...]
        """
        return list(cls._providers.keys())

    @classmethod
    def register_provider(
        cls,
        name: str,
        class_path: str,
        hybrid_support: bool = False,
        description: str = "",
    ) -> None:
        """
        새로운 Retriever provider를 등록합니다.

        Args:
            name: provider 이름 (예: "pinecone", "qdrant")
            class_path: 클래스의 전체 경로
                (예: "app.modules.core.retrieval.retrievers.pinecone_retriever.PineconeRetriever")
            hybrid_support: 하이브리드 검색 지원 여부 (기본: False)
            description: provider 설명 (선택사항)

        사용 예시:
            RetrieverFactory.register_provider(
                "pinecone",
                "app.modules.core.retrieval.retrievers.pinecone_retriever.PineconeRetriever",
                hybrid_support=True,
                description="Pinecone 클라우드 벡터 DB Retriever"
            )
        """
        cls._providers[name] = {
            "class_path": class_path,
            "hybrid_support": hybrid_support,
            "description": description or f"{name} Retriever",
        }
        logger.info(
            f"RetrieverFactory: '{name}' provider 등록 완료 "
            f"(hybrid_support={hybrid_support})"
        )

    @classmethod
    def get_provider_info(cls, name: str) -> RetrieverProviderInfo | None:
        """
        특정 provider의 정보를 반환합니다.

        Args:
            name: provider 이름

        Returns:
            RetrieverProviderInfo | None: provider 정보 딕셔너리 또는 None

        사용 예시:
            info = RetrieverFactory.get_provider_info("weaviate")
            if info and info["hybrid_support"]:
                # 하이브리드 검색 사용 가능
                pass
        """
        return cls._providers.get(name)

    @classmethod
    def supports_hybrid(cls, provider: str) -> bool:
        """
        지정된 provider가 하이브리드 검색을 지원하는지 확인합니다.

        하이브리드 검색 지원 DB:
        - weaviate: Dense + BM25 내장 하이브리드
        - pinecone: Dense + Sparse 하이브리드 (추후 지원)
        - qdrant: Dense + Full-Text 하이브리드 (추후 지원)

        미지원 DB:
        - chroma: Dense 전용
        - pgvector: Dense 전용 (기본)
        - mongodb: Dense 전용 (레거시)

        Args:
            provider: provider 이름

        Returns:
            bool: 하이브리드 검색 지원 여부

        Raises:
            ValueError: 지원하지 않는 provider인 경우

        사용 예시:
            if RetrieverFactory.supports_hybrid("weaviate"):
                # BM25 전처리 모듈 주입 가능
                retriever = RetrieverFactory.create(
                    "weaviate", embedder, config, bm25_preprocessors
                )
        """
        if provider not in cls._providers:
            available = ", ".join(cls._providers.keys())
            raise ValueError(
                f"지원하지 않는 Retriever provider입니다: '{provider}'. "
                f"사용 가능한 provider: {available}"
            )

        return cls._providers[provider]["hybrid_support"]

    @classmethod
    def create(
        cls,
        provider: str,
        embedder: IEmbedder,
        config: dict[str, Any],
        bm25_preprocessors: dict[str, Any] | None = None,
    ) -> Any:
        """
        지정된 provider의 Retriever 인스턴스를 생성합니다.

        지연 로딩(Lazy Import)을 사용하여 실제 사용 시에만
        해당 provider의 의존성을 로드합니다.

        Args:
            provider: Retriever provider 이름 (예: "weaviate", "pinecone")
            embedder: IEmbedder 인터페이스를 구현한 임베딩 모델
            config: Retriever 초기화 설정 딕셔너리
                - weaviate_client: Weaviate 클라이언트 인스턴스
                - collection_name: 컬렉션 이름 (선택)
                - alpha: 하이브리드 검색 가중치 (선택)
            bm25_preprocessors: 하이브리드 지원 DB일 때 BM25 전처리 모듈 (선택)
                - synonym_manager: 동의어 확장 모듈
                - stopword_filter: 불용어 제거 모듈
                - user_dictionary: 사용자 사전 모듈

        Returns:
            IRetriever: 생성된 Retriever 인스턴스

        Raises:
            ValueError: 지원하지 않는 provider인 경우
            ImportError: 필요한 라이브러리가 설치되지 않은 경우

        사용 예시:
            # Weaviate Retriever 생성
            retriever = RetrieverFactory.create(
                provider="weaviate",
                embedder=gemini_embedder,
                config={
                    "weaviate_client": weaviate_client,
                    "collection_name": "Documents",
                    "alpha": 0.6
                }
            )

            # BM25 전처리 모듈과 함께
            retriever = RetrieverFactory.create(
                provider="weaviate",
                embedder=embedder,
                config=config,
                bm25_preprocessors={
                    "synonym_manager": synonym_manager,
                    "stopword_filter": stopword_filter,
                }
            )
        """
        if provider not in cls._providers:
            available = ", ".join(cls._providers.keys())
            raise ValueError(
                f"지원하지 않는 Retriever provider입니다: '{provider}'. "
                f"사용 가능한 provider: {available}"
            )

        provider_info = cls._providers[provider]
        class_path = provider_info["class_path"]
        hybrid_support = provider_info["hybrid_support"]

        try:
            # 지연 로딩: 모듈과 클래스를 동적으로 임포트
            retriever_class = cls._import_class(class_path)
            logger.info(f"RetrieverFactory: '{provider}' 인스턴스 생성 중...")

            # 설정 딕셔너리 준비
            init_kwargs: dict[str, Any] = {
                "embedder": embedder,
                **config,
            }

            # 하이브리드 지원 DB이고 BM25 전처리 모듈이 있는 경우 주입
            if hybrid_support and bm25_preprocessors:
                init_kwargs.update(bm25_preprocessors)
                logger.debug(
                    f"RetrieverFactory: BM25 전처리 모듈 주입 - "
                    f"{list(bm25_preprocessors.keys())}"
                )

            # 인스턴스 생성
            instance = retriever_class(**init_kwargs)
            logger.info(f"RetrieverFactory: '{provider}' 인스턴스 생성 완료")

            return instance

        except ModuleNotFoundError as e:
            # 모듈을 찾을 수 없는 경우 (라이브러리 미설치)
            missing_module = str(e).replace("No module named ", "").strip("'")
            raise ImportError(
                f"'{provider}' Retriever를 사용하려면 필요한 라이브러리가 설치되어야 합니다. "
                f"누락된 모듈: {missing_module}. "
                f"설치 방법: pip install {cls._get_install_package(provider)}"
            ) from e

        except Exception as e:
            logger.error(f"RetrieverFactory: '{provider}' 인스턴스 생성 실패 - {e}")
            raise

    @classmethod
    def _import_class(cls, class_path: str) -> type:
        """
        클래스 경로로부터 클래스를 동적 임포트합니다.

        Args:
            class_path: 전체 클래스 경로
                (예: "app.modules.core.retrieval.retrievers.weaviate_retriever.WeaviateRetriever")

        Returns:
            type: 임포트된 Retriever 클래스
        """
        module_path, class_name = class_path.rsplit(".", 1)
        module = import_module(module_path)
        retriever_class: type = getattr(module, class_name)
        return retriever_class

    @classmethod
    def _get_install_package(cls, provider: str) -> str:
        """
        provider별 설치해야 할 패키지 이름을 반환합니다.

        Args:
            provider: provider 이름

        Returns:
            str: pip install에 사용할 패키지 이름
        """
        # provider별 패키지 매핑
        package_map = {
            "weaviate": "weaviate-client",
            "pinecone": "pinecone-client",
            "chroma": "chromadb",
            "qdrant": "qdrant-client",
            "milvus": "pymilvus",
            "pgvector": "pgvector",
        }
        return package_map.get(provider, provider)
