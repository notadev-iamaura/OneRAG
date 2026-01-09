# E2E 테스트 활성화 구현 계획

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Skip된 3개 E2E 테스트를 활성화하여 Self-RAG 품질 게이트 전체 플로우 검증

**Architecture:** Chat API → RAGPipeline(debug_trace 생성) → Session(debug_trace 저장) → Admin API(debug_trace 조회)

**Tech Stack:** FastAPI, Pydantic, pytest

---

## 심층 분석: E2E 테스트가 필요한 원론적 이유

### 1. E2E 테스트의 본질적 목적

**단위 테스트 vs 통합 테스트 vs E2E 테스트:**

| 레벨 | 검증 대상 | 한계 |
|------|----------|------|
| Unit | 개별 함수/클래스 | 컴포넌트 간 연결 검증 불가 |
| Integration | 2-3개 컴포넌트 조합 | 전체 사용자 시나리오 검증 불가 |
| **E2E** | **실제 사용자 플로우 전체** | 느림, 유지보수 비용 높음 |

**RAG 시스템에서 E2E가 특히 중요한 이유:**
- RAG 파이프라인은 **6+개 컴포넌트**가 순차적으로 동작 (Query→Retrieval→Rerank→Generation→Self-RAG→Response)
- 각 컴포넌트가 단위 테스트를 통과해도 **전체 흐름에서 데이터 손실** 발생 가능
- Self-RAG 품질 게이트는 **여러 단계의 메타데이터 전달**이 핵심

### 2. 현재 E2E 테스트가 검증하려는 것

```
┌─────────────────────────────────────────────────────────────────────┐
│  E2E 테스트 검증 범위                                                │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  [사용자] ──POST /chat──→ [Chat Router] ──→ [RAGPipeline]           │
│                                   │              │                  │
│                                   │      ┌───────┴───────┐          │
│                                   │      │ enable_debug  │ ← 검증점1│
│                                   │      │ _trace=True   │          │
│                                   │      └───────┬───────┘          │
│                                   │              │                  │
│                                   │      ┌───────┴───────┐          │
│                                   │      │ debug_trace   │ ← 검증점2│
│                                   │      │ 생성 & 반환   │          │
│                                   │      └───────┬───────┘          │
│                                   │              │                  │
│                                   ▼              │                  │
│                           [add_conversation]◄────┘                  │
│                                   │                                 │
│                           ┌───────┴───────┐                         │
│                           │ messages_     │ ← 검증점3               │
│                           │ metadata에    │                         │
│                           │ debug_trace   │                         │
│                           │ 저장          │                         │
│                           └───────┬───────┘                         │
│                                   │                                 │
│  [관리자] ─GET /admin/debug──→ [Admin Router]                       │
│                                   │                                 │
│                           ┌───────┴───────┐                         │
│                           │ debug_trace   │ ← 검증점4               │
│                           │ 조회 & 반환   │                         │
│                           └───────────────┘                         │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

**E2E로만 검증 가능한 것들:**
1. **데이터 무결성**: debug_trace가 생성→저장→조회 과정에서 손실되지 않는가?
2. **API 계약 준수**: Chat API 응답의 `metadata.quality`와 Admin API의 `self_rag_evaluation`이 일치하는가?
3. **실제 시나리오**: 고품질/저품질 답변 시 시스템이 예상대로 동작하는가?

### 3. 현재 구현 상태 분석

| Task | 상태 | 위치 | 비고 |
|------|------|------|------|
| Task 1: Self-RAG 품질 게이트 | ✅ 완료 | `rag_pipeline.py:1418-1461` | SelfRAGEvaluation 생성 |
| Task 2: API 응답 품질 메타데이터 | ✅ 완료 | `chat_router.py:196-228` | `metadata.quality` 반환 |
| Task 3: DebugTrace 스키마 | ✅ 완료 | `schemas/debug.py` | 4개 필드 정의 |
| Task 4: RAGPipeline debug_trace | ✅ 완료 | `rag_pipeline.py:609-703` | `enable_debug_trace` 옵션 |
| Task 5: Admin 디버깅 API | ✅ 완료 | `admin_router.py:180-226` | GET 엔드포인트 |
| **연결 코드** | ❌ 누락 | `chat_router.py:167-183` | **핵심 문제** |

### 4. 누락된 연결 코드 (3줄)

**문제 1: `enable_debug_trace` 옵션 미전달**
```python
# chat_router.py:167-168 (현재)
rag_result = await chat_service.execute_rag_pipeline(
    chat_request.message, session_id, options  # ← enable_debug_trace 없음
)
```

**문제 2: `debug_trace` 세션 저장 누락**
```python
# chat_router.py:171-183 (현재)
await chat_service.add_conversation_to_session(
    session_id,
    chat_request.message,
    rag_result["answer"],
    {
        ...
        # ❌ "debug_trace": rag_result.get("debug_trace") 누락!
    },
)
```

---

## 구현 계획

### Task 1: ChatRequest에 enable_debug_trace 필드 추가

**Files:**
- Modify: `app/api/schemas/chat_schemas.py:60-75`
- Test: `tests/unit/api/test_chat_schemas.py` (기존 테스트 확인)

**Step 1: 스키마 수정**

```python
# app/api/schemas/chat_schemas.py의 ChatRequest 클래스에 추가
class ChatRequest(BaseModel):
    """채팅 요청 스키마"""
    message: str = Field(..., min_length=1, max_length=10000)
    session_id: str | None = Field(None, description="세션 ID")
    options: dict | None = Field(None, description="추가 옵션")
    use_agent: bool = Field(False, description="Agent 모드 사용 여부")
    enable_debug_trace: bool = Field(False, description="디버깅 추적 활성화")  # ⭐ 추가
