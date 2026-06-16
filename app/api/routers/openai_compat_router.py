# app/api/routers/openai_compat_router.py
"""
OpenAI 호환 API 라우터

POST /v1/chat/completions - OpenAI SDK 형식의 채팅 완료 (RAG 파이프라인 포함)
GET  /v1/models            - 사용 가능한 모델 목록

외부 도구(LangChain, Cursor, Open WebUI 등)가 OpenAI SDK로
OneRAG에 바로 연결할 수 있도록 표준 형식을 제공합니다.

인증: 전역 API Key 미들웨어 적용 (/v1/*)
"""

from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.api.schemas.openai_compat import (
    OpenAICompletionRequest,
    OpenAICompletionResponse,
    OpenAIModelInfo,
    OpenAIModelList,
    OpenAIStreamChunk,
)
from app.api.services.openai_model_resolver import (
    list_available_models,
    parse_model,
    resolve_model_config,
)
from app.lib.errors.codes import ErrorCode
from app.lib.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/v1", tags=["OpenAI Compatible"])

# DI: main.py에서 주입
_modules: dict[str, Any] = {}

# 검색 결과 최대 개수 (openai_compat.yaml에서 설정 가능)
_MAX_SEARCH_RESULTS = 5

# =============================================================================
# RAG 프롬프트 래퍼 (기본값 + 외부화 오버라이드 경로)
# =============================================================================
# /v1/chat/completions(OpenAI 호환 API)는 글로벌 SDK 통합의 핵심 진입점이라,
# 영어권/타도메인 사용자가 RAG 래퍼 문구를 코드 포크 없이 바꿀 수 있어야 한다.
# 같은 기능의 demo_pipeline.py는 이미 env로 외부화돼 있어 비대칭을 해소한다.
#
# 우선순위(미설정 시 한국어 기본값과 byte-identical → 회귀 0):
#   1) config: _modules["config"].openai_compat.rag_prompt_template (주입 시)
#   2) env:    OPENAI_COMPAT_RAG_PROMPT_TEMPLATE
#   3) 코드 내장 기본값(DEFAULT_RAG_PROMPT_TEMPLATE)
#
# 템플릿 자리표시자(필수):
#   {context} - 검색된 참고문서 본문(아래 [문서 N] 포맷으로 조립됨)
#   {query}   - 현재 사용자 질문
DEFAULT_RAG_PROMPT_TEMPLATE = (
    "다음 참고문서를 기반으로 질문에 답변하세요.\n\n"
    "## 참고문서\n{context}\n\n"
    "## 질문\n{query}"
)

# 개별 참고문서 항목 포맷(기본값). {index}/{content} 자리표시자 사용.
# 외부화하지 않아도 래퍼만 바꾸면 대부분의 다국어/도메인 요구를 만족하지만,
# 항목 라벨('[문서 N]')까지 영어화하려는 경우를 위해 함께 외부화한다.
DEFAULT_RAG_DOC_ITEM_TEMPLATE = "[문서 {index}]\n{content}"

# 환경 변수 키(코드가 실제로 읽는 키 — 데드키 아님)
ENV_RAG_PROMPT_TEMPLATE = "OPENAI_COMPAT_RAG_PROMPT_TEMPLATE"
ENV_RAG_DOC_ITEM_TEMPLATE = "OPENAI_COMPAT_RAG_DOC_ITEM_TEMPLATE"


def set_modules(modules: dict[str, Any]) -> None:
    """모듈 의존성 주입 (main.py에서 호출)"""
    global _modules
    _modules = modules


def _resolve_rag_template(config_key: str, env_name: str, default: str) -> str:
    """RAG 프롬프트 래퍼 템플릿을 config → env → 기본값 순으로 해석한다.

    미설정/공백이면 다음 우선순위로 폴백하여, 아무것도 주입하지 않으면
    코드 내장 한국어 기본값과 byte-identical을 보장한다(회귀 0).

    Args:
        config_key: openai_compat 설정 섹션 내 키(예: "rag_prompt_template").
        env_name: 환경 변수 이름(예: "OPENAI_COMPAT_RAG_PROMPT_TEMPLATE").
        default: 코드 내장 기본 템플릿.

    Returns:
        해석된 템플릿 문자열(주입 우선순위: config > env > default).
    """
    # 1) config 주입 경로(_modules["config"]가 주입된 경우에만 동작)
    config = _modules.get("config")
    if config is not None:
        try:
            section = config.get("openai_compat") or {}
            value = section.get(config_key) if isinstance(section, dict) else None
        except Exception:  # noqa: BLE001 - config 접근 실패는 비치명적(env/기본값 폴백)
            value = None
        if isinstance(value, str) and value.strip():
            return value

    # 2) env 오버라이드 경로(demo_pipeline.py와 동일한 패턴)
    env_value = os.getenv(env_name)
    if env_value is not None and env_value.strip():
        return env_value

    # 3) 코드 내장 기본값
    return default


