# Reranker Minor 이슈 해결 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** OpenRouter 리랭커 구현 및 YAML 필드명 일관성 수정

**Architecture:** GeminiFlashReranker를 템플릿으로 OpenRouterReranker 구현, YAML의 `default_provider`를 `provider`로 통일

**Tech Stack:** Python, httpx, Pydantic, pytest

---

## Task 1: OpenRouterReranker 구현

**Files:**
- Create: `app/modules/core/retrieval/rerankers/openrouter_reranker.py`
- Modify: `app/modules/core/retrieval/rerankers/__init__.py`
- Modify: `app/modules/core/retrieval/rerankers/factory.py:108-116`
- Test: `tests/unit/retrieval/rerankers/test_openrouter_reranker.py`

---

### Step 1: 테스트 파일 작성

```python
# tests/unit/retrieval/rerankers/test_openrouter_reranker.py
"""OpenRouterReranker 단위 테스트"""

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.modules.core.retrieval.interfaces import SearchResult


class TestOpenRouterRerankerInitialization:
    """초기화 테스트"""

    def test_init_with_valid_api_key(self):
        """유효한 API 키로 초기화"""
        from app.modules.core.retrieval.rerankers.openrouter_reranker import (
            OpenRouterReranker,
        )

        reranker = OpenRouterReranker(api_key="test-key")
        assert reranker.api_key == "test-key"
        assert reranker.model == "google/gemini-2.5-flash-lite"

    def test_init_without_api_key_raises_error(self):
        """API 키 없이 초기화 시 에러"""
        from app.modules.core.retrieval.rerankers.openrouter_reranker import (
            OpenRouterReranker,
        )

        with pytest.raises(ValueError, match="API key"):
            OpenRouterReranker(api_key="")

    def test_init_with_custom_model(self):
        """커스텀 모델로 초기화"""
        from app.modules.core.retrieval.rerankers.openrouter_reranker import (
            OpenRouterReranker,
        )

        reranker = OpenRouterReranker(
            api_key="test-key", model="anthropic/claude-3-haiku"
        )
        assert reranker.model == "anthropic/claude-3-haiku"


class TestOpenRouterRerankerReranking:
    """리랭킹 기능 테스트"""

    @pytest.fixture
    def sample_results(self) -> list[SearchResult]:
        return [
            SearchResult(id="1", content="문서 1 내용", score=0.8, metadata={}),
            SearchResult(id="2", content="문서 2 내용", score=0.6, metadata={}),
            SearchResult(id="3", content="문서 3 내용", score=0.4, metadata={}),
        ]

    @pytest.mark.asyncio
    async def test_rerank_empty_results(self):
        """빈 결과 리랭킹"""
        from app.modules.core.retrieval.rerankers.openrouter_reranker import (
            OpenRouterReranker,
        )

        reranker = OpenRouterReranker(api_key="test-key")
        result = await reranker.rerank("쿼리", [])
        assert result == []

    @pytest.mark.asyncio
    async def test_rerank_success(self, sample_results: list[SearchResult]):
        """정상 리랭킹"""
        from app.modules.core.retrieval.rerankers.openrouter_reranker import (
            OpenRouterReranker,
        )

        mock_response = {
            "choices": [
                {
                    "message": {
                        "content": '{"rankings": [{"index": 1, "score": 0.95}, {"index": 0, "score": 0.85}, {"index": 2, "score": 0.70}]}'
                    }
                }
            ]
        }

        reranker = OpenRouterReranker(api_key="test-key")

        with patch.object(
            reranker.http_client, "post", new_callable=AsyncMock
        ) as mock_post:
            mock_post.return_value = AsyncMock(
                status_code=200,
                json=lambda: mock_response,
                raise_for_status=lambda: None,
            )

            result = await reranker.rerank("테스트 쿼리", sample_results)

            assert len(result) == 3
            assert result[0].score == 0.95
            assert result[0].id == "2"  # index 1 → id "2"


class TestOpenRouterRerankerErrorHandling:
    """에러 처리 테스트"""

    @pytest.fixture
    def sample_results(self) -> list[SearchResult]:
        return [
            SearchResult(id="1", content="문서 1 내용", score=0.8, metadata={}),
        ]

    @pytest.mark.asyncio
    async def test_timeout_returns_original(self, sample_results: list[SearchResult]):
        """타임아웃 시 원본 반환"""
        from app.modules.core.retrieval.rerankers.openrouter_reranker import (
            OpenRouterReranker,
        )

        reranker = OpenRouterReranker(api_key="test-key", timeout=1)

        with patch.object(
            reranker.http_client, "post", new_callable=AsyncMock
        ) as mock_post:
            mock_post.side_effect = httpx.TimeoutException("timeout")

            result = await reranker.rerank("쿼리", sample_results)

            assert result == sample_results  # 원본 반환

    @pytest.mark.asyncio
    async def test_api_error_returns_original(self, sample_results: list[SearchResult]):
        """API 에러 시 원본 반환"""
        from app.modules.core.retrieval.rerankers.openrouter_reranker import (
            OpenRouterReranker,
        )

        reranker = OpenRouterReranker(api_key="test-key")

        with patch.object(
            reranker.http_client, "post", new_callable=AsyncMock
        ) as mock_post:
            mock_post.side_effect = httpx.HTTPStatusError(
                "error", request=None, response=AsyncMock(status_code=500)
            )

            result = await reranker.rerank("쿼리", sample_results)

            assert result == sample_results  # 원본 반환


class TestOpenRouterRerankerUtilities:
    """유틸리티 메서드 테스트"""

    def test_supports_caching(self):
        """캐싱 지원 여부"""
        from app.modules.core.retrieval.rerankers.openrouter_reranker import (
            OpenRouterReranker,
        )

        reranker = OpenRouterReranker(api_key="test-key")
        assert reranker.supports_caching() is True

    def test_get_stats_initial(self):
        """초기 통계"""
        from app.modules.core.retrieval.rerankers.openrouter_reranker import (
            OpenRouterReranker,
        )

        reranker = OpenRouterReranker(api_key="test-key")
        stats = reranker.get_stats()

        assert stats["total_requests"] == 0
        assert stats["successful_requests"] == 0
        assert stats["failed_requests"] == 0
```

