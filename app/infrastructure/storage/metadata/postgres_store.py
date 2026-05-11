"""
PostgreSQL Metadata Store Adapter

IMetadataStore 인터페이스를 구현한 Postgres 어댑터입니다.
asyncpg를 사용하여 비동기 처리를 지원합니다.
"""
import json
import os
import re
from typing import Any

import asyncpg
from asyncpg.pool import Pool

from app.core.interfaces.storage import IMetadataStore
from app.lib.logger import get_logger

logger = get_logger(__name__)


class PostgresMetadataStore(IMetadataStore):
    def __init__(self, database_url: str | None = None) -> None:
        resolved_url = database_url or os.getenv("DATABASE_URL")
        if not resolved_url:
            raise ValueError("DATABASE_URL is required for PostgresMetadataStore")
        self.database_url: str = resolved_url
        self.pool: Pool | None = None

    def _validate_collection_name(self, collection: str) -> None:
        """SQL Injection 방지를 위해 테이블 이름 검증 (알파벳, 숫자, _ 만 허용)"""
        if not re.match(r'^[a-zA-Z0-9_]+$', collection):
            raise ValueError(f"Invalid collection name: {collection}")

    async def _get_pool(self) -> Pool:
        if not self.pool:
            self.pool = await asyncpg.create_pool(self.database_url)
        return self.pool

    async def save(self, collection: str, data: dict[str, Any], key_field: str = "id") -> bool:
        """
        데이터 저장 (Upsert)
        """
        self._validate_collection_name(collection)
        pool = await self._get_pool()

        # JSON 필드 자동 변환
        processed_data = {}
        for k, v in data.items():
            if isinstance(v, dict | list):
                processed_data[k] = json.dumps(v, ensure_ascii=False)
            else:
                processed_data[k] = v

        columns = list(processed_data.keys())
        values = list(processed_data.values())
        placeholders = [f"${i+1}" for i in range(len(values))]

        # Upsert Query Construction
        # ON CONFLICT (key_field) DO UPDATE SET ...
        update_clause = ", ".join([f"{col} = EXCLUDED.{col}" for col in columns if col != key_field])

        query = f"""
            INSERT INTO {collection} ({', '.join(columns)})
            VALUES ({', '.join(placeholders)})
            ON CONFLICT ({key_field})
            DO UPDATE SET {update_clause}
        """

        try:
            async with pool.acquire() as conn:
                await conn.execute(query, *values)
            return True
        except Exception as e:
            logger.error(f"Postgres save error: {e}")
            return False

    async def get(self, collection: str, filters: dict[str, Any]) -> list[dict[str, Any]]:
        pool = await self._get_pool()

        where_clauses = []
        values = []
        for i, (k, v) in enumerate(filters.items()):
            where_clauses.append(f"{k} = ${i+1}")
            values.append(v)

        where_stmt = " AND ".join(where_clauses) if where_clauses else "TRUE"
        query = f"SELECT * FROM {collection} WHERE {where_stmt}"

        try:
            async with pool.acquire() as conn:
                rows = await conn.fetch(query, *values)
                return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Postgres get error: {e}")
            return []

    async def delete(self, collection: str, filters: dict[str, Any]) -> int:
        self._validate_collection_name(collection)
        pool = await self._get_pool()

        where_clauses = []
        values = []
        for i, (k, v) in enumerate(filters.items()):
            where_clauses.append(f"{k} = ${i+1}")
            values.append(v)

        where_stmt = " AND ".join(where_clauses) if where_clauses else "FALSE" # 안전장치: 조건 없으면 삭제 안함
        query = f"DELETE FROM {collection} WHERE {where_stmt}"

        try:
            async with pool.acquire() as conn:
                result = await conn.execute(query, *values)
                # result string format: "DELETE <count>"
                return int(result.split()[-1])
        except Exception as e:
            logger.error(f"Postgres delete error: {e}")
            return 0

    async def close(self) -> None:
        if self.pool:
            await self.pool.close()
