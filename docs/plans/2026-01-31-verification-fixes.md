# 검증 리포트 Warning 수정 구현 계획

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 검증 리포트에서 발견된 높음/중간 우선순위 Warning 4건을 수정하여 프로젝트 품질을 높인다.

**Architecture:** 각 수정은 독립적이며 순서 무관. gitignore 추가 → 버전 통일 확인 → mypy 에러 수정 → CHANGELOG 생성 → base.yaml 기본값 통일 순서로 진행.

**Tech Stack:** Python 3.11+, mypy, dataclasses, YAML

---

## Task 0: 검증 리포트 gitignore 처리

**Files:**
- Modify: `.gitignore` (141행 근처)

**Step 1: gitignore 상태 확인**

현재 `.gitignore`에 `docs/verification-report.md`가 이미 포함되어 있는지 확인:

```bash
grep "verification-report" .gitignore
```

Expected: `docs/verification-report.md` 출력 (이미 존재)

**Step 2: 이미 존재하면 skip, 없으면 추가**

만약 없다면 `.gitignore`의 `# Internal Analysis` 섹션 마지막에 추가:

```
docs/verification-report.md
```

**Step 3: 확인**

```bash
git status docs/verification-report.md
```

Expected: Untracked 또는 표시 안 됨 (ignored)

---

## Task 1: 버전 통일 확인

**Files:**
- 확인: `pyproject.toml:3`
- 확인: `CLAUDE.md:1, 8`

**Step 1: 현재 버전 확인**

```bash
grep -n "version" pyproject.toml | head -3
grep -n "v1\." CLAUDE.md | head -5
```

**Step 2: 판단**

- `pyproject.toml` = `1.0.7`, `CLAUDE.md` 헤더 = `v1.0.7` → 이미 통일됨 ✅
- 만약 불일치하면: `CLAUDE.md` 헤더의 버전을 `pyproject.toml` 값에 맞춰 수정
- `CLAUDE.md` 본문의 `v1.2.1`은 Reranker 기능의 릴리스 버전 태그이므로 그대로 유지 (기능별 버전 표기)

**Step 3: 커밋 (변경 있을 때만)**

```bash
git add CLAUDE.md
git commit -m "문서: CLAUDE.md 버전을 pyproject.toml과 통일"
```

---

## Task 2: mypy 타입 에러 수정 — hybrid_merger.py (4건)

**Files:**
- Modify: `app/modules/core/retrieval/bm25_engine/hybrid_merger.py:75-82`
- Test: `tests/unit/retrieval/` (기존 테스트)

**배경:**

`hybrid_merger.py`의 `merge()` 메서드에서 `bm25_results` 파라미터 타입이 `list[dict[str, Any]]`인데, mypy가 4가지 에러를 보고:

1. 75행: `result` 변수에 `dict[str, Any]`를 할당하는데 타입 추론 문제
2. 76행: `result["id"]` — `SearchResult`는 인덱싱 불가
3. 81행: `result["content"]` — 같은 문제
4. 82행: `result.get("metadata", {})` — `SearchResult`에 `.get()` 없음

**원인 분석:**

실제 코드를 보면 75행부터는 BM25 결과 처리 블록이고, `bm25_results`는 이미 `list[dict[str, Any]]`로 선언되어 있다. mypy가 혼동하는 이유는 `for rank, result in enumerate(bm25_results)` 루프에서 이전 루프의 `result` 변수(타입: `SearchResult`)와 같은 이름을 재사용하기 때문이다.

**Step 1: 실패 테스트 작성**

`tests/unit/retrieval/test_hybrid_merger.py` 파일 생성:

