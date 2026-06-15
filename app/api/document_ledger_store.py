"""문서 수명주기 원장 (lineage + audit + soft-delete).

업로드 원본 → 페이지 → 청크 → 삭제 이력을 하나의 영속 원장에 기록하기 위한
모듈입니다. 의존성 0(파이썬 표준 라이브러리 sqlite3만 사용)을 원칙으로 하며,
기본 백엔드는 SQLite(WAL)입니다.

주요 구성:
    - SQLiteDocumentLedgerStore: 문서/원본파일/페이지/청크/감사 5테이블 원장
    - create_uploaded_document: 업로드 시 원본 + 문서 행 생성(멱등 upsert)
    - replace_pages/replace_chunks: 재처리 시 멱등 교체(누적 방지)
    - find_source_chunk: source_id 기반 출처 역조회(PDF 인용/소스 상세용)
    - tombstone_document: soft-delete(deleted_at) + 로컬 원본 파일 정리
    - mark_status: 처리 상태 전이 + 감사 이벤트 기록

설계 노트:
    - JapanRAG 원장의 멀티테넌트(company_id) 결합을 OneRAG 단일 테넌트에 맞춰
      전면 제거했다(companies 테이블 삭제, documents PK = document_id 단독).
    - BEGIN IMMEDIATE + ON CONFLICT upsert로 동시 재처리에 안전하다.

의존성: 표준 라이브러리(sqlite3, json)만 사용. 외부 패키지 없음.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4


class SQLiteDocumentLedgerStore:
    """로컬 SQLite 문서 수명주기 원장(단일 테넌트).

    업로드된 원본/페이지/청크/감사 메타데이터를 프로덕션 의존성 없이 보존한다.
    민감한 로컬 경로는 SQLite 내부에만 보관하며, 공개 API 형태 가공은 업로드
    라우터의 책임이다.
    """

    def __init__(self, path: Path) -> None:
        """원장을 초기화한다.

        Args:
            path: SQLite 데이터베이스 파일 경로.
        """
        self.path = path

    def create_uploaded_document(
        self,
        *,
        document_id: str,
        filename: str,
        file_type: str,
        file_size: int,
        original_file_path: str,
        source_uri: str | None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """업로드 문서와 원본 파일 메타를 생성한다(재업로드 시 멱등 upsert).

        Args:
            document_id: 문서 식별자(업로드 job_id와 동일하게 사용).
            filename: 원본 파일명.
            file_type: 파일 확장자/타입.
            file_size: 파일 크기(바이트).
            original_file_path: 보관된 원본 파일의 로컬 경로(또는 외부 참조).
            source_uri: 원본 소스 URI(없으면 None).
            metadata: 추가 문서 메타데이터.
        """
        now = _now()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            self._ensure_schema(connection)
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                INSERT INTO documents (
                    document_id, filename, file_type, file_size, status,
                    chunk_count, processing_time, extraction_summary, metadata,
                    created_at, updated_at, deleted_at
                )
                VALUES (?, ?, ?, ?, 'pending', NULL, NULL, NULL, ?, ?, ?, NULL)
                ON CONFLICT(document_id) DO UPDATE SET
                    filename = excluded.filename,
                    file_type = excluded.file_type,
                    file_size = excluded.file_size,
                    status = 'pending',
                    metadata = excluded.metadata,
                    updated_at = excluded.updated_at,
                    deleted_at = NULL
                """,
                (
                    document_id,
                    filename,
                    file_type,
                    file_size,
                    _json_dumps(metadata or {}),
                    now,
                    now,
                ),
            )
            connection.execute(
                """
                INSERT INTO document_files (
                    file_id, document_id, file_role, filename, file_type,
                    file_size, local_path, source_uri, status, created_at, deleted_at
                )
                VALUES (?, ?, 'original', ?, ?, ?, ?, ?, 'active', ?, NULL)
                ON CONFLICT(document_id, file_role) DO UPDATE SET
                    filename = excluded.filename,
                    file_type = excluded.file_type,
                    file_size = excluded.file_size,
                    local_path = excluded.local_path,
                    source_uri = excluded.source_uri,
                    status = 'active',
                    deleted_at = NULL
                """,
                (
                    str(uuid4()),
                    document_id,
                    filename,
                    file_type,
                    file_size,
                    original_file_path,
                    source_uri,
                    now,
                ),
            )
            self._record_audit_event(
                connection,
                document_id=document_id,
                event_type="uploaded",
                metadata={"filename": filename, "file_size": file_size},
                created_at=now,
            )
            connection.commit()

    def mark_status(
        self,
        *,
        document_id: str,
        status: str,
        chunk_count: int | None = None,
        processing_time: float | None = None,
        extraction_summary: dict[str, Any] | None = None,
        error_message: str | None = None,
    ) -> bool:
        """문서 처리 상태를 전이하고 감사 이벤트를 남긴다.

        Returns:
            대상 문서가 존재(미삭제)하면 True, 없으면 False.
        """
        now = _now()
        with self._connect() as connection:
            self._ensure_schema(connection)
            connection.execute("BEGIN IMMEDIATE")
            row = self._get_document_row(connection, document_id=document_id)
            if row is None:
                connection.rollback()
                return False
            existing_summary = _json_loads(row["extraction_summary"])
            summary = extraction_summary if extraction_summary is not None else existing_summary
            connection.execute(
                """
                UPDATE documents
                SET status = ?,
                    chunk_count = COALESCE(?, chunk_count),
                    processing_time = COALESCE(?, processing_time),
                    extraction_summary = ?,
                    updated_at = ?
                WHERE document_id = ? AND deleted_at IS NULL
                """,
                (
                    status,
                    chunk_count,
                    processing_time,
                    _json_dumps(summary) if summary is not None else None,
                    now,
                    document_id,
                ),
            )
            self._record_audit_event(
                connection,
                document_id=document_id,
                event_type=f"status:{status}",
                metadata={"error_message": error_message} if error_message else {},
                created_at=now,
            )
            connection.commit()
        return True

    def replace_pages(
        self,
        *,
        document_id: str,
        documents: list[Any],
    ) -> bool:
        """문서 페이지 레코드를 멱등 교체한다(기존 삭제 후 재삽입).

        Returns:
            대상 문서가 존재(미삭제)하면 True, 없으면 False.
        """
        now = _now()
        with self._connect() as connection:
            self._ensure_schema(connection)
            connection.execute("BEGIN IMMEDIATE")
            if self._get_document_row(connection, document_id=document_id) is None:
                connection.rollback()
                return False
            connection.execute(
                "DELETE FROM document_pages WHERE document_id = ?",
                (document_id,),
            )
            for sequence_id, document in enumerate(documents, start=1):
                metadata = _metadata_from_document(document)
                page_number = _page_number(metadata, sequence_id)
                page_content = str(getattr(document, "page_content", "") or "")
                connection.execute(
                    """
                    INSERT INTO document_pages (
                        page_id, document_id, page_number, content_preview,
                        metadata, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(uuid4()),
                        document_id,
                        page_number,
                        page_content[:1000],
                        _json_dumps(metadata),
                        now,
                    ),
                )
            self._record_audit_event(
                connection,
                document_id=document_id,
                event_type="pages_recorded",
                metadata={"page_count": len(documents)},
                created_at=now,
            )
            connection.commit()
        return True

    def replace_chunks(
        self,
        *,
        document_id: str,
        chunks: list[dict[str, Any]],
    ) -> bool:
        """문서 청크 레코드를 멱등 교체한다(출처 역조회용 source_id 부여).

        Returns:
            대상 문서가 존재(미삭제)하면 True, 없으면 False.
        """
        now = _now()
        with self._connect() as connection:
            self._ensure_schema(connection)
            connection.execute("BEGIN IMMEDIATE")
            if self._get_document_row(connection, document_id=document_id) is None:
                connection.rollback()
                return False
            connection.execute(
                "DELETE FROM document_chunks WHERE document_id = ?",
                (document_id,),
            )
            for sequence_id, chunk in enumerate(chunks):
                metadata = dict(chunk.get("metadata") or {})
                metadata["document_id"] = document_id
                page_number = _page_number(metadata, None)
                chunk_index = _chunk_index(metadata, sequence_id)
                metadata.setdefault("chunk_index", chunk_index)
                if page_number is not None:
                    metadata.setdefault("page", page_number)
                source_id = _source_id(document_id, page_number, chunk_index)
                connection.execute(
                    """
                    INSERT INTO document_chunks (
                        chunk_id, document_id, source_id, page_number,
                        chunk_index, content, metadata, vector_id, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(uuid4()),
                        document_id,
                        source_id,
                        page_number,
                        chunk_index,
                        str(chunk.get("content") or ""),
                        _json_dumps(metadata),
                        _optional_str(chunk.get("id")),
                        now,
                    ),
                )
            self._record_audit_event(
                connection,
                document_id=document_id,
                event_type="chunks_recorded",
                metadata={"chunk_count": len(chunks)},
                created_at=now,
            )
            connection.commit()
        return True

    def get_document(
        self,
        *,
        document_id: str,
        include_deleted: bool = False,
    ) -> dict[str, Any] | None:
        """문서 1건을 조회한다(기본은 soft-delete 제외)."""
        if not self.path.exists():
            return None
        with self._connect() as connection:
            self._ensure_schema(connection)
            row = self._get_document_row(
                connection,
                document_id=document_id,
                include_deleted=include_deleted,
            )
        return _document_from_row(row) if row is not None else None

    def list_documents(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
    ) -> dict[str, Any]:
        """문서 목록을 페이지네이션 조회한다(soft-delete 제외)."""
        if not self.path.exists():
            return {"documents": [], "total_count": 0}
        offset = max(page - 1, 0) * page_size
        with self._connect() as connection:
            self._ensure_schema(connection)
            total_count = connection.execute(
                """
                SELECT COUNT(*) AS count
                FROM documents
                WHERE deleted_at IS NULL
                """
            ).fetchone()["count"]
            rows = connection.execute(
                """
                SELECT *
                FROM documents
                WHERE deleted_at IS NULL
                ORDER BY created_at DESC, document_id DESC
                LIMIT ? OFFSET ?
                """,
                (page_size, offset),
            ).fetchall()
        return {
            "documents": [_document_from_row(row) for row in rows],
            "total_count": int(total_count),
        }

    def get_original_file(
        self,
        *,
        document_id: str,
    ) -> dict[str, Any] | None:
        """문서의 활성 원본 파일 메타를 조회한다(미삭제 문서만)."""
        if not self.path.exists():
            return None
        with self._connect() as connection:
            self._ensure_schema(connection)
            row = connection.execute(
                """
                SELECT f.*
                FROM document_files f
                JOIN documents d
                  ON d.document_id = f.document_id
                WHERE f.document_id = ?
                  AND f.file_role = 'original'
                  AND f.status = 'active'
                  AND f.deleted_at IS NULL
                  AND d.deleted_at IS NULL
                """,
                (document_id,),
            ).fetchone()
        return _file_from_row(row) if row is not None else None

    def find_source_chunk(
        self,
        *,
        document_id: str,
        source_id: str,
        page: int | None = None,
        chunk: int | None = None,
    ) -> dict[str, Any] | None:
        """source_id(+옵션 page/chunk)로 청크 출처를 역조회한다."""
        if not self.path.exists():
            return None
        conditions = [
            "c.document_id = ?",
            "c.source_id = ?",
            "d.deleted_at IS NULL",
        ]
        params: list[Any] = [document_id, source_id]
        if page is not None:
            conditions.append("c.page_number = ?")
            params.append(page)
        if chunk is not None:
            conditions.append("c.chunk_index = ?")
            params.append(chunk)
        with self._connect() as connection:
            self._ensure_schema(connection)
            row = connection.execute(
                f"""
                SELECT c.*, d.filename AS document_filename
                FROM document_chunks c
                JOIN documents d
                  ON d.document_id = c.document_id
                WHERE {" AND ".join(conditions)}
                ORDER BY c.created_at, c.chunk_index
                LIMIT 1
                """,
                tuple(params),
            ).fetchone()
        return _chunk_from_row(row) if row is not None else None

    def tombstone_document(
        self,
        *,
        document_id: str,
        remove_files: bool = True,
    ) -> bool:
        """문서를 soft-delete하고 로컬 원본 파일을 정리한다.

        Returns:
            대상 문서가 존재(미삭제)하면 True, 없으면 False.
        """
        now = _now()
        with self._connect() as connection:
            self._ensure_schema(connection)
            connection.execute("BEGIN IMMEDIATE")
            row = self._get_document_row(connection, document_id=document_id)
            if row is None:
                connection.rollback()
                return False
            files = connection.execute(
                """
                SELECT local_path
                FROM document_files
                WHERE document_id = ? AND deleted_at IS NULL
                """,
                (document_id,),
            ).fetchall()
            connection.execute(
                """
                UPDATE documents
                SET status = 'deleted', deleted_at = ?, updated_at = ?
                WHERE document_id = ? AND deleted_at IS NULL
                """,
                (now, now, document_id),
            )
            connection.execute(
                """
                UPDATE document_files
                SET status = 'deleted', deleted_at = ?
                WHERE document_id = ? AND deleted_at IS NULL
                """,
                (now, document_id),
            )
            self._record_audit_event(
                connection,
                document_id=document_id,
                event_type="deleted",
                metadata={"remove_files": remove_files},
                created_at=now,
            )
            connection.commit()
        if remove_files:
            for file_row in files:
                _unlink_if_exists(file_row["local_path"])
        return True

    def list_audit_events(
        self,
        *,
        document_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """감사 이벤트를 시간순으로 조회한다(옵션 document_id 필터)."""
        if not self.path.exists():
            return []
        params: list[Any] = []
        clause = "1 = 1"
        if document_id is not None:
            clause = "document_id = ?"
            params.append(document_id)
        with self._connect() as connection:
            self._ensure_schema(connection)
            rows = connection.execute(
                f"""
                SELECT *
                FROM audit_events
                WHERE {clause}
                ORDER BY created_at, event_id
                """,
                tuple(params),
            ).fetchall()
        return [_audit_from_row(row) for row in rows]

    def record_audit_event(
        self,
        *,
        document_id: str | None,
        event_type: str,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        """감사 이벤트 1건을 추가한다.

        문서 범위 이벤트는 해당 문서가 존재할 때만 기록한다(삭제된 문서 포함).

        Returns:
            기록 성공 시 True. document_id가 지정됐으나 미존재 시 False.
        """
        now = _now()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            self._ensure_schema(connection)
            connection.execute("BEGIN IMMEDIATE")
            if document_id is not None and self._get_document_row(
                connection,
                document_id=document_id,
                include_deleted=True,
            ) is None:
                connection.rollback()
                return False
            self._record_audit_event(
                connection,
                document_id=document_id,
                event_type=event_type,
                metadata=metadata or {},
                created_at=now,
            )
            connection.commit()
        return True

    def _connect(self) -> sqlite3.Connection:
        """WAL + 외래키 활성 연결을 생성한다."""
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _ensure_schema(self, connection: sqlite3.Connection) -> None:
        """5테이블(문서/원본파일/페이지/청크/감사) + 인덱스를 멱등 생성한다."""
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS documents (
                document_id TEXT PRIMARY KEY,
                filename TEXT NOT NULL,
                file_type TEXT NOT NULL,
                file_size INTEGER NOT NULL,
                status TEXT NOT NULL,
                chunk_count INTEGER,
                processing_time REAL,
                extraction_summary TEXT,
                metadata TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                deleted_at TEXT
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS document_files (
                file_id TEXT PRIMARY KEY,
                document_id TEXT NOT NULL,
                file_role TEXT NOT NULL,
                filename TEXT NOT NULL,
                file_type TEXT NOT NULL,
                file_size INTEGER NOT NULL,
                local_path TEXT NOT NULL,
                source_uri TEXT,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                deleted_at TEXT,
                FOREIGN KEY(document_id)
                    REFERENCES documents(document_id) ON DELETE CASCADE,
                UNIQUE(document_id, file_role)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS document_pages (
                page_id TEXT PRIMARY KEY,
                document_id TEXT NOT NULL,
                page_number INTEGER,
                content_preview TEXT,
                metadata TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(document_id)
                    REFERENCES documents(document_id) ON DELETE CASCADE
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS document_chunks (
                chunk_id TEXT PRIMARY KEY,
                document_id TEXT NOT NULL,
                source_id TEXT NOT NULL,
                page_number INTEGER,
                chunk_index INTEGER,
                content TEXT,
                metadata TEXT,
                vector_id TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(document_id)
                    REFERENCES documents(document_id) ON DELETE CASCADE
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS audit_events (
                event_id TEXT PRIMARY KEY,
                document_id TEXT,
                event_type TEXT NOT NULL,
                metadata TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_documents_deleted
            ON documents(deleted_at)
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_document_chunks_source
            ON document_chunks(document_id, source_id)
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_audit_events_document
            ON audit_events(document_id, created_at)
            """
        )

    def _get_document_row(
        self,
        connection: sqlite3.Connection,
        *,
        document_id: str,
        include_deleted: bool = False,
    ) -> sqlite3.Row | None:
        """문서 행을 조회한다(기본은 soft-delete 제외)."""
        deleted_clause = "" if include_deleted else "AND deleted_at IS NULL"
        return connection.execute(
            f"""
            SELECT *
            FROM documents
            WHERE document_id = ? {deleted_clause}
            """,
            (document_id,),
        ).fetchone()

    def _record_audit_event(
        self,
        connection: sqlite3.Connection,
        *,
        document_id: str | None,
        event_type: str,
        metadata: dict[str, Any],
        created_at: str,
    ) -> None:
        """원장 내부 감사 이벤트를 1건 삽입한다(같은 트랜잭션)."""
        connection.execute(
            """
            INSERT INTO audit_events (
                event_id, document_id, event_type, metadata, created_at
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                str(uuid4()),
                document_id,
                event_type,
                _json_dumps(metadata),
                created_at,
            ),
        )


def _now() -> str:
    """현재 시각을 ISO 문자열로 반환한다."""
    return datetime.now().isoformat()


def _json_dumps(value: Any) -> str:
    """객체를 JSON 문자열로 직렬화한다(비ASCII 보존)."""
    return json.dumps(value, ensure_ascii=False, default=str)


def _json_loads(value: Any) -> Any:
    """JSON 문자열을 역직렬화한다(빈 값/오류 시 None)."""
    if value is None or value == "":
        return None
    try:
        return json.loads(str(value))
    except json.JSONDecodeError:
        return None


def _metadata_from_document(document: Any) -> dict[str, Any]:
    """Document 객체의 metadata를 딕셔너리로 추출한다."""
    metadata = getattr(document, "metadata", None)
    return dict(metadata) if isinstance(metadata, dict) else {}


def _page_number(metadata: dict[str, Any], fallback: int | None) -> int | None:
    """메타데이터에서 페이지 번호를 추정한다(page/page_number/page_index)."""
    for key in ("page", "page_number"):
        value = _optional_int(metadata.get(key))
        if value is not None:
            return value
    page_index = _optional_int(metadata.get("page_index"))
    if page_index is not None:
        return page_index + 1
    return fallback


def _chunk_index(metadata: dict[str, Any], fallback: int) -> int:
    """메타데이터에서 청크 인덱스를 추정한다(없으면 순번 폴백)."""
    for key in ("chunk", "chunk_index"):
        value = _optional_int(metadata.get(key))
        if value is not None:
            return value
    return fallback


def _source_id(document_id: str, page: int | None, chunk_index: int) -> str:
    """출처 역조회용 안정 source_id를 생성한다."""
    stable_page: int | str = page if page is not None else "na"
    return f"rag:{document_id}:{stable_page}:{chunk_index}"


def _document_from_row(row: sqlite3.Row) -> dict[str, Any]:
    """문서 행을 공개 딕셔너리로 변환한다."""
    return {
        "id": row["document_id"],
        "document_id": row["document_id"],
        "filename": row["filename"],
        "file_type": row["file_type"],
        "file_size": row["file_size"],
        "status": row["status"],
        "chunk_count": row["chunk_count"] or 0,
        "processing_time": row["processing_time"],
        "extraction_summary": _json_loads(row["extraction_summary"]),
        "metadata": _json_loads(row["metadata"]) or {},
        "upload_date": row["created_at"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "deleted_at": row["deleted_at"],
    }


def _file_from_row(row: sqlite3.Row) -> dict[str, Any]:
    """원본 파일 행을 공개 딕셔너리로 변환한다."""
    return {
        "file_id": row["file_id"],
        "document_id": row["document_id"],
        "file_role": row["file_role"],
        "filename": row["filename"],
        "file_type": row["file_type"],
        "file_size": row["file_size"],
        "local_path": row["local_path"],
        "source_uri": row["source_uri"],
        "status": row["status"],
        "created_at": row["created_at"],
        "deleted_at": row["deleted_at"],
    }


def _chunk_from_row(row: sqlite3.Row) -> dict[str, Any]:
    """청크 행을 공개 딕셔너리로 변환한다(출처 정보 포함)."""
    metadata = _json_loads(row["metadata"]) or {}
    return {
        "id": row["chunk_id"],
        "source_id": row["source_id"],
        "document_id": row["document_id"],
        "document": row["document_filename"],
        "content": row["content"] or "",
        "metadata": metadata,
        "page": row["page_number"],
        "chunk": row["chunk_index"],
        "vector_id": row["vector_id"],
    }


def _audit_from_row(row: sqlite3.Row) -> dict[str, Any]:
    """감사 이벤트 행을 공개 딕셔너리로 변환한다."""
    return {
        "event_id": row["event_id"],
        "document_id": row["document_id"],
        "event_type": row["event_type"],
        "metadata": _json_loads(row["metadata"]) or {},
        "created_at": row["created_at"],
    }


def _optional_int(value: Any) -> int | None:
    """정수 변환 가능하면 int로, 아니면 None(bool/빈값 제외)."""
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_str(value: Any) -> str | None:
    """None이 아니면 문자열로 변환한다."""
    if value is None:
        return None
    return str(value)


def _unlink_if_exists(path_value: Any) -> None:
    """로컬 파일이 존재하면 best-effort로 삭제한다(실패는 무시)."""
    if not path_value:
        return
    try:
        path = Path(str(path_value))
        if path.exists() and path.is_file():
            path.unlink()
    except OSError:
        return
