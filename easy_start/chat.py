#!/usr/bin/env python3
"""
Rich CLI 대화형 RAG 챗봇

Docker 없이 로컬에서 RAG 하이브리드 검색 + LLM 답변 생성을 체험하는 CLI 인터페이스입니다.
FastAPI 서버 없이 직접 검색 파이프라인과 LLM을 호출합니다.

사용법:
    uv run python easy_start/chat.py

의존성:
    - rich: CLI UI
    - chromadb: 벡터 검색
    - sentence-transformers: 임베딩
    - kiwipiepy, rank-bm25: BM25 검색 (선택적)
    - openai: LLM 호출 (선택적, Gemini/OpenRouter OpenAI 호환 API)
"""

import asyncio
import os
import sys
from pathlib import Path
from typing import Any

# 프로젝트 루트를 Python 경로에 추가
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from easy_start.load_data import (  # noqa: E402
    BM25_INDEX_PATH,
    CHROMA_PERSIST_DIR,
    COLLECTION_NAME,
)

# 상수
TOP_K = 5

# LLM Provider 설정
GEMINI_MODEL = "gemini-3-flash-preview"
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
OPENROUTER_MODEL = "google/gemini-3-flash-preview"
OPENROUTER_API_URL = "https://openrouter.ai/api/v1"

# RAG 시스템 프롬프트
SYSTEM_PROMPT = """당신은 OneRAG 시스템의 AI 어시스턴트입니다.
사용자의 질문에 대해 제공된 참고 문서를 기반으로 정확하고 친절하게 답변하세요.

규칙:
- 참고 문서에 있는 정보만 사용하여 답변하세요.
- 문서에 없는 내용은 "제공된 문서에서 해당 정보를 찾을 수 없습니다"라고 답하세요.
- 답변은 자연스러운 한국어로 작성하세요.
- 핵심 내용을 먼저 말하고, 필요하면 부연 설명을 추가하세요."""


def build_user_prompt(query: str, documents: list[dict[str, Any]]) -> str:
    """
    검색 결과를 포함한 사용자 프롬프트 구성

    Args:
        query: 사용자 질문
        documents: 검색된 문서 리스트

    Returns:
        LLM에 전달할 사용자 프롬프트
    """
    context_parts = []
    for i, doc in enumerate(documents, 1):
        content = doc.get("content", "")
        context_parts.append(f"[문서 {i}]\n{content}")

    context = "\n\n".join(context_parts)

    return f"""<참고문서>
{context}
</참고문서>

<질문>
{query}
</질문>

위 참고문서를 바탕으로 질문에 답변해주세요."""


def _resolve_llm_providers() -> list[tuple[str, str, str, str]]:
    """
    사용 가능한 LLM provider 목록 반환 (Gemini 우선)

    Returns:
        (base_url, api_key, model, provider_name) 튜플 리스트
    """
    providers: list[tuple[str, str, str, str]] = []

    google_key = os.getenv("GOOGLE_API_KEY")
    if google_key:
        providers.append((GEMINI_API_URL, google_key, GEMINI_MODEL, "Gemini"))

    openrouter_key = os.getenv("OPENROUTER_API_KEY")
    if openrouter_key:
        providers.append((OPENROUTER_API_URL, openrouter_key, OPENROUTER_MODEL, "OpenRouter"))

    return providers


async def _call_llm(
    base_url: str, api_key: str, model: str, user_prompt: str,
) -> str:
    """
    단일 LLM provider에 API 호출 수행

    Args:
        base_url: OpenAI 호환 API 엔드포인트
        api_key: API 키
        model: 모델 이름
        user_prompt: 사용자 프롬프트

    Returns:
        LLM 응답 문자열

    Raises:
        Exception: API 호출 실패 시
    """
    from openai import AsyncOpenAI

    client = AsyncOpenAI(
        base_url=base_url,
        api_key=api_key,
        timeout=60,
    )

    try:
        response = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=2048,
            temperature=0.3,
        )

        return response.choices[0].message.content or ""
    finally:
        await client.close()


