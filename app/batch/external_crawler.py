"""
외부 사이트 크롤러 (Playwright 기반)
====================================
기능: 외부 웹 소스 크롤링 (설정 기반)
용도: 외부 사이트 데이터 수집

대상 소스:
- `app/config/features/batch.yaml`의 `batch.external.sources`에 정의된 항목

참고: 구조화 데이터 소스는 별도 배치 모듈에서 처리
"""

import asyncio
import os
from dataclasses import dataclass, field
from typing import Any

import httpx
from langchain_text_splitters import RecursiveCharacterTextSplitter
from playwright.async_api import async_playwright

from app.lib.logger import get_logger

logger = get_logger(__name__)


# ============================================================================
# 설정
# ============================================================================


@dataclass
class ExternalSourceConfig:
    """외부 소스 설정"""

    name: str  # source_file로 사용
    url: str  # 크롤링 시작 URL
    content_selector: str = "main"  # 콘텐츠 영역 CSS 셀렉터
    max_depth: int = 2  # 재귀 깊이
    link_whitelist: list[str] = field(default_factory=list)  # 허용 링크 패턴


# 외부 소스 설정
# - Blank 시스템에서는 특정 도메인/사이트를 코드에 하드코딩하지 않습니다.
# - 실제 소스는 설정 파일에서 정의하고, 필요 시 run_external_batch()에 주입하세요.
EXTERNAL_SOURCES: list[ExternalSourceConfig] = []


@dataclass
class CrawlResult:
    """크롤링 결과"""

    source_name: str
    pages: list[dict]  # [{"url": str, "content": str, "title": str}]
    total_pages: int
    error_message: str = ""


@dataclass
class ChunkData:
    """청크 데이터"""

    content: str
    source_file: str
    chunk_index: int
    url: str


@dataclass
class BatchResult:
    """배치 결과"""

    source_name: str
    total_pages: int
    total_chunks: int
    uploaded_chunks: int
    deleted_chunks: int
    success: bool
    error_message: str = ""
    processing_time_seconds: float = 0.0


# ============================================================================
# 외부 크롤러
# ============================================================================


