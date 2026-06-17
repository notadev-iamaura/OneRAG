"""
Chroma Vector Store Adapter

IVectorStore 인터페이스를 구현한 ChromaDB 어댑터입니다.
Chroma는 경량 벡터 DB로, 로컬 개발과 테스트에 최적화되어 있습니다.

주요 기능:
- in-memory 및 persistent 모드 지원
- 동기 API를 asyncio.to_thread로 비동기 래핑
- IVectorStore 인터페이스 완전 구현

의존성:
- chromadb: pip install chromadb
"""

import asyncio
import json
from collections.abc import Sequence
from typing import Any

import chromadb
from chromadb.config import Settings

from app.core.interfaces.storage import IVectorStore
from app.lib.logger import get_logger

logger = get_logger(__name__)


def _restore_metadata_json(item: dict[str, Any]) -> None:
    """add_documents에서 metadata_json으로 직렬화된 비기본 메타데이터를 복원한다.

    Chroma는 기본 타입만 저장하므로 list/dict 같은 값은 metadata_json 문자열로 보관된다.
    읽기 시 이를 역직렬화해 원래 키를 복원하고, 불투명한 metadata_json 키는 제거해
    클라이언트로 누출되지 않게 한다(검색/조회 라운드트립 정합).
    """
    raw = item.pop("metadata_json", None)
    if not isinstance(raw, str):
        return
    try:
        restored = json.loads(raw)
    except (ValueError, TypeError):
        return
    if isinstance(restored, dict):
        for key, value in restored.items():
            item.setdefault(key, value)


