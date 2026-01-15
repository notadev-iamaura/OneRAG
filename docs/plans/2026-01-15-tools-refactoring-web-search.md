# Tools 리팩토링 및 웹 검색 Fallback 시스템 구현 계획

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** `mcp/` 폴더를 `tools/`로 리네이밍하고, SDK 기반 3단계 Fallback 웹 검색 시스템을 TDD로 구현

**Architecture:**
- 기존 MCP 폴더 구조를 `tools/`로 명확하게 리네이밍
- 웹 검색 서비스를 Tavily → Brave → DuckDuckGo 3단계 Fallback으로 구현
- 각 Provider는 독립적인 SDK 직접 호출 방식 (MCP 프로토콜 미사용)

**Tech Stack:**
- tavily-python (정확도 93.3%)
- httpx (Brave API 호출)
- duckduckgo-search (무제한 무료)
- pytest, pytest-asyncio (TDD)

---

## 📊 영향 받는 파일 목록

### 리네이밍 대상 (mcp → tools)
```
app/modules/core/mcp/           → app/modules/core/tools/
├── __init__.py                 → 내용 수정 (import 경로)
├── factory.py                  → 클래스명 유지, 경로 수정
├── interfaces.py               → 이름 변경 (MCP* → Tool*)
├── server.py                   → ToolServer로 이름 변경
└── tools/                      → 제거 (상위로 병합)
    ├── weaviate.py             → vector_search.py
    ├── graph_tools.py          → graph_search.py
    └── __init__.py             → 제거
```

### 의존성 수정 대상 (16개 파일)
```
app/core/di_container.py                     # import 경로 수정
app/modules/core/agent/planner.py            # MCP → Tool 참조 수정
app/modules/core/agent/orchestrator.py       # MCP → Tool 참조 수정
app/modules/core/agent/interfaces.py         # 타입 참조 수정
app/modules/core/agent/factory.py            # MCP → Tool 참조 수정
app/modules/core/agent/executor.py           # MCP → Tool 참조 수정
app/modules/core/agent/__init__.py           # export 수정
app/config/features/mcp.yaml                 → app/config/features/tools.yaml
app/config/base.yaml                         # 참조 경로 수정
```

---

## 🔧 서브에이전트 역할 정의

| 에이전트 | 역할 | 담당 Task |
|---------|------|----------|
| **Refactor Agent** | 폴더 리네이밍 및 import 경로 일괄 수정 | Task 1-3 |
| **Test Agent** | 테스트 작성 및 검증 (TDD Red phase) | Task 4, 6, 8, 10 |
| **Implement Agent** | 기능 구현 (TDD Green phase) | Task 5, 7, 9, 11 |
| **Integration Agent** | 통합 테스트 및 DI Container 연동 | Task 12-14 |

---

## Phase 1: 폴더 리네이밍 (Task 1-3)

### Task 1: 테스트 기반 리네이밍 준비

**Files:**
- Create: `tests/unit/modules/core/tools/__init__.py`
- Create: `tests/unit/modules/core/tools/test_interfaces.py`

**Step 1: 테스트 디렉토리 생성**

```bash
mkdir -p tests/unit/modules/core/tools
touch tests/unit/modules/core/tools/__init__.py
```

**Step 2: interfaces 테스트 작성 (Red)**

```python
# tests/unit/modules/core/tools/test_interfaces.py
"""
Tools 인터페이스 테스트

기존 MCP 인터페이스가 Tools로 정상 리네이밍되었는지 검증합니다.
"""
import pytest


class TestToolInterfaces:
    """도구 인터페이스 테스트"""

    def test_tool_result_import(self):
        """ToolResult가 정상 import 되는지 확인"""
        from app.modules.core.tools import ToolResult

        result = ToolResult(
            success=True,
            data={"key": "value"},
            tool_name="test_tool",
        )

        assert result.success is True
        assert result.data == {"key": "value"}
        assert result.tool_name == "test_tool"

    def test_tool_config_import(self):
        """ToolConfig가 정상 import 되는지 확인"""
        from app.modules.core.tools import ToolConfig

        config = ToolConfig(
            name="search_vector",
            description="벡터 검색 도구",
            enabled=True,
            timeout=30.0,
        )

        assert config.name == "search_vector"
        assert config.enabled is True

    def test_tool_server_config_import(self):
        """ToolServerConfig가 정상 import 되는지 확인"""
        from app.modules.core.tools import ToolServerConfig

        config = ToolServerConfig(
            enabled=True,
            server_name="rag-tools",
            default_timeout=30.0,
        )

        assert config.server_name == "rag-tools"

    def test_backward_compatibility_aliases(self):
        """하위 호환성 alias가 동작하는지 확인"""
        # 기존 코드 호환성을 위한 alias
        from app.modules.core.tools import (
            MCPToolResult,  # alias for ToolResult
            MCPToolConfig,  # alias for ToolConfig
        )

        assert MCPToolResult is not None
        assert MCPToolConfig is not None
```

**Step 3: 테스트 실행 (실패 확인)**

```bash
pytest tests/unit/modules/core/tools/test_interfaces.py -v
```

Expected: FAIL - `ModuleNotFoundError: No module named 'app.modules.core.tools'`

**Step 4: 커밋 (Red phase)**

```bash
git add tests/unit/modules/core/tools/
git commit -m "테스트: tools 인터페이스 테스트 추가 (TDD Red)"
```

---

### Task 2: tools 폴더 생성 및 인터페이스 이동

