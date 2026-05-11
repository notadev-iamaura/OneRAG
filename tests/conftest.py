"""
테스트 공통 설정 및 픽스처

pytest conftest.py - 모든 테스트에서 공유되는 설정과 픽스처 정의.

구현일: 2025-12-01
"""

import os
import sys
from pathlib import Path

import pytest

# 프로젝트 루트 경로를 sys.path에 추가
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

RUN_OPTIONAL_PROVIDER_TESTS_ENV = "ONERAG_RUN_OPTIONAL_PROVIDER_TESTS"
OPTIONAL_PROVIDER_TEST_PATHS = (
    Path("tests/unit/infrastructure/storage/vector"),
    Path("tests/unit/retrieval/bm25_engine"),
    Path("tests/unit/retrieval/rerankers"),
    Path("tests/unit/retrieval/retrievers"),
)


def pytest_configure(config: pytest.Config) -> None:
    """
    pytest 설정 훅

    테스트 환경에서 불필요한 외부 연결 및 트레이싱 비활성화.
    """
    # Langfuse 비활성화
    os.environ["LANGFUSE_ENABLED"] = "False"
    # LangSmith 비활성화
    os.environ["LANGCHAIN_TRACING_V2"] = "false"
    # 테스트 환경임을 명시
    os.environ["ENVIRONMENT"] = "test"


def pytest_ignore_collect(collection_path: Path, config: pytest.Config) -> bool | None:
    """
    Skip optional provider tests by default.

    These tests import heavyweight/native provider packages at collection or execution time.
    Keep the default release gate deterministic; run them explicitly with
    ONERAG_RUN_OPTIONAL_PROVIDER_TESTS=1 when validating optional providers.
    """
    if os.getenv(RUN_OPTIONAL_PROVIDER_TESTS_ENV) == "1":
        return None

    try:
        relative_path = Path(str(collection_path)).resolve().relative_to(project_root.resolve())
    except ValueError:
        return None

    for optional_path in OPTIONAL_PROVIDER_TEST_PATHS:
        if relative_path == optional_path or optional_path in relative_path.parents:
            return True

    return None


@pytest.fixture(scope="session")
def project_root_path() -> Path:
    """프로젝트 루트 경로"""
    return project_root


@pytest.fixture(scope="session")
def test_data_path(project_root_path: Path) -> Path:
    """테스트 데이터 경로"""
    return project_root_path / "tests" / "data"


@pytest.fixture(scope="session")
def neo4j_connection_config():
    """
    Neo4j 연결 설정 픽스처 (세션 범위)

    환경 변수가 없으면 로컬 Docker 기본값 사용
    """
    return {
        "uri": os.getenv("NEO4J_URI", "bolt://localhost:7687"),
        "user": os.getenv("NEO4J_USER", "neo4j"),
        "password": os.getenv("NEO4J_PASSWORD", "testpassword123"),
        "database": os.getenv("NEO4J_DATABASE", "neo4j"),
    }


@pytest.fixture
def neo4j_store(neo4j_connection_config):
    """
    Neo4jGraphStore 인스턴스 픽스처

    테스트 후 그래프 클리어
    """
    from app.modules.core.graph.stores.neo4j_store import Neo4jGraphStore

    store = Neo4jGraphStore(neo4j_connection_config)
    yield store

    # Teardown: 테스트 데이터 클리어
    import asyncio

    asyncio.get_event_loop().run_until_complete(store.clear())
    asyncio.get_event_loop().run_until_complete(store.close())
