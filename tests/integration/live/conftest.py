"""tests/integration/live 전용 conftest.

이 디렉터리의 테스트는 실제 외부 서비스(Pinecone, MongoDB Atlas, Jev 등)에 접속한다.
이 디렉터리 아래에서 수집된 항목에만 `live` 마커를 붙여 기본 게이트(`-m "not live"`)에서
제외하고, ONERAG_RUN_LIVE_PROVIDER_TESTS=1 이 없으면 건너뛴다.

주의: conftest의 pytest_collection_modifyitems 훅은 세션 전체 items를 받는다.
디렉터리로 걸러내지 않으면 저장소의 모든 테스트가 live로 표시되어 기본 게이트가 비게 된다.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

LIVE_ENV_FLAG = "ONERAG_RUN_LIVE_PROVIDER_TESTS"
LIVE_DIR = Path(__file__).resolve().parent


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    run_live = os.getenv(LIVE_ENV_FLAG) == "1"
    skip = pytest.mark.skip(reason=f"live 테스트는 {LIVE_ENV_FLAG}=1 일 때만 실행")
    for item in items:
        if not Path(str(item.fspath)).resolve().is_relative_to(LIVE_DIR):
            continue
        item.add_marker(pytest.mark.live)
        if not run_live:
            item.add_marker(skip)