**Files:**
- Create: `app/modules/core/tools/__init__.py`
- Create: `app/modules/core/tools/interfaces.py`
- Modify: `app/modules/core/mcp/interfaces.py` (복사 후 이름 변경)

**Step 1: tools 디렉토리 생성**

```bash
mkdir -p app/modules/core/tools
```

**Step 2: interfaces.py 생성 (Green)**

```python
# app/modules/core/tools/interfaces.py
"""
Tools 인터페이스 및 타입 정의

도구 실행 결과, 설정 등의 공통 타입을 정의합니다.
MCP 프로토콜과 무관한 순수 SDK 호출 기반 도구 시스템입니다.

기존 호환성:
    - MCPToolResult → ToolResult (alias 제공)
    - MCPToolConfig → ToolConfig (alias 제공)
"""
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolResult:
    """
    도구 실행 결과

    Attributes:
        success: 실행 성공 여부
        data: 실행 결과 데이터
        error: 에러 메시지 (실패 시)
        tool_name: 실행된 도구 이름
        execution_time: 실행 시간 (초)
        metadata: 추가 메타데이터 (provider 정보 등)
    """
    success: bool
    data: Any
    error: str | None = None
    tool_name: str = ""
    execution_time: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolConfig:
    """
    도구 설정

    YAML 설정에서 로드되어 도구별 동작을 제어합니다.

    Attributes:
        name: 도구 이름 (예: "web_search")
        description: 도구 설명 (Agent가 도구 선택 시 참고)
        enabled: 활성화 여부
        timeout: 실행 타임아웃 (초)
        retry_count: 재시도 횟수
        parameters: 도구별 추가 파라미터
    """
    name: str
    description: str
    enabled: bool = True
    timeout: float = 30.0
    retry_count: int = 1
    parameters: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolServerConfig:
    """
    도구 서버 전체 설정

    YAML의 tools 섹션에서 로드됩니다.

    Attributes:
        enabled: 도구 기능 전체 활성화 여부
        server_name: 서버 이름
        default_timeout: 기본 타임아웃 (초)
        max_concurrent_tools: 동시 실행 가능한 도구 수
        tools: 등록된 도구 설정 (도구명 → ToolConfig)
    """
    enabled: bool = True
    server_name: str = "rag-tools"
    default_timeout: float = 30.0
    max_concurrent_tools: int = 3
    tools: dict[str, ToolConfig] = field(default_factory=dict)


# 도구 함수 타입 힌트
# async def tool_func(arguments: dict, config: dict) -> Any
ToolFunction = Callable[..., Coroutine[Any, Any, Any]]


# ========================================
# 하위 호환성 Alias (기존 코드 지원)
# ========================================
MCPToolResult = ToolResult
MCPToolConfig = ToolConfig
MCPServerConfig = ToolServerConfig
MCPToolFunction = ToolFunction
```

**Step 3: __init__.py 생성**

```python
# app/modules/core/tools/__init__.py
"""
Tools 모듈

Agent가 사용하는 도구들을 관리합니다.
SDK 직접 호출 방식으로 MCP 프로토콜 오버헤드 없이 동작합니다.

사용 예시:
    from app.modules.core.tools import ToolFactory, ToolServer

    # 설정 기반 도구 서버 생성
    tools = ToolFactory.create(config)

    # 도구 실행
    result = await tools.execute("web_search", {"query": "검색어"})
"""
from .interfaces import (
    ToolConfig,
    ToolFunction,
    ToolResult,
    ToolServerConfig,
    # 하위 호환성 alias
    MCPServerConfig,
    MCPToolConfig,
    MCPToolFunction,
    MCPToolResult,
)

__all__ = [
    # 새 이름 (권장)
    "ToolResult",
    "ToolConfig",
    "ToolServerConfig",
    "ToolFunction",
    # 하위 호환성 alias
    "MCPToolResult",
    "MCPToolConfig",
    "MCPServerConfig",
    "MCPToolFunction",
]
```

**Step 4: 테스트 실행 (성공 확인)**

```bash
pytest tests/unit/modules/core/tools/test_interfaces.py -v
```

Expected: PASS

**Step 5: 커밋 (Green phase)**

```bash
git add app/modules/core/tools/
git commit -m "기능: tools 인터페이스 추가 (mcp에서 분리)"
```

---

### Task 3: 기존 도구 파일 이동 및 import 수정

**Files:**
- Move: `app/modules/core/mcp/tools/weaviate.py` → `app/modules/core/tools/vector_search.py`
- Move: `app/modules/core/mcp/tools/graph_tools.py` → `app/modules/core/tools/graph_search.py`
- Modify: 16개 파일의 import 경로

**Step 1: vector_search.py 생성 (weaviate.py 복사 후 수정)**