async def generate_answer(query: str, documents: list[dict[str, Any]]) -> str | None:
    """
    LLM API로 RAG 답변 생성 (비동기, Gemini → OpenRouter 자동 fallback)

    두 API 키가 모두 설정된 경우, 첫 번째 provider 실패 시 두 번째로 자동 전환합니다.

    Args:
        query: 사용자 질문
        documents: 검색된 문서 리스트

    Returns:
        LLM 답변 문자열. API 키 미설정 또는 openai 미설치 시 None 반환.
        에러 발생 시 사용자 친화적 에러 메시지 문자열 반환.
    """
    providers = _resolve_llm_providers()
    if not providers:
        return None

    try:
        from openai import AsyncOpenAI  # noqa: F401
    except ImportError:
        return None

    user_prompt = build_user_prompt(query, documents)
    last_error: Exception | None = None
    last_provider_name = providers[0][3]

    for base_url, api_key, model, provider_name in providers:
        last_provider_name = provider_name
        try:
            return await _call_llm(base_url, api_key, model, user_prompt)
        except Exception as e:
            last_error = e
            # 다음 provider로 fallback 시도
            continue

    # 모든 provider 실패
    return _format_llm_error(last_error or Exception("알 수 없는 오류"), last_provider_name)


def _format_llm_error(error: Exception, provider_name: str = "Gemini") -> str:
    """
    LLM API 에러를 사용자 친화적 메시지로 변환

    Args:
        error: 발생한 예외
        provider_name: LLM provider 이름 ("Gemini" 또는 "OpenRouter")

    Returns:
        사용자에게 보여줄 에러 메시지
    """
    error_str = str(error)

    # Provider별 안내 링크
    if provider_name == "OpenRouter":
        key_env = "OPENROUTER_API_KEY"
        key_url = "https://openrouter.ai/keys"
    else:
        key_env = "GOOGLE_API_KEY"
        key_url = "https://aistudio.google.com/apikey"

    # API 할당량 초과 (429)
    if "429" in error_str or "quota" in error_str.lower():
        return (
            "API 호출 한도를 초과했습니다.\n"
            f"해결: 잠시 후 다시 시도하거나, {key_url} 에서 새 키를 발급받으세요."
        )

    # 인증 실패 (401/403)
    if "401" in error_str or "403" in error_str or "auth" in error_str.lower():
        return (
            "API 키 인증에 실패했습니다.\n"
            f"해결: {key_env} 환경변수가 올바른지 확인하세요."
        )

    # 타임아웃
    if "timeout" in error_str.lower() or "timed out" in error_str.lower():
        return "API 응답 시간이 초과되었습니다.\n해결: 잠시 후 다시 시도하세요."

    # 기타 에러
    return f"답변 생성 중 오류가 발생했습니다: {type(error).__name__}"


async def search_documents(
    query: str,
    retriever: Any = None,
    top_k: int = TOP_K,
) -> list[dict[str, Any]]:
    """
    ChromaDB + BM25 하이브리드 검색 수행

    Args:
        query: 검색 쿼리
        retriever: ChromaRetriever 인스턴스
        top_k: 반환할 결과 수

    Returns:
        검색 결과 리스트
    """
    if retriever is None:
        return []

    search_results = await retriever.search(
        query=query,
        top_k=top_k,
    )

    # SearchResult → dict 변환
    results = []
    for sr in search_results:
        results.append({
            "content": getattr(sr, "content", ""),
            "score": getattr(sr, "score", 0.0),
            "source": getattr(sr, "id", ""),
            "metadata": getattr(sr, "metadata", {}),
        })

    return results


