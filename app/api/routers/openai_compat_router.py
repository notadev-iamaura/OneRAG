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


def set_modules(modules: dict[str, Any]) -> None:
    """모듈 의존성 주입 (main.py에서 호출)"""
    global _modules
    _modules = modules


def _build_rag_prompt(query: str, documents: list[dict[str, Any]]) -> str:
    """검색 결과를 포함한 RAG 프롬프트 구성"""
    if not documents:
        return query

    doc_texts = []
    for i, doc in enumerate(documents, 1):
        content = doc.get("content", "")
        doc_texts.append(f"[문서 {i}]\n{content}")

    context = "\n\n".join(doc_texts)
    return (
        f"다음 참고문서를 기반으로 질문에 답변하세요.\n\n"
        f"## 참고문서\n{context}\n\n"
        f"## 질문\n{query}"
    )


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
    chat_service: Any, user_message: str
) -> list[dict[str, Any]]:
    """메인 채팅 경로와 동일한 RAG 검색 체인을 재사용한다.

    /v1 경로가 단순 retriever.search만 호출해 rerank·멀티쿼리가 빠지던 비대칭을
    해소한다. 재사용 체인:
    route_query(라우팅/namespace 판단) → prepare_context(standalone rewrite +
    멀티쿼리 확장) → retrieve_documents(멀티쿼리 RRF) → rerank_documents.

    OneRAG 시그니처에 맞춰 적응한다:
    - route_query(message, session_id, start_time) / prepare_context(message, session_id)는
      options·chat_history 인자를 받지 않으므로 전달하지 않는다(멀티턴 맥락은
      session_module의 server-side 세션 기반이라 stateless /v1에서는 비어 있다).
    - anchor_sources는 OneRAG에 없으므로 미사용.

    생성 모델은 호출측이 /v1 선택 모델로 유지한다(OpenAI 계약 보존).

    Returns:
        [{"content": str}, ...] 형태의 문서 리스트. 결과가 없으면 빈 리스트.

    Raises:
        Exception: prepare_context/retrieve 실패는 호출측이 잡아 단순 검색으로 폴백한다.
    """
    pipeline = chat_service.rag_pipeline
    session_id = f"v1-{uuid.uuid4()}"  # ephemeral 세션(영속하지 않음)
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

    # standalone rewrite + 멀티쿼리 확장
    prepared = await pipeline.prepare_context(user_message, session_id)

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


async def _rag_search(user_message: str) -> list[dict[str, Any]]:
    """/v1 경로 공용 검색 진입점.

    chat_service(파이프라인)가 주입돼 있으면 메인 채팅과 동일한 멀티쿼리·rerank
    체인을 재사용하고(#14 비대칭 해소), 미주입/실패 시 retriever.search 단순 검색으로
    폴백한다(graceful degradation, 동작 보존).
    """
    chat_service = _modules.get("chat_service")
    if chat_service is not None:
        try:
            return await _pipeline_rag_search(chat_service, user_message)
        except Exception as e:  # noqa: BLE001 - 파이프라인 실패는 단순 검색으로 폴백
            logger.warning(f"RAG 파이프라인 검색 실패, 단순 검색으로 폴백: {e}")

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
    #    chat_service 미주입/실패 시 retriever.search 단순 검색으로 폴백.
    documents = await _rag_search(user_message)

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
        documents = await _rag_search(user_message)

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