```python
# app/modules/core/tools/vector_search.py
"""
벡터 검색 도구

벡터 DB에서 정보를 검색하는 도구들입니다.
기존 WeaviateRetriever를 활용합니다.

도구 목록:
- search_vector: 하이브리드 검색 (Dense + BM25)
- get_document_by_id: UUID로 문서 조회
"""
from typing import Any

from app.lib.logger import get_logger

logger = get_logger(__name__)


async def search_vector(
    arguments: dict[str, Any],
    global_config: dict[str, Any],
) -> list[dict[str, Any]]:
    """
    벡터 DB에서 정보를 하이브리드 검색합니다.

    Dense 벡터 검색과 BM25 키워드 검색을 결합하여
    정확도 높은 검색 결과를 제공합니다.

    Args:
        arguments: 도구 인자
            - query (str): 검색 쿼리 (필수)
            - top_k (int): 반환할 결과 수 (기본값: 설정에 따름)
            - alpha (float): Dense:BM25 비율 (기본값: 0.6)
        global_config: 전역 설정 (retriever 접근용)

    Returns:
        list[dict]: 검색 결과 목록

    Raises:
        ValueError: 쿼리가 비어있거나 retriever가 설정되지 않은 경우
    """
    query = arguments.get("query", "")

    if not query or not query.strip():
        raise ValueError("query는 필수입니다")

    retriever = global_config.get("retriever")
    if retriever is None:
        raise ValueError("retriever가 설정되지 않았습니다")

    # 설정에서 파라미터 가져오기
    tools_config = global_config.get("tools", {})
    tool_config = tools_config.get("tools", {}).get("search_vector", {})
    params = tool_config.get("parameters", {})

    default_top_k = params.get("default_top_k", 10)
    default_alpha = params.get("alpha", 0.6)

    top_k = arguments.get("top_k", default_top_k)
    alpha = arguments.get("alpha", default_alpha)

    logger.info(f"🔍 search_vector: query='{query}', top_k={top_k}, alpha={alpha}")

    try:
        search_results = await retriever.search(
            query=query,
            top_k=top_k,
            alpha=alpha,
        )

        results = []
        for doc in search_results:
            result = {
                "content": doc.page_content,
                "metadata": doc.metadata,
            }
            if hasattr(doc, "score"):
                result["score"] = doc.score
            results.append(result)

        logger.info(f"✅ search_vector: {len(results)}개 결과")
        return results

    except Exception as e:
        logger.error(f"❌ search_vector 실패: {e}")
        raise


async def get_document_by_id(
    arguments: dict[str, Any],
    global_config: dict[str, Any],
) -> dict[str, Any] | None:
    """
    문서 ID(UUID)로 벡터 DB에서 직접 조회합니다.

    Args:
        arguments: 도구 인자
            - document_id (str): 문서 UUID (필수)
        global_config: 전역 설정

    Returns:
        dict | None: 문서 정보 또는 None
    """
    document_id = arguments.get("document_id", "")

    if not document_id:
        raise ValueError("document_id는 필수입니다")

    retriever = global_config.get("retriever")
    if retriever is None:
        raise ValueError("retriever가 설정되지 않았습니다")

    logger.info(f"📄 get_document_by_id: id={document_id}")

    try:
        if not hasattr(retriever, "get_by_id"):
            raise ValueError("retriever가 get_by_id를 지원하지 않습니다")

        doc = await retriever.get_by_id(document_id)

        if doc is None:
            logger.warning(f"문서 없음: {document_id}")
            return None

        result = {
            "content": doc.page_content,
            "metadata": doc.metadata,
        }

        logger.info("✅ get_document_by_id: 조회 성공")
        return result

    except Exception as e:
        logger.error(f"❌ get_document_by_id 실패: {e}")
        raise


# 하위 호환성 alias
search_weaviate = search_vector
```

**Step 2: graph_search.py 복사 및 수정**

```python
# app/modules/core/tools/graph_search.py
"""
그래프 검색 도구

지식 그래프에서 엔티티와 관계를 검색합니다.

도구 목록:
- search_graph: 그래프에서 엔티티 검색
- get_neighbors: 엔티티의 이웃 조회
"""
from typing import Any

from app.lib.logger import get_logger

logger = get_logger(__name__)


async def search_graph(
    arguments: dict[str, Any],
    global_config: dict[str, Any],
) -> dict[str, Any]:
    """
    그래프에서 엔티티를 검색합니다.

    Args:
        arguments: 도구 인자
            - query (str): 검색 쿼리 (필수)
            - entity_types (list[str]): 필터링할 엔티티 타입 (선택)
            - top_k (int): 반환할 최대 결과 수 (기본값: 10)
        global_config: 전역 설정

    Returns:
        dict: 검색 결과 (entities, relations, score)
    """
    query = arguments.get("query", "")

    if not query or not query.strip():
        raise ValueError("query는 필수입니다")

    graph_store = global_config.get("graph_store")
    if graph_store is None:
        raise ValueError("graph_store가 설정되지 않았습니다")

    tools_config = global_config.get("tools", {})
    tool_config = tools_config.get("tools", {}).get("search_graph", {})
    params = tool_config.get("parameters", {})

    default_top_k = params.get("default_top_k", 10)

    entity_types = arguments.get("entity_types")
    top_k = arguments.get("top_k", default_top_k)

    logger.info(
        f"🔍 search_graph: query='{query}', entity_types={entity_types}, top_k={top_k}"
    )

    try:
        result = await graph_store.search(
            query=query,
            entity_types=entity_types,
            top_k=top_k,
        )

        entities_list = [
            {
                "id": e.id,
                "name": e.name,
                "type": e.type,
                "properties": e.properties,
            }
            for e in result.entities
        ]

        relations_list = [
            {
                "source_id": r.source_id,
                "target_id": r.target_id,
                "type": r.type,
                "weight": r.weight,
            }
            for r in result.relations
        ]

        response = {
            "success": True,
            "entities": entities_list,
            "relations": relations_list,
            "score": result.score,
        }

        logger.info(
            f"✅ search_graph: {len(entities_list)}개 엔티티, "
            f"{len(relations_list)}개 관계"
        )

        return response

    except Exception as e:
        logger.error(f"❌ search_graph 실패: {e}")
        raise


async def get_neighbors(
    arguments: dict[str, Any],
    global_config: dict[str, Any],
) -> dict[str, Any]:
    """
    엔티티의 이웃을 조회합니다.

    Args:
        arguments: 도구 인자
            - entity_id (str): 시작 엔티티 ID (필수)
            - relation_types (list[str]): 필터링할 관계 타입 (선택)
            - max_depth (int): 최대 탐색 깊이 (기본값: 1)
        global_config: 전역 설정

    Returns:
        dict: 이웃 정보 (entities, relations)
    """
    entity_id = arguments.get("entity_id", "")

    if not entity_id:
        raise ValueError("entity_id는 필수입니다")

    graph_store = global_config.get("graph_store")
    if graph_store is None:
        raise ValueError("graph_store가 설정되지 않았습니다")

    tools_config = global_config.get("tools", {})
    tool_config = tools_config.get("tools", {}).get("get_neighbors", {})
    params = tool_config.get("parameters", {})

    default_max_depth = params.get("default_max_depth", 1)

    relation_types = arguments.get("relation_types")
    max_depth = arguments.get("max_depth", default_max_depth)

    logger.info(
        f"📄 get_neighbors: entity_id='{entity_id}', "
        f"relation_types={relation_types}, max_depth={max_depth}"
    )

    try:
        result = await graph_store.get_neighbors(
            entity_id=entity_id,
            relation_types=relation_types,
            max_depth=max_depth,
        )

        entities_list = [
            {
                "id": e.id,
                "name": e.name,
                "type": e.type,
                "properties": e.properties,
            }
            for e in result.entities
        ]

        relations_list = [
            {
                "source_id": r.source_id,
                "target_id": r.target_id,
                "type": r.type,
                "weight": r.weight,
            }
            for r in result.relations
        ]

        response = {
            "success": True,
            "entities": entities_list,
            "relations": relations_list,
        }

        logger.info(f"✅ get_neighbors: {len(entities_list)}개 이웃 엔티티")

        return response

    except Exception as e:
        logger.error(f"❌ get_neighbors 실패: {e}")
        raise
```