class ExternalCrawler:
    """
    Playwright 기반 외부 사이트 크롤러

    주요 기능:
    - JavaScript 렌더링 지원
    - 재귀 링크 탐색
    - 텍스트 추출 및 청킹
    """

    def __init__(
        self,
        chunk_size: int = 1400,
        chunk_overlap: int = 200,
        weaviate_url: str | None = None,
    ):
        """
        크롤러 초기화

        Args:
            chunk_size: 청크 크기
            chunk_overlap: 청크 오버랩
            weaviate_url: Weaviate URL
        """
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.weaviate_url = weaviate_url or os.getenv(
            "WEAVIATE_URL", "https://weaviate-production-70aa.up.railway.app"
        )
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=["\n\n", "\n", ". ", " ", ""],
        )
        self._http_client: httpx.AsyncClient | None = None

        logger.info("✅ ExternalCrawler 초기화 완료")

    async def _get_http_client(self) -> httpx.AsyncClient:
        """HTTP 클라이언트 지연 초기화"""
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(timeout=60.0)
        return self._http_client

    async def close(self) -> None:
        """리소스 정리"""
        if self._http_client and not self._http_client.is_closed:
            await self._http_client.aclose()

    async def crawl_source(self, config: ExternalSourceConfig) -> CrawlResult:
        """
        단일 소스 크롤링

        HTTPS 실패 시 HTTP로 자동 fallback 시도

        Args:
            config: 소스 설정

        Returns:
            CrawlResult: 크롤링 결과
        """
        pages: list[dict] = []
        visited: set[str] = set()

        # HTTPS → HTTP fallback 지원
        urls_to_try = [config.url]
        if config.url.startswith("https://"):
            # HTTPS 실패 시 HTTP로 fallback
            http_url = config.url.replace("https://", "http://", 1)
            urls_to_try.append(http_url)

        last_error: str = ""

        for url_to_try in urls_to_try:
            logger.info(f"🌐 크롤링 시작: {config.name} ({url_to_try})")
            pages = []
            visited = set()

            try:
                async with async_playwright() as p:
                    browser = await p.chromium.launch(headless=True)
                    context = await browser.new_context(
                        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0.0.0 Safari/537.36"
                    )

                    # 재귀 크롤링 (현재 시도 URL 사용)
                    await self._crawl_recursive(
                        context=context,
                        config=config,
                        url=url_to_try,
                        depth=0,
                        visited=visited,
                        pages=pages,
                    )

                    await browser.close()

                logger.info(f"✅ 크롤링 완료: {config.name} ({len(pages)}페이지)")

                return CrawlResult(
                    source_name=config.name,
                    pages=pages,
                    total_pages=len(pages),
                )

            except Exception as e:
                error_str = str(e)
                last_error = error_str

                # SSL/인증서 관련 오류인 경우 HTTP fallback 시도
                ssl_errors = ["SSL", "CERT", "certificate", "ERR_CERT", "TLS"]
                is_ssl_error = any(err in error_str for err in ssl_errors)

                if is_ssl_error and url_to_try.startswith("https://"):
                    logger.warning(
                        f"⚠️ HTTPS 연결 실패 (SSL 오류), HTTP로 fallback 시도: {config.name}"
                    )
                    continue  # HTTP로 재시도
                else:
                    logger.error(f"❌ 크롤링 실패 ({config.name}): {e}")
                    break  # SSL 오류가 아니면 중단

        # 모든 시도 실패
        return CrawlResult(
            source_name=config.name,
            pages=pages,
            total_pages=len(pages),
            error_message=last_error,
        )

    async def _crawl_recursive(
        self,
        context: Any,
        config: ExternalSourceConfig,
        url: str,
        depth: int,
        visited: set[str],
        pages: list[dict],
    ) -> None:
        """
        재귀 크롤링

        Args:
            context: Playwright 브라우저 컨텍스트
            config: 소스 설정
            url: 크롤링 URL
            depth: 현재 깊이
            visited: 방문한 URL 집합
            pages: 수집된 페이지 리스트
        """
        # 중복 방문 방지
        normalized_url = url.rstrip("/")
        if normalized_url in visited:
            return
        visited.add(normalized_url)

        # 깊이 제한
        if depth > config.max_depth:
            return

        logger.debug(f"  📄 [{depth}] {url}")

        try:
            page = await context.new_page()
            await page.goto(url, wait_until="networkidle", timeout=30000)

            # 페이지 로딩 대기
            await asyncio.sleep(1)

            # 제목 추출
            title = await page.title()

            # 콘텐츠 추출
            content = ""
            for selector in config.content_selector.split(", "):
                try:
                    element = await page.query_selector(selector)
                    if element:
                        content = await element.inner_text()
                        break
                except Exception:
                    continue

            if not content:
                # fallback: body 전체
                body = await page.query_selector("body")
                if body:
                    content = await body.inner_text()

            # 페이지 저장
            if content.strip():
                pages.append(
                    {
                        "url": url,
                        "title": title,
                        "content": f"[{title}]\n\n{content}",
                    }
                )

            # 링크 추출 및 재귀 크롤링
            if depth < config.max_depth:
                links = await self._extract_links(page, config)
                await page.close()

                for link in links:
                    if link not in visited:
                        await self._crawl_recursive(
                            context, config, link, depth + 1, visited, pages
                        )
            else:
                await page.close()

        except Exception as e:
            error_str = str(e)
            logger.warning(f"⚠️ 페이지 크롤링 실패 ({url}): {e}")

            # 루트 페이지(depth=0)에서 SSL 오류 발생 시 상위로 전파
            # → crawl_source()에서 HTTP fallback 시도
            ssl_errors = ["SSL", "CERT", "certificate", "ERR_CERT", "TLS"]
            is_ssl_error = any(err in error_str for err in ssl_errors)

            if depth == 0 and is_ssl_error:
                raise  # 상위로 전파하여 HTTP fallback 트리거

    async def _extract_links(self, page: Any, config: ExternalSourceConfig) -> list[str]:
        """
        페이지에서 링크 추출

        Args:
            page: Playwright 페이지
            config: 소스 설정

        Returns:
            링크 URL 리스트
        """
        links = []

        try:
            elements = await page.query_selector_all("a[href]")
            for element in elements:
                href = await element.get_attribute("href")
                if not href:
                    continue

                # 절대 URL 변환
                if href.startswith("/"):
                    base_url = "/".join(config.url.split("/")[:3])
                    href = base_url + href
                elif not href.startswith("http"):
                    continue

                # 화이트리스트 필터링
                if config.link_whitelist:
                    if not any(pattern in href for pattern in config.link_whitelist):
                        continue

                # 앵커, 자바스크립트 제외
                if "#" in href:
                    href = href.split("#")[0]
                if href.startswith("javascript:"):
                    continue

                links.append(href)

        except Exception as e:
            logger.warning(f"⚠️ 링크 추출 실패: {e}")

        return list(set(links))  # 중복 제거

    async def process_source(
        self, config: ExternalSourceConfig, dry_run: bool = False
    ) -> BatchResult:
        """
        단일 소스 처리: 크롤링 → 청킹 → Weaviate 업로드

        Args:
            config: 소스 설정
            dry_run: True면 Weaviate 업로드 건너뜀

        Returns:
            BatchResult: 처리 결과
        """
        import time

        start_time = time.time()

        try:
            # 1. 크롤링
            crawl_result = await self.crawl_source(config)

            if not crawl_result.pages:
                return BatchResult(
                    source_name=config.name,
                    total_pages=0,
                    total_chunks=0,
                    uploaded_chunks=0,
                    deleted_chunks=0,
                    success=False,
                    error_message=crawl_result.error_message or "페이지 없음",
                )

            # 2. 청킹
            all_chunks: list[ChunkData] = []
            for page_data in crawl_result.pages:
                chunks = self.text_splitter.split_text(page_data["content"])
                for i, chunk in enumerate(chunks):
                    all_chunks.append(
                        ChunkData(
                            content=chunk,
                            source_file=config.name,
                            chunk_index=i,
                            url=page_data["url"],
                        )
                    )

            logger.info(f"📦 {len(all_chunks)}개 청크 생성")

            # 3. Weaviate 업서트
            if dry_run:
                logger.info("🔸 Dry-run 모드: Weaviate 업로드 건너뜀")
                deleted_count = 0
                uploaded_count = len(all_chunks)
            else:
                deleted_count = await self._delete_existing_data(config.name)
                uploaded_count = await self._upload_chunks(all_chunks)

            elapsed = time.time() - start_time

            return BatchResult(
                source_name=config.name,
                total_pages=len(crawl_result.pages),
                total_chunks=len(all_chunks),
                uploaded_chunks=uploaded_count,
                deleted_chunks=deleted_count,
                success=True,
                processing_time_seconds=elapsed,
            )

        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(f"❌ 소스 처리 실패 ({config.name}): {e}")
            return BatchResult(
                source_name=config.name,
                total_pages=0,
                total_chunks=0,
                uploaded_chunks=0,
                deleted_chunks=0,
                success=False,
                error_message=str(e),
                processing_time_seconds=elapsed,
            )

    async def _delete_existing_data(self, source_file: str) -> int:
        """Weaviate에서 기존 데이터 삭제"""
        client = await self._get_http_client()

        # 개수 확인
        count_query = {
            "query": f"""{{
                Aggregate {{
                    Documents(where: {{
                        path: ["source_file"]
                        operator: Equal
                        valueText: "{source_file}"
                    }}) {{
                        meta {{ count }}
                    }}
                }}
            }}"""
        }

        try:
            count_response = await client.post(
                f"{self.weaviate_url}/v1/graphql",
                json=count_query,
            )
            count_data = count_response.json()
            existing_count = (
                count_data.get("data", {})
                .get("Aggregate", {})
                .get("Documents", [{}])[0]
                .get("meta", {})
                .get("count", 0)
            )
        except Exception:
            existing_count = 0

        if existing_count == 0:
            return 0

        # 삭제
        delete_payload = {
            "match": {
                "class": "Documents",
                "where": {
                    "path": ["source_file"],
                    "operator": "Equal",
                    "valueText": source_file,
                },
            },
        }

        try:
            # httpx.AsyncClient.delete()는 json 파라미터를 지원하지 않음
            # request() 메서드 사용
            response = await client.request(
                "DELETE",
                f"{self.weaviate_url}/v1/batch/objects",
                json=delete_payload,
            )

            if response.status_code in (200, 204):
                logger.info(f"🗑️ 기존 데이터 삭제: {source_file} ({existing_count}개)")
                return existing_count

        except Exception as e:
            logger.error(f"❌ 삭제 실패: {e}")

        return 0

    async def _upload_chunks(self, chunks: list[ChunkData]) -> int:
        """청크를 Weaviate에 업로드"""
        if not chunks:
            return 0

        client = await self._get_http_client()
        uploaded = 0
        batch_size = 100

        for i in range(0, len(chunks), batch_size):
            batch = chunks[i : i + batch_size]

            objects = [
                {
                    "class": "Documents",
                    "properties": {
                        "content": chunk.content,
                        "source_file": chunk.source_file,
                        "chunk_index": chunk.chunk_index,
                    },
                }
                for chunk in batch
            ]

            try:
                response = await client.post(
                    f"{self.weaviate_url}/v1/batch/objects",
                    json={"objects": objects},
                )

                if response.status_code == 200:
                    result = response.json()
                    success_count = sum(
                        1 for obj in result if obj.get("result", {}).get("status") == "SUCCESS"
                    )
                    uploaded += success_count

            except Exception as e:
                logger.error(f"❌ 업로드 실패: {e}")

        logger.info(f"✅ 업로드 완료: {uploaded}/{len(chunks)}개")
        return uploaded

    async def run_batch(
        self, sources: list[ExternalSourceConfig] | None = None, dry_run: bool = False
    ) -> list[BatchResult]:
        """
        전체 배치 실행

        Args:
            sources: 처리할 소스 목록 (None이면 기본 소스 전체)
            dry_run: True면 Weaviate 업로드 건너뜀

        Returns:
            배치 결과 리스트
        """
        sources = sources or EXTERNAL_SOURCES
        results: list[BatchResult] = []

        logger.info("=" * 60)
        logger.info("🌐 외부 사이트 크롤링 배치 시작")
        logger.info(f"📊 대상: {[s.name for s in sources]}")
        logger.info("=" * 60)

        for config in sources:
            logger.info(f"\n{'─' * 40}")
            logger.info(f"📁 [{config.name}] 처리 시작")
            logger.info(f"{'─' * 40}")

            result = await self.process_source(config, dry_run=dry_run)
            results.append(result)

            if result.success:
                logger.info(
                    f"✅ [{config.name}] 완료: "
                    f"{result.total_pages}페이지 → {result.uploaded_chunks}청크"
                )
            else:
                logger.error(f"❌ [{config.name}] 실패: {result.error_message}")

        await self.close()

        total_chunks = sum(r.uploaded_chunks for r in results)
        logger.info("\n" + "=" * 60)
        logger.info(f"✅ 외부 크롤링 배치 완료: 총 {total_chunks}개 청크")
        logger.info("=" * 60)

        return results


