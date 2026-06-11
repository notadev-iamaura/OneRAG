"""
Notion API 클라이언트

Notion 공식 API를 활용한 데이터 조회 모듈
기존 Playwright 크롤링의 데이터 정합성 문제를 해결하기 위해 도입

주요 기능:
- Database Query: 데이터베이스 내 모든 페이지 조회 (자동 페이지네이션)
- Page Retrieve: 단일 페이지 상세 정보 조회
- Block Children: 페이지 내 콘텐츠 블록 조회
- Rich Text 변환: Notion 포맷 → Plain Text 변환
"""

import os
from dataclasses import dataclass, field
from typing import Any

import httpx
from tenacity import RetryCallState, RetryError
from tenacity.wait import wait_base

from app.lib.logger import get_logger
from app.lib.retry import (
    DEFAULT_BACKOFF_JITTER_S,
    BackoffStrategy,
    RetryPolicy,
    build_backoff_wait,
)

logger = get_logger(__name__)


# ============================================================================
# 예외 클래스 정의
# ============================================================================


class NotionAPIError(Exception):
    """Notion API 기본 에러"""

    pass


class NotionRateLimitError(NotionAPIError):
    """API Rate Limit 초과 에러"""

    pass


class NotionAuthError(NotionAPIError):
    """인증 실패 에러"""

    pass


class NotionNotFoundError(NotionAPIError):
    """리소스를 찾을 수 없음"""

    pass


# ============================================================================
# 재시도 백오프 wait 전략 (tenacity)
# ============================================================================


class _NotionBackoffWait(wait_base):
    """
    Notion API 재시도 대기 전략 (발생 예외 타입별 분기)

    예외 타입에 따라 다른 백오프를 적용하는 분기는 ``RetryPolicy`` 필드로
    표현할 수 없는 진짜 커스텀 로직이므로 이 클래스에 유지하고,
    개별 wait 구성(EXPONENTIAL/FIXED)은 공용 ``build_backoff_wait``에 위임합니다.

    동작 보존:
    - ``NotionRateLimitError``(429): 지수 백오프 ``BASE_DELAY * 2^(attempt-1)`` + jitter.
      tenacity의 ``attempt_number``는 1부터 시작하므로 기존 ``BASE_DELAY * 2^attempt``
      (attempt 0부터) 시퀀스(1, 2, 4, 8, 16초)와 base가 정확히 일치합니다.
    - ``httpx.TimeoutException``: 고정 ``BASE_DELAY``(1.0초) + jitter.

    jitter는 thundering herd(동시 재시도 폭주) 완화를 위해 추가했습니다.
    """

    def __init__(self, base_delay: float, jitter: float = 0.0) -> None:
        # 지수 백오프: initial=base_delay, 상한 없음(기존 동작 유지) — 429 경로용
        self._exponential = build_backoff_wait(
            BackoffStrategy.EXPONENTIAL,
            initial_delay_s=base_delay,
            max_delay_s=float("inf"),
            jitter_s=jitter,
        )
        # 고정 백오프: timeout 경로용
        self._fixed = build_backoff_wait(
            BackoffStrategy.FIXED,
            initial_delay_s=base_delay,
            jitter_s=jitter,
        )

    def __call__(self, retry_state: RetryCallState) -> float:
        exc = retry_state.outcome.exception() if retry_state.outcome else None
        if isinstance(exc, httpx.TimeoutException):
            return self._fixed(retry_state)
        # NotionRateLimitError(429) 및 그 외 재시도 대상은 지수 백오프
        return self._exponential(retry_state)


# ============================================================================
# 데이터 클래스 정의
# ============================================================================


@dataclass
class NotionPage:
    """
    Notion 페이지 데이터 클래스

    API 응답에서 추출한 페이지 정보를 담는 컨테이너
    """

    id: str  # 페이지 UUID
    title: str  # 페이지 제목
    properties: dict[str, Any] = field(default_factory=dict)  # 속성 딕셔너리
    content: str = ""  # 본문 텍스트 (블록에서 추출)
    url: str = ""  # Notion 페이지 URL
    created_time: str = ""  # 생성 시간
    last_edited_time: str = ""  # 수정 시간