---

### Step 2: 테스트 실행하여 실패 확인

Run: `uv run pytest tests/unit/retrieval/rerankers/test_openrouter_reranker.py -v`

Expected: FAIL with "ModuleNotFoundError" 또는 "ImportError"

---

### Step 3: OpenRouterReranker 구현

```python
# app/modules/core/retrieval/rerankers/openrouter_reranker.py
"""
OpenRouter LLM 기반 리랭커

OpenRouter API를 통해 다양한 LLM 모델로 리랭킹 수행.
지원 모델: google/gemini-2.5-flash-lite, anthropic/claude-3-haiku 등

참고: https://openrouter.ai/docs
"""

import json
import re
import time
from typing import Any

import httpx

from .....lib.logger import get_logger
from ..interfaces import IReranker, SearchResult

logger = get_logger(__name__)


class OpenRouterReranker(IReranker):
    """
    OpenRouter API 기반 LLM 리랭커

    특징:
    - 다양한 LLM 모델 지원 (Gemini, Claude, GPT 등)
    - httpx 비동기 HTTP 호출
    - JSON 형식 응답 파싱
    - Graceful Fallback (오류 시 원본 반환)
    """

    def __init__(
        self,
        api_key: str,
        model: str = "google/gemini-2.5-flash-lite",
        max_documents: int = 20,
        timeout: int = 15,
    ):
        """
        Args:
            api_key: OpenRouter API 키
            model: 사용할 모델 (provider/model 형식)
            max_documents: 처리할 최대 문서 개수
            timeout: 타임아웃 (초)
        """
        if not api_key:
            raise ValueError("OpenRouter API key is required")

        self.api_key = api_key
        self.model = model
        self.max_documents = max_documents
        self.timeout = timeout

        # httpx AsyncClient 생성
        self.http_client = httpx.AsyncClient(
            base_url="https://openrouter.ai/api/v1",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            timeout=httpx.Timeout(timeout, connect=5.0),
        )

        # 통계 추적
        self._stats = {
            "total_requests": 0,
            "successful_requests": 0,
            "failed_requests": 0,
            "total_processing_time": 0.0,
        }

        logger.info(f"OpenRouterReranker 초기화: model={model}")

    async def initialize(self) -> None:
        """리랭커 초기화 (HTTP API이므로 추가 초기화 불필요)"""
        logger.debug("OpenRouterReranker 초기화 완료")

    async def close(self) -> None:
        """리소스 정리"""
        await self.http_client.aclose()
        logger.info("OpenRouterReranker 종료 완료")

    async def rerank(
        self,
        query: str,
        results: list[SearchResult],
        top_n: int | None = None,
    ) -> list[SearchResult]:
        """
        검색 결과 리랭킹

        Args:
            query: 사용자 쿼리
            results: 원본 검색 결과
            top_n: 반환할 최대 결과 수 (None이면 전체)

        Returns:
            리랭킹된 검색 결과
        """
        if not results:
            logger.warning("리랭킹할 결과가 없습니다")
            return []

        self._stats["total_requests"] += 1
        start_time = time.time()

        # 문서 수 제한
        documents = results[: self.max_documents]

        try:
            # 프롬프트 구성
            prompt = self._build_prompt(query, documents)

            # API 요청
            response = await self.http_client.post(
                "/chat/completions",
                json={
                    "model": self.model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.0,  # 결정론적 응답
                },
            )
            response.raise_for_status()
            response_data = response.json()

            # 응답 파싱
            content = response_data["choices"][0]["message"]["content"]
            rankings = self._parse_rankings(content, len(documents))

            # 결과 재구성
            reranked = self._apply_rankings(documents, rankings)

            # top_n 적용
            if top_n is not None:
                reranked = reranked[:top_n]

            self._stats["successful_requests"] += 1
            self._stats["total_processing_time"] += time.time() - start_time

            logger.info(
                f"OpenRouter 리랭킹 완료: {len(results)} -> {len(reranked)}개 반환"
            )
            return reranked

        except httpx.TimeoutException:
            self._stats["failed_requests"] += 1
            logger.error(f"OpenRouter API 타임아웃 (timeout={self.timeout}s)")
            return results

        except httpx.HTTPStatusError as e:
            self._stats["failed_requests"] += 1
            logger.error(f"OpenRouter API HTTP 에러: {e.response.status_code}")
            return results

        except Exception as e:
            self._stats["failed_requests"] += 1
            logger.error(f"OpenRouter 리랭킹 실패: {e}")
            return results

    def _build_prompt(self, query: str, documents: list[SearchResult]) -> str:
        """리랭킹 프롬프트 생성"""
        docs_text = "\n".join(
            f"[{i}] {doc.content[:500]}" for i, doc in enumerate(documents)
        )

        return f"""다음 문서들을 쿼리와의 관련성에 따라 순위를 매겨주세요.

쿼리: {query}

문서들:
{docs_text}

JSON 형식으로 응답해주세요:
{{"rankings": [{{"index": 문서번호, "score": 0.0-1.0 점수}}]}}

점수가 높은 순서대로 정렬하여 응답해주세요."""

    def _parse_rankings(
        self, content: str, num_docs: int
    ) -> list[dict[str, Any]]:
        """응답에서 rankings 파싱"""
        try:
            # JSON 추출 시도
            json_match = re.search(r"\{.*\}", content, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
                if "rankings" in data:
                    return data["rankings"]
        except json.JSONDecodeError:
            pass

        # 파싱 실패 시 기본 순위 반환
        logger.warning("Rankings 파싱 실패, 기본 순위 사용")
        return [{"index": i, "score": 1.0 - (i * 0.1)} for i in range(num_docs)]

    def _apply_rankings(
        self, documents: list[SearchResult], rankings: list[dict[str, Any]]
    ) -> list[SearchResult]:
        """rankings를 적용하여 결과 재구성"""
        reranked = []
        for rank in rankings:
            idx = rank.get("index", 0)
            score = rank.get("score", 0.5)

            if 0 <= idx < len(documents):
                doc = documents[idx]
                reranked.append(
                    SearchResult(
                        id=doc.id,
                        content=doc.content,
                        score=float(score),
                        metadata=doc.metadata,
                    )
                )

        # 누락된 문서 추가
        included_ids = {r.id for r in reranked}
        for doc in documents:
            if doc.id not in included_ids:
                reranked.append(doc)

        return reranked

    def supports_caching(self) -> bool:
        """캐싱 지원 여부"""
        return True

    def get_stats(self) -> dict[str, Any]:
        """통계 반환"""
        total = self._stats["total_requests"]
        success_rate = (
            self._stats["successful_requests"] / total * 100 if total > 0 else 0.0
        )

        return {
            "total_requests": self._stats["total_requests"],
            "successful_requests": self._stats["successful_requests"],
            "failed_requests": self._stats["failed_requests"],
            "success_rate": round(success_rate, 2),
            "model": self.model,
            "avg_processing_time": (
                round(self._stats["total_processing_time"] / total, 3)
                if total > 0
                else 0.0
            ),
        }
```

