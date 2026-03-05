#!/usr/bin/env python3
"""
Rich CLI 대화형 RAG 챗봇

Docker 없이 로컬에서 RAG 하이브리드 검색 + LLM 답변 생성을 체험하는 CLI 인터페이스입니다.
FastAPI 서버 없이 직접 검색 파이프라인과 LLM을 호출합니다.
다국어 지원: EASY_START_LANG 환경변수로 언어 선택 (ko, en, ja, zh)

사용법:
    uv run python easy_start/chat.py
    EASY_START_LANG=en uv run python easy_start/chat.py

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

from easy_start.i18n import load_prompt, t  # noqa: E402
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
OLLAMA_DEFAULT_MODEL = "llama3.2"
OLLAMA_BASE_URL = "http://localhost:11434"


def _get_system_prompt() -> str:
    """
    언어별 시스템 프롬프트 로드

    Returns:
        시스템 프롬프트 문자열
    """
    prompt = load_prompt("system_prompt")
    if prompt:
        return prompt

    # 폴백: 다국어 기본 프롬프트 (프롬프트 파일 누락 시)
    return t("chat.prompt.system_fallback")


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
        doc_label = t("chat.prompt.doc_label", index=i)
        context_parts.append(f"{doc_label}\n{content}")

    context = "\n\n".join(context_parts)
    instruction = t("chat.prompt.instruction")

    return f"""<context>
{context}
</context>

<question>
{query}
</question>