class ChromaVectorStore(IVectorStore):
    """
    ChromaDB 기반 벡터 스토어 구현체.

    IVectorStore 인터페이스를 구현하여 벡터 저장, 검색, 삭제 기능을 제공합니다.
    Chroma의 동기 API를 asyncio.to_thread로 래핑하여 비동기로 사용 가능합니다.

    사용 예시:
        # in-memory 모드 (기본)
        store = ChromaVectorStore()

        # persistent 모드
        store = ChromaVectorStore(persist_directory="/path/to/data")

        # 원격 서버 모드
        store = ChromaVectorStore(host="localhost", port=8000)
    """

    def __init__(
        self,
        persist_directory: str | None = None,
        host: str | None = None,
        port: int = 8000,
    ) -> None:
        """
        ChromaVectorStore 초기화.

        Args:
            persist_directory: 데이터 저장 경로. None이면 in-memory 모드.
            host: 원격 Chroma 서버 호스트. 설정 시 HTTP 클라이언트 사용.
            port: 원격 Chroma 서버 포트. 기본값 8000.
        """
        self.persist_directory = persist_directory
        self.host = host
        self.port = port

        # Chroma 클라이언트 초기화
        if host:
            # 원격 서버 모드
            self._client = chromadb.HttpClient(host=host, port=port)
            logger.info(f"ChromaVectorStore: 원격 서버 연결 ({host}:{port})")
        elif persist_directory:
            # Persistent 모드
            self._client = chromadb.PersistentClient(
                path=persist_directory,
                settings=Settings(anonymized_telemetry=False),
            )
            logger.info(f"ChromaVectorStore: Persistent 모드 ({persist_directory})")
        else:
            # In-memory 모드 (기본)
            self._client = chromadb.Client(
                settings=Settings(anonymized_telemetry=False),
            )
            logger.info("ChromaVectorStore: In-memory 모드")

    async def add_documents(
        self, collection: str, documents: list[dict[str, Any]]
    ) -> int:
        """
        문서(벡터 포함) 저장 (Upsert).

        동일 ID의 문서가 있으면 업데이트, 없으면 추가합니다.

        Args:
            collection: 컬렉션 이름
            documents: 문서 리스트. 각 문서는 {"id": str, "vector": list[float], "metadata": dict} 형식

        Returns:
            저장된 문서 개수
        """
        if not documents:
            return 0

        def _add_sync() -> int:
            # 컬렉션 가져오기 (없으면 생성)
            col = self._client.get_or_create_collection(
                name=collection,
                metadata={"hnsw:space": "cosine"},
            )

            # 문서 데이터 분리
            ids: list[str] = []
            embeddings: list[Sequence[float]] = []
            metadatas: list[dict[str, str | int | float | bool]] = []
            contents: list[str] = []

            for doc in documents:
                doc_id = str(doc.get("id", ""))
                # vector/embedding/dense_embedding 호환 입력 허용(동일 패턴)
                vector: Sequence[float] = (
                    doc.get("vector")
                    or doc.get("embedding")
                    or doc.get("dense_embedding")
                    or []
                )
                raw_metadata: dict[str, Any] = doc.get("metadata", {})
                # 검색이 본문을 반환할 수 있도록 content를 chroma documents로 저장한다.
                content = str(
                    doc.get("content")
                    or doc.get("page_content")
                    or raw_metadata.get("content")
                    or ""
                )

                if not doc_id or not vector:
                    continue

                # Chroma는 빈 메타데이터를 허용하지 않음
                # 빈 경우 기본 필드 추가
                if not raw_metadata:
                    raw_metadata = {"_source": "chroma_store"}

                # Chroma 메타데이터는 기본 타입만 허용. 비기본 타입은 metadata_json으로 보존.
                metadata: dict[str, str | int | float | bool] = {
                    k: v for k, v in raw_metadata.items()
                    if isinstance(v, str | int | float | bool)
                }
                if any(not isinstance(v, str | int | float | bool) for v in raw_metadata.values()):
                    metadata["metadata_json"] = json.dumps(raw_metadata, ensure_ascii=False, default=str)
                if not metadata:
                    metadata = {"_source": "chroma_store"}

                ids.append(doc_id)
                embeddings.append(vector)
                metadatas.append(metadata)
                contents.append(content)

            if not ids:
                return 0

            # Upsert (추가 또는 업데이트). 본문(documents)도 함께 저장.
            # mypy와 chromadb 타입 시스템 간 호환성 문제로 ignore 처리
            col.upsert(
                ids=ids,
                embeddings=embeddings,
                metadatas=metadatas,
                documents=contents,
            )

            return len(ids)

        try:
            count = await asyncio.to_thread(_add_sync)
            logger.debug(f"ChromaVectorStore: {count}개 문서 저장 완료 (collection={collection})")
            return count
        except Exception as e:
            logger.error(f"ChromaVectorStore: 문서 저장 실패 - {e}")
            raise RuntimeError(
                f"문서 저장 중 오류가 발생했습니다: {len(documents)}개 문서. "
                "해결 방법: 1) 문서 형식을 확인하세요 (id, vector, metadata 필수). "
                "2) 벡터 차원이 일치하는지 확인하세요. "
                "3) Chroma 로그를 확인하세요."
            ) from e

    async def search(
        self,
        collection: str,
        query_vector: list[float],
        top_k: int,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """
        벡터 유사도 검색.

        Args:
            collection: 컬렉션 이름
            query_vector: 검색 쿼리 벡터
            top_k: 반환할 최대 결과 수
            filters: 메타데이터 필터 (Chroma where 절로 변환)

        Returns:
            검색 결과 리스트. 각 결과는 {"_id": str, "_distance": float, ...metadata} 형식
        """
        def _search_sync() -> list[dict[str, Any]]:
            try:
                col = self._client.get_collection(name=collection)
            except Exception:
                # 컬렉션이 없으면 빈 리스트 반환
                return []

            # Chroma where 절 구성
            where_clause: dict[str, Any] | None = None
            if filters:
                where_clause = self._build_where_clause(filters)

            # 검색 실행
            query_embedding: Sequence[float] = query_vector
            results = col.query(
                query_embeddings=[query_embedding],
                n_results=top_k,
                where=where_clause,
                include=["metadatas", "documents", "distances"],
            )

            # 결과 변환
            output: list[dict[str, Any]] = []

            if not results or not results.get("ids") or not results["ids"][0]:
                return output

            ids = results["ids"][0]
            distances_result = results.get("distances")
            metadatas_result = results.get("metadatas")
            documents_result = results.get("documents")

            # 타입 안전하게 추출
            distances: list[float] = []
            if distances_result and len(distances_result) > 0:
                distances = list(distances_result[0]) if distances_result[0] else []

            metadatas: list[dict[str, Any]] = []
            if metadatas_result and len(metadatas_result) > 0:
                raw_metadatas = metadatas_result[0]
                if raw_metadatas:
                    metadatas = [dict(m) if m else {} for m in raw_metadatas]

            documents: list[str] = []
            if documents_result and len(documents_result) > 0:
                documents = [str(d or "") for d in documents_result[0]]

            for i, doc_id in enumerate(ids):
                item: dict[str, Any] = {}

                # 메타데이터 복사
                if i < len(metadatas) and metadatas[i]:
                    item.update(metadatas[i])
                _restore_metadata_json(item)

                # 표준 필드 추가
                item["_id"] = doc_id
                item["_distance"] = distances[i] if i < len(distances) else 0.0
                # 본문(content)을 chroma documents에서 복원 (검색 결과에 포함)
                item["content"] = documents[i] if i < len(documents) else ""

                output.append(item)

            return output

        try:
            results = await asyncio.to_thread(_search_sync)
            logger.debug(
                f"ChromaVectorStore: {len(results)}개 결과 검색 완료 "
                f"(collection={collection}, top_k={top_k})"
            )
            return results
        except Exception as e:
            logger.error(f"ChromaVectorStore: 검색 실패 - {e}")
            return []

    async def delete(
        self, collection: str, filters: dict[str, Any]
    ) -> int:
        """
        조건에 맞는 문서 삭제.

        Args:
            collection: 컬렉션 이름
            filters: 삭제 조건 (id, ids, 또는 메타데이터 필터)

        Returns:
            삭제된 문서 개수
        """
        def _delete_sync() -> int:
            try:
                col = self._client.get_collection(name=collection)
            except Exception:
                # 컬렉션이 없으면 0 반환
                return 0

            # ID 기반 삭제
            if "id" in filters:
                doc_id = str(filters["id"])
                try:
                    # 존재 확인
                    existing = col.get(ids=[doc_id])
                    if not existing.get("ids"):
                        return 0

                    col.delete(ids=[doc_id])
                    return 1
                except Exception:
                    return 0

            # 여러 ID 삭제
            if "ids" in filters:
                ids_to_delete = [str(id_) for id_ in filters["ids"]]
                if not ids_to_delete:
                    return 0

                try:
                    # 존재하는 ID만 삭제
                    existing = col.get(ids=ids_to_delete)
                    existing_ids = existing.get("ids", [])

                    if not existing_ids:
                        return 0

                    col.delete(ids=existing_ids)
                    return len(existing_ids)
                except Exception:
                    return 0

            # 메타데이터 필터 기반 삭제
            where_clause = self._build_where_clause(filters)
            if where_clause:
                try:
                    # 먼저 조건에 맞는 문서 조회
                    results = col.get(where=where_clause)
                    ids_to_delete = results.get("ids", [])

                    if not ids_to_delete:
                        return 0

                    col.delete(ids=ids_to_delete)
                    return len(ids_to_delete)
                except Exception:
                    return 0

            return 0

        try:
            count = await asyncio.to_thread(_delete_sync)
            logger.debug(f"ChromaVectorStore: {count}개 문서 삭제 완료 (collection={collection})")
            return count
        except Exception as e:
            logger.error(f"ChromaVectorStore: 삭제 실패 - {e}")
            raise RuntimeError(
                "문서 삭제 중 오류가 발생했습니다. "
                "해결 방법: 1) 컬렉션 이름을 확인하세요. "
                "2) 필터 형식을 확인하세요. "
                "3) Chroma 로그를 확인하세요."
            ) from e

    async def fetch_objects(
        self,
        collection: str,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """컬렉션 객체를 메타데이터 필터로 조회한다(문서관리/인접청크 확장용).

        ChromaRetriever의 get_document_chunks/list_documents 등이 이 메서드에 위임한다
        (ChromaVectorStore 파리티 백포트).
        """

        def _fetch_sync() -> list[dict[str, Any]]:
            try:
                col = self._client.get_collection(name=collection)
            except Exception:
                return []

            filters_value = filters or {}
            ids_filter: list[str] | None = None
            if "id" in filters_value:
                ids_filter = [str(filters_value["id"])]
            elif "ids" in filters_value:
                ids_filter = [str(value) for value in filters_value["ids"]]

            where_clause = self._build_where_clause(filters_value)
            results = col.get(
                ids=ids_filter,
                where=where_clause,
                include=["metadatas", "documents"],
            )
            ids = [str(value) for value in results.get("ids", [])]
            metadatas = [
                dict(value) if value else {} for value in (results.get("metadatas") or [])
            ]
            documents = [str(value or "") for value in (results.get("documents") or [])]

            output: list[dict[str, Any]] = []
            for index, doc_id in enumerate(ids):
                item: dict[str, Any] = {}
                if index < len(metadatas):
                    item.update(metadatas[index])
                _restore_metadata_json(item)
                item["_id"] = doc_id
                item["content"] = documents[index] if index < len(documents) else ""
                output.append(item)
            return output

        try:
            return await asyncio.to_thread(_fetch_sync)
        except Exception as e:
            logger.error(f"ChromaVectorStore: 객체 조회 실패 - {e}")
            return []

    async def delete_objects(self, collection: str, object_ids: list[str]) -> int:
        """ID 목록으로 객체를 삭제한다(문서관리용)."""
        return await self.delete(collection=collection, filters={"ids": object_ids})

    def _build_where_clause(
        self, filters: dict[str, Any]
    ) -> dict[str, Any] | None:
        """
        필터 딕셔너리를 Chroma where 절로 변환.

        단순 키-값 필터만 지원합니다.
        복잡한 쿼리(and, or, 범위 등)는 Chroma 문서를 참조하세요.

        Args:
            filters: 메타데이터 필터 딕셔너리

        Returns:
            Chroma where 절 딕셔너리 또는 None
        """
        if not filters:
            return None

        # id, ids는 where 절이 아닌 별도 처리
        where_filters = {k: v for k, v in filters.items() if k not in ("id", "ids")}

        if not where_filters:
            return None

        # 단일 필터면 그대로 반환
        if len(where_filters) == 1:
            key, value = next(iter(where_filters.items()))
            return {key: value}

        # 여러 필터면 $and로 결합
        conditions = [{k: v} for k, v in where_filters.items()]
        return {"$and": conditions}

    def close(self) -> None:
        """
        리소스 정리.

        PersistentClient의 경우 데이터가 자동으로 저장됩니다.
        """
        # Chroma 클라이언트는 명시적 close가 필요하지 않지만
        # 일관성을 위해 메서드 제공
        if hasattr(self, "_client"):
            logger.debug("ChromaVectorStore: 연결 종료")

    def __del__(self) -> None:
        """소멸자에서 리소스 정리."""
        self.close()