---

### Step 4: 테스트 실행하여 통과 확인

Run: `uv run pytest tests/unit/retrieval/rerankers/test_openrouter_reranker.py -v`

Expected: PASS

---

### Step 5: __init__.py에 export 추가

Modify: `app/modules/core/retrieval/rerankers/__init__.py`

```python
# 기존 import 뒤에 추가
from .openrouter_reranker import OpenRouterReranker

# __all__ 리스트에 추가
__all__ = [
    # ... 기존 항목들 ...
    "OpenRouterReranker",
]
```

---

### Step 6: Factory에 OpenRouterReranker 등록

Modify: `app/modules/core/retrieval/rerankers/factory.py:29` (import 추가)

```python
from .openrouter_reranker import OpenRouterReranker
```

Modify: `app/modules/core/retrieval/rerankers/factory.py:108-116`

```python
    "openrouter": {
        "class": OpenRouterReranker,  # ✅ None → OpenRouterReranker
        "api_key_env": "OPENROUTER_API_KEY",
        "default_config": {
            "model": "google/gemini-2.5-flash-lite",
            "max_documents": 20,
            "timeout": 15,
        },
    },
```

Modify: `app/modules/core/retrieval/rerankers/factory.py:237-240` (_create_llm_reranker 메서드에 openrouter 케이스 추가)