def initialize_components() -> tuple[Any, Any | None, Any | None]:
    """
    검색 파이프라인 컴포넌트 초기화

    Returns:
        (retriever, bm25_index, merger) 튜플
    """
    from app.infrastructure.storage.vector.chroma_store import ChromaVectorStore
    from app.modules.core.embedding.local_embedder import LocalEmbedder
    from app.modules.core.retrieval.retrievers.chroma_retriever import ChromaRetriever

    # 1. 임베딩 모델
    embedder = LocalEmbedder(
        model_name="Qwen/Qwen3-Embedding-0.6B",
        output_dimensionality=1024,
        batch_size=32,
        normalize=True,
    )

    # 2. ChromaVectorStore (persistent)
    store = ChromaVectorStore(persist_directory=CHROMA_PERSIST_DIR)

    # 3. BM25 인덱스 + HybridMerger (선택적)
    bm25_index = None
    merger = None
    try:
        if Path(BM25_INDEX_PATH).exists():
            from easy_start.load_data import load_bm25_index
            bm25_index = load_bm25_index(BM25_INDEX_PATH)

            from app.modules.core.retrieval.bm25_engine import HybridMerger
            merger = HybridMerger(alpha=0.6)
    except (ImportError, Exception):
        pass

    # 4. ChromaRetriever (하이브리드 DI 주입)
    retriever = ChromaRetriever(
        embedder=embedder,
        store=store,
        collection_name=COLLECTION_NAME,
        top_k=TOP_K,
        bm25_index=bm25_index,
        hybrid_merger=merger,
    )

    return retriever, bm25_index, merger


def _check_llm_available() -> tuple[bool, str]:
    """
    LLM API 키 설정 여부 및 provider 이름 확인

    Returns:
        (가용 여부, provider 이름) 튜플. 복수 provider 시 "Gemini+OpenRouter" 형태.
    """
    providers = _resolve_llm_providers()
    if providers:
        names = [p[3] for p in providers]
        return True, "+".join(names)
    return False, ""