```python
"""
HybridMerger 단위 테스트

목적: RRF 병합 로직의 정확성과 타입 안전성을 검증합니다.
대상: app/modules/core/retrieval/bm25_engine/hybrid_merger.py
의존성: pytest, app.modules.core.retrieval.interfaces.SearchResult
"""

import pytest

from app.modules.core.retrieval.bm25_engine.hybrid_merger import HybridMerger
from app.modules.core.retrieval.interfaces import SearchResult


class TestHybridMergerMerge:
    """merge() 메서드의 RRF 병합 로직 검증"""

    def test_dense_전용_병합(self) -> None:
        """BM25 결과 없이 Dense만으로 병합 시 정상 동작해야 합니다."""
        merger = HybridMerger(alpha=1.0)
        dense = [
            SearchResult(id="d1", content="문서1", score=0.9, metadata={"src": "dense"}),
        ]

        results = merger.merge(dense_results=dense, bm25_results=[], top_k=5)

        assert len(results) == 1
        assert results[0].id == "d1"

    def test_bm25_전용_병합(self) -> None:
        """Dense 결과 없이 BM25만으로 병합 시 정상 동작해야 합니다."""
        merger = HybridMerger(alpha=0.0)
        bm25 = [
            {"id": "b1", "content": "BM25 문서", "metadata": {"src": "bm25"}},
        ]

        results = merger.merge(dense_results=[], bm25_results=bm25, top_k=5)

        assert len(results) == 1
        assert results[0].id == "b1"
        assert results[0].content == "BM25 문서"

    def test_하이브리드_병합_중복_문서(self) -> None:
        """동일 문서가 Dense와 BM25 모두에 있으면 점수가 합산되어야 합니다."""
        merger = HybridMerger(alpha=0.5)
        dense = [
            SearchResult(id="shared", content="공유 문서", score=0.9, metadata={}),
        ]
        bm25 = [
            {"id": "shared", "content": "공유 문서", "metadata": {}},
        ]

        results = merger.merge(dense_results=dense, bm25_results=bm25, top_k=5)

        assert len(results) == 1
        assert results[0].id == "shared"
        # Dense RRF + BM25 RRF 합산
        expected_score = 0.5 * (1.0 / 61) + 0.5 * (1.0 / 61)
        assert abs(results[0].score - expected_score) < 1e-9

    def test_bm25_metadata_없으면_빈_dict(self) -> None:
        """BM25 결과에 metadata 키가 없으면 빈 dict가 사용되어야 합니다."""
        merger = HybridMerger(alpha=0.0)
        bm25 = [
            {"id": "no-meta", "content": "메타 없음"},  # metadata 키 없음
        ]

        results = merger.merge(dense_results=[], bm25_results=bm25, top_k=5)

        assert results[0].metadata == {}

    def test_빈_결과(self) -> None:
        """양쪽 모두 비어 있으면 빈 리스트를 반환해야 합니다."""
        merger = HybridMerger(alpha=0.5)

        results = merger.merge(dense_results=[], bm25_results=[], top_k=5)

        assert results == []


class TestHybridMergerInit:
    """HybridMerger 초기화 검증"""

    def test_유효하지_않은_alpha_예외(self) -> None:
        """alpha가 0.0~1.0 범위 밖이면 ValueError를 발생시켜야 합니다."""
        with pytest.raises(ValueError, match="alpha"):
            HybridMerger(alpha=1.5)

        with pytest.raises(ValueError, match="alpha"):
            HybridMerger(alpha=-0.1)
```

**Step 2: 테스트 실행 — 현재 상태 확인**

```bash
uv run pytest tests/unit/retrieval/test_hybrid_merger.py -v
```

Expected: 모든 테스트 PASS (코드 자체는 런타임에 정상 동작, mypy만 에러)

**Step 3: mypy 에러 확인**

```bash
uv run mypy app/modules/core/retrieval/bm25_engine/hybrid_merger.py
```

Expected: 4건 에러

**Step 4: 코드 수정 — 변수명 분리로 mypy 에러 해결**

`app/modules/core/retrieval/bm25_engine/hybrid_merger.py`의 BM25 루프에서 변수명을 `bm25_item`으로 변경하여 mypy가 이전 루프의 `result: SearchResult` 타입과 혼동하지 않도록 합니다:

**수정 전 (74-83행):**
```python
        bm25_weight = 1.0 - self._alpha
        for rank, result in enumerate(bm25_results):
            doc_id = result["id"]
            rrf_score = bm25_weight * (1.0 / (_RRF_K + rank + 1))
            rrf_scores[doc_id] = rrf_scores.get(doc_id, 0.0) + rrf_score
            if doc_id not in doc_info:
                doc_info[doc_id] = {
                    "content": result["content"],
                    "metadata": result.get("metadata", {}),
                }
```

**수정 후:**
```python
        bm25_weight = 1.0 - self._alpha
        for rank, bm25_item in enumerate(bm25_results):
            doc_id = bm25_item["id"]
            rrf_score = bm25_weight * (1.0 / (_RRF_K + rank + 1))
            rrf_scores[doc_id] = rrf_scores.get(doc_id, 0.0) + rrf_score
            if doc_id not in doc_info:
                doc_info[doc_id] = {
                    "content": bm25_item["content"],
                    "metadata": bm25_item.get("metadata", {}),
                }
```

**Step 5: mypy 재검증**

```bash
uv run mypy app/modules/core/retrieval/bm25_engine/hybrid_merger.py
```

Expected: Success (0 에러)

**Step 6: 테스트 재실행**

