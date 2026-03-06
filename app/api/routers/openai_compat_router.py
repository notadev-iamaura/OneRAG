# app/api/routers/openai_compat_router.py
"""
OpenAI 호환 API 라우터

POST /v1/chat/completions - OpenAI SDK 형식의 채팅 완료 (RAG 파이프라인 포함)
GET  /v1/models            - 사용 가능한 모델 목록

외부 도구(LangChain, Cursor, Open WebUI 등)가 OpenAI SDK로
OneRAG에 바로 연결할 수 있도록 표준 형식을 제공합니다.

인증: 없음 (Ollama 방식 — 로컬 서비스 전제)
"""

from __future__ import annotations

import json
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

    # 4. 문서 검색 (RAG)
    documents: list[dict[str, Any]] = []
    retriever = _modules.get("retrieval")
    if retriever:
        try:
            search_results = await retriever.search(query=user_message, top_k=_MAX_SEARCH_RESULTS)
            documents = [
                {"content": getattr(r, "content", ""), "score": getattr(r, "score", 0.0)}
                for r in search_results
            ]
        except Exception as e:
            logger.warning(f"검색 실패, LLM 단독 답변으로 전환: {e}")

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
        # 1. 문서 검색
        documents: list[dict[str, Any]] = []
        retriever = _modules.get("retrieval")
        if retriever:
            try:
                search_results = await retriever.search(query=user_message, top_k=_MAX_SEARCH_RESULTS)
                documents = [
                    {"content": getattr(r, "content", "")}
                    for r in search_results
                ]
            except Exception as e:
                logger.warning(f"검색 실패: {e}")

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
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
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
