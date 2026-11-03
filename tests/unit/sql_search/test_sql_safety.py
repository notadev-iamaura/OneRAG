"""SQL 검색 안전장치 테스트.

- 기본값: SQL 검색은 꺼져 있어야 한다(명시적 opt-in).
- 검증기: SELECT 안에 숨은 파일/지연/세션 조작 함수와 SELECT INTO를 막아야 한다.
- 실행기: 실제 쿼리 전에 READ ONLY 트랜잭션과 statement_timeout을 건다.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.modules.core.sql_search.query_executor import QueryExecutor
from app.modules.core.sql_search.service import SQLSearchService
from app.modules.core.sql_search.sql_generator import SQLGenerator


def _generator() -> SQLGenerator:
    return SQLGenerator(config={"model": "test", "max_tokens": 10}, api_key="unused")


class TestSqlValidator:
    @pytest.mark.parametrize(
        "sql",
        [
            "SELECT * FROM metadata WHERE pg_sleep(10) IS NULL",
            "SELECT pg_read_file('/etc/passwd')",
            "SELECT * INTO new_table FROM metadata",
            "SELECT * FROM dblink('host=evil', 'select 1') AS t(a int)",
            "SELECT lo_import('/etc/passwd')",
            "SELECT 1; SET role postgres",
            "SELECT pg_terminate_backend(1)",
            "SELECT * FROM metadata; DROP TABLE metadata; SELECT 1",
        ],
    )
    def test_dangerous_statements_are_rejected(self, sql: str) -> None:
        assert _generator().validate_sql(sql) is False

    @pytest.mark.parametrize(
        "sql",
        [
            "SELECT name, amount FROM metadata WHERE category = 'insert_log' LIMIT 10",
            "SELECT COUNT(*) AS total FROM metadata",
            "SELECT * FROM metadata WHERE note = 'pg_sleep is just text' LIMIT 5",
        ],
    )
    def test_plain_reads_are_allowed(self, sql: str) -> None:
        assert _generator().validate_sql(sql) is True


class TestSqlSearchDefaultOff:
    def test_service_is_disabled_without_explicit_opt_in(self) -> None:
        service = SQLSearchService(config={}, db_manager=MagicMock(), api_key=None)
        assert service.is_enabled() is False

    def test_service_can_be_explicitly_enabled(self) -> None:
        service = SQLSearchService(config={"enabled": True}, db_manager=MagicMock(), api_key=None)
        assert service.is_enabled() is True

    def test_feature_yaml_defaults_to_disabled(self) -> None:
        from pathlib import Path

        yaml_text = Path("app/config/features/sql_search.yaml").read_text(encoding="utf-8")
        assert "${SQL_SEARCH_ENABLED:-false}" in yaml_text


class TestQueryExecutorReadOnlyGuards:
    @pytest.mark.asyncio
    async def test_read_only_and_timeout_are_applied_before_query(self) -> None:
        executed: list[str] = []

        session = MagicMock()

        async def _execute(statement: Any, *args: Any, **kwargs: Any) -> MagicMock:
            executed.append(str(statement))
            result = MagicMock()
            result.fetchall.return_value = [("a", 1)]
            result.keys.return_value = ["name", "value"]
            return result

        session.execute = AsyncMock(side_effect=_execute)

        db_manager = MagicMock()

        @asynccontextmanager
        async def _get_session():
            yield session

        db_manager.get_session = _get_session

        executor = QueryExecutor(db_manager, config={"timeout": 3, "max_rows": 10})
        result = await executor.execute("SELECT name, value FROM metadata")

        assert result.success is True
        assert executed[0] == "SET TRANSACTION READ ONLY"
        assert executed[1] == "SET LOCAL statement_timeout = 3000"
        assert executed[2] == "SELECT name, value FROM metadata"

    @pytest.mark.asyncio
    async def test_non_select_is_rejected_before_touching_db(self) -> None:
        db_manager = MagicMock()
        executor = QueryExecutor(db_manager, config={})
        result = await executor.execute("DELETE FROM metadata")
        assert result.success is False
        db_manager.get_session.assert_not_called()