```python
        elif provider == "openrouter":
            reranker = OpenRouterReranker(
                api_key=api_key,
                model=provider_config.get("model", defaults["model"]),
                max_documents=provider_config.get(
                    "max_documents", defaults["max_documents"]
                ),
                timeout=provider_config.get("timeout", defaults["timeout"]),
            )
```

---

### Step 7: 린트 및 타입 체크

Run: `make lint && make type-check`

Expected: All checks passed, no issues found

---

### Step 8: 커밋

```bash
git add app/modules/core/retrieval/rerankers/openrouter_reranker.py \
        app/modules/core/retrieval/rerankers/__init__.py \
        app/modules/core/retrieval/rerankers/factory.py \
        tests/unit/retrieval/rerankers/test_openrouter_reranker.py

git commit -m "기능: OpenRouterReranker 구현

- OpenRouter API 기반 LLM 리랭커 구현
- httpx 비동기 HTTP 호출
- Graceful Fallback (오류 시 원본 반환)
- Factory에 openrouter provider 등록
- 단위 테스트 추가

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Task 2: YAML 필드명 일관성 수정

**Files:**
- Modify: `app/config/features/reranking.yaml:28`
- Modify: `app/config/schemas/reranking.py:173-202`
- Test: `tests/unit/config/schemas/test_reranking_schema_v2.py`

---

### Step 1: 스키마에 default_provider alias 추가 테스트

```python
# tests/unit/config/schemas/test_reranking_schema_v2.py에 추가

class TestRerankingConfigV2FieldAliases:
    """필드 별칭 테스트"""

    def test_default_provider_alias_accepted(self):
        """default_provider가 provider로 매핑됨"""
        from app.config.schemas.reranking import RerankingConfigV2

        config = RerankingConfigV2(
            approach="cross-encoder",
            default_provider="jina",  # 레거시 필드명
        )
        assert config.provider == "jina"

    def test_provider_field_preferred(self):
        """provider 필드가 우선"""
        from app.config.schemas.reranking import RerankingConfigV2

        config = RerankingConfigV2(
            approach="cross-encoder",
            provider="cohere",
        )
        assert config.provider == "cohere"
```

---

### Step 2: 테스트 실행하여 실패 확인

Run: `uv run pytest tests/unit/config/schemas/test_reranking_schema_v2.py::TestRerankingConfigV2FieldAliases -v`

Expected: FAIL

---

### Step 3: 스키마에 default_provider alias 추가

Modify: `app/config/schemas/reranking.py:197-202`

```python
    provider: Literal[
        "google", "openai", "jina", "cohere", "openrouter", "sentence-transformers"
    ] = Field(
        default="jina",
        alias="default_provider",  # ✅ 레거시 호환 alias 추가
        description="서비스 제공자",
    )
