"""
Sitemap Connector Unit Test

실제 웹 호출 없이 모킹된 응답을 통해 사이트맵 분석 및 본문 추출 로직을 검증합니다.
"""
import asyncio
import gc
from typing import Any

import httpx
import pytest
import respx

from app.modules.ingestion.connectors.sitemap import SitemapConnector
from app.modules.ingestion.interfaces import StandardDocument


@pytest.mark.asyncio
@respx.mock
async def test_sitemap_connector_fetches_and_parses():
    """사이트맵을 읽고 하위 페이지들의 내용을 추출하는지 확인"""
    # Given
    sitemap_url = "https://example.com/sitemap.xml"
    page_url = "https://example.com/page1"

    # 1. Sitemap XML Mocking
    sitemap_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
    <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
       <url><loc>{page_url}</loc></url>
    </urlset>
    """
    respx.get(sitemap_url).mock(return_value=httpx.Response(200, content=sitemap_xml))

    # 2. Page HTML Mocking
    page_html = "<html><body><article><h1>제목</h1><p>본문 내용입니다.</p></article></body></html>"
    respx.get(page_url).mock(return_value=httpx.Response(200, html=page_html))

    connector = SitemapConnector(url=sitemap_url)

    # When
    docs = []
    async for doc in connector.fetch_documents():
        docs.append(doc)

    # Then
    assert len(docs) == 1
    assert isinstance(docs[0], StandardDocument)
    assert "본문 내용입니다" in docs[0].content
    assert docs[0].source_url == page_url


@pytest.mark.asyncio
@respx.mock
async def test_fetch_documents_reuses_single_http_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """크롤 전체에서 httpx.AsyncClient가 1회만 생성되는지 확인 (커넥션 풀 재사용)"""
    # Given: 사이트맵 1개 + 페이지 3개
    sitemap_url = "https://example.com/sitemap.xml"
    page_urls = [f"https://example.com/page{i}" for i in range(1, 4)]

    locs = "".join(f"<url><loc>{u}</loc></url>" for u in page_urls)
    sitemap_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{locs}</urlset>'
    )
    respx.get(sitemap_url).mock(return_value=httpx.Response(200, content=sitemap_xml))
    page_html = "<html><body><article><p>본문</p></article></body></html>"
    for u in page_urls:
        respx.get(u).mock(return_value=httpx.Response(200, html=page_html))

    # AsyncClient 생성 횟수를 세기 위해 __init__을 래핑
    created_clients = 0
    original_init = httpx.AsyncClient.__init__

    def counting_init(self: httpx.AsyncClient, *args: object, **kwargs: object) -> None:
        nonlocal created_clients
        created_clients += 1
        original_init(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(httpx.AsyncClient, "__init__", counting_init)

    connector = SitemapConnector(url=sitemap_url)

    # When
    docs = []
    async for doc in connector.fetch_documents():
        docs.append(doc)

    # Then: 문서 3개 수집 + 클라이언트는 단 1개만 생성 (사이트맵/페이지/재시도 공유)
    assert len(docs) == 3
    assert created_clients == 1


@pytest.mark.asyncio
@respx.mock
async def test_fetch_documents_early_break_cancels_inflight_tasks() -> None:
    """소비자가 조기 break해도 잔여(in-flight) 태스크가 취소·회수되는지 검증

    기존 결함: async-for 조기 break → GeneratorExit → 공유 클라이언트가
    먼저 close되면서 잔여 태스크들이 'client has been closed' 에러와
    'Task exception was never retrieved' 경고를 발생시켰다.
    수정 후: finally에서 미완료 태스크를 cancel하고 gather로 회수하므로
    모든 태스크가 클라이언트 close 전에 종료(취소 포함)되어야 한다.
    """
    # Given: 사이트맵 1개 + 빠른 페이지 2개 + 느린(행) 페이지 3개
    sitemap_url = "https://example.com/sitemap.xml"
    fast_urls = [f"https://example.com/fast{i}" for i in (1, 2)]
    slow_urls = [f"https://example.com/slow{i}" for i in (1, 2, 3)]
    all_urls = fast_urls + slow_urls

    locs = "".join(f"<url><loc>{u}</loc></url>" for u in all_urls)
    sitemap_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{locs}</urlset>'
    )
    respx.get(sitemap_url).mock(return_value=httpx.Response(200, content=sitemap_xml))

    page_html = "<html><body><article><p>본문</p></article></body></html>"
    for u in fast_urls:
        respx.get(u).mock(return_value=httpx.Response(200, html=page_html))

    async def slow_response(request: httpx.Request) -> httpx.Response:
        """취소되기 전까지 응답하지 않는 느린 페이지 (in-flight 시뮬레이션)"""
        await asyncio.sleep(30)
        return httpx.Response(200, html=page_html)

    for u in slow_urls:
        respx.get(u).mock(side_effect=slow_response)

    connector = SitemapConnector(url=sitemap_url)

    # 페이지 수집 태스크 추적: 코루틴 시작 시점의 current_task를 기록
    started_tasks: list[asyncio.Task[Any]] = []
    original_fetch = connector._safe_fetch_and_parse

    async def tracking_fetch(
        url: str, client: httpx.AsyncClient | None = None
    ) -> StandardDocument | None:
        task = asyncio.current_task()
        if task is not None:
            started_tasks.append(task)
        return await original_fetch(url, client)

    # 인스턴스 속성으로 덮어써 fetch_documents 내부 호출을 가로챈다
    connector._safe_fetch_and_parse = tracking_fetch  # type: ignore[method-assign]

    # 이벤트 루프 예외 핸들러 후킹 ('Task exception was never retrieved' 감지)
    loop = asyncio.get_running_loop()
    unhandled_contexts: list[dict[str, Any]] = []
    previous_handler = loop.get_exception_handler()
    loop.set_exception_handler(lambda _loop, context: unhandled_contexts.append(context))
    try:
        # When: 5개 중 2개만 소비하고 break → 명시적 aclose로 GeneratorExit 유발
        docs = []
        gen = connector.fetch_documents()
        async for doc in gen:
            docs.append(doc)
            if len(docs) == 2:
                break
        await gen.aclose()

        # Then 1: 빠른 페이지 2개만 수집됨
        assert len(docs) == 2
        # Then 2: 태스크 5개 모두 시작되었고, aclose 후 전부 종료(취소 포함) 상태
        assert len(started_tasks) == 5, f"시작된 태스크 수: {len(started_tasks)}"
        not_done = [t for t in started_tasks if not t.done()]
        assert not not_done, (
            f"조기 종료 후에도 미완료 태스크 {len(not_done)}개 잔존 "
            "(finally에서 cancel+gather 회수 누락)"
        )

        # Then 3: 'Task exception was never retrieved' 경고 없음
        # (태스크 참조 해제 + GC 강제로 미회수 예외 경고를 표면화시켜 검증)
        started_tasks.clear()
        del gen
        gc.collect()
        await asyncio.sleep(0)
        assert not unhandled_contexts, (
            f"미회수 태스크 예외 발생: {[c.get('message') for c in unhandled_contexts]}"
        )
    finally:
        loop.set_exception_handler(previous_handler)
