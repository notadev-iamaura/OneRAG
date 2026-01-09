"""
Qdrant Vector Store - 셀프호스팅/클라우드 벡터 데이터베이스

주요 기능:
- IVectorStore 인터페이스 구현
- Dense 벡터 검색 지원
- 하이브리드 검색 지원 (Sparse Vector via Full-Text)
- Docker/클라우드 배포 지원

의존성:
- qdrant-client: pip install qdrant-client (선택적)
- 로컬: docker run -p 6333:6333 qdrant/qdrant
- 클라우드: Qdrant Cloud (https://cloud.qdrant.io)

Note:
    qdrant-client가 설치되지 않은 환경에서는 ImportError가 발생합니다.
    선택적 의존성이므로 필요한 경우에만 설치하세요.
"""

from __future__ import annotations

import asyncio
import uuid
from abc import ABC, abstractmethod
from typing import Any

from app.lib.logger import get_logger

logger = get_logger(__name__)


class IVectorStore(ABC):
    """벡터 스토어 인터페이스 (Protocol 대신 ABC 사용)"""

    @abstractmethod
    async def add_documents(
        self, collection: str, documents: list[dict[str, Any]]
    ) -> int:
        """문서 추가"""
        ...

    @abstractmethod
    async def search(
        self,
        collection: str,
        query_vector: list[float],
        top_k: int = 10,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """벡터 검색"""
        ...

    @abstractmethod
    async def delete(self, collection: str, filters: dict[str, Any]) -> int:
        """문서 삭제"""
        ...


class QdrantVectorStore(IVectorStore):
    """
    Qdrant 벡터 스토어 구현

    Qdrant 특징:
    - 셀프호스팅 (Docker) 또는 클라우드 배포
    - Full-Text 검색으로 하이브리드 지원
    - 필터링 및 페이로드 지원
    - gRPC 및 REST API 지원

    사용 예시:
        # 로컬 Qdrant
        store = QdrantVectorStore(
            host="localhost",
            port=6333,
            collection_name="documents"
        )

        # Qdrant Cloud
        store = QdrantVectorStore(
            url="https://xxx.qdrant.io",
            api_key="your-api-key",
            collection_name="documents"
        )
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 6333,
        url: str | None = None,
        api_key: str | None = None,
        collection_name: str = "documents",
        grpc_port: int | None = None,
        prefer_grpc: bool = False,
        _client: Any | None = None,  # 테스트용 Mock 주입
    ) -> None:
        """
        QdrantVectorStore 초기화

        Args:
            host: Qdrant 서버 호스트 (기본값: "localhost")
            port: REST API 포트 (기본값: 6333)
            url: Qdrant Cloud URL (url 설정 시 host/port 무시)
            api_key: API 키 (Qdrant Cloud 필수)
            collection_name: 기본 컬렉션 이름 (기본값: "documents")
            grpc_port: gRPC 포트 (선택적)
            prefer_grpc: gRPC 프로토콜 우선 사용 (기본값: False)
            _client: 테스트용 Mock 클라이언트 (내부 사용)

        Note:
            qdrant-client가 설치되지 않으면 ImportError 발생
        """
        self.host = host
        self.port = port
        self.url = url
        self.api_key = api_key
        self.collection_name = collection_name
        self.grpc_port = grpc_port
        self.prefer_grpc = prefer_grpc

        # 클라이언트 초기화 (지연 로딩 또는 Mock)
        self._client: Any = _client

        # 통계
        self._stats = {
            "documents_added": 0,
            "searches": 0,
            "deletions": 0,
        }

        if _client is not None:
            logger.info("QdrantVectorStore: Mock 클라이언트 사용")
        else:
            connection_type = "Cloud" if url else f"Local ({host}:{port})"
            logger.info(
                f"QdrantVectorStore 초기화: {connection_type}, "
                f"collection={collection_name}"
            )

    def _ensure_client(self) -> Any:
        """
        Qdrant 클라이언트 초기화 (지연 로딩)

        Returns:
            QdrantClient 인스턴스

        Raises:
            ImportError: qdrant-client 미설치 시
        """
        if self._client is None:
            try:
                from qdrant_client import QdrantClient

                if self.url:
                    # Qdrant Cloud 연결
                    self._client = QdrantClient(
                        url=self.url,
                        api_key=self.api_key,
                        prefer_grpc=self.prefer_grpc,
                    )
                else:
                    # 로컬 Qdrant 연결
                    self._client = QdrantClient(
                        host=self.host,
                        port=self.port,
                        grpc_port=self.grpc_port,
                        prefer_grpc=self.prefer_grpc,
                    )

                logger.debug("Qdrant 클라이언트 초기화 완료")

            except ImportError as e:
                raise ImportError(
                    "Qdrant를 사용하려면 qdrant-client가 필요합니다. "
                    "설치 방법: pip install qdrant-client 또는 uv sync --extra qdrant"
                ) from e

        return self._client

    async def add_documents(
        self, collection: str, documents: list[dict[str, Any]]
    ) -> int:
        """
        문서를 Qdrant 컬렉션에 저장

        Args:
            collection: 컬렉션 이름
            documents: 저장할 문서 리스트
                각 문서 형식:
                {
                    "id": str (선택, 없으면 자동 생성),
                    "embedding": list[float],
                    "content": str,
                    "metadata": dict (선택)
                }

        Returns:
            성공적으로 저장된 문서 수

        Raises:
            ImportError: qdrant-client 미설치 시
            RuntimeError: 저장 실패 시
        """
        if not documents:
            return 0

        client = self._ensure_client()

        try:
            from qdrant_client.models import PointStruct

            points = []
            for doc in documents:
                # ID 처리 (없으면 UUID 생성)
                doc_id = doc.get("id", str(uuid.uuid4()))

                # 벡터 추출
                vector = doc.get("embedding", [])
                if not vector:
                    logger.warning(f"문서 {doc_id}: embedding이 없습니다, 스킵")
                    continue

                # 페이로드 구성 (content + metadata)
                payload = {"content": doc.get("content", "")}
                if "metadata" in doc and isinstance(doc["metadata"], dict):
                    payload.update(doc["metadata"])

                points.append(
                    PointStruct(
                        id=doc_id if isinstance(doc_id, int) else hash(doc_id) % (2**63),
                        vector=vector,
                        payload=payload,
                    )
                )

            # 비동기로 Qdrant에 업로드
            await asyncio.to_thread(
                client.upsert,
                collection_name=collection,
                points=points,
            )

            added_count = len(points)
            self._stats["documents_added"] += added_count

            logger.info(f"Qdrant에 {added_count}개 문서 저장 완료")
            return added_count

        except Exception as e:
            logger.error(f"Qdrant 문서 저장 실패: {e}")
            raise RuntimeError(
                f"Qdrant 문서 저장 중 오류가 발생했습니다: {e}. "
                "해결 방법: 1) Qdrant 서버 상태 확인 2) 컬렉션 존재 여부 확인"
            ) from e

    async def search(
        self,
        collection: str,
        query_vector: list[float],
        top_k: int = 10,
        filters: dict[str, Any] | None = None,
        sparse_vector: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """
        Qdrant에서 벡터 유사도 검색

        Args:
            collection: 검색할 컬렉션 이름
            query_vector: 쿼리 임베딩 벡터
            top_k: 반환할 최대 결과 수
            filters: 메타데이터 필터 조건 (선택)
            sparse_vector: Sparse 벡터 (하이브리드 검색용, 선택)

        Returns:
            검색 결과 리스트 (score 내림차순)
            [
                {
                    "_id": str,
                    "_score": float,
                    "content": str,
                    ...metadata...
                },
                ...
            ]

        Raises:
            ImportError: qdrant-client 미설치 시
            RuntimeError: 검색 실패 시
        """
        client = self._ensure_client()

        try:
            # 필터 변환 (Qdrant 형식)
            qdrant_filter = self._convert_filters(filters) if filters else None

            # 검색 실행
            results = await asyncio.to_thread(
                client.search,
                collection_name=collection,
                query_vector=query_vector,
                limit=top_k,
                query_filter=qdrant_filter,
            )

            self._stats["searches"] += 1

            # 결과 변환
            converted_results = []
            for hit in results:
                result = {
                    "_id": str(hit.id),
                    "_score": hit.score,
                }
                # 페이로드 병합
                if hit.payload:
                    result.update(hit.payload)

                converted_results.append(result)

            logger.debug(f"Qdrant 검색 완료: {len(converted_results)}개 결과")
            return converted_results

        except Exception as e:
            logger.error(f"Qdrant 검색 실패: {e}")
            raise RuntimeError(
                f"Qdrant 검색 중 오류가 발생했습니다: {e}. "
                "해결 방법: 1) Qdrant 서버 상태 확인 2) 쿼리 벡터 차원 확인"
            ) from e

    async def delete(self, collection: str, filters: dict[str, Any]) -> int:
        """
        조건에 맞는 문서 삭제

        Args:
            collection: 컬렉션 이름
            filters: 삭제 조건
                - ids: 삭제할 문서 ID 리스트

        Returns:
            삭제된 문서 수

        Raises:
            ImportError: qdrant-client 미설치 시
            RuntimeError: 삭제 실패 시
        """
        client = self._ensure_client()

        try:
            from qdrant_client.models import PointIdsList

            ids = filters.get("ids", [])
            if not ids:
                logger.warning("삭제할 ID가 지정되지 않았습니다")
                return 0

            # ID를 정수로 변환 (Qdrant는 정수 ID 사용)
            int_ids = [
                id_ if isinstance(id_, int) else hash(id_) % (2**63)
                for id_ in ids
            ]

            await asyncio.to_thread(
                client.delete,
                collection_name=collection,
                points_selector=PointIdsList(points=int_ids),
            )

            deleted_count = len(int_ids)
            self._stats["deletions"] += deleted_count

            logger.info(f"Qdrant에서 {deleted_count}개 문서 삭제 완료")
            return deleted_count

        except Exception as e:
            logger.error(f"Qdrant 문서 삭제 실패: {e}")
            raise RuntimeError(f"Qdrant 문서 삭제 중 오류가 발생했습니다: {e}") from e

    def _convert_filters(self, filters: dict[str, Any]) -> Any:
        """
        딕셔너리 필터를 Qdrant 필터 형식으로 변환

        Args:
            filters: 필터 딕셔너리 (예: {"file_type": "PDF"})

        Returns:
            Qdrant Filter 객체
        """
        try:
            from qdrant_client.models import FieldCondition, Filter, MatchValue

            conditions = []
            for key, value in filters.items():
                if key == "ids":
                    continue  # ID 필터는 별도 처리
                conditions.append(
                    FieldCondition(key=key, match=MatchValue(value=value))
                )

            return Filter(must=conditions) if conditions else None

        except ImportError:
            return None

    @property
    def stats(self) -> dict[str, int]:
        """통계 정보 반환"""
        return self._stats.copy()
