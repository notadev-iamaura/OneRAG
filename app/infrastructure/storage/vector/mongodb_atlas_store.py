"""
MongoDB Atlas Vector Store - 클라우드 기반 벡터 데이터베이스

주요 기능:
- IVectorStore 인터페이스 구현
- Dense 벡터 검색 지원
- MongoDB Atlas Vector Search 활용
- 클라우드 기반 관리형 서비스

의존성:
- pymongo: pip install pymongo (선택적)
- MongoDB Atlas 계정 및 Vector Search 인덱스 필요

Note:
    pymongo가 설치되지 않은 환경에서는 ImportError가 발생합니다.
    선택적 의존성이므로 필요한 경우에만 설치하세요.
"""

from __future__ import annotations

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


class MongoDBAtlasStore(IVectorStore):
    """
    MongoDB Atlas 벡터 스토어 구현

    MongoDB Atlas 특징:
    - 클라우드 관리형 벡터 데이터베이스
    - Atlas Vector Search로 ANN 검색
    - 유연한 스키마 (BSON)
    - 전 세계 배포 지원

    사용 예시:
        store = MongoDBAtlasStore(
            connection_string="mongodb+srv://user:pass@cluster.mongodb.net",
            database_name="rag_db",
            collection_name="documents",
            index_name="vector_index"
        )

    Note:
        Atlas Vector Search 인덱스가 미리 생성되어 있어야 합니다.
    """

    def __init__(
        self,
        connection_string: str,
        database_name: str = "rag_vectors",
        collection_name: str = "documents",
        index_name: str = "vector_index",
        embedding_field: str = "embedding",
        _client: Any | None = None,  # 테스트용 Mock 주입
    ) -> None:
        """
        MongoDBAtlasStore 초기화

        Args:
            connection_string: MongoDB Atlas 연결 문자열
                (예: "mongodb+srv://user:pass@cluster.mongodb.net")
            database_name: 데이터베이스 이름 (기본값: "rag_vectors")
            collection_name: 컬렉션 이름 (기본값: "documents")
            index_name: Vector Search 인덱스 이름 (기본값: "vector_index")
            embedding_field: 벡터 필드 이름 (기본값: "embedding")
            _client: 테스트용 Mock 클라이언트 (내부 사용)

        Note:
            pymongo가 설치되지 않으면 ImportError 발생
        """
        self.connection_string = connection_string
        self.database_name = database_name
        self.collection_name = collection_name
        self.index_name = index_name
        self.embedding_field = embedding_field

        # 클라이언트 초기화 (지연 로딩 또는 Mock)
        self._client: Any = _client

        # 통계
        self._stats = {
            "documents_added": 0,
            "searches": 0,
            "deletions": 0,
        }

        if _client is not None:
            logger.info("MongoDBAtlasStore: Mock 클라이언트 사용")
        else:
            logger.info(
                f"MongoDBAtlasStore 초기화: db={database_name}, "
                f"collection={collection_name}, index={index_name}"
            )

    def _ensure_client(self) -> Any:
        """
        MongoDB 클라이언트 초기화 (지연 로딩)

        Returns:
            MongoClient 인스턴스

        Raises:
            ImportError: pymongo 미설치 시
        """
        if self._client is None:
            try:
                from pymongo import MongoClient

                self._client = MongoClient(self.connection_string)
                logger.debug("MongoDB 클라이언트 초기화 완료")

            except ImportError as e:
                raise ImportError(
                    "MongoDB Atlas를 사용하려면 pymongo가 필요합니다. "
                    "설치 방법: pip install pymongo 또는 uv sync --extra mongodb"
                ) from e

        return self._client

    def _get_collection(self, collection_name: str | None = None) -> Any:
        """
        컬렉션 객체 반환

        Args:
            collection_name: 컬렉션 이름 (None이면 기본 컬렉션 사용)

        Returns:
            MongoDB Collection 객체
        """
        client = self._ensure_client()
        db = client[self.database_name]
        return db[collection_name or self.collection_name]

    async def add_documents(
        self, collection: str, documents: list[dict[str, Any]]
    ) -> int:
        """
        문서를 MongoDB Atlas 컬렉션에 저장

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
            ImportError: pymongo 미설치 시
            RuntimeError: 저장 실패 시
        """
        if not documents:
            return 0

        coll = self._get_collection(collection)

        try:
            added_count = 0

            for doc in documents:
                # ID 처리 (없으면 UUID 생성)
                doc_id = doc.get("id", str(uuid.uuid4()))

                # 벡터 추출
                vector = doc.get("embedding", [])
                if not vector:
                    logger.warning(f"문서 {doc_id}: embedding이 없습니다, 스킵")
                    continue

                # MongoDB 문서 구성
                mongo_doc = {
                    "_id": doc_id,
                    "content": doc.get("content", ""),
                    self.embedding_field: vector,
                    "metadata": doc.get("metadata", {}),
                }

                # UPSERT (있으면 업데이트, 없으면 삽입)
                coll.update_one(
                    {"_id": doc_id},
                    {"$set": mongo_doc},
                    upsert=True,
                )
                added_count += 1

            self._stats["documents_added"] += added_count

            logger.info(f"MongoDB Atlas에 {added_count}개 문서 저장 완료")
            return added_count

        except Exception as e:
            logger.error(f"MongoDB Atlas 문서 저장 실패: {e}")
            raise RuntimeError(
                f"MongoDB Atlas 문서 저장 중 오류가 발생했습니다: {e}. "
                "해결 방법: 1) MongoDB Atlas 연결 확인 2) 컬렉션 권한 확인"
            ) from e

    async def search(
        self,
        collection: str,
        query_vector: list[float],
        top_k: int = 10,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """
        MongoDB Atlas에서 벡터 유사도 검색

        Atlas Vector Search aggregation pipeline을 사용합니다.

        Args:
            collection: 검색할 컬렉션 이름
            query_vector: 쿼리 임베딩 벡터
            top_k: 반환할 최대 결과 수
            filters: 메타데이터 필터 조건 (선택)

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
            ImportError: pymongo 미설치 시
            RuntimeError: 검색 실패 시
        """
        coll = self._get_collection(collection)

        try:
            # Vector Search aggregation pipeline 구성
            pipeline: list[dict[str, Any]] = [
                {
                    "$vectorSearch": {
                        "index": self.index_name,
                        "path": self.embedding_field,
                        "queryVector": query_vector,
                        "numCandidates": top_k * 10,  # 후보 수 (top_k의 10배 권장)
                        "limit": top_k,
                    }
                },
                {
                    "$project": {
                        "_id": 1,
                        "content": 1,
                        "metadata": 1,
                        "score": {"$meta": "vectorSearchScore"},
                    }
                },
            ]

            # 필터가 있는 경우 $match 스테이지 추가
            if filters:
                match_conditions: dict[str, Any] = {}
                for key, value in filters.items():
                    if key == "ids":
                        continue  # ID 필터는 별도 처리
                    match_conditions[f"metadata.{key}"] = value

                if match_conditions:
                    # $vectorSearch 뒤에 $match 추가
                    pipeline.insert(1, {"$match": match_conditions})

            # 검색 실행
            results = list(coll.aggregate(pipeline))

            self._stats["searches"] += 1

            # 결과 변환
            converted_results = []
            for doc in results:
                result: dict[str, Any] = {
                    "_id": str(doc.get("_id", "")),
                    "_score": float(doc.get("score", 0.0)),
                    "content": doc.get("content", ""),
                }
                # 메타데이터 병합
                if "metadata" in doc and isinstance(doc["metadata"], dict):
                    result.update(doc["metadata"])

                converted_results.append(result)

            logger.debug(f"MongoDB Atlas 검색 완료: {len(converted_results)}개 결과")
            return converted_results

        except Exception as e:
            logger.error(f"MongoDB Atlas 검색 실패: {e}")
            raise RuntimeError(
                f"MongoDB Atlas 검색 중 오류가 발생했습니다: {e}. "
                "해결 방법: 1) Vector Search 인덱스 확인 2) 쿼리 벡터 차원 확인"
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
            ImportError: pymongo 미설치 시
            RuntimeError: 삭제 실패 시
        """
        coll = self._get_collection(collection)

        try:
            ids = filters.get("ids", [])
            if not ids:
                logger.warning("삭제할 ID가 지정되지 않았습니다")
                return 0

            # ID 리스트로 삭제
            result = coll.delete_many({"_id": {"$in": ids}})
            deleted_count = int(result.deleted_count)

            self._stats["deletions"] += deleted_count

            logger.info(f"MongoDB Atlas에서 {deleted_count}개 문서 삭제 완료")
            return deleted_count

        except Exception as e:
            logger.error(f"MongoDB Atlas 문서 삭제 실패: {e}")
            raise RuntimeError(
                f"MongoDB Atlas 문서 삭제 중 오류가 발생했습니다: {e}"
            ) from e

    @property
    def stats(self) -> dict[str, int]:
        """통계 정보 반환"""
        return self._stats.copy()

    def close(self) -> None:
        """연결 종료"""
        if self._client is not None:
            self._client.close()
            self._client = None
            logger.debug("MongoDB 연결 종료")