{instruction}"""


def _check_ollama_available(base_url: str = OLLAMA_BASE_URL) -> bool:
    """
    Ollama 서버 가용성 확인

    /api/tags 엔드포인트를 호출하여 Ollama 서버가 실행 중인지 확인합니다.

    Args:
        base_url: Ollama 서버 URL

    Returns:
        서버 가용 여부
    """
    try:
        import urllib.error
        import urllib.request

        req = urllib.request.Request(
            f"{base_url}/api/tags",
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=3) as resp:
            return bool(resp.status == 200)
    except Exception:
        return False


def _resolve_llm_providers() -> list[tuple[str, str, str, str]]:
    """
    사용 가능한 LLM provider 목록 반환 (Gemini > OpenRouter > Ollama 우선순위)

    Ollama는 API 키 없이 로컬 서버 감지로 자동 추가됩니다.

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

    # Ollama 자동감지: API 키 기반 provider가 없을 때 또는 fallback으로 추가
    ollama_url = os.getenv("OLLAMA_BASE_URL", OLLAMA_BASE_URL)
    if _check_ollama_available(ollama_url):
        ollama_model = os.getenv("OLLAMA_MODEL", OLLAMA_DEFAULT_MODEL)
        providers.append(
            (f"{ollama_url}/v1", "not-needed", ollama_model, "Ollama")
        )

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
                {"role": "system", "content": _get_system_prompt()},
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
    return _format_llm_error(
        last_error or Exception(t("chat.errors.unknown")), last_provider_name,
    )


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
        return t("chat.errors.quota_exceeded", url=key_url)

    # 인증 실패 (401/403)
    if "401" in error_str or "403" in error_str or "auth" in error_str.lower():
        return t("chat.errors.auth_failed", env=key_env)

    # 타임아웃
    if "timeout" in error_str.lower() or "timed out" in error_str.lower():
        return t("chat.errors.timeout")

    # 기타 에러
    return t("chat.errors.generation_error", error_type=type(error).__name__)


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
        print(t("chat.errors.rich_missing"))
        sys.exit(1)

    console = Console()

    # ── 헤더 출력 ──
    header = Text()
    header.append(t("chat.header.title") + "\n", style="bold white")
    header.append(t("chat.header.subtitle") + "\n\n", style="dim")
    header.append("  quit", style="bold yellow")
    header.append(f"  {t('chat.header.quit_label')}  ", style="dim")
    header.append("help", style="bold yellow")
    header.append(f"  {t('chat.header.help_label')}  ", style="dim")
    header.append("search", style="bold yellow")
    header.append(f"  {t('chat.header.search_label')}", style="dim")
    console.print(Panel(header, title="[bold cyan]OneRAG[/bold cyan]", border_style="cyan"))
    console.print()

    # ── 컴포넌트 초기화 ──
    with console.status(f"[bold cyan]{t('chat.status.initializing')}", spinner="dots"):
        retriever, bm25_index, merger = initialize_components()
        llm_available, llm_provider_name = _check_llm_available()

    # 상태 테이블 출력
    status_table = Table(show_header=False, box=None, padding=(0, 2))
    status_table.add_column(t("chat.status.item"), style="dim")
    status_table.add_column(t("chat.status.state"))

    hybrid_status = (
        f"[green]{t('chat.status.hybrid_active')}[/green]"
        if bm25_index
        else f"[yellow]{t('chat.status.hybrid_inactive')}[/yellow]"
    )
    llm_status = (
        f"[green]{t('chat.status.llm_active', provider=llm_provider_name)}[/green]"
        if llm_available
        else f"[yellow]{t('chat.status.llm_inactive')}[/yellow]"
    )

    status_table.add_row(t("chat.status.hybrid_search"), hybrid_status)
    status_table.add_row(t("chat.status.llm_generation"), llm_status)

    console.print(Panel(
        status_table,
        title=f"[bold]{t('chat.status.init_complete')}[/bold]",
        border_style="green",
    ))

    if not llm_available:
        console.print()
        console.print(
            Panel(
                f"[bold yellow]{t('chat.api_key_guide.message')}[/bold yellow]\n\n"
                f"[bold]{t('chat.api_key_guide.option1_title')}[/bold]\n"
                f"  {t('chat.api_key_guide.option1_step1')}\n"
                f"  [bold]{t('chat.api_key_guide.option1_step2')}[/bold]\n\n"
                f"[bold]{t('chat.api_key_guide.option2_title')}[/bold]\n"
                f"  {t('chat.api_key_guide.option2_step1')}\n"
                f"  [bold]{t('chat.api_key_guide.option2_step2')}[/bold]\n\n"
                f"[dim]{t('chat.api_key_guide.note')}[/dim]",
                title=f"[yellow]{t('chat.api_key_guide.title')}[/yellow]",
                border_style="yellow",
            )
        )

    console.print()

    # ── 대화 루프 ──
    while True:
        try:
            console.print("[bold cyan]─[/bold cyan]" * 50)
            query = console.input(f"[bold yellow]{t('chat.input.prompt')}[/bold yellow]").strip()
        except (EOFError, KeyboardInterrupt):
            console.print(f"\n[dim]{t('chat.input.exit_message')}[/dim]")
            break

        if not query:
            continue
        if query.lower() in ("quit", "exit", "q"):
            console.print(f"[dim]{t('chat.input.exit_message')}[/dim]")
            break

        if query.lower() == "help":
            help_table = Table(
                title=t("chat.help.title"),
                show_header=True,
                header_style="bold",
                border_style="dim",
            )
            help_table.add_column(t("chat.help.cmd_header"), style="bold yellow", width=12)
            help_table.add_column(t("chat.help.desc_header"))
            help_table.add_row("quit / q", t("chat.help.quit_desc"))
            help_table.add_row("help", t("chat.help.help_desc"))
            help_table.add_row("search <query>", t("chat.help.search_desc"))

            console.print()
            console.print(help_table)
            console.print()
            console.print(f"[bold]{t('chat.help.example_title')}[/bold]")

            # 동적 예시 질문 출력
            from easy_start.i18n import Translator
            translator = Translator.get_instance()
            examples_data = translator.translate("chat.help.examples")
            if isinstance(examples_data, str) and examples_data != "chat.help.examples":
                # 단일 문자열인 경우
                console.print(f"  [dim]-[/dim] {examples_data}")
            else:
                # YAML 리스트인 경우 - 원본 데이터에서 직접 접근
                translations = translator._translations
                examples = (
                    translations.get("chat", {})
                    .get("help", {})
                    .get("examples", [])
                )
                for ex in examples:
                    console.print(f"  [dim]-[/dim] {ex}")

            console.print()
            continue

        # "search" 접두사: 검색만 수행
        search_only = False
        if query.lower().startswith("search "):
            search_only = True
            query = query[7:].strip()
            if not query:
                console.print(f"[dim]{t('chat.input.search_hint')}[/dim]")
                continue

        # ── 검색 실행 ──
        console.print()
        with console.status(f"[bold cyan]{t('chat.input.searching')}", spinner="dots"):
            results = await search_documents(
                query=query,
                retriever=retriever,
            )

        if not results:
            console.print(
                Panel(f"[dim]{t('chat.input.no_results')}[/dim]", border_style="dim")
            )
            console.print()
            continue

        # ── 검색 결과 테이블 ──
        result_table = Table(
            title=t("chat.input.search_results", count=len(results)),
            show_header=True,
            header_style="bold",
            border_style="blue",
            title_style="bold blue",
            expand=True,
        )
        result_table.add_column("#", style="dim", width=3, justify="right")
        result_table.add_column(t("chat.input.content_col"), ratio=5)
        result_table.add_column(t("chat.input.score_col"), style="cyan", width=10, justify="right")

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
            with console.status(f"[bold cyan]{t('chat.input.generating')}", spinner="dots"):
                answer = await generate_answer(query, results)

            if answer:
                # Markdown 렌더링으로 깔끔하게 출력
                console.print(
                    Panel(
                        Markdown(answer),
                        title=f"[bold green]{t('chat.input.ai_answer')}[/bold green]",
                        border_style="green",
                        padding=(1, 2),
                    )
                )
            else:
                console.print(f"[dim]{t('chat.input.generation_failed')}[/dim]")
        elif not search_only and not llm_available:
            console.print()
            console.print(f"[dim]{t('chat.input.api_key_hint')}[/dim]")

        console.print()


def main() -> None:
    """메인 진입점"""
    asyncio.run(chat_loop())


if __name__ == "__main__":
    main()