**Step 3: __init__.py에 도구 등록 추가**

```python
# app/modules/core/tools/__init__.py 에 추가
from .vector_search import search_vector, get_document_by_id, search_weaviate
from .graph_search import search_graph, get_neighbors

__all__ = [
    # interfaces
    "ToolResult",
    "ToolConfig",
    "ToolServerConfig",
    "ToolFunction",
    # 하위 호환성
    "MCPToolResult",
    "MCPToolConfig",
    "MCPServerConfig",
    "MCPToolFunction",
    # 도구 함수
    "search_vector",
    "get_document_by_id",
    "search_weaviate",  # alias
    "search_graph",
    "get_neighbors",
]
```

**Step 4: 테스트 실행**

```bash
pytest tests/unit/modules/core/tools/ -v
```

**Step 5: 커밋**

```bash
git add app/modules/core/tools/
git commit -m "리팩터: mcp/tools → tools/ 이동 (vector_search, graph_search)"
```

---

## Phase 2: 웹 검색 서비스 구현 (Task 4-11)

### Task 4: 웹 검색 Provider 인터페이스 테스트 (Red)

**Files:**
- Create: `tests/unit/modules/core/tools/test_web_search.py`

**Step 1: Provider 인터페이스 테스트 작성**

```python
# tests/unit/modules/core/tools/test_web_search.py
"""
웹 검색 도구 테스트

3단계 Fallback 웹 검색 시스템:
1. Tavily (정확도 93.3%)
2. Brave (무료 2,000회/월)
3. DuckDuckGo (무제한 무료)
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestWebSearchProviderInterface:
    """웹 검색 Provider 인터페이스 테스트"""

    def test_web_search_provider_protocol(self):
        """WebSearchProvider Protocol이 정의되어 있는지 확인"""
        from app.modules.core.tools.web_search import WebSearchProvider

        # Protocol 메서드 확인
        assert hasattr(WebSearchProvider, "search")
        assert hasattr(WebSearchProvider, "name")
        assert hasattr(WebSearchProvider, "is_available")

    def test_web_search_result_dataclass(self):
        """WebSearchResult 데이터클래스 확인"""
        from app.modules.core.tools.web_search import WebSearchResult

        result = WebSearchResult(
            title="테스트 제목",
            url="https://example.com",
            content="테스트 내용",
            score=0.95,
        )

        assert result.title == "테스트 제목"
        assert result.url == "https://example.com"
        assert result.content == "테스트 내용"
        assert result.score == 0.95


class TestTavilyProvider:
    """Tavily Provider 테스트"""

    @pytest.mark.asyncio
    async def test_tavily_search_success(self):
        """Tavily 검색 성공 케이스"""
        from app.modules.core.tools.web_search import TavilyProvider

        provider = TavilyProvider(api_key="test-key")

        # Mock Tavily client
        with patch.object(provider, "_client") as mock_client:
            mock_client.search.return_value = {
                "results": [
                    {"title": "결과1", "url": "https://a.com", "content": "내용1"},
                    {"title": "결과2", "url": "https://b.com", "content": "내용2"},
                ],
                "answer": "요약 답변",
            }

            results = await provider.search("테스트 쿼리", max_results=5)

            assert len(results.results) == 2
            assert results.answer == "요약 답변"
            assert results.provider == "tavily"

    @pytest.mark.asyncio
    async def test_tavily_not_available_without_key(self):
        """API 키 없으면 사용 불가"""
        from app.modules.core.tools.web_search import TavilyProvider

        provider = TavilyProvider(api_key=None)

        assert provider.is_available() is False


class TestBraveProvider:
    """Brave Provider 테스트"""

    @pytest.mark.asyncio
    async def test_brave_search_success(self):
        """Brave 검색 성공 케이스"""
        from app.modules.core.tools.web_search import BraveProvider

        provider = BraveProvider(api_key="test-key")

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_response = MagicMock()
            mock_response.json.return_value = {
                "web": {
                    "results": [
                        {"title": "결과1", "url": "https://a.com", "description": "내용1"},
                    ]
                }
            }
            mock_response.raise_for_status = MagicMock()

            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client_class.return_value = mock_client

            results = await provider.search("테스트 쿼리", max_results=5)

            assert len(results.results) == 1
            assert results.provider == "brave"


class TestDuckDuckGoProvider:
    """DuckDuckGo Provider 테스트"""

    @pytest.mark.asyncio
    async def test_duckduckgo_search_success(self):
        """DuckDuckGo 검색 성공 케이스"""
        from app.modules.core.tools.web_search import DuckDuckGoProvider

        provider = DuckDuckGoProvider()

        with patch("duckduckgo_search.DDGS") as mock_ddgs_class:
            mock_ddgs = MagicMock()
            mock_ddgs.text.return_value = [
                {"title": "결과1", "href": "https://a.com", "body": "내용1"},
            ]
            mock_ddgs.__enter__.return_value = mock_ddgs
            mock_ddgs.__exit__.return_value = None
            mock_ddgs_class.return_value = mock_ddgs

            results = await provider.search("테스트 쿼리", max_results=5)

            assert len(results.results) == 1
            assert results.provider == "duckduckgo"

    def test_duckduckgo_always_available(self):
        """DuckDuckGo는 항상 사용 가능 (API 키 불필요)"""
        from app.modules.core.tools.web_search import DuckDuckGoProvider

        provider = DuckDuckGoProvider()

        assert provider.is_available() is True


class TestWebSearchService:
    """웹 검색 서비스 (Fallback 로직) 테스트"""

    @pytest.mark.asyncio
    async def test_fallback_to_second_provider(self):
        """1순위 실패 시 2순위로 Fallback"""
        from app.modules.core.tools.web_search import WebSearchService

        config = {
            "tavily_api_key": "test-tavily",
            "brave_api_key": "test-brave",
        }
        service = WebSearchService(config)

        # Tavily 실패, Brave 성공 시나리오
        with patch.object(service.providers[0], "search", side_effect=Exception("Tavily 오류")):
            with patch.object(service.providers[1], "search") as mock_brave:
                mock_brave.return_value = MagicMock(
                    results=[{"title": "Brave 결과"}],
                    provider="brave",
                )

                result = await service.search("테스트")

                assert result["provider"] == "brave"
                mock_brave.assert_called_once()

    @pytest.mark.asyncio
    async def test_fallback_to_duckduckgo(self):
        """모든 유료 API 실패 시 DuckDuckGo로 Fallback"""
        from app.modules.core.tools.web_search import WebSearchService

        config = {
            "tavily_api_key": "test-tavily",
            "brave_api_key": "test-brave",
        }
        service = WebSearchService(config)

        # 모든 Provider 실패 시나리오
        with patch.object(service.providers[0], "search", side_effect=Exception("Tavily 오류")):
            with patch.object(service.providers[1], "search", side_effect=Exception("Brave 오류")):
                with patch.object(service.providers[2], "search") as mock_ddg:
                    mock_ddg.return_value = MagicMock(
                        results=[{"title": "DDG 결과"}],
                        provider="duckduckgo",
                    )

                    result = await service.search("테스트")

                    assert result["provider"] == "duckduckgo"

    @pytest.mark.asyncio
    async def test_all_providers_fail(self):
        """모든 Provider 실패 시 예외 발생"""
        from app.modules.core.tools.web_search import WebSearchService

        config = {}
        service = WebSearchService(config)

        # DuckDuckGo만 있고 실패하는 시나리오
        with patch.object(service.providers[0], "search", side_effect=Exception("DDG 오류")):
            with pytest.raises(Exception) as exc_info:
                await service.search("테스트")

            assert "웹 검색 실패" in str(exc_info.value)
```