def _build_chat_history_from_messages(messages: list[Any]) -> dict[str, Any] | None:
    """OpenAI messages 배열을 파이프라인 chat_history 형태로 변환한다(GAP #1).

    마지막 user 메시지(=현재 질문)는 제외하고, 그 이전의 user/assistant 교환만 직전
    대화 맥락으로 담는다(system은 제외). stateless /v1 요청에서도 멀티턴 standalone
    rewrite가 직전 맥락을 참조해 오검색/맥락 오염(대명사·생략·축약)을 막도록 한다.

    OneRAG 파이프라인의 소비 배선(get_chat_history/get_context_string)은 동일한
    {"messages":[{"type","content"}...]} 포맷을 기대하므로 그 형태로 변환한다.

    Args:
        messages: OpenAI 요청의 messages(각 .role/.content 보유).

    Returns:
        {"messages": [{"type": "user"|"assistant", "content": str}, ...]} 또는
        직전 교환이 없으면 None.
    """
    last_user_idx: int | None = None
    for i in range(len(messages) - 1, -1, -1):
        if messages[i].role == "user":
            last_user_idx = i
            break
    history: list[dict[str, str]] = []
    for i, msg in enumerate(messages):
        if i == last_user_idx:
            continue
        if msg.role in ("user", "assistant"):
            history.append({"type": msg.role, "content": msg.content})
    return {"messages": history} if history else None


async def _seed_ephemeral_session(
    chat_service: Any, chat_history: dict[str, Any] | None
) -> str | None:
    """직전 대화(chat_history)를 임시 server-side 세션에 적재하고 세션 ID를 반환한다(GAP #1).

    OneRAG 파이프라인은 멀티턴 맥락을 server-side 세션(session 모듈)에서 읽으므로,
    stateless /v1의 messages 히스토리를 ephemeral 세션에 user/assistant 교환으로
    주입한다. 이렇게 하면 rag_pipeline.py를 수정하지 않고도 standalone-rewrite와
    anchor 소비 배선이 직전 맥락을 참조한다.

    graceful degradation: session 모듈 미주입/주입 실패/직전 교환 부재 시 None을
    반환해 기존 stateless 동작(맥락 미적용)으로 폴백한다(회귀 0).

    Args:
        chat_service: rag_pipeline과 modules(session)를 보유한 채팅 서비스.
        chat_history: _build_chat_history_from_messages 결과(없으면 주입 생략).

    Returns:
        적재 완료된 ephemeral 세션 ID, 또는 주입 불가/생략 시 None.
    """
    if not chat_history:
        return None
    session_module = getattr(chat_service, "modules", {}).get("session")
    if session_module is None:
        return None

    messages = chat_history.get("messages", [])
    # user/assistant를 순서대로 교환 쌍으로 묶는다(파이프라인 add_conversation 계약).
    pairs: list[tuple[str, str]] = []
    pending_user: str | None = None
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        if msg.get("type") == "user":
            pending_user = str(msg.get("content", ""))
        elif msg.get("type") == "assistant" and pending_user is not None:
            pairs.append((pending_user, str(msg.get("content", ""))))
            pending_user = None
    if not pairs:
        return None

    sid = f"v1-{uuid.uuid4()}"
    try:
        await session_module.create_session(metadata={"ephemeral": True}, session_id=sid)
        for user_message, assistant_response in pairs:
            await session_module.add_conversation(
                sid,
                user_message=user_message,
                assistant_response=assistant_response,
            )
        return sid
    except Exception as e:  # noqa: BLE001 - 세션 적재 실패는 비치명적(맥락 미적용으로 폴백)
        logger.warning(f"/v1 멀티턴 세션 적재 실패(맥락 미적용으로 폴백): {e}")
        # 부분 적재된 세션 정리(best-effort)
        await _cleanup_ephemeral_session(session_module, sid)
        return None


async def _cleanup_ephemeral_session(session_module: Any, sid: str | None) -> None:
    """ephemeral 세션을 정리한다(best-effort, 실패는 무시)."""
    if session_module is None or sid is None:
        return
    delete_session = getattr(session_module, "delete_session", None)
    if delete_session is None:
        return
    try:
        await delete_session(sid)
    except Exception as e:  # noqa: BLE001 - 정리 실패는 비치명적
        logger.debug(f"/v1 ephemeral 세션 정리 실패(무시): {e}")


