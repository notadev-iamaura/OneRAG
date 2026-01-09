"""
VectorStoreFactory - 설정 기반 벡터 스토어 생성 팩토리

다양한 벡터 데이터베이스(Weaviate, Pinecone, Chroma 등)를 설정에 따라
동적으로 선택하고 인스턴스화하는 팩토리 클래스입니다.

주요 기능:
- 지연 로딩(Lazy Import)으로 불필요한 의존성 방지
- 런타임에 새 provider 등록 가능
- 친절한 에러 메시지로 설치 가이드 제공
"""

from importlib import import_module
from typing import Any, TypedDict

from app.core.interfaces.storage import IVectorStore
from app.lib.logger import get_logger

logger = get_logger(__name__)


class ProviderInfo(TypedDict):
    """Provider 정보를 담는 타입"""
    class_path: str
    description: str


# 기본 등록된 벡터 스토어 provider 레지스트리
_DEFAULT_PROVIDERS: dict[str, ProviderInfo] = {
    "weaviate": {
        "class_path": "app.infrastructure.storage.vector.weaviate_store.WeaviateVectorStore",
        "description": "Weaviate 벡터 데이터베이스 - Dense + Sparse 하이브리드 검색 지원",
    },
    "chroma": {
        "class_path": "app.infrastructure.storage.vector.chroma_store.ChromaVectorStore",
        "description": "Chroma 경량 벡터 데이터베이스 - 로컬 개발 및 테스트 최적화",
    },
    "pinecone": {
        "class_path": "app.infrastructure.storage.vector.pinecone_store.PineconeVectorStore",
        "description": "Pinecone 서버리스 벡터 데이터베이스 - 하이브리드 검색 지원",
    },
    "qdrant": {
        "class_path": "app.infrastructure.storage.vector.qdrant_store.QdrantVectorStore",
        "description": "Qdrant 셀프호스팅/클라우드 벡터 데이터베이스 - 하이브리드 검색 지원",
    },
    "pgvector": {
        "class_path": "app.infrastructure.storage.vector.pgvector_store.PgVectorStore",
        "description": "pgvector PostgreSQL 확장 - 기존 PostgreSQL 인프라 활용 벡터 검색",
    },
    "mongodb": {
        "class_path": "app.infrastructure.storage.vector.mongodb_atlas_store.MongoDBAtlasStore",
        "description": "MongoDB Atlas 벡터 검색 - 클라우드 관리형 벡터 데이터베이스",
    },
}