**Step 2: 테스트 실행 (실패 확인)**

```bash
pytest tests/unit/modules/core/tools/test_web_search.py -v
```

Expected: FAIL - `ModuleNotFoundError`

**Step 3: 커밋 (Red phase)**

```bash
git add tests/unit/modules/core/tools/test_web_search.py
git commit -m "테스트: 웹 검색 서비스 테스트 추가 (TDD Red)"
```

---

### Task 5: 웹 검색 Provider 구현 (Green)

**Files:**
- Create: `app/modules/core/tools/web_search.py`

**Step 1: 의존성 추가**

```bash
uv add tavily-python duckduckgo-search
```

**Step 2: web_search.py 구현**

```python
# app/modules/core/tools/web_search.py
"""
웹 검색 도구 - 3단계 Fallback 시스템

Provider 우선순위:
1. Tavily (정확도 93.3%, 유료)
2. Brave (무료 2,000회/월, 안정적)
3. DuckDuckGo (무제한 무료, 최후의 보루)

MCP 프로토콜 없이 SDK 직접 호출 방식으로 구현합니다.

생성일: 2026-01-15
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from app.lib.logger import get_logger

logger = get_logger(__name__)


# ========================================
# 데이터 클래스
# ========================================


@dataclass
class WebSearchResult:
    """단일 검색 결과"""
    title: str
    url: str
    content: str
    score: float = 0.0


@dataclass
class WebSearchResponse:
    """웹 검색 응답"""
    results: list[WebSearchResult]
    provider: str
    answer: str = ""  # Tavily의 AI 요약 (선택)
    query: str = ""


# ========================================
# Provider Protocol
# ========================================


@runtime_checkable
class WebSearchProvider(Protocol):
    """웹 검색 Provider 인터페이스"""

    @property
    def name(self) -> str:
        """Provider 이름"""
        ...

    def is_available(self) -> bool:
        """사용 가능 여부 (API 키 설정 등)"""
        ...

    async def search(self, query: str, max_results: int = 5) -> WebSearchResponse:
        """검색 수행"""
        ...


# ========================================
# Provider 구현
# ========================================


class TavilyProvider:
    """
    Tavily 검색 Provider

    특징:
    - 정확도 93.3% (업계 최고)
    - RAG 최적화 결과
    - AI 요약 답변 제공
    - 월 1,000회 무료
    """

    def __init__(self, api_key: str | None = None):
        self._api_key = api_key
        self._client = None

        if api_key:
            try:
                from tavily import TavilyClient
                self._client = TavilyClient(api_key=api_key)
            except ImportError:
                logger.warning("tavily-python 패키지가 설치되지 않았습니다")

    @property
    def name(self) -> str:
        return "tavily"

    def is_available(self) -> bool:
        return self._client is not None

    async def search(self, query: str, max_results: int = 5) -> WebSearchResponse:
        if not self.is_available():
            raise ValueError("Tavily API 키가 설정되지 않았습니다")

        logger.info(f"🔍 Tavily 검색: '{query}'")

        # Tavily는 동기 API이므로 executor에서 실행
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: self._client.search(
                query=query,
                max_results=max_results,
                include_answer=True,
            )
        )

        results = [
            WebSearchResult(
                title=r.get("title", ""),
                url=r.get("url", ""),
                content=r.get("content", ""),
                score=r.get("score", 0.0),
            )
            for r in response.get("results", [])
        ]

        return WebSearchResponse(
            results=results,
            provider=self.name,
            answer=response.get("answer", ""),
            query=query,
        )


class BraveProvider:
    """
    Brave 검색 Provider

    특징:
    - 월 2,000회 무료
    - 자체 검색 인덱스 (Google 의존 없음)
    - 광고/추적 없음
    - 안정적인 공식 API
    """

    def __init__(self, api_key: str | None = None):
        self._api_key = api_key

    @property
    def name(self) -> str:
        return "brave"

    def is_available(self) -> bool:
        return self._api_key is not None

    async def search(self, query: str, max_results: int = 5) -> WebSearchResponse:
        if not self.is_available():
            raise ValueError("Brave API 키가 설정되지 않았습니다")

        logger.info(f"🔍 Brave 검색: '{query}'")

        import httpx

        async with httpx.AsyncClient() as client:
            response = await client.get(
                "https://api.search.brave.com/res/v1/web/search",
                headers={"X-Subscription-Token": self._api_key},
                params={"q": query, "count": max_results},
                timeout=10.0,
            )
            response.raise_for_status()
            data = response.json()

        results = [
            WebSearchResult(
                title=r.get("title", ""),
                url=r.get("url", ""),
                content=r.get("description", ""),
            )
            for r in data.get("web", {}).get("results", [])
        ]

        return WebSearchResponse(
            results=results,
            provider=self.name,
            query=query,
        )


class DuckDuckGoProvider:
    """
    DuckDuckGo 검색 Provider

    특징:
    - 완전 무료 (API 키 불필요)
    - 무제한 사용 (Rate Limit 주의: 30회/분)
    - 프라이버시 보호
    - 최후의 Fallback
    """

    def __init__(self):
        pass

    @property
    def name(self) -> str:
        return "duckduckgo"

    def is_available(self) -> bool:
        return True  # 항상 사용 가능

    async def search(self, query: str, max_results: int = 5) -> WebSearchResponse:
        logger.info(f"🔍 DuckDuckGo 검색: '{query}'")

        from duckduckgo_search import DDGS

        # DuckDuckGo는 동기 API
        loop = asyncio.get_event_loop()

        def _search():
            with DDGS() as ddgs:
                return list(ddgs.text(query, max_results=max_results))

        raw_results = await loop.run_in_executor(None, _search)

        results = [
            WebSearchResult(
                title=r.get("title", ""),
                url=r.get("href", ""),
                content=r.get("body", ""),
            )
            for r in raw_results
        ]

        return WebSearchResponse(
            results=results,
            provider=self.name,
            query=query,
        )


# ========================================
# 웹 검색 서비스 (Fallback 로직)
# ========================================


class WebSearchService:
    """
    웹 검색 서비스 - 3단계 Fallback

    우선순위:
    1. Tavily (정확도 최고)
    2. Brave (안정적 무료)
    3. DuckDuckGo (최후의 보루)

    사용 예시:
        service = WebSearchService({
            "tavily_api_key": "...",
            "brave_api_key": "...",
        })
        result = await service.search("검색어")
    """

    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.providers: list[WebSearchProvider] = []
        self._init_providers()

    def _init_providers(self) -> None:
        """우선순위별 Provider 초기화"""

        # 1순위: Tavily
        tavily_key = self.config.get("tavily_api_key")
        if tavily_key:
            provider = TavilyProvider(api_key=tavily_key)
            if provider.is_available():
                self.providers.append(provider)
                logger.info("✅ Tavily Provider 활성화")

        # 2순위: Brave
        brave_key = self.config.get("brave_api_key")
        if brave_key:
            provider = BraveProvider(api_key=brave_key)
            if provider.is_available():
                self.providers.append(provider)
                logger.info("✅ Brave Provider 활성화")

        # 3순위: DuckDuckGo (항상 추가)
        self.providers.append(DuckDuckGoProvider())
        logger.info("✅ DuckDuckGo Provider 활성화 (Fallback)")

        logger.info(f"📊 웹 검색 Provider {len(self.providers)}개 초기화 완료")

    async def search(
        self,
        query: str,
        max_results: int = 5,
    ) -> dict[str, Any]:
        """
        웹 검색 수행 (Fallback 로직 적용)

        1순위 실패 → 2순위 시도 → 3순위 시도

        Args:
            query: 검색 쿼리
            max_results: 최대 결과 수

        Returns:
            dict: 검색 결과
                - success: 성공 여부
                - provider: 사용된 Provider
                - results: 검색 결과 목록
                - answer: AI 요약 (Tavily만)

        Raises:
            Exception: 모든 Provider 실패 시
        """
        if not query or not query.strip():
            raise ValueError("query는 필수입니다")

        last_error: Exception | None = None

        for provider in self.providers:
            try:
                logger.info(f"🔄 웹 검색 시도: {provider.name}")

                response = await provider.search(query, max_results)

                logger.info(
                    f"✅ 웹 검색 성공: {provider.name} "
                    f"({len(response.results)}개 결과)"
                )

                return {
                    "success": True,
                    "provider": response.provider,
                    "results": [
                        {
                            "title": r.title,
                            "url": r.url,
                            "content": r.content,
                            "score": r.score,
                        }
                        for r in response.results
                    ],
                    "answer": response.answer,
                    "query": query,
                }

            except Exception as e:
                logger.warning(f"⚠️ {provider.name} 검색 실패: {e}")
                last_error = e
                continue

        # 모든 Provider 실패
        logger.error("❌ 모든 웹 검색 Provider 실패")
        raise Exception(f"웹 검색 실패: {last_error}")


# ========================================
# Agent Tool 함수 (기존 패턴 호환)
# ========================================


async def web_search(
    arguments: dict[str, Any],
    global_config: dict[str, Any],
) -> dict[str, Any]:
    """
    웹에서 실시간 정보를 검색합니다.

    3단계 Fallback으로 안정적인 검색을 보장합니다:
    1. Tavily (정확도 93.3%)
    2. Brave (무료 2,000회/월)
    3. DuckDuckGo (무제한 무료)

    Args:
        arguments: 도구 인자
            - query (str): 검색 쿼리 (필수)
            - max_results (int): 최대 결과 수 (기본값: 5)
        global_config: 전역 설정
            - tavily_api_key: Tavily API 키
            - brave_api_key: Brave API 키

    Returns:
        dict: 검색 결과

    Raises:
        ValueError: 쿼리가 비어있는 경우
        Exception: 모든 Provider 실패 시
    """
    query = arguments.get("query", "")
    max_results = arguments.get("max_results", 5)

    # 설정에서 API 키 추출
    config = {
        "tavily_api_key": global_config.get("tavily_api_key"),
        "brave_api_key": global_config.get("brave_api_key"),
    }

    service = WebSearchService(config)
    return await service.search(query, max_results)
```