async def chat_loop() -> None:
    """메인 대화 루프"""
    try:
        from rich.console import Console
        from rich.markdown import Markdown
        from rich.panel import Panel
        from rich.table import Table
        from rich.text import Text
    except ImportError:
        print("rich 패키지가 필요합니다: uv pip install rich")
        sys.exit(1)

    console = Console()

    # ── 헤더 출력 ──
    header = Text()
    header.append("OneRAG 로컬 챗봇\n", style="bold white")
    header.append("하이브리드 검색 (벡터 + 한글 키워드) + LLM 답변 생성\n\n", style="dim")
    header.append("  quit", style="bold yellow")
    header.append("  종료  ", style="dim")
    header.append("help", style="bold yellow")
    header.append("  도움말  ", style="dim")
    header.append("search", style="bold yellow")
    header.append("  검색만 (답변 생성 없이)", style="dim")
    console.print(Panel(header, title="[bold cyan]OneRAG[/bold cyan]", border_style="cyan"))
    console.print()

    # ── 컴포넌트 초기화 ──
    with console.status("[bold cyan]검색 엔진 초기화 중...", spinner="dots"):
        retriever, bm25_index, merger = initialize_components()
        llm_available, llm_provider_name = _check_llm_available()

    # 상태 테이블 출력
    status_table = Table(show_header=False, box=None, padding=(0, 2))
    status_table.add_column("항목", style="dim")
    status_table.add_column("상태")

    hybrid_status = "[green]활성[/green]" if bm25_index else "[yellow]비활성 (Dense만)[/yellow]"
    llm_status = (
        f"[green]활성 ({llm_provider_name})[/green]"
        if llm_available
        else "[yellow]비활성[/yellow]"
    )

    status_table.add_row("하이브리드 검색", hybrid_status)
    status_table.add_row("LLM 답변 생성", llm_status)

    console.print(Panel(status_table, title="[bold]초기화 완료[/bold]", border_style="green"))

    if not llm_available:
        console.print()
        console.print(
            Panel(
                "[bold yellow]LLM 답변 생성을 사용하려면 API 키를 하나 설정하세요.[/bold yellow]\n\n"
                "[bold]Option 1: Google Gemini (추천 - 무료)[/bold]\n"
                "  1. https://aistudio.google.com/apikey 에서 API 키 발급\n"
                "  2. [bold]export GOOGLE_API_KEY=\"발급받은키\"[/bold]\n\n"
                "[bold]Option 2: OpenRouter (다양한 모델)[/bold]\n"
                "  1. https://openrouter.ai/keys 에서 API 키 발급\n"
                "  2. [bold]export OPENROUTER_API_KEY=\"발급받은키\"[/bold]\n\n"
                "[dim]API 키 없이도 검색 기능은 정상 작동합니다.[/dim]",
                title="[yellow]API 키 안내[/yellow]",
                border_style="yellow",
            )
        )

    console.print()

    # ── 대화 루프 ──
    while True:
        try:
            console.print("[bold cyan]─[/bold cyan]" * 50)
            query = console.input("[bold yellow]질문 > [/bold yellow]").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]종료합니다.[/dim]")
            break

        if not query:
            continue
        if query.lower() in ("quit", "exit", "q"):
            console.print("[dim]종료합니다.[/dim]")
            break

        if query.lower() == "help":
            help_table = Table(
                title="사용 가능한 명령어",
                show_header=True,
                header_style="bold",
                border_style="dim",
            )
            help_table.add_column("명령어", style="bold yellow", width=12)
            help_table.add_column("설명")
            help_table.add_row("quit / q", "챗봇 종료")
            help_table.add_row("help", "이 도움말 표시")
            help_table.add_row("search <질문>", "검색만 수행 (LLM 답변 없이)")

            console.print()
            console.print(help_table)
            console.print()
            console.print("[bold]예시 질문:[/bold]")
            console.print("  [dim]-[/dim] RAG 시스템이란?")
            console.print("  [dim]-[/dim] 설치 방법 알려줘")
            console.print("  [dim]-[/dim] 하이브리드 검색이 뭐야?")
            console.print("  [dim]-[/dim] 환경변수 설정 어떻게 해?")
            console.print()
            continue

        # "search" 접두사: 검색만 수행
        search_only = False
        if query.lower().startswith("search "):
            search_only = True
            query = query[7:].strip()
            if not query:
                console.print("[dim]검색어를 입력하세요. 예: search RAG란?[/dim]")
                continue

        # ── 검색 실행 ──
        console.print()
        with console.status("[bold cyan]검색 중...", spinner="dots"):
            results = await search_documents(
                query=query,
                retriever=retriever,
            )

        if not results:
            console.print(
                Panel("[dim]검색 결과가 없습니다.[/dim]", border_style="dim")
            )
            console.print()
            continue

        # ── 검색 결과 테이블 ──
        result_table = Table(
            title=f"검색 결과 ({len(results)}건)",
            show_header=True,
            header_style="bold",
            border_style="blue",
            title_style="bold blue",
            expand=True,
        )
        result_table.add_column("#", style="dim", width=3, justify="right")
        result_table.add_column("내용", ratio=5)
        result_table.add_column("정규화 점수", style="cyan", width=10, justify="right")

        # 점수 정규화: 최고 점수를 1.0 기준으로 스케일링
        display_results = results[:5]
        max_score = max((r.get("score", 0.0) for r in display_results), default=0.0)

        for i, r in enumerate(display_results, 1):
            raw_score = r.get("score", 0.0)
            normalized = raw_score / max_score if max_score > 0 else 0.0
            content = r.get("content", "")
            # 첫 줄만 표시 (제목 역할)
            first_line = content.split("\n")[0][:80]
            result_table.add_row(str(i), first_line, f"{normalized:.2f}")

        console.print(result_table)

        # ── LLM 답변 생성 ──
        if not search_only and llm_available:
            console.print()
            with console.status("[bold cyan]답변 생성 중...", spinner="dots"):
                answer = await generate_answer(query, results)

            if answer:
                # Markdown 렌더링으로 깔끔하게 출력
                console.print(
                    Panel(
                        Markdown(answer),
                        title="[bold green]AI 답변[/bold green]",
                        border_style="green",
                        padding=(1, 2),
                    )
                )
            else:
                console.print("[dim]답변 생성에 실패했습니다.[/dim]")
        elif not search_only and not llm_available:
            console.print()
            console.print(
                "[dim]GOOGLE_API_KEY 또는 OPENROUTER_API_KEY를 설정하면 AI 답변도 함께 제공됩니다.[/dim]"
            )

        console.print()


def main() -> None:
    """메인 진입점"""
    asyncio.run(chat_loop())


if __name__ == "__main__":
    main()