def _build_rag_prompt(query: str, documents: list[dict[str, Any]]) -> str:
    """검색 결과를 포함한 RAG 프롬프트 구성.

    래퍼/항목 템플릿은 config → env → 코드 기본값 순으로 해석한다(외부화).
    아무것도 주입하지 않으면 기존 한국어 프롬프트와 byte-identical을 유지한다(회귀 0).
    """
    if not documents:
        return query

    item_template = _resolve_rag_template(
        "rag_doc_item_template",
        ENV_RAG_DOC_ITEM_TEMPLATE,
        DEFAULT_RAG_DOC_ITEM_TEMPLATE,
    )
    doc_texts = []
    for i, doc in enumerate(documents, 1):
        content = doc.get("content", "")
        doc_texts.append(item_template.format(index=i, content=content))

    context = "\n\n".join(doc_texts)
    prompt_template = _resolve_rag_template(
        "rag_prompt_template",
        ENV_RAG_PROMPT_TEMPLATE,
        DEFAULT_RAG_PROMPT_TEMPLATE,
    )
    return prompt_template.format(context=context, query=query)


def _doc_content(doc: Any) -> str:
    """파이프라인 Document/검색 결과에서 본문 텍스트를 견고하게 추출한다.

    표준 파이프라인 출력은 content/page_content를 쓰지만, 일부 경로는 text 또는
    metadata.content/content_preview를 쓰므로 여러 후보를 순서대로 폴백한다.
    """
    for attr in ("content", "page_content", "text"):
        value = getattr(doc, attr, None)
        if value:
            return str(value)
    metadata = getattr(doc, "metadata", None)
    if isinstance(metadata, dict):
        value = metadata.get("content") or metadata.get("content_preview")
        if value:
            return str(value)
    return ""


async def _pipeline_rag_search(
    chat_service: Any, user_message: str, session_id: str | None = None
) -> list[dict[str, Any]]:
    """메인 채팅 경로와 동일한 RAG 검색 체인을 재사용한다.

    /v1 경로가 단순 retriever.search만 호출해 rerank·멀티쿼리가 빠지던 비대칭을
    해소한다. 재사용 체인:
    route_query(라우팅/namespace 판단) → prepare_context(standalone rewrite +
    멀티쿼리 확장) → retrieve_documents(멀티쿼리 RRF) → rerank_documents.

    OneRAG 시그니처에 맞춰 적응한다:
    - route_query(message, session_id, start_time) / prepare_context(message, session_id)는
      chat_history 인자를 받지 않고 멀티턴 맥락을 server-side 세션에서 읽는다.
      따라서 stateless /v1의 messages 히스토리는 _seed_ephemeral_session이 미리
      적재한 ephemeral 세션 ID(session_id)를 넘겨 직전 맥락을 참조하게 한다(GAP #1).
    - session_id가 None이면 비-멀티턴 ephemeral 세션을 새로 만든다(기존 동작).
    - anchor_sources는 prepare_context 결과에 있으면 rerank 후처리에 전달한다.

    생성 모델은 호출측이 /v1 선택 모델로 유지한다(OpenAI 계약 보존).

    Returns:
        [{"content": str}, ...] 형태의 문서 리스트. 결과가 없으면 빈 리스트.

    Raises:
        Exception: prepare_context/retrieve 실패는 호출측이 잡아 단순 검색으로 폴백한다.
    """
    pipeline = chat_service.rag_pipeline
    # 멀티턴 히스토리가 적재된 세션 ID가 있으면 재사용, 없으면 ephemeral 세션 생성.
    session_id = session_id or f"v1-{uuid.uuid4()}"
    start_time = time.time()
    options: dict[str, Any] = {"limit": _MAX_SEARCH_RESULTS}

    # 라우팅으로 data_source(namespace) 재판단(통짜 경로와 일관화). 실패는 비치명적.
    try:
        route_decision = await pipeline.route_query(user_message, session_id, start_time)
        data_source = route_decision.metadata.get("data_source")
        if data_source is not None:
            options["data_source"] = data_source
    except Exception as e:  # noqa: BLE001 - 라우팅 실패는 비치명적
        logger.warning(f"/v1 라우팅 실패(무시): {e}")

    # standalone rewrite + 멀티쿼리 확장(적재된 ephemeral 세션 맥락 참조)
    prepared = await pipeline.prepare_context(user_message, session_id)

    # 멀티턴 anchor soft-boost: 직전 채택 문서를 rerank 후처리에서 약하게 우대한다.
    # 주제 전환이거나 기능 비활성이면 빈 리스트 → no-op(통짜 채팅 경로와 일관).
    if getattr(prepared, "anchor_sources", None):
        options["anchor_sources"] = prepared.anchor_sources

    # 멀티쿼리 RRF 검색
    retrieval_results = await pipeline.retrieve_documents(
        prepared.expanded_queries or [user_message],
        prepared.query_weights or [1.0],
        prepared.session_context,
        options,
    )
    documents = retrieval_results.documents

    # 리랭킹(설정에 따라 no-op일 수 있음). 실패 시 검색 결과 그대로 사용.
    try:
        rerank_results = await pipeline.rerank_documents(
            prepared.expanded_query, documents, options
        )
        documents = rerank_results.documents
    except Exception as e:  # noqa: BLE001 - 리랭킹 실패는 비치명적
        logger.warning(f"/v1 리랭킹 실패, 검색 결과 사용: {e}")

    return [{"content": _doc_content(d)} for d in documents]