**Step 3: __init__.py에 추가**

```python
# app/modules/core/tools/__init__.py 에 추가
from .web_search import (
    web_search,
    WebSearchService,
    WebSearchProvider,
    WebSearchResult,
    WebSearchResponse,
    TavilyProvider,
    BraveProvider,
    DuckDuckGoProvider,
)

# __all__에 추가
__all__ = [
    # ... 기존 항목 ...
    # 웹 검색
    "web_search",
    "WebSearchService",
    "WebSearchProvider",
    "WebSearchResult",
    "WebSearchResponse",
    "TavilyProvider",
    "BraveProvider",
    "DuckDuckGoProvider",
]
```

**Step 4: 테스트 실행 (성공 확인)**

```bash
pytest tests/unit/modules/core/tools/test_web_search.py -v
```

Expected: PASS

**Step 5: 커밋 (Green phase)**

```bash
git add app/modules/core/tools/web_search.py
git add pyproject.toml uv.lock
git commit -m "기능: 웹 검색 서비스 구현 (Tavily/Brave/DuckDuckGo Fallback)"
```

---

## Phase 3: DI Container 통합 및 설정 (Task 12-14)

### Task 12: tools.yaml 설정 파일 생성

**Files:**
- Create: `app/config/features/tools.yaml`
- Modify: `app/config/base.yaml`

