"""
Weaviate Vector Store Adapter

IVectorStore 인터페이스를 구현한 Weaviate 어댑터입니다.
기존 app.lib.weaviate_client.WeaviateClient를 활용하거나 직접 weaviate-client를 사용합니다.
"""
import os
from typing import Any

import weaviate
from weaviate import WeaviateClient

from app.core.interfaces.storage import IVectorStore
from app.lib.logger import get_logger

logger = get_logger(__name__)


class WeaviateVectorStore(IVectorStore):
    def __init__(
        self,
        url: str | None = None,
        api_key: str | None = None,
        grpc_port: int | None = None,
    ) -> None:
        resolved_url = url or os.getenv("WEAVIATE_URL")
        if not resolved_url:
            raise ValueError("WEAVIATE_URL 환경 변수가 필요합니다.")
        self.url: str = resolved_url

        self.api_key = api_key or os.getenv("WEAVIATE_API_KEY")

        if grpc_port is not None:
            self.grpc_port = grpc_port
        else:
            self.grpc_port = int(os.getenv("WEAVIATE_GRPC_PORT", "50051"))

        # Weaviate Client 초기화 (v4)
        auth_config = weaviate.auth.AuthApiKey(api_key=self.api_key) if self.api_key else None
        # URL에서 호스트와 포트 파싱
        url_without_scheme = self.url.replace("https://", "").replace("http://", "")
        url_parts = url_without_scheme.split(":")
        host = url_parts[0]
        # URL에서 포트 추출, 없으면 기본값 사용
        if len(url_parts) > 1:
            http_port = int(url_parts[1].split("/")[0])  # 경로 제거
        else:
            http_port = 443 if self.url.startswith("https") else 80
        is_secure = self.url.startswith("https")
        self.client: WeaviateClient = weaviate.connect_to_custom(
            http_host=host,
            http_port=http_port,
            http_secure=is_secure,
            grpc_host=host,
            grpc_port=self.grpc_port,
            grpc_secure=is_secure,
            auth_credentials=auth_config,
        )
        logger.info(f"WeaviateVectorStore initialized connected to {self.url}")

    async def add_documents(self, collection: str, documents: list[dict[str, Any]]) -> int:
        """
        문서 저장 (Batch)
        """
        try:
            col = self.client.collections.get(collection)
            with col.batch.dynamic() as batch:
                for doc in documents:
                    # 벡터가 명시적으로 제공된 경우와 아닌 경우 분기 처리 가능
                    # 여기서는 간단히 properties와 vector를 분리한다고 가정
                    payload = doc.copy()
                    vector = payload.pop("vector", None)
                    batch.add_object(
                        properties=payload,
                        vector=vector,
                    )

            if len(col.batch.failed_objects) > 0:
                failed_ids = [str(obj.original_uuid) for obj in col.batch.failed_objects[:5]]
                raise RuntimeError(
                    f"문서 인덱싱 중 오류가 발생했습니다: {len(documents)}개 문서. "
                    + "해결 방법: 1) Weaviate 서버 용량을 확인하세요 (GET /v1/.well-known/ready). "
                    + "2) 배치 크기를 줄이세요 (기본값: 100). "
                    + "3) Weaviate 로그를 확인하세요. "
                    + f"실패한 문서 ID: {failed_ids}"
                )

            return len(documents)
        except Exception as e:
            logger.error(f"Error adding documents to Weaviate: {e}")
            raise RuntimeError(
                f"문서 인덱싱 중 오류가 발생했습니다: {len(documents)}개 문서. "
                + "해결 방법: 1) Weaviate 서버 용량을 확인하세요 (GET /v1/.well-known/ready). "
                + "2) 배치 크기를 줄이세요 (기본값: 100). "
                + "3) Weaviate 로그를 확인하세요. "
                + "실패한 문서 ID: []"
            ) from e

    async def search(self, collection: str, query_vector: list[float], top_k: int, filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """
        벡터 검색
        """
        try:
            col = self.client.collections.get(collection)

            # Filter 구성 로직은 복잡할 수 있으므로 여기서는 단순화함
            # 실제 구현 시 weaviate.classes.query.Filter를 사용하여 filters 딕셔너리를 변환해야 함

            response = col.query.near_vector(
                near_vector=query_vector,
                limit=top_k,
                return_metadata=weaviate.classes.query.MetadataQuery(distance=True, score=True)
            )

            results: list[dict[str, Any]] = []
            for obj in response.objects:
                item: dict[str, Any] = dict(obj.properties)
                item["_id"] = str(obj.uuid)
                item["_distance"] = obj.metadata.distance
                results.append(item)

            return results
        except Exception as e:
            logger.error(f"Error searching Weaviate: {e}")
            return []

    async def delete(self, collection: str, filters: dict[str, Any]) -> int:
        """
        조건부 삭제
        """
        try:
            col = self.client.collections.get(collection)
            # Filter 변환 로직 필요. 임시로 id 기반 삭제만 예시로 구현
            if "id" in filters:
                doc_id = filters["id"]
                col.data.delete_by_id(doc_id)
                return 1
            # 실제로는 delete_many 사용
            return 0
        except Exception as e:
            doc_id = filters.get("id", "unknown")
            logger.error(f"Error deleting from Weaviate: {e}")
            raise RuntimeError(
                f"문서 삭제 실패: {doc_id}. "
                + "해결 방법: 1) 문서 ID가 존재하는지 확인하세요. "
                + "2) Weaviate 권한을 확인하세요. "
                + "3) 문서가 다른 프로세스에서 사용 중인지 확인하세요. "
                + "4) 잠시 후 다시 시도하세요."
            ) from e

    def close(self) -> None:
        """명시적 연결 종료"""
        if hasattr(self, "client") and self.client:
            self.client.close()

    def __del__(self) -> None:
        self.close()