async def _rag_search(
    user_message: str, messages: list[Any] | None = None
) -> list[dict[str, Any]]:
    """/v1 경로 공용 검색 진입점.

    chat_service(파이프라인)가 주입돼 있으면 메인 채팅과 동일한 멀티쿼리·rerank
    체인을 재사용하고(#14 비대칭 해소), 미주입/실패 시 retriever.search 단순 검색으로
    폴백한다(graceful degradation, 동작 보존).

    멀티턴(GAP #1): messages에 직전 user/assistant 교환이 있으면 ephemeral 세션에
    적재해 standalone-rewrite/anchor 소비 배선이 직전 맥락을 참조하게 한다. 검색 후
    세션은 best-effort로 정리한다.

    Args:
        user_message: 현재 사용자 질문(마지막 user 메시지).
        messages: 원본 OpenAI messages 배열(멀티턴 히스토리 추출용). None이면 비활성.
    """
    chat_service = _modules.get("chat_service")
    if chat_service is not None:
        ephemeral_sid: str | None = None
        session_module = getattr(chat_service, "modules", {}).get("session")
        try:
            chat_history = (
                _build_chat_history_from_messages(messages) if messages else None
            )
            ephemeral_sid = await _seed_ephemeral_session(chat_service, chat_history)
            return await _pipeline_rag_search(chat_service, user_message, ephemeral_sid)
        except Exception as e:  # noqa: BLE001 - 파이프라인 실패는 단순 검색으로 폴백
            logger.warning(f"RAG 파이프라인 검색 실패, 단순 검색으로 폴백: {e}")
        finally:
            await _cleanup_ephemeral_session(session_module, ephemeral_sid)

    # 폴백: retriever.search 단순 검색
    retriever = _modules.get("retrieval")
    # 방어선: dependency-injector async Singleton 구성에서 retrieval 모듈이
    # 코루틴/Future로 지연 제공될 수 있어 사용 직전에 해소한다
    # ('_asyncio.Future' object has no attribute 'search' 방지,
    # chat_service의 Future-unwrap 가드와 동일 패턴).
    if asyncio.iscoroutine(retriever) or isinstance(retriever, asyncio.Future):
        retriever = await retriever
        # 코루틴은 1회만 await 가능하므로(재-await 시 'cannot reuse already
        # awaited coroutine' RuntimeError), 해소된 인스턴스를 _modules에
        # 되저장해 두 번째 요청부터는 인스턴스를 직접 사용하게 한다.
        _modules["retrieval"] = retriever
    if not retriever:
        return []
    try:
        # RetrievalOrchestrator.search(query, options)와 정합: top_k 키워드 대신 options dict
        search_results = await retriever.search(user_message, {"limit": _MAX_SEARCH_RESULTS})
        return [{"content": getattr(r, "content", "")} for r in search_results]
    except Exception as e:
        logger.warning(f"검색 실패, LLM 단독 답변으로 전환: {e}")
        return []


