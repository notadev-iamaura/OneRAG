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
# [단일 진실원] optional-provider 테스트 수집 제외 경로 목록.
# - 이 목록이 단일 진실원(single source of truth)이며, .github/workflows/ci.yml 의
#   Optional Providers 잡은 경로를 중복 명시하지 않는다
#   (ONERAG_RUN_OPTIONAL_PROVIDER_TESTS=1 + tests/unit 전체 실행 방식).
# - 새 optional 테스트 디렉토리는 반드시 "여기에만" 추가할 것. conftest/ci.yml 에
#   경로가 이중 관리되면 한쪽에만 추가된 테스트가 로컬에서는 skip, CI에서는 미실행
#   되는 '어디서도 실행되지 않는 테스트'가 재발한다.
# - marker+deselect 가 아니라 ignore-collect 인 이유: 네이티브 클라이언트 미설치
#   환경에서 수집 시점 import 자체를 차단해 collection error 를 방지하기 위함.
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
