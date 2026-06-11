"""
Sitemap Connector Unit Test

실제 웹 호출 없이 모킹된 응답을 통해 사이트맵 분석 및 본문 추출 로직을 검증합니다.
"""
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