```

---

### Step 4: 테스트 실행하여 통과 확인

Run: `uv run pytest tests/unit/config/schemas/test_reranking_schema_v2.py -v`

Expected: PASS

---

### Step 5: YAML 주석 업데이트

Modify: `app/config/features/reranking.yaml:28`

```yaml
  provider: "jina"  # approach에 따라 유효한 provider 선택 (레거시: default_provider)
```

---

### Step 6: 린트 및 타입 체크

Run: `make lint && make type-check`

Expected: All checks passed

---

### Step 7: 전체 테스트 실행

Run: `make test`

Expected: 모든 테스트 통과

---

### Step 8: 커밋

```bash
git add app/config/features/reranking.yaml \
        app/config/schemas/reranking.py \
        tests/unit/config/schemas/test_reranking_schema_v2.py

git commit -m "개선: Reranking 설정 필드명 일관성 수정

- provider 필드에 default_provider alias 추가 (레거시 호환)
- YAML 필드명 default_provider → provider로 변경
- 필드 별칭 테스트 추가

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Task 3: 통합 테스트 및 문서 업데이트

**Files:**
- Modify: `docs/PRODUCTION_READINESS_VERIFICATION.md`
- Modify: `CLAUDE.md`

---

### Step 1: Factory 통합 테스트 추가

```python
# tests/unit/retrieval/rerankers/test_reranker_factory_v2.py에 추가

class TestRerankerFactoryV2OpenRouter:
    """OpenRouter provider 테스트"""

    def test_create_openrouter_reranker(self, monkeypatch):
        """OpenRouter 리랭커 생성"""
        monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")

        from app.modules.core.retrieval.rerankers.factory import RerankerFactoryV2
        from app.modules.core.retrieval.rerankers.openrouter_reranker import (
            OpenRouterReranker,
        )

        config = {
            "reranking": {
                "approach": "llm",
                "provider": "openrouter",
                "openrouter": {"model": "anthropic/claude-3-haiku"},
            }
        }

        reranker = RerankerFactoryV2.create(config)
        assert isinstance(reranker, OpenRouterReranker)
        assert reranker.model == "anthropic/claude-3-haiku"
```

---

### Step 2: 테스트 실행

Run: `uv run pytest tests/unit/retrieval/rerankers/test_reranker_factory_v2.py -v`

Expected: PASS

---

### Step 3: CLAUDE.md 업데이트

Modify: `CLAUDE.md` (Reranker 섹션)

```markdown
### 1. 지능형 검색 (Hybrid Retrieval)
- **Reranker v2.1**: 3단계 계층 구조 (approach → provider → model)로 명확한 설정
  - **approach**: `llm`, `cross-encoder`, `late-interaction`, `local` (4종)
  - **provider**: google, openai, jina, cohere, openrouter, sentence-transformers (6종)
  - **v1.2.1 신규**: Cohere (100+ 언어), Local (API 키 불필요)
  - **v1.2.2 신규**: OpenRouter LLM 리랭커 구현 완료
```

---

### Step 4: 린트 및 전체 테스트

Run: `make lint && make test`

Expected: All checks passed

---

### Step 5: 최종 커밋

```bash
git add tests/unit/retrieval/rerankers/test_reranker_factory_v2.py \
        CLAUDE.md

git commit -m "문서: Reranker Minor 이슈 해결 완료

- OpenRouter 리랭커 Factory 통합 테스트 추가
- CLAUDE.md OpenRouter 지원 문서화
- Minor 이슈 2건 모두 해결 완료

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## 검증 체크리스트

- [ ] `uv run pytest tests/unit/retrieval/rerankers/test_openrouter_reranker.py -v` 통과
- [ ] `uv run pytest tests/unit/config/schemas/test_reranking_schema_v2.py -v` 통과
- [ ] `uv run pytest tests/unit/retrieval/rerankers/test_reranker_factory_v2.py -v` 통과
- [ ] `make lint` 통과
- [ ] `make type-check` 통과
- [ ] `make test` 전체 통과

---

## 예상 결과

| 항목 | 이전 | 이후 |
|------|------|------|
| OpenRouter class | `None` | `OpenRouterReranker` |
| YAML 필드명 | `default_provider` | `provider` (alias 지원) |
| Reranker 점수 | 92/100 | 95/100 |
