#!/usr/bin/env python3
"""
Rich CLI 대화형 챗봇

Docker 없이 로컬에서 RAG 하이브리드 검색을 체험하는 CLI 인터페이스입니다.
FastAPI 서버 없이 직접 검색 파이프라인을 호출합니다.

사용법:
    uv run python quickstart_local/chat.py

의존성:
    - rich: CLI UI
    - chromadb: 벡터 검색
    - sentence-transformers: 임베딩
    - kiwipiepy, rank-bm25: BM25 검색 (선택적)
"""

import asyncio
import sys
from pathlib import Path
from typing import Any

# 프로젝트 루트를 Python 경로에 추가
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from quickstart_local.load_data import (  # noqa: E402
    BM25_INDEX_PATH,
    CHROMA_PERSIST_DIR,
    COLLECTION_NAME,
)

# 상수
TOP_K = 5


def format_search_results(results: list[dict[str, Any]]) -> str:
    """
    검색 결과를 포맷된 문자열로 변환

    Args:
        results: 검색 결과 리스트 (content, score, source 필드)

    Returns:
        Rich 마크업이 포함된 문자열
    """
    if not results:
        return "[dim]검색 결과가 없습니다.[/dim]"

    lines = []
    for i, r in enumerate(results, 1):
        score = r.get("score", 0.0)
        content = r.get("content", "")[:80]
        lines.append(f"  {i}. [bold]{content}...[/bold] (점수: {score:.2f})")

    return "\n".join(lines)


async def search_documents(
    query: str,
    retriever: Any = None,
    bm25_index: Any = None,
    merger: Any = None,
    top_k: int = TOP_K,
) -> list[dict[str, Any]]:
    """
    ChromaDB + BM25 하이브리드 검색 수행

    Args:
        query: 검색 쿼리
        retriever: ChromaRetriever 인스턴스
        bm25_index: BM25Index 인스턴스 (선택적)
        merger: HybridMerger 인스턴스 (선택적)
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
            "content": sr.content,
            "score": sr.score,
            "source": sr.id,
            "metadata": sr.metadata,
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
            from quickstart_local.load_data import load_bm25_index
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


async def chat_loop() -> None:
    """메인 대화 루프"""
    try:
        from rich.console import Console
        from rich.panel import Panel
        from rich.text import Text
    except ImportError:
        print("rich 패키지가 필요합니다: uv pip install rich")
        sys.exit(1)

    console = Console()

    # 헤더 출력
    header = Text()
    header.append("OneRAG 로컬 챗봇\n", style="bold cyan")
    header.append("하이브리드 검색 (벡터 + 한글 키워드)\n", style="dim")
    header.append("종료: quit | 도움: help", style="dim")
    console.print(Panel(header, border_style="cyan"))
    console.print()

    # 컴포넌트 초기화
    console.print("[dim]검색 엔진 초기화 중...[/dim]")
    retriever, bm25_index, merger = initialize_components()

    hybrid_status = "활성" if bm25_index is not None else "비활성 (Dense만 사용)"
    console.print(f"[green]초기화 완료[/green] (하이브리드: {hybrid_status})")
    console.print()

    # 대화 루프
    while True:
        try:
            query = console.input("[bold yellow]질문: [/bold yellow]").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]종료합니다.[/dim]")
            break

        if not query:
            continue
        if query.lower() in ("quit", "exit", "q"):
            console.print("[dim]종료합니다.[/dim]")
            break
        if query.lower() == "help":
            console.print()
            console.print("[bold]예시 질문:[/bold]")
            console.print("  - RAG 시스템이란?")
            console.print("  - 설치 방법 알려줘")
            console.print("  - 하이브리드 검색이 뭐야?")
            console.print("  - 환경변수 설정 어떻게 해?")
            console.print()
            continue

        # 검색 실행
        console.print("[dim]  검색 중...[/dim]")
        results = await search_documents(
            query=query,
            retriever=retriever,
        )

        # 결과 출력
        if results:
            console.print(f"\n  [bold]검색 결과 ({len(results)}건):[/bold]")
            for i, r in enumerate(results[:5], 1):
                score = r.get("score", 0.0)
                content = r.get("content", "")
                # 첫 100자만 표시
                preview = content[:100].replace("\n", " ")
                console.print(f"    {i}. {preview}... [dim](점수: {score:.2f})[/dim]")
        else:
            console.print("  [dim]검색 결과가 없습니다.[/dim]")

        console.print()


def main() -> None:
    """메인 진입점"""
    asyncio.run(chat_loop())


if __name__ == "__main__":
    main()