@dataclass
class NotionDatabaseResult:
    """
    데이터베이스 쿼리 결과

    페이지네이션 처리된 전체 결과를 담는 컨테이너
    """

    pages: list[NotionPage] = field(default_factory=list)
    total_count: int = 0
    database_id: str = ""
    query_time_seconds: float = 0.0


# ============================================================================
# Notion API 클라이언트
# ============================================================================


class NotionAPIClient:
    """
    Notion 공식 API 클라이언트

    주요 기능:
    - Database Query: 데이터베이스 내 모든 페이지 조회 (자동 페이지네이션)
    - Page Retrieve: 단일 페이지 상세 정보 조회
    - Block Children: 페이지 내 콘텐츠 블록 조회
    - 지수 백오프: Rate Limit 대응

    사용 예시:
        >>> client = NotionAPIClient(api_key="ntn_xxx")
        >>> result = await client.query_database("db-id")
        >>> for page in result.pages:
        ...     print(page.title)
    """

    # Notion API 상수
    BASE_URL = "https://api.notion.com/v1"
    API_VERSION = "2022-06-28"
    MAX_PAGE_SIZE = 100  # Notion API 최대 페이지 크기
    DEFAULT_TIMEOUT = 30.0  # 요청 타임아웃 (초)

    # 지수 백오프 설정
    MAX_RETRIES = 5
    BASE_DELAY = 1.0  # 초기 대기 시간 (초)
    # 재시도 폭주 완화용 무작위 지연 범위 (공용 상수로 통일, [0, JITTER) 추가)
    BACKOFF_JITTER = DEFAULT_BACKOFF_JITTER_S

    def __init__(self, api_key: str | None = None):
        """
        Notion API 클라이언트 초기화

        Args:
            api_key: Notion Integration API 키 (없으면 환경변수에서 로드)

        Raises:
            ValueError: API 키가 없는 경우
        """
        self.api_key = api_key or os.getenv("NOTION_API_KEY")
        if not self.api_key:
            raise ValueError("NOTION_API_KEY가 설정되지 않았습니다.")

        # HTTP 클라이언트 헤더
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Notion-Version": self.API_VERSION,
            "Content-Type": "application/json",
        }

        # httpx 비동기 클라이언트
        self._client: httpx.AsyncClient | None = None

        # 재시도 정책을 요청마다 재생성하지 않도록 인스턴스 레벨로 1회 구성.
        # frozen RetryPolicy와 tenacity wait 객체(_NotionBackoffWait 내부 포함)는
        # 상태가 없어(stateless) 재사용해도 안전하며, 상태를 가지는 AsyncRetrying은
        # _request_with_backoff에서 호출마다 build_async_retrying()으로 새로 만듭니다.
        self._retry_policy = RetryPolicy(
            retry_exceptions=(NotionRateLimitError, httpx.TimeoutException),
            max_attempts=self.MAX_RETRIES,
            reraise=False,  # 소진 시 RetryError로 감싸 _request_with_backoff에서 통일 변환
            wait_override=_NotionBackoffWait(
                base_delay=self.BASE_DELAY, jitter=self.BACKOFF_JITTER
            ),
        )

        logger.info("✅ NotionAPIClient 초기화 완료")

    async def _get_client(self) -> httpx.AsyncClient:
        """
        httpx 클라이언트 지연 초기화 (Lazy Initialization)

        Returns:
            httpx.AsyncClient 인스턴스
        """
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(headers=self.headers, timeout=self.DEFAULT_TIMEOUT)
        return self._client

    async def close(self) -> None:
        """HTTP 클라이언트 종료"""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            logger.debug("🔌 NotionAPIClient HTTP 클라이언트 종료")

    async def _request_with_backoff(
        self, method: str, url: str, json_data: dict | None = None
    ) -> dict:
        """
        지수 백오프를 적용한 API 요청

        Rate Limit(429) 발생 시 지수적으로 대기 시간을 늘려 재시도

        Args:
            method: HTTP 메서드 (GET, POST 등)
            url: 요청 URL
            json_data: POST 요청 시 JSON 바디

        Returns:
            API 응답 JSON

        Raises:
            NotionRateLimitError: 최대 재시도 횟수 초과
            NotionAuthError: 인증 실패
            NotionNotFoundError: 리소스 없음
            NotionAPIError: 기타 API 에러
        """
        client = await self._get_client()

        async def _do_request() -> dict:
            """
            단일 요청 수행 + 응답코드/예외 분기

            동작 보존:
            - 200: JSON 반환
            - 429: ``NotionRateLimitError`` raise → tenacity가 지수 백오프 재시도
            - TimeoutException: 그대로 전파 → tenacity가 고정 백오프 재시도
            - 401/404/기타 status: 해당 최종 예외 raise (재시도 대상 아님, 즉시 전파)
            - RequestError(타임아웃 외): ``NotionAPIError`` raise (재시도 대상 아님)
            """
            try:
                if method.upper() == "GET":
                    response = await client.get(url)
                elif method.upper() == "POST":
                    response = await client.post(url, json=json_data or {})
                elif method.upper() == "PATCH":
                    response = await client.patch(url, json=json_data or {})
                elif method.upper() == "DELETE":
                    response = await client.delete(url)
                else:
                    raise ValueError(f"지원하지 않는 HTTP 메서드: {method}")
            except httpx.TimeoutException:
                # 고정 백오프 재시도를 위해 그대로 전파 (tenacity retry 대상)
                logger.warning("⚠️ 요청 타임아웃, 재시도 중")
                raise
            except httpx.RequestError as e:
                # 타임아웃 외 연결 오류: 재시도하지 않고 즉시 전파
                logger.error(f"❌ HTTP 요청 실패: {e}")
                raise NotionAPIError(f"HTTP 요청 실패: {e}") from e

            # 응답 상태 코드 처리
            if response.status_code == 200:
                return response.json()
            elif response.status_code == 429:
                # Rate Limit: 지수 백오프 재시도를 위해 예외 raise
                logger.warning("⚠️ Rate Limit 발생, 재시도 예정")
                raise NotionRateLimitError("Notion API Rate Limit (429)")
            elif response.status_code == 401:
                raise NotionAuthError("Notion API 인증 실패: API 키를 확인하세요")
            elif response.status_code == 404:
                raise NotionNotFoundError(f"리소스를 찾을 수 없음: {url}")
            else:
                error_body = response.text
                raise NotionAPIError(
                    f"Notion API 에러 (status={response.status_code}): {error_body}"
                )

        # RetryPolicy 재시도: 429(NotionRateLimitError)와 timeout만 재시도 대상.
        # 그 외 예외(Auth/NotFound/API/Value)는 retry 조건에 걸리지 않아 즉시 전파됩니다.
        # 예외 타입별 백오프 분기는 wait_override로 커스텀 wait를 주입해 표현합니다.
        # 정책 자체(__init__에서 1회 구성)는 stateless이므로 재사용하고,
        # 상태를 가지는 AsyncRetrying만 요청마다 새로 생성합니다.
        retrying = self._retry_policy.build_async_retrying()
        try:
            async for attempt in retrying:
                with attempt:
                    return await _do_request()
        except RetryError:
            # 최대 재시도 횟수 초과 (429/timeout 모두 동일하게 변환 — 기존 동작 보존)
            raise NotionRateLimitError(
                f"최대 재시도 횟수({self.MAX_RETRIES}) 초과"
            ) from None
        # 도달 불가 (AsyncRetrying은 항상 반환 또는 예외) — 타입 체커 안전장치
        raise NotionRateLimitError(f"최대 재시도 횟수({self.MAX_RETRIES}) 초과")

    # ========================================================================
    # 핵심 API 메서드
    # ========================================================================

    async def query_database(
        self,
        database_id: str,
        filter_conditions: dict | None = None,
        sorts: list | None = None,
        page_size: int = 100,
    ) -> NotionDatabaseResult:
        """
        데이터베이스 내 모든 페이지 조회 (자동 페이지네이션)

        Notion API의 100개 제한을 자동으로 처리하여
        데이터베이스 내 모든 페이지를 가져옵니다.

        Args:
            database_id: Notion 데이터베이스 ID
            filter_conditions: 필터 조건 (선택)
            sorts: 정렬 조건 (선택)
            page_size: 페이지당 결과 수 (최대 100)

        Returns:
            NotionDatabaseResult: 전체 페이지 목록

        사용 예시:
            >>> result = await client.query_database("e0b54685...")
            >>> print(f"총 {result.total_count}개 페이지 조회")
        """
        import time

        start_time = time.time()

        # 페이지 크기 제한
        page_size = min(page_size, self.MAX_PAGE_SIZE)

        url = f"{self.BASE_URL}/databases/{database_id}/query"
        all_pages: list[NotionPage] = []
        start_cursor: str | None = None
        page_num = 1

        logger.info(f"🔍 Notion Database 쿼리 시작: {database_id}")

        while True:
            # 요청 바디 구성
            payload: dict[str, Any] = {"page_size": page_size}
            if start_cursor:
                payload["start_cursor"] = start_cursor
            if filter_conditions:
                payload["filter"] = filter_conditions
            if sorts:
                payload["sorts"] = sorts

            # API 요청
            response = await self._request_with_backoff("POST", url, payload)

            # 결과 파싱
            results = response.get("results", [])
            for item in results:
                page = self._parse_page(item)
                all_pages.append(page)

            logger.debug(
                f"  페이지 {page_num}: {len(results)}개 조회 " f"(누적: {len(all_pages)}개)"
            )

            # 다음 페이지 확인
            if response.get("has_more"):
                start_cursor = response.get("next_cursor")
                page_num += 1
            else:
                break

        elapsed = time.time() - start_time
        logger.info(f"✅ Database 쿼리 완료: {len(all_pages)}개 페이지, " f"{elapsed:.2f}초 소요")

        return NotionDatabaseResult(
            pages=all_pages,
            total_count=len(all_pages),
            database_id=database_id,
            query_time_seconds=elapsed,
        )

    async def get_page(self, page_id: str) -> NotionPage:
        """
        단일 페이지 상세 정보 조회

        Args:
            page_id: Notion 페이지 ID

        Returns:
            NotionPage 객체
        """
        url = f"{self.BASE_URL}/pages/{page_id}"
        response = await self._request_with_backoff("GET", url)
        return self._parse_page(response)

    async def get_block_children(self, block_id: str, page_size: int = 100) -> list[dict]:
        """
        블록의 자식 블록들 조회 (페이지 본문 내용)

        Args:
            block_id: 블록 ID (일반적으로 페이지 ID)
            page_size: 페이지당 결과 수

        Returns:
            블록 목록
        """
        url = f"{self.BASE_URL}/blocks/{block_id}/children"
        all_blocks: list[dict] = []
        start_cursor: str | None = None

        while True:
            # URL에 쿼리 파라미터 추가
            request_url = f"{url}?page_size={page_size}"
            if start_cursor:
                request_url += f"&start_cursor={start_cursor}"

            response = await self._request_with_backoff("GET", request_url)
            results = response.get("results", [])
            all_blocks.extend(results)

            if response.get("has_more"):
                start_cursor = response.get("next_cursor")
            else:
                break

        return all_blocks

    async def append_blocks(self, block_id: str, children: list[dict]) -> dict:
        """
        블록에 자식 블록들 추가 (페이지 본문에 콘텐츠 추가)

        Args:
            block_id: 블록 ID (일반적으로 페이지 ID)
            children: 추가할 블록 리스트

        Returns:
            API 응답

        사용 예시:
            >>> blocks = [
            ...     {"type": "heading_2", "heading_2": {"rich_text": [{"text": {"content": "제목"}}]}},
            ...     {"type": "paragraph", "paragraph": {"rich_text": [{"text": {"content": "내용"}}]}}
            ... ]
            >>> await client.append_blocks(page_id, blocks)
        """
        url = f"{self.BASE_URL}/blocks/{block_id}/children"
        payload = {"children": children}

        response = await self._request_with_backoff("PATCH", url, payload)
        logger.info(f"✅ {len(children)}개 블록 추가 완료: {block_id[:8]}...")
        return response

    async def delete_block(self, block_id: str) -> dict:
        """
        블록 삭제

        Args:
            block_id: 삭제할 블록 ID

        Returns:
            API 응답
        """
        url = f"{self.BASE_URL}/blocks/{block_id}"
        response = await self._request_with_backoff("DELETE", url)
        logger.debug(f"🗑️ 블록 삭제: {block_id[:8]}...")
        return response

    async def create_page(
        self,
        parent_id: str,
        title: str,
        children: list[dict] | None = None,
        parent_type: str = "page_id",
    ) -> dict:
        """
        새 페이지 생성

        Args:
            parent_id: 부모 페이지 또는 데이터베이스 ID
            title: 페이지 제목
            children: 페이지 본문 블록들 (선택)
            parent_type: 부모 타입 ("page_id" 또는 "database_id")

        Returns:
            생성된 페이지 정보

        사용 예시:
            >>> page = await client.create_page(
            ...     parent_id="60eab216-...",
            ...     title="새 페이지",
            ...     children=[
            ...         {"type": "paragraph", "paragraph": {"rich_text": [{"text": {"content": "내용"}}]}}
            ...     ]
            ... )
        """
        url = f"{self.BASE_URL}/pages"

        payload: dict[str, Any] = {
            "parent": {parent_type: parent_id},
            "properties": {"title": {"title": [{"type": "text", "text": {"content": title}}]}},
        }

        if children:
            payload["children"] = children

        response = await self._request_with_backoff("POST", url, payload)
        logger.info(f"✅ 페이지 생성 완료: {title} (ID: {response.get('id', '')[:8]}...)")
        return response

    async def get_page_content(self, page_id: str) -> str:
        """
        페이지 전체 콘텐츠를 텍스트로 변환

        페이지의 모든 블록을 조회하고 Plain Text로 변환합니다.

        Args:
            page_id: Notion 페이지 ID

        Returns:
            페이지 본문 텍스트
        """
        blocks = await self.get_block_children(page_id)
        return self._blocks_to_text(blocks)

    async def find_databases_in_page(self, page_id: str) -> list[dict]:
        """
        페이지 내에 포함된 데이터베이스(Inline Database) 찾기

        Args:
            page_id: Notion 페이지 ID

        Returns:
            데이터베이스 정보 리스트 [{"id": "...", "type": "...", "title": "..."}]
        """
        blocks = await self.get_block_children(page_id)
        databases = []

        for block in blocks:
            block_type = block.get("type", "")

            # Inline Database 또는 Linked Database
            if block_type in ("child_database", "linked_database"):
                db_info = {"id": block.get("id", ""), "type": block_type, "title": ""}

                # child_database인 경우 제목 추출
                if block_type == "child_database":
                    db_data = block.get("child_database", {})
                    db_info["title"] = db_data.get("title", "")
                elif block_type == "linked_database":
                    # linked_database는 다른 구조
                    db_data = block.get("linked_database", {})
                    db_info["database_id"] = db_data.get("database_id", "")

                databases.append(db_info)
                logger.debug(f"📊 데이터베이스 발견: {db_info}")

        return databases

    async def search_databases(self, query: str = "", page_size: int = 100) -> list[dict]:
        """
        Integration에 공유된 모든 데이터베이스 검색

        Args:
            query: 검색어 (빈 문자열이면 전체 검색)
            page_size: 페이지당 결과 수

        Returns:
            데이터베이스 목록
        """
        url = f"{self.BASE_URL}/search"
        all_databases: list[dict] = []
        start_cursor: str | None = None

        logger.info(f"🔍 데이터베이스 검색 시작 (query='{query}')")

        while True:
            payload: dict[str, Any] = {
                "filter": {"property": "object", "value": "database"},
                "page_size": min(page_size, self.MAX_PAGE_SIZE),
            }
            if query:
                payload["query"] = query
            if start_cursor:
                payload["start_cursor"] = start_cursor

            response = await self._request_with_backoff("POST", url, payload)
            results = response.get("results", [])

            for item in results:
                db_info = {
                    "id": item.get("id", ""),
                    "title": self._extract_database_title(item),
                    "url": item.get("url", ""),
                    "created_time": item.get("created_time", ""),
                }
                all_databases.append(db_info)

            if response.get("has_more"):
                start_cursor = response.get("next_cursor")
            else:
                break

        logger.info(f"✅ {len(all_databases)}개 데이터베이스 발견")
        return all_databases

    def _extract_database_title(self, data: dict) -> str:
        """
        데이터베이스 응답에서 제목 추출

        Args:
            data: Notion API 데이터베이스 응답

        Returns:
            데이터베이스 제목
        """
        title_array = data.get("title", [])
        return self._rich_text_to_plain(title_array)

    # ========================================================================
    # 파싱 유틸리티
    # ========================================================================

    def _parse_page(self, data: dict) -> NotionPage:
        """
        API 응답에서 NotionPage 객체 생성

        Args:
            data: Notion API 페이지 응답

        Returns:
            NotionPage 객체
        """
        page_id = data.get("id", "")
        properties = data.get("properties", {})

        # 제목 추출 (title 타입 속성 찾기)
        title = self._extract_title(properties)

        # URL 생성
        url = data.get("url", "")

        return NotionPage(
            id=page_id,
            title=title,
            properties=self._parse_properties(properties),
            url=url,
            created_time=data.get("created_time", ""),
            last_edited_time=data.get("last_edited_time", ""),
        )

    def _extract_title(self, properties: dict) -> str:
        """
        속성에서 제목 추출

        Args:
            properties: 페이지 속성 딕셔너리

        Returns:
            제목 문자열
        """
        for _prop_name, prop_data in properties.items():
            if prop_data.get("type") == "title":
                title_array = prop_data.get("title", [])
                if title_array:
                    return self._rich_text_to_plain(title_array)
        return ""

    def _parse_properties(self, properties: dict) -> dict[str, Any]:
        """
        Notion 속성을 Python 딕셔너리로 변환

        Args:
            properties: Notion 속성 원본

        Returns:
            변환된 속성 딕셔너리
        """
        result: dict[str, Any] = {}

        for prop_name, prop_data in properties.items():
            prop_type = prop_data.get("type", "")
            value = self._extract_property_value(prop_data, prop_type)
            result[prop_name] = value

        return result

    def _extract_property_value(self, prop_data: dict, prop_type: str) -> Any:
        """
        속성 타입별 값 추출

        Args:
            prop_data: 속성 데이터
            prop_type: 속성 타입

        Returns:
            추출된 값
        """
        if prop_type == "title":
            return self._rich_text_to_plain(prop_data.get("title", []))

        elif prop_type == "rich_text":
            return self._rich_text_to_plain(prop_data.get("rich_text", []))

        elif prop_type == "select":
            select_data = prop_data.get("select")
            return select_data.get("name", "") if select_data else ""

        elif prop_type == "multi_select":
            return [item.get("name", "") for item in prop_data.get("multi_select", [])]

        elif prop_type == "number":
            return prop_data.get("number")

        elif prop_type == "checkbox":
            return prop_data.get("checkbox", False)

        elif prop_type == "date":
            date_data = prop_data.get("date")
            return date_data.get("start", "") if date_data else ""

        elif prop_type == "url":
            return prop_data.get("url", "")

        elif prop_type == "email":
            return prop_data.get("email", "")

        elif prop_type == "phone_number":
            return prop_data.get("phone_number", "")

        elif prop_type == "files":
            files = prop_data.get("files", [])
            return [f.get("name", "") for f in files]

        elif prop_type == "relation":
            relations = prop_data.get("relation", [])
            return [r.get("id", "") for r in relations]

        elif prop_type == "formula":
            formula = prop_data.get("formula", {})
            formula_type = formula.get("type", "")
            return formula.get(formula_type)

        elif prop_type == "rollup":
            rollup = prop_data.get("rollup", {})
            rollup_type = rollup.get("type", "")
            return rollup.get(rollup_type)

        elif prop_type == "people":
            people = prop_data.get("people", [])
            return [p.get("name", "") for p in people]

        elif prop_type == "created_time":
            return prop_data.get("created_time", "")

        elif prop_type == "last_edited_time":
            return prop_data.get("last_edited_time", "")

        elif prop_type == "created_by":
            created_by = prop_data.get("created_by", {})
            return created_by.get("name", "")

        elif prop_type == "last_edited_by":
            last_edited_by = prop_data.get("last_edited_by", {})
            return last_edited_by.get("name", "")

        elif prop_type == "status":
            status_data = prop_data.get("status")
            return status_data.get("name", "") if status_data else ""

        else:
            # 알 수 없는 타입은 원본 반환
            return prop_data.get(prop_type)

    def _rich_text_to_plain(self, rich_text_array: list) -> str:
        """
        Rich Text 배열을 Plain Text로 변환

        Args:
            rich_text_array: Notion Rich Text 배열

        Returns:
            Plain Text 문자열
        """
        texts = []
        for item in rich_text_array:
            if item.get("type") == "text":
                texts.append(item.get("text", {}).get("content", ""))
            elif item.get("type") == "mention":
                # 멘션은 plain_text로 처리
                texts.append(item.get("plain_text", ""))
            elif item.get("type") == "equation":
                texts.append(item.get("equation", {}).get("expression", ""))
        return "".join(texts)

    def _blocks_to_text(self, blocks: list[dict]) -> str:
        """
        블록 목록을 텍스트로 변환

        Args:
            blocks: Notion 블록 목록

        Returns:
            변환된 텍스트
        """
        lines: list[str] = []

        for block in blocks:
            block_type = block.get("type", "")
            block_data = block.get(block_type, {})

            text = ""

            # 텍스트 기반 블록
            if block_type in (
                "paragraph",
                "heading_1",
                "heading_2",
                "heading_3",
                "bulleted_list_item",
                "numbered_list_item",
                "quote",
                "callout",
                "toggle",
            ):
                rich_text = block_data.get("rich_text", [])
                text = self._rich_text_to_plain(rich_text)

                # 헤딩 마크다운 스타일
                if block_type == "heading_1":
                    text = f"# {text}"
                elif block_type == "heading_2":
                    text = f"## {text}"
                elif block_type == "heading_3":
                    text = f"### {text}"
                elif block_type in ("bulleted_list_item", "numbered_list_item"):
                    text = f"• {text}"
                elif block_type == "quote":
                    text = f"> {text}"

            # 코드 블록
            elif block_type == "code":
                rich_text = block_data.get("rich_text", [])
                code_text = self._rich_text_to_plain(rich_text)
                language = block_data.get("language", "")
                text = f"```{language}\n{code_text}\n```"

            # To-Do
            elif block_type == "to_do":
                rich_text = block_data.get("rich_text", [])
                checked = block_data.get("checked", False)
                checkbox = "[x]" if checked else "[ ]"
                text = f"{checkbox} {self._rich_text_to_plain(rich_text)}"

            # 구분선
            elif block_type == "divider":
                text = "---"

            # 테이블 (간단 처리)
            elif block_type == "table_row":
                cells = block_data.get("cells", [])
                row_texts = [self._rich_text_to_plain(cell) for cell in cells]
                text = " | ".join(row_texts)

            if text:
                lines.append(text)

        return "\n".join(lines)


# ============================================================================
# 테스트/검증용 유틸리티 함수
# ============================================================================


async def test_notion_connection(
    api_key: str | None = None, database_id: str | None = None
) -> dict:
    """
    Notion API 연결 테스트

    Args:
        api_key: API 키 (없으면 환경변수 사용)
        database_id: 테스트할 데이터베이스 ID

    Returns:
        테스트 결과 딕셔너리
    """
    result = {"success": False, "message": "", "pages_count": 0, "sample_titles": []}

    try:
        client = NotionAPIClient(api_key=api_key)

        if database_id:
            db_result = await client.query_database(database_id)
            result["success"] = True
            result["message"] = "연결 성공"
            result["pages_count"] = db_result.total_count
            result["sample_titles"] = [p.title for p in db_result.pages[:5]]
        else:
            result["success"] = True
            result["message"] = "클라이언트 초기화 성공 (DB ID 없음)"

        await client.close()

    except NotionAuthError as e:
        result["message"] = f"인증 실패: {e}"
    except NotionNotFoundError as e:
        result["message"] = f"데이터베이스 없음: {e}"
    except NotionAPIError as e:
        result["message"] = f"API 에러: {e}"
    except Exception as e:
        result["message"] = f"예외 발생: {e}"

    return result