# ============================================================================
# 편의 함수
# ============================================================================


async def run_external_batch(
    source_names: list[str] | None = None,
    dry_run: bool = False,
) -> list[BatchResult]:
    """
    외부 사이트 배치 실행 편의 함수

    Args:
        source_names: 처리할 소스명 목록 (None이면 전체)
        dry_run: True면 Weaviate 업로드 건너뜀

    Returns:
        배치 결과 리스트
    """
    if source_names:
        sources = [s for s in EXTERNAL_SOURCES if s.name in source_names]
    else:
        sources = EXTERNAL_SOURCES

    crawler = ExternalCrawler()
    return await crawler.run_batch(sources=sources, dry_run=dry_run)


# ============================================================================
# 메인 실행
# ============================================================================


async def main():
    """메인 실행 함수"""
    import argparse

    parser = argparse.ArgumentParser(description="외부 사이트 크롤러")
    parser.add_argument(
        "--source",
        "-s",
        default="all",
        help="처리할 소스명 (설정에 정의된 source name 또는 all)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Weaviate 업로드 건너뜀",
    )

    args = parser.parse_args()

    source_names = None if args.source == "all" else [args.source]

    results = await run_external_batch(source_names=source_names, dry_run=args.dry_run)

    # 결과 요약
    print("\n" + "=" * 60)
    print("📊 외부 크롤링 결과 요약")
    print("=" * 60)

    for result in results:
        status = "✅" if result.success else "❌"
        print(
            f"{status} {result.source_name}: "
            f"{result.total_pages}페이지 → {result.uploaded_chunks}청크 "
            f"({result.processing_time_seconds:.1f}초)"
        )


if __name__ == "__main__":
    asyncio.run(main())