```

**Step 2: 검증**

Run: `uv run pytest tests/unit/api/ -k "chat" -v --tb=short`
Expected: 기존 테스트 PASS

**Step 3: 커밋**

```bash
git add app/api/schemas/chat_schemas.py
git commit -m "기능: ChatRequest에 enable_debug_trace 필드 추가"
```

---

### Task 2: chat_router에서 enable_debug_trace 전달

**Files:**
- Modify: `app/api/routers/chat_router.py:163-168`

**Step 1: options에 enable_debug_trace 추가**

```python
# chat_router.py 수정 (라인 163-168)
options = chat_request.options or {}
if chat_request.use_agent:
    options["use_agent"] = True
if chat_request.enable_debug_trace:  # ⭐ 추가
    options["enable_debug_trace"] = True  # ⭐ 추가
rag_result = await chat_service.execute_rag_pipeline(
    chat_request.message, session_id, options
)
```

**Step 2: 검증**

Run: `uv run pytest tests/unit/api/test_chat_router.py -v --tb=short`
Expected: PASS

**Step 3: 커밋**

```bash
git add app/api/routers/chat_router.py
git commit -m "기능: chat_router에서 enable_debug_trace 옵션 전달"
```

---

### Task 3: debug_trace를 세션에 저장

**Files:**
- Modify: `app/api/routers/chat_router.py:171-184`

**Step 1: metadata에 debug_trace 추가**

```python
# chat_router.py 수정 (라인 171-184)
await chat_service.add_conversation_to_session(
    session_id,
    chat_request.message,
    rag_result["answer"],
    {
        "tokens_used": rag_result["tokens_used"],
        "processing_time": time.time() - start_time,
        "sources": rag_result["sources"],
        "topic": rag_result["topic"],
        "model_info": rag_result.get("model_info"),
        "message_id": message_id,
        "can_evaluate": True,
        "debug_trace": rag_result.get("debug_trace"),  # ⭐ 추가
    },
)
```

**Step 2: 검증**

Run: `uv run pytest tests/unit/api/test_chat_router.py -v --tb=short`
Expected: PASS

**Step 3: 커밋**

```bash
git add app/api/routers/chat_router.py
git commit -m "기능: debug_trace를 세션 메타데이터에 저장"
```

---

### Task 4: E2E 테스트 Skip 제거 및 활성화

**Files:**
- Modify: `tests/integration/api/test_e2e_debug_flow.py:40,132,173`

**Step 1: Skip 데코레이터 제거**

```python
# 3개 테스트에서 @pytest.mark.skip 라인 제거
# 라인 40, 132, 173의 @pytest.mark.skip(...) 삭제
```

**Step 2: API 경로 수정 (필요시)**

```python
# /admin/debug → /api/admin/debug 확인
# 라인 99-101, 201-203의 경로가 올바른지 확인
```

**Step 3: E2E 테스트 실행**

Run: `ENVIRONMENT=test uv run pytest tests/integration/api/test_e2e_debug_flow.py -v --tb=short`
Expected: 3 passed (또는 일부 skip - 실제 LLM 호출 필요 시)

**Step 4: 커밋**

```bash
git add tests/integration/api/test_e2e_debug_flow.py
git commit -m "테스트: E2E 디버깅 플로우 테스트 활성화"
```

---

### Task 5: 전체 검증 및 문서 업데이트

**Step 1: 전체 테스트 실행**

Run: `ENVIRONMENT=test uv run pytest tests/ -q --tb=no`
Expected: 1259+ passed

**Step 2: CLAUDE.md 업데이트**

- E2E 테스트 활성화 반영
- 테스트 수 업데이트

**Step 3: 최종 커밋**

```bash
git add CLAUDE.md
git commit -m "문서: E2E 테스트 활성화 반영"
```

---

## 예상 결과

| 항목 | 변경 전 | 변경 후 |
|------|---------|---------|
| Skip 테스트 | 3개 | 0개 |
| E2E 테스트 | 비활성 | 활성 |
| 코드 변경량 | - | ~10줄 |
| 예상 소요시간 | - | 15-20분 |

## 실행 옵션

**Plan complete and saved to `docs/plans/2026-01-09-e2e-test-activation.md`. Two execution options:**

**1. Subagent-Driven (this session)** - I dispatch fresh subagent per task, review between tasks, fast iteration

**2. Parallel Session (separate)** - Open new session with executing-plans, batch execution with checkpoints

**Which approach?**