@router.post("/chat/completions")
async def chat_completions(request: Request, req: OpenAICompletionRequest) -> Any:
    """
    OpenAI 호환 채팅 완료 엔드포인트

    RAG 파이프라인: 문서 검색 -> 컨텍스트 조합 -> LLM 답변 생성
    model 필드로 LLM provider 선택 (예: "gemini", "ollama/qwen2.5:3b")
    """
    # 1. 모델 파싱
    try:
        provider, sub_model = parse_model(req.model)
        model_config = resolve_model_config(provider, sub_model)
    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail={"error": {"message": str(e), "type": "invalid_request_error", "code": ErrorCode.OPENAI_001.value}},
        )

    # 2. 메시지 추출
    user_message = ""
    system_prompt = None
    for msg in req.messages:
        if msg.role == "system":
            system_prompt = msg.content

    # 마지막 user 메시지 사용
    for msg in reversed(req.messages):
        if msg.role == "user":
            user_message = msg.content
            break

    if not user_message:
        raise HTTPException(
            status_code=400,
            detail={"error": {"message": "user 메시지가 필요합니다", "type": "invalid_request_error"}},
        )

    # 3. 스트리밍 분기
    if req.stream:
        return await _stream_completion(req, user_message, system_prompt, model_config)

    # 4. 문서 검색 (RAG) — 메인 채팅과 동일한 멀티쿼리·rerank 체인 재사용(#14 비대칭 해소).
    #    messages를 함께 넘겨 멀티턴 직전 맥락을 검색에 반영한다(GAP #1).
    #    chat_service 미주입/실패 시 retriever.search 단순 검색으로 폴백.
    documents = await _rag_search(user_message, req.messages)

    # 5. RAG 프롬프트 구성
    rag_prompt = _build_rag_prompt(user_message, documents)

    # 6. LLM 답변 생성
    try:
        llm_factory = _modules.get("llm_factory")
        if not llm_factory:
            raise HTTPException(status_code=503, detail={"error": {"message": "LLM 서비스 사용 불가", "code": ErrorCode.OPENAI_002.value}})

        llm_client = llm_factory.get_client(model_config["provider"])

        answer = await llm_client.generate_text(
            prompt=rag_prompt,
            system_prompt=system_prompt,
            model=model_config["model"],
            temperature=req.temperature,
            max_tokens=req.max_tokens,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"LLM 생성 실패: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={"error": {"message": f"답변 생성 실패: {e}", "type": "server_error", "code": ErrorCode.OPENAI_003.value}},
        )

    # 7. OpenAI 형식 응답
    return OpenAICompletionResponse.create(
        model=req.model,
        content=answer,
        prompt_tokens=len(user_message.split()),
        completion_tokens=len(answer.split()),
    ).model_dump()


async def _stream_completion(
    req: OpenAICompletionRequest,
    user_message: str,
    system_prompt: str | None,
    model_config: dict[str, str],
) -> StreamingResponse:
    """스트리밍 응답 생성"""

    async def event_generator():  # type: ignore[return]
        # 1. 문서 검색 — 비스트리밍 경로와 동일한 멀티쿼리·rerank 체인 재사용(#14).
        #    messages를 함께 넘겨 멀티턴 직전 맥락을 검색에 반영한다(GAP #1).
        documents = await _rag_search(user_message, req.messages)

        # 2. RAG 프롬프트
        rag_prompt = _build_rag_prompt(user_message, documents)

        # 3. LLM 스트리밍
        try:
            llm_factory = _modules.get("llm_factory")
            if not llm_factory:
                error = {"error": {"message": "LLM 서비스 사용 불가"}}
                yield f"data: {json.dumps(error, ensure_ascii=False)}\n\n"
                return

            llm_client = llm_factory.get_client(model_config["provider"])
            chunk_index = 0

            async for token in llm_client.stream_text(
                prompt=rag_prompt,
                system_prompt=system_prompt,
                model=model_config["model"],
                temperature=req.temperature,
                max_tokens=req.max_tokens,
            ):
                chunk = OpenAIStreamChunk.create(
                    model=req.model,
                    content=token,
                    index=chunk_index,
                    is_first=(chunk_index == 0),
                )
                yield f"data: {json.dumps(chunk.model_dump(exclude_none=True), ensure_ascii=False)}\n\n"
                chunk_index += 1

            # 종료 청크
            finish = OpenAIStreamChunk.create_finish(model=req.model)
            yield f"data: {json.dumps(finish.model_dump(exclude_none=True), ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"

        except Exception as e:
            logger.error(f"스트리밍 오류: {e}", exc_info=True)
            error = {"error": {"message": str(e)}}
            yield f"data: {json.dumps(error, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Content-Encoding": "identity",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/models")
async def list_models() -> dict[str, Any]:
    """사용 가능한 모델 목록 (OpenAI 형식)"""
    models = list_available_models()
    return OpenAIModelList(
        data=[
            OpenAIModelInfo(id=m["id"], owned_by="onerag")
            for m in models
        ]
    ).model_dump()
