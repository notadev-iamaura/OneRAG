"""
Weaviate 연결 및 관리 모듈

주요 기능:
- Weaviate Vector Database 연결 (로컬/프로덕션)
- Collection 관리 및 Health Check
- 한국어 토크나이저(kagome_kr) 지원
- 연결 풀링 및 재시도 로직

의존성:
- weaviate-client: Weaviate Python 클라이언트 (v4+)
- app.lib.config_loader: 설정 파일 로드
- app.lib.logger: 구조화된 로깅
"""

from __future__ import annotations

import weaviate
from weaviate.client import WeaviateClient as WeaviateClientSDK
from weaviate.collections.collection import Collection
from weaviate.connect import ConnectionParams
from weaviate.exceptions import WeaviateConnectionError

from app.lib.config_loader import load_config
from app.lib.logger import get_logger

# 로거 설정
logger = get_logger(__name__)


class WeaviateClient:
    """
    Weaviate 클라이언트 싱글톤 클래스

    애플리케이션 전체에서 하나의 Weaviate 연결 인스턴스를 공유합니다.
    HTTP 및 gRPC 프로토콜을 통해 효율적인 리소스 관리를 제공합니다.

    Attributes:
        _instance: 싱글톤 인스턴스
        _client: WeaviateClient 인스턴스 (SDK)
        _config: Weaviate 설정 정보
    """

    _instance: WeaviateClient | None = None
    _client: WeaviateClientSDK | None = None
    _config: dict | None = None

    def __new__(cls) -> WeaviateClient:
        """싱글톤 패턴 구현 - 하나의 인스턴스만 생성"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        """Weaviate 클라이언트 초기화"""
        # 이미 초기화된 경우 스킵
        if self._client is not None:
            return

        try:
            # 설정 로드
            config = load_config()
            self._config = config.get("weaviate", {})

            if not self._config or not self._config.get("url"):
                logger.warning("Weaviate 설정이 없습니다. Weaviate 기능이 비활성화됩니다.")
                return

            # Weaviate 연결 설정
            url = self._config.get("url", "http://localhost:8080")
            grpc_host = self._config.get("grpc_host", "localhost")
            grpc_port = self._config.get("grpc_port", 50051)
            self._config.get("api_key")
            timeout = self._config.get("timeout", 30)

            # 연결 파라미터 구성
            if url.startswith("http://localhost") or url.startswith("http://127.0.0.1"):
                # 로컬 연결
                logger.info("Weaviate 로컬 연결 시도")
                self._client = weaviate.connect_to_local(
                    host=grpc_host,
                    port=int(url.split(":")[-1]),
                    grpc_port=grpc_port,
                )
            else:
                # 커스텀 연결 (프로덕션) - Railway 환경
                logger.info(f"Weaviate 커스텀 연결 시도: {url}")
                connection_params = ConnectionParams.from_url(url, grpc_port)

                # Railway 환경에서는 인증 비활성화 (AUTHENTICATION_APIKEY_ENABLED=false)
                # API 키 인증 없이 연결
                # skip_init_checks=True: gRPC health check 건너뛰기 (로컬에서 프로덕션 접속 시 필요)
                self._client = weaviate.WeaviateClient(
                    connection_params=connection_params,
                    skip_init_checks=True,
                )

                self._client.connect()

            # 연결 테스트
            if self._client.is_ready():
                logger.info(
                    "Weaviate 연결 성공",
                    extra={
                        "url": url,
                        "grpc_port": grpc_port,
                        "timeout": timeout,
                    },
                )
            else:
                raise WeaviateConnectionError("Weaviate 연결 실패: ready check failed")

        except WeaviateConnectionError as e:
            logger.error(
                "Weaviate 연결 실패",
                extra={
                    "error": str(e),
                    "error_type": type(e).__name__,
                    "url": url,
                    "suggestion": (
                        "1. docker-compose.weaviate.yml이 실행 중인지 확인하세요 (docker ps | grep weaviate)\n"
                        "2. WEAVIATE_URL 환경 변수가 올바른지 확인하세요\n"
                        "3. 로컬 연결 시: http://localhost:8080 (기본 포트)\n"
                        "4. 프로덕션 연결 시: https://로 시작하는 Railway URL\n"
                        "5. 네트워크 방화벽 또는 포트 충돌 여부를 확인하세요"
                    ),
                },
            )
            # SDK 클라이언트 연결을 명시적으로 닫아 ResourceWarning(Con004) 방지
            if self._client is not None:
                try:
                    self._client.close()
                except Exception:
                    pass
            self._client = None

        except Exception as e:
            logger.error(
                "Weaviate 초기화 중 예상치 못한 오류 발생",
                extra={"error": str(e), "error_type": type(e).__name__},
            )
            # SDK 클라이언트 연결을 명시적으로 닫아 ResourceWarning(Con004) 방지
            if self._client is not None:
                try:
                    self._client.close()
                except Exception:
                    pass
            self._client = None

    @property
    def client(self) -> WeaviateClientSDK | None:
        """
        WeaviateClient 인스턴스 반환

        Returns:
            WeaviateClient 인스턴스 또는 None (연결 실패 시)
        """
        return self._client

    def get_collection(self, collection_name: str) -> Collection | None:
        """
        지정된 이름의 Collection 반환

        Args:
            collection_name: Collection 이름 (예: "Documents")

        Returns:
            Collection 인스턴스 또는 None (연결 실패 시)

        Example:
            documents = weaviate_client.get_collection("Documents")
            response = documents.query.hybrid(query="강화학습", alpha=0.6)
        """
        if self._client is None:
            logger.warning(
                "Weaviate 연결이 없어 Collection을 가져올 수 없습니다.",
                extra={"collection_name": collection_name},
            )
            return None

        try:
            return self._client.collections.get(collection_name)
        except Exception as e:
            logger.error(
                "Collection 가져오기 실패",
                extra={
                    "collection_name": collection_name,
                    "error": str(e),
                    "error_type": type(e).__name__,
                    "suggestion": (
                        "1. Collection 이름이 올바른지 확인하세요 (예: 'Documents')\n"
                        "2. Weaviate 스키마가 생성되었는지 확인하세요\n"
                        "3. 대소문자를 정확히 맞춰주세요 (Collection 이름은 대소문자를 구분합니다)"
                    ),
                },
            )
            return None

    def get_documents_collection(self) -> Collection | None:
        """
        Documents Collection 반환 (기본 컬렉션)

        Returns:
            Documents Collection 인스턴스 또는 None
        """
        collection_name = (
            self._config.get("collection_name", "Documents") if self._config else "Documents"
        )
        return self.get_collection(collection_name)

    def is_ready(self) -> bool:
        """
        Weaviate 연결 상태 확인

        Returns:
            연결 성공 시 True, 실패 시 False
        """
        if self._client is None:
            return False

        try:
            return bool(self._client.is_ready())
        except Exception as e:
            logger.error("Weaviate ready check 실패", extra={"error": str(e)})
            return False

    def close(self) -> None:
        """
        Weaviate 연결 종료

        Note:
            일반적으로 애플리케이션 종료 시에만 호출됩니다.
        """
        if self._client is not None:
            self._client.close()
            logger.info("Weaviate 연결이 종료되었습니다.")
            self._client = None


# 싱글톤 인스턴스 생성
weaviate_client = WeaviateClient()


def get_weaviate_client() -> WeaviateClient:
    """
    전역 Weaviate 클라이언트 인스턴스 반환

    Returns:
        WeaviateClient 싱글톤 인스턴스

    Example:
        from app.lib.weaviate_client import get_weaviate_client

        client = get_weaviate_client()
        documents = client.get_documents_collection()
        if documents:
            response = documents.query.hybrid(query="검색어", alpha=0.6)
    """
    return weaviate_client