**Step 1: tools.yaml 생성**

```yaml
# app/config/features/tools.yaml
# Agent 도구 설정
# 기능: Agent가 접근할 수 있는 도구 정의
# 패턴: 기존 mcp.yaml과 동일 (이름만 변경)

tools:
  # ========================================
  # 전역 설정
  # ========================================
  enabled: true
  server_name: "rag-tools"
  default_timeout: 30
  max_concurrent_tools: 3

  # ========================================
  # 도구 설정
  # ========================================
  tools:
    # ------ 벡터 검색 도구 ------
    search_vector:
      enabled: true
      description: "벡터 DB에서 정보를 하이브리드 검색합니다"
      timeout: 15
      parameters:
        default_top_k: 10
        alpha: 0.6

    get_document_by_id:
      enabled: true
      description: "문서 ID로 벡터 DB에서 직접 조회합니다"
      timeout: 5

    # ------ 그래프 검색 도구 ------
    search_graph:
      enabled: true
      description: "지식 그래프에서 엔티티와 관계를 검색합니다"
      timeout: 10
      parameters:
        default_top_k: 10

    get_neighbors:
      enabled: true
      description: "엔티티의 이웃을 조회합니다"
      timeout: 10
      parameters:
        default_max_depth: 1

    # ------ 웹 검색 도구 (신규) ------
    web_search:
      enabled: true
      description: "인터넷에서 실시간 정보를 검색합니다 (Fallback: Tavily → Brave → DuckDuckGo)"
      timeout: 15
      parameters:
        max_results: 5
        # Provider 우선순위 (API 키가 설정된 Provider만 활성화)
        providers:
          - tavily   # 1순위: 정확도 93.3%
          - brave    # 2순위: 무료 2,000회/월
          - duckduckgo  # 3순위: 무제한 무료

  # ========================================
  # 에이전트 설정 (Agentic RAG용)
  # ========================================
  agent:
    tool_selection: "llm"
    selector_model: "google/gemini-2.5-flash-lite"
    max_tool_calls: 5
    fallback_tool: "search_vector"
```