```bash
uv run pytest tests/unit/retrieval/test_hybrid_merger.py -v
```

Expected: 모든 테스트 PASS

**Step 7: 커밋**

```bash
git add app/modules/core/retrieval/bm25_engine/hybrid_merger.py tests/unit/retrieval/test_hybrid_merger.py
git commit -m "수정: hybrid_merger.py mypy 타입 에러 4건 해결

BM25 루프 변수명을 bm25_item으로 분리하여
SearchResult 타입과의 혼동 해소.
테스트 7건 추가."
```

---

## Task 3: mypy 타입 에러 수정 — chroma_retriever.py (3건)

**Files:**
- Modify: `app/modules/core/retrieval/retrievers/chroma_retriever.py:160-179`

**배경:**

3건의 mypy 에러:
1. 161행: `self._bm25_index.search()` — `_bm25_index`가 `Any | None`인데 None 체크 없음
2. 162행: `self._hybrid_merger.merge()` — `_hybrid_merger`가 `Any | None`인데 None 체크 없음
3. 179행: `Returning Any from function declared to return list[SearchResult]` — 반환 타입 불명확

**Step 1: mypy 에러 확인**

```bash
uv run mypy app/modules/core/retrieval/retrievers/chroma_retriever.py
```

Expected: 3건 에러

**Step 2: 코드 수정**

`chroma_retriever.py`의 159-168행을 수정합니다. `self._hybrid_enabled`는 이미 `bm25_index is not None and hybrid_merger is not None`를 체크하지만, mypy는 이 상관관계를 추론하지 못합니다. 명시적 None 체크를 추가합니다:

**수정 전 (159-168행):**
```python
            # Phase 1: 하이브리드 검색 (BM25 엔진이 주입된 경우)
            if self._hybrid_enabled:
                bm25_results = self._bm25_index.search(query, top_k=top_k)
                results = self._hybrid_merger.merge(
                    dense_results=dense_results,
                    bm25_results=bm25_results,
                    top_k=top_k,
                )
            else:
                results = dense_results
```

**수정 후:**
```python
            # Phase 1: 하이브리드 검색 (BM25 엔진이 주입된 경우)
            if self._hybrid_enabled and self._bm25_index is not None and self._hybrid_merger is not None:
                bm25_results = self._bm25_index.search(query, top_k=top_k)
                merged: list[SearchResult] = self._hybrid_merger.merge(
                    dense_results=dense_results,
                    bm25_results=bm25_results,
                    top_k=top_k,
                )
                results = merged
            else:
                results = dense_results
```

핵심 변경:
1. `self._bm25_index is not None and self._hybrid_merger is not None` 명시적 narrowing 추가
2. `merged` 변수에 `list[SearchResult]` 타입 어노테이션으로 반환 타입 명확화

**Step 3: mypy 재검증**

```bash
uv run mypy app/modules/core/retrieval/retrievers/chroma_retriever.py
```

Expected: Success (0 에러)

**Step 4: 기존 테스트 실행**

```bash
uv run pytest tests/unit/retrieval/ -v --timeout=10
```

Expected: 모든 테스트 PASS

**Step 5: 커밋**

```bash
git add app/modules/core/retrieval/retrievers/chroma_retriever.py
git commit -m "수정: chroma_retriever.py mypy 타입 에러 3건 해결

Optional 타입 명시적 None narrowing 추가 및
반환 타입 어노테이션으로 Any 반환 에러 해소."
```

---

## Task 4: CHANGELOG.md 생성

**Files:**
- Create: `CHANGELOG.md`

**Step 1: git log로 릴리스 이력 파악**

```bash
git log --oneline --no-walk --tags 2>/dev/null || git log --oneline -20
```

**Step 2: Keep a Changelog 형식으로 CHANGELOG.md 작성**

