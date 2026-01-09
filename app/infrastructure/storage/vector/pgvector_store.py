"""
pgvector Vector Store - PostgreSQL 벡터 확장

주요 기능:
- IVectorStore 인터페이스 구현
- Dense 벡터 검색 지원
- PostgreSQL 기반 안정적인 벡터 저장
- 기존 PostgreSQL 인프라 활용 가능

의존성:
- psycopg[binary]: pip install "psycopg[binary]" (선택적)
- pgvector 확장: PostgreSQL에 설치 필요

Note:
    psycopg가 설치되지 않은 환경에서는 ImportError가 발생합니다.
    선택적 의존성이므로 필요한 경우에만 설치하세요.
"""

from __future__ import annotations

import json
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


class PgVectorStore(IVectorStore):
    """
    pgvector 벡터 스토어 구현

    pgvector 특징:
    - PostgreSQL 확장으로 안정적인 벡터 저장
    - 기존 PostgreSQL 인프라 활용 가능
    - 트랜잭션 및 ACID 지원
    - SQL 기반 필터링 지원

    사용 예시:
        # 직접 연결
        store = PgVectorStore(
            host="localhost",
            port=5432,
            database="vectors",
            user="postgres",
            password="password",
            table_name="documents"
        )

        # DSN으로 연결
        store = PgVectorStore(
            dsn="postgresql://postgres:password@localhost:5432/vectors",
            table_name="documents"
        )
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 5432,
        database: str = "vectors",
        user: str = "postgres",
        password: str = "",
        dsn: str | None = None,
        table_name: str = "documents",
        vector_dimension: int = 1024,
        _connection: Any | None = None,  # 테스트용 Mock 주입
    ) -> None:
        """
        PgVectorStore 초기화

        Args:
            host: PostgreSQL 서버 호스트 (기본값: "localhost")
            port: PostgreSQL 포트 (기본값: 5432)
            database: 데이터베이스 이름 (기본값: "vectors")
            user: 사용자 이름 (기본값: "postgres")
            password: 비밀번호
            dsn: 전체 연결 문자열 (설정 시 host/port/database/user/password 무시)
            table_name: 벡터 테이블 이름 (기본값: "documents")
            vector_dimension: 벡터 차원 (기본값: 1024)
            _connection: 테스트용 Mock 연결 (내부 사용)

        Note:
            psycopg가 설치되지 않으면 ImportError 발생
        """
        self.host = host
        self.port = port
        self.database = database
        self.user = user
        self.password = password
        self.dsn = dsn
        self.table_name = table_name
        self.vector_dimension = vector_dimension

        # 연결 초기화 (지연 로딩 또는 Mock)
        self._connection: Any = _connection

        # 통계
        self._stats = {
            "documents_added": 0,
            "searches": 0,
            "deletions": 0,
        }

        if _connection is not None:
            logger.info("PgVectorStore: Mock 연결 사용")
        else:
            connection_info = dsn if dsn else f"{host}:{port}/{database}"
            logger.info(
                f"PgVectorStore 초기화: {connection_info}, "
                f"table={table_name}, dim={vector_dimension}"
            )

    def _ensure_connection(self) -> Any:
        """
        PostgreSQL 연결 초기화 (지연 로딩)

        Returns:
            psycopg 연결 인스턴스

        Raises:
            ImportError: psycopg 미설치 시
        """
        if self._connection is None:
            try:
                import psycopg

                if self.dsn:
                    # DSN으로 연결
                    self._connection = psycopg.connect(self.dsn)
                else:
                    # 개별 파라미터로 연결
                    self._connection = psycopg.connect(
                        host=self.host,
                        port=self.port,
                        dbname=self.database,
                        user=self.user,
                        password=self.password,
                    )

                logger.debug("PostgreSQL 연결 초기화 완료")

            except ImportError as e:
                raise ImportError(
                    "pgvector를 사용하려면 psycopg가 필요합니다. "
                    "설치 방법: pip install 'psycopg[binary]' 또는 uv sync --extra pgvector"
                ) from e

        return self._connection

    async def add_documents(
        self, collection: str, documents: list[dict[str, Any]]
    ) -> int:
        """
        문서를 pgvector 테이블에 저장

        Args:
            collection: 테이블 이름 (또는 참조용 컬렉션 이름)
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
            ImportError: psycopg 미설치 시
            RuntimeError: 저장 실패 시
        """
        if not documents:
            return 0

        conn = self._ensure_connection()

        try:
            added_count = 0

            with conn.cursor() as cursor:
                for doc in documents:
                    # ID 처리 (없으면 UUID 생성)
                    doc_id = doc.get("id", str(uuid.uuid4()))

                    # 벡터 추출
                    vector = doc.get("embedding", [])
                    if not vector:
                        logger.warning(f"문서 {doc_id}: embedding이 없습니다, 스킵")
                        continue

                    # 콘텐츠 및 메타데이터 추출
                    content = doc.get("content", "")
                    metadata = doc.get("metadata", {})
                    metadata_json = json.dumps(metadata, ensure_ascii=False)

                    # INSERT 또는 UPDATE (UPSERT)
                    cursor.execute(
                        f"""
                        INSERT INTO {self.table_name} (id, content, embedding, metadata)
                        VALUES (%s, %s, %s::vector, %s::jsonb)
                        ON CONFLICT (id) DO UPDATE SET
                            content = EXCLUDED.content,
                            embedding = EXCLUDED.embedding,
                            metadata = EXCLUDED.metadata
                        """,
                        (doc_id, content, str(vector), metadata_json),
                    )
                    added_count += 1

                conn.commit()

            self._stats["documents_added"] += added_count

            logger.info(f"pgvector에 {added_count}개 문서 저장 완료")
            return added_count

        except Exception as e:
            conn.rollback()
            logger.error(f"pgvector 문서 저장 실패: {e}")
            raise RuntimeError(
                f"pgvector 문서 저장 중 오류가 발생했습니다: {e}. "
                "해결 방법: 1) PostgreSQL 서버 상태 확인 2) 테이블 존재 여부 확인 "
                "3) pgvector 확장 설치 확인"
            ) from e

    async def search(
        self,
        collection: str,
        query_vector: list[float],
        top_k: int = 10,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """
        pgvector에서 벡터 유사도 검색

        Args:
            collection: 테이블 이름 (또는 참조용 컬렉션 이름)
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
            ImportError: psycopg 미설치 시
            RuntimeError: 검색 실패 시
        """
        conn = self._ensure_connection()

        try:
            # 필터 조건 구성
            filter_clause = ""
            filter_params: list[Any] = []
            if filters:
                filter_conditions = []
                for key, value in filters.items():
                    if key == "ids":
                        continue  # ID 필터는 별도 처리
                    filter_conditions.append(f"metadata->>'{key}' = %s")
                    filter_params.append(str(value))
                if filter_conditions:
                    filter_clause = "WHERE " + " AND ".join(filter_conditions)

            # 유사도 검색 쿼리 (코사인 거리 사용)
            query = f"""
                SELECT id, content, 1 - (embedding <=> %s::vector) as score, metadata
                FROM {self.table_name}
                {filter_clause}
                ORDER BY embedding <=> %s::vector
                LIMIT %s
            """

            with conn.cursor() as cursor:
                cursor.execute(
                    query,
                    [str(query_vector)] + filter_params + [str(query_vector), top_k],
                )
                results = cursor.fetchall()

            self._stats["searches"] += 1

            # 결과 변환
            converted_results = []
            for row in results:
                doc_id, content, score, metadata = row
                result: dict[str, Any] = {
                    "_id": str(doc_id),
                    "_score": float(score),
                    "content": content,
                }
                # 메타데이터 병합
                if metadata:
                    if isinstance(metadata, str):
                        metadata = json.loads(metadata)
                    result.update(metadata)

                converted_results.append(result)

            logger.debug(f"pgvector 검색 완료: {len(converted_results)}개 결과")
            return converted_results

        except Exception as e:
            logger.error(f"pgvector 검색 실패: {e}")
            raise RuntimeError(
                f"pgvector 검색 중 오류가 발생했습니다: {e}. "
                "해결 방법: 1) PostgreSQL 서버 상태 확인 2) 쿼리 벡터 차원 확인"
            ) from e

    async def delete(self, collection: str, filters: dict[str, Any]) -> int:
        """
        조건에 맞는 문서 삭제

        Args:
            collection: 테이블 이름
            filters: 삭제 조건
                - ids: 삭제할 문서 ID 리스트

        Returns:
            삭제된 문서 수

        Raises:
            ImportError: psycopg 미설치 시
            RuntimeError: 삭제 실패 시
        """
        conn = self._ensure_connection()

        try:
            ids = filters.get("ids", [])
            if not ids:
                logger.warning("삭제할 ID가 지정되지 않았습니다")
                return 0

            with conn.cursor() as cursor:
                # ID 리스트로 삭제
                placeholders = ",".join(["%s"] * len(ids))
                cursor.execute(
                    f"DELETE FROM {self.table_name} WHERE id IN ({placeholders})",
                    ids,
                )
                deleted_count = len(ids)
                conn.commit()

            self._stats["deletions"] += deleted_count

            logger.info(f"pgvector에서 {deleted_count}개 문서 삭제 완료")
            return deleted_count

        except Exception as e:
            conn.rollback()
            logger.error(f"pgvector 문서 삭제 실패: {e}")
            raise RuntimeError(f"pgvector 문서 삭제 중 오류가 발생했습니다: {e}") from e

    async def create_table_if_not_exists(self) -> None:
        """
        pgvector 테이블 생성 (없는 경우)

        테이블 스키마:
        - id: TEXT PRIMARY KEY
        - content: TEXT
        - embedding: vector(dimension)
        - metadata: JSONB
        - created_at: TIMESTAMP
        """
        conn = self._ensure_connection()

        try:
            with conn.cursor() as cursor:
                # pgvector 확장 활성화
                cursor.execute("CREATE EXTENSION IF NOT EXISTS vector")

                # 테이블 생성
                cursor.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS {self.table_name} (
                        id TEXT PRIMARY KEY,
                        content TEXT,
                        embedding vector({self.vector_dimension}),
                        metadata JSONB DEFAULT '{{}}',
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )

                # 벡터 인덱스 생성 (IVFFlat)
                cursor.execute(
                    f"""
                    CREATE INDEX IF NOT EXISTS {self.table_name}_embedding_idx
                    ON {self.table_name}
                    USING ivfflat (embedding vector_cosine_ops)
                    WITH (lists = 100)
                    """
                )

                conn.commit()

            logger.info(f"pgvector 테이블 생성 완료: {self.table_name}")

        except Exception as e:
            conn.rollback()
            logger.error(f"pgvector 테이블 생성 실패: {e}")
            raise

    @property
    def stats(self) -> dict[str, int]:
        """통계 정보 반환"""
        return self._stats.copy()

    def close(self) -> None:
        """연결 종료"""
        if self._connection is not None:
            self._connection.close()
            self._connection = None
            logger.debug("PostgreSQL 연결 종료")