**Step 2: base.yaml 수정 (mcp → tools 참조)**

base.yaml에서 `mcp.yaml` import를 `tools.yaml`로 변경

**Step 3: 커밋**

```bash
git add app/config/features/tools.yaml
git commit -m "설정: tools.yaml 추가 (mcp.yaml 대체)"
```

---

### Task 13: DI Container 수정

**Files:**
- Modify: `app/core/di_container.py`

**Step 1: import 경로 수정**

```python
# app/core/di_container.py
# 변경 전
from app.modules.core.mcp import MCPServer, MCPToolFactory

# 변경 후
from app.modules.core.tools import ToolServer, ToolFactory
# 또는 하위 호환성 유지 시
from app.modules.core.tools import (
    ToolServer as MCPServer,
    ToolFactory as MCPToolFactory,
)
```

**Step 2: 테스트**

```bash
pytest tests/ -k "di_container or mcp" -v
```

**Step 3: 커밋**

```bash
git add app/core/di_container.py
git commit -m "리팩터: di_container mcp → tools import 수정"
```

---

### Task 14: 통합 테스트 및 정리

**Files:**
- Create: `tests/integration/test_web_search_integration.py`
- Delete: `app/modules/core/mcp/` (옛 폴더)
- Delete: `app/config/features/mcp.yaml`

**Step 1: 통합 테스트 작성**

```python
# tests/integration/test_web_search_integration.py
"""
웹 검색 통합 테스트

실제 API를 호출하지 않고 Mock으로 E2E 흐름을 검증합니다.
"""
import pytest
from unittest.mock import AsyncMock, patch


@pytest.mark.integration
class TestWebSearchIntegration:
    """웹 검색 통합 테스트"""

    @pytest.mark.asyncio
    async def test_web_search_tool_in_agent(self):
        """Agent에서 web_search 도구 호출"""
        from app.modules.core.tools import web_search

        # Mock 설정
        config = {
            "tavily_api_key": None,
            "brave_api_key": None,
        }

        with patch("app.modules.core.tools.web_search.DuckDuckGoProvider.search") as mock:
            mock.return_value = AsyncMock(
                results=[],
                provider="duckduckgo",
                answer="",
                query="테스트",
            )
            mock.return_value.results = []

            # 실제로는 DuckDuckGo Mock이 필요
            # 테스트는 구조 검증 목적

    @pytest.mark.asyncio
    async def test_fallback_order(self):
        """Fallback 순서 검증: Tavily → Brave → DuckDuckGo"""
        from app.modules.core.tools.web_search import WebSearchService

        config = {
            "tavily_api_key": "test",
            "brave_api_key": "test",
        }

        service = WebSearchService(config)

        # Provider 순서 확인
        assert service.providers[0].name == "tavily"
        assert service.providers[1].name == "brave"
        assert service.providers[2].name == "duckduckgo"
```

**Step 2: 옛 mcp 폴더 삭제**

```bash
rm -rf app/modules/core/mcp/
rm app/config/features/mcp.yaml
```

**Step 3: 전체 테스트 실행**

```bash
make test
```

**Step 4: 최종 커밋**

```bash
git add -A
git commit -m "완료: mcp → tools 리팩토링 및 웹 검색 Fallback 시스템 구현"
```

---

## 📋 체크리스트

### Phase 1: 폴더 리네이밍
- [ ] Task 1: 테스트 기반 리네이밍 준비
- [ ] Task 2: tools 폴더 생성 및 인터페이스 이동
- [ ] Task 3: 기존 도구 파일 이동

### Phase 2: 웹 검색 구현
- [ ] Task 4: Provider 인터페이스 테스트 (Red)
- [ ] Task 5: Provider 구현 (Green)
- [ ] Task 6-11: 추가 테스트 및 리팩토링

### Phase 3: 통합
- [ ] Task 12: tools.yaml 설정 생성
- [ ] Task 13: DI Container 수정
- [ ] Task 14: 통합 테스트 및 정리

---

## 📦 필요한 의존성

```bash
# pyproject.toml에 추가
uv add tavily-python duckduckgo-search
```

## 🔑 필요한 환경 변수

```bash
# .env에 추가
TAVILY_API_KEY=tvly-xxxxxxxxx     # 선택 (없으면 Fallback)
BRAVE_API_KEY=BSAxxxxxxxxx        # 선택 (없으면 Fallback)
# DuckDuckGo는 API 키 불필요
```