```markdown
# Changelog

이 프로젝트의 주요 변경 사항을 기록합니다.
형식: [Keep a Changelog](https://keepachangelog.com/ko/1.1.0/)

## [1.0.7] - 2026-01-30

### 변경됨
- Deprecated 전역 헬퍼 함수 완전 제거/리팩토링 (`get_cost_tracker`, `get_mongodb_client`, `get_prompt_manager`, `get_circuit_breaker`)
- `uv.lock` 패키지명 동기화 (`rag-chatbot` → `onerag`)

### 문서
- ARCHITECTURE.md Mermaid 다이어그램 교체
- 아키텍처 다이어그램 및 튜토리얼 추가
- README.md / README_EN.md 개선

## [1.0.6] - 2026-01-27

### 추가됨
- Docker-Free 로컬 퀵스타트 (`quickstart_local/`)
- 테스트 스위트 24개 → 79개 의미있는 테스트로 교체

## [1.0.5] - 2026-01-20

### 추가됨
- Multi Vector DB 지원 (Chroma, Pinecone, Qdrant, pgvector, MongoDB Atlas)
- `VectorStoreFactory`, `RetrieverFactory` 패턴

## [1.0.4] - 2026-01-15

### 추가됨
- Observability: 실시간 메트릭 (`/api/admin/realtime-metrics`)
- 캐시 모니터링, 비용 추적

## [1.0.3] - 2026-01-10

### 추가됨
- Multi-LLM Factory (Google Gemini, OpenAI GPT, Anthropic Claude, OpenRouter)
- 자동 Fallback 체인

## [1.0.2] - 2026-01-05

### 추가됨
- 양언어(한/영) 에러 시스템 v2.0
- ErrorCode 기반 구조화된 에러 처리

## [1.0.1] - 2026-01-01

### 추가됨
- 환경별 설정 관리 (development, test, production YAML 분리)
- Pydantic 기반 설정 검증
- ConfigLoader 다층 환경 감지

## [1.0.0] - 2025-12-20

### 추가됨
- 초기 릴리스
- 모듈형 한국어 RAG 시스템
- Weaviate 하이브리드 검색 (Dense + BM25)
- DI 컨테이너 (80+ Provider)
- PII 보호 및 Admin 인증
- 1,500+ 테스트
```

> **참고**: 위 날짜와 내용은 git log 기반으로 조정합니다. 정확한 날짜는 커밋 히스토리에서 추출하세요.

**Step 3: 커밋**

```bash
git add CHANGELOG.md
git commit -m "문서: CHANGELOG.md 생성 (Keep a Changelog 형식)"
```

---

## Task 5: base.yaml default_provider 통일

**Files:**
- Modify: `app/config/features/generation.yaml:13`

**배경:**

`generation.yaml`(base 설정)에서 `default_provider: "openrouter"`이지만, 모든 환경별 YAML(development, test, production)에서 `"google"`로 오버라이드합니다. base 기본값을 `"google"`로 변경하여 혼란을 제거합니다.

**Step 1: 현재 값 확인**

```bash
grep "default_provider" app/config/features/generation.yaml
```

Expected: `default_provider: "openrouter"`

**Step 2: 수정**

`app/config/features/generation.yaml`의 13행:

**수정 전:**
```yaml
  default_provider: "openrouter"
```

**수정 후:**
```yaml
  default_provider: "google"
```

동시에 해당 줄 위의 주석도 업데이트:

**수정 전 (8-13행):**
```yaml
  # ========================================
  # OpenRouter 통합 모드 (단일 게이트웨이)
  # ========================================
  # 모든 LLM 호출을 OpenRouter로 통합하여 관리 단순화
  # 장점: 단일 API 키, 통합 청구, 300+ 모델 접근

  # 기본 프로바이더 (항상 openrouter)
  default_provider: "openrouter"
```

**수정 후:**
```yaml
  # ========================================
  # 기본 프로바이더 설정
  # ========================================
  # Google Gemini를 기본값으로 사용 (Quickstart 호환, 무료 API 키)
  # OpenRouter 사용 시: GENERATION_PROVIDER=openrouter 환경변수 설정

  # 기본 프로바이더 (모든 환경에서 google 사용)
  default_provider: "google"
```

**Step 3: 기존 테스트 실행**

```bash
uv run pytest tests/ -x -q --timeout=30 2>&1 | tail -5
```

Expected: 모든 테스트 PASS (환경별 YAML이 이미 google로 오버라이드하므로 영향 없음)

**Step 4: 커밋**

```bash
git add app/config/features/generation.yaml
git commit -m "설정: generation.yaml default_provider를 google로 통일

모든 환경별 YAML(dev/test/prod)이 이미 google을
사용하므로 base 설정도 일치시켜 혼란 제거."
```

---

## 최종 검증

모든 Task 완료 후:

```bash
# 1. mypy 전체 확인
uv run mypy app/modules/core/retrieval/bm25_engine/hybrid_merger.py app/modules/core/retrieval/retrievers/chroma_retriever.py

# 2. ruff 린트
uv run ruff check app/modules/core/retrieval/bm25_engine/hybrid_merger.py app/modules/core/retrieval/retrievers/chroma_retriever.py

# 3. 전체 테스트
uv run pytest tests/ -x -q --timeout=30 2>&1 | tail -10

# 4. git status 정리 확인
git status
```

Expected: mypy 0 에러, ruff 통과, 테스트 전량 통과