class VectorStoreFactory:
    """
    벡터 스토어 팩토리 클래스

    설정 기반으로 다양한 벡터 DB 인스턴스를 생성합니다.
    지연 로딩(Lazy Import)을 사용하여 실제 사용 시에만 의존성을 로드합니다.

    사용 예시:
        # 기본 사용
        store = VectorStoreFactory.create("weaviate", {"url": "http://localhost:8080"})

        # 새 provider 등록
        VectorStoreFactory.register_provider(
            "pinecone",
            "app.infrastructure.storage.vector.pinecone_store.PineconeVectorStore"
        )
    """

    # 클래스 레벨 provider 레지스트리 (런타임 수정 가능)
    _providers: dict[str, ProviderInfo] = _DEFAULT_PROVIDERS.copy()

    @classmethod
    def get_available_providers(cls) -> list[str]:
        """
        등록된 provider 목록을 반환합니다.

        Returns:
            list[str]: 사용 가능한 provider 이름 리스트

        사용 예시:
            providers = VectorStoreFactory.get_available_providers()
            # ['weaviate', 'pinecone', ...]
        """
        return list(cls._providers.keys())

    @classmethod
    def register_provider(cls, name: str, class_path: str, description: str = "") -> None:
        """
        새로운 벡터 스토어 provider를 등록합니다.

        Args:
            name: provider 이름 (예: "pinecone", "chroma")
            class_path: 클래스의 전체 경로 (예: "app.infrastructure.storage.vector.pinecone_store.PineconeVectorStore")
            description: provider 설명 (선택사항)

        사용 예시:
            VectorStoreFactory.register_provider(
                "pinecone",
                "app.infrastructure.storage.vector.pinecone_store.PineconeVectorStore",
                "Pinecone 클라우드 벡터 DB"
            )
        """
        cls._providers[name] = {
            "class_path": class_path,
            "description": description or f"{name} 벡터 스토어",
        }
        logger.info(f"VectorStoreFactory: '{name}' provider 등록 완료")

    @classmethod
    def get_provider_info(cls, name: str) -> ProviderInfo | None:
        """
        특정 provider의 정보를 반환합니다.

        Args:
            name: provider 이름

        Returns:
            ProviderInfo | None: provider 정보 딕셔너리 또는 None
        """
        return cls._providers.get(name)

    @classmethod
    def create(cls, provider: str, config: dict[str, Any]) -> IVectorStore:
        """
        지정된 provider의 벡터 스토어 인스턴스를 생성합니다.

        지연 로딩(Lazy Import)을 사용하여 실제 사용 시에만
        해당 provider의 의존성을 로드합니다.

        Args:
            provider: 벡터 스토어 provider 이름 (예: "weaviate", "pinecone")
            config: 벡터 스토어 초기화 설정 딕셔너리

        Returns:
            IVectorStore: 생성된 벡터 스토어 인스턴스

        Raises:
            ValueError: 지원하지 않는 provider인 경우
            ImportError: 필요한 라이브러리가 설치되지 않은 경우

        사용 예시:
            # Weaviate 생성
            store = VectorStoreFactory.create("weaviate", {
                "url": "http://localhost:8080",
                "api_key": "your-api-key"
            })
        """
        if provider not in cls._providers:
            available = ", ".join(cls._providers.keys())
            raise ValueError(
                f"지원하지 않는 벡터 스토어 provider입니다: '{provider}'. "
                f"사용 가능한 provider: {available}"
            )

        provider_info = cls._providers[provider]
        class_path = provider_info["class_path"]

        try:
            # 지연 로딩: 모듈과 클래스를 동적으로 임포트
            store_class = cls._import_class(class_path)
            logger.info(f"VectorStoreFactory: '{provider}' 인스턴스 생성 중...")

            # 설정을 kwargs로 전달하여 인스턴스 생성
            instance = store_class(**config)
            logger.info(f"VectorStoreFactory: '{provider}' 인스턴스 생성 완료")

            return instance

        except ModuleNotFoundError as e:
            # 모듈을 찾을 수 없는 경우 (라이브러리 미설치)
            missing_module = str(e).replace("No module named ", "").strip("'")
            raise ImportError(
                f"'{provider}' 벡터 스토어를 사용하려면 필요한 라이브러리가 설치되어야 합니다. "
                f"누락된 모듈: {missing_module}. "
                f"설치 방법: pip install {cls._get_install_package(provider)}"
            ) from e

        except Exception as e:
            logger.error(f"VectorStoreFactory: '{provider}' 인스턴스 생성 실패 - {e}")
            raise

    @classmethod
    def _import_class(cls, class_path: str) -> type[IVectorStore]:
        """
        클래스 경로로부터 클래스를 동적 임포트합니다.

        Args:
            class_path: 전체 클래스 경로 (예: "app.infrastructure.storage.vector.weaviate_store.WeaviateVectorStore")

        Returns:
            type[IVectorStore]: 임포트된 IVectorStore 구현 클래스
        """
        module_path, class_name = class_path.rsplit(".", 1)
        module = import_module(module_path)
        store_class: type[IVectorStore] = getattr(module, class_name)
        return store_class

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
            "pinecone": "pinecone",
            "chroma": "chromadb",
            "qdrant": "qdrant-client",
            "milvus": "pymilvus",
        }
        return package_map.get(provider, provider)
