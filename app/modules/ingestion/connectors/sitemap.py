"""
Sitemap Connector Implementation

사이트맵 XML을 분석하고 각 페이지의 본문을 추출하는 실질적인 구현체.

변경 이력:
- 2026-01-08: QA-001 대응 - encoding 모듈 import 추가 (향후 파일 처리 확장 대비)
"""
import asyncio
import logging
from collections.abc import AsyncGenerator
from typing import Any

import httpx
from bs4 import BeautifulSoup
from tenacity import RetryError

from app.lib.retry import DEFAULT_BACKOFF_JITTER_S, BackoffStrategy, RetryPolicy
from app.modules.ingestion.interfaces import IIngestionConnector, StandardDocument

logger = logging.getLogger(__name__)

class SitemapConnector(IIngestionConnector):
    def __init__(self, url: str, **kwargs: Any) -> None:
        self.url = url
        self.timeout = kwargs.get("timeout", 30.0)
        self.max_parallel = kwargs.get("max_parallel", 5) # 동시 요청 제한
        self.max_retries = kwargs.get("max_retries", 3)
        self._semaphore = asyncio.Semaphore(self.max_parallel)

    async def fetch_documents(self) -> AsyncGenerator[StandardDocument, None]:
        """사이트맵에서 URL 목록을 가져와 각 페이지의 내용을 병렬로 추출

        커넥션 풀 재사용: 크롤 전체(사이트맵 조회 + 모든 페이지 수집/재시도)에서
        ``httpx.AsyncClient`` 1개를 공유합니다. 기존에는 재시도 attempt마다 새
        클라이언트를 생성해 N페이지 크롤에 N+α회 TCP+TLS 핸드셰이크가 발생했습니다.
        """
        # 크롤 전체가 공유하는 단일 클라이언트 (커넥션 풀 재사용)
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            urls = await self._parse_sitemap(self.url, client)
            if not urls:
                logger.warning(f"No URLs found in sitemap: {self.url}")
                return

            # 병렬 태스크 생성 (공유 클라이언트 전달)
            tasks = [self._safe_fetch_and_parse(url, client) for url in urls]

            # 결과를 스트리밍하기 위해 as_completed 사용
            for task in asyncio.as_completed(tasks):
                try:
                    doc = await task
                    if doc:
                        yield doc
                except Exception as e:
                    logger.error(f"Critical error during document fetch task: {e}")

    async def _safe_fetch_and_parse(
        self, url: str, client: httpx.AsyncClient | None = None
    ) -> StandardDocument | None:
        """
        세마포어와 재시도 로직을 적용한 안전한 페이지 수집

        클라이언트 수명: ``fetch_documents()``가 만든 공유 클라이언트를 주입받아
        재시도(attempt) 간에도 커넥션 풀을 재사용합니다. 단독 호출(client=None) 시
        1회용 클라이언트를 만들어 동일 경로로 위임합니다(하위호환).

        동작 보존 (RetryPolicy 이관):
        - 세마포어로 동시 요청 수를 ``max_parallel``로 제한합니다(재시도 루프 외부 유지).
        - 재시도 대상: ``httpx.ConnectError``, ``httpx.TimeoutException``.
          선형 백오프 ``(attempt + 1) * 2`` → 2, 4, 6...초(+jitter).
          ``increment_s`` 미지정 시 ``initial_delay_s``(2.0)와 동일하게 증가해
          기존 시퀀스를 정확히 재현합니다.
        - 최대 시도(``max_retries``) 소진 시: ``None`` 반환(예외 전파 없음).
        - 그 외 예외: 즉시 ``None`` 반환(재시도/대기 없음).
        """
        if client is None:
            # 하위호환 경로: 단독 호출 시 1회용 클라이언트를 만들어 공유 경로로 위임
            async with httpx.AsyncClient(timeout=self.timeout) as own_client:
                return await self._safe_fetch_and_parse(url, own_client)
        # 선언적 재시도 정책: 선형 백오프 2, 4, 6...초 (+jitter)
        policy = RetryPolicy(
            retry_exceptions=(httpx.ConnectError, httpx.TimeoutException),
            max_attempts=self.max_retries,
            strategy=BackoffStrategy.LINEAR,
            initial_delay_s=2.0,
            # increment_s 미지정 → initial_delay_s와 동일(2.0): (attempt+1)*2 시퀀스
            max_delay_s=float("inf"),  # 기존 wait_incrementing 기본(사실상 무상한) 보존
            jitter_s=DEFAULT_BACKOFF_JITTER_S,
            reraise=True,  # 소진 시 마지막 예외를 받아 None 반환
            before_sleep=lambda rs: logger.warning(
                f"Retry {rs.attempt_number}/{self.max_retries} for {url} "
                f"in ~{rs.next_action.sleep if rs.next_action else 0:.1f}s..."
            ),
        )
        async with self._semaphore:
            try:
                async for attempt in policy.build_async_retrying():
                    with attempt:
                        # 공유 클라이언트 재사용 (attempt마다 새 연결 생성 금지)
                        return await self._fetch_and_parse_page(client, url)
            except (httpx.ConnectError, httpx.TimeoutException) as e:
                # 재시도 소진: 기존과 동일하게 None 반환
                logger.error(f"Failed to fetch {url} after {self.max_retries} retries: {e}")
                return None
            except RetryError:
                # reraise=True이므로 통상 도달하지 않지만 안전장치로 None 반환
                logger.error(f"Failed to fetch {url} after {self.max_retries} retries")
                return None
            except Exception as e:
                # 비재시도 예외: 즉시 None 반환
                logger.error(f"Non-retryable error for {url}: {e}")
                return None
        return None

    async def _parse_sitemap(
        self, sitemap_url: str, client: httpx.AsyncClient
    ) -> list[str]:
        """사이트맵 XML에서 <loc> 태그의 URL 목록 추출 (공유 클라이언트 사용)"""
        response = await client.get(sitemap_url)
        response.raise_for_status()

        soup = BeautifulSoup(response.content, "xml")
        urls = [loc.text.strip() for loc in soup.find_all("loc")]
        logger.info(f"Found {len(urls)} URLs in sitemap {sitemap_url}")
        return urls

    async def _fetch_and_parse_page(self, client: httpx.AsyncClient, url: str) -> StandardDocument:
        """단일 HTML 페이지에서 본문 텍스트 추출"""
        response = await client.get(url)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "lxml")

        # 1. 불필요한 태그 제거 (스크립트, 스타일, 네비게이션 등)
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()

        # 2. 본문으로 추정되는 태그 찾기 (article -> main -> body 순)
        body = soup.find("article") or soup.find("main") or soup.find("body")

        # 3. 텍스트 추출 및 정제
        text = body.get_text(separator="\n").strip() if body else ""
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        cleaned_text = "\n".join(lines)

        title = soup.title.string if soup.title else url

        return StandardDocument(
            content=cleaned_text,
            source_url=url,
            metadata={
                "title": title,
                "type": "web_page"
            }
        )
