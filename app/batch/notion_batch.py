"""
Notion API 기반 배치 프로세서
==============================
기능: Notion API를 통해 데이터베이스에서 데이터를 추출하고 Weaviate에 업로드
용도: 일배치 데이터 갱신 (Playwright 크롤링 대체)

파이프라인:
1. Notion API로 데이터베이스 조회
2. 각 페이지 콘텐츠 추출
3. 텍스트 청킹 (RecursiveCharacterTextSplitter)
4. Weaviate 업서트 (기존 데이터 삭제 후 업로드)

참고: 비Notion(외부 웹) 소스는 external_crawler.py에서 처리
"""

import asyncio
import os
from dataclasses import dataclass, field

import httpx
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.batch.notion_client import NotionAPIClient, NotionPage
from app.lib.config_loader import load_config
from app.lib.logger import get_logger

logger = get_logger(__name__)


# ============================================================================
# 설정 상수
# ============================================================================

# 카테고리/DB 매핑은 설정에서 로드됩니다.
# - Blank 시스템에서는 특정 도메인의 카테고리(DB ID)를 코드에 하드코딩하지 않습니다.
# - 권장 설정 위치: app/config/features/domain.yaml → domain.batch.categories

# 청킹 설정
DEFAULT_CHUNK_SIZE = 1400
DEFAULT_CHUNK_OVERLAP = 200


# ============================================================================
# 데이터 클래스
# ============================================================================


@dataclass
class ChunkData:
    """청크 데이터"""

    content: str
    source_file: str
    chunk_index: int
    page_title: str
    page_id: str
    metadata: dict = field(default_factory=dict)


@dataclass
class BatchResult:
    """배치 처리 결과"""

    category: str
    total_pages: int
    total_chunks: int
    uploaded_chunks: int
    deleted_chunks: int
    success: bool
    error_message: str = ""
    processing_time_seconds: float = 0.0


@dataclass
class NotionBatchConfig:
    """배치 프로세서 설정"""

    chunk_size: int = DEFAULT_CHUNK_SIZE
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP
    # 기본값: 환경변수에서 로드, 없으면 프로덕션 URL
    weaviate_url: str = field(
        default_factory=lambda: os.getenv(
            "WEAVIATE_URL", "https://weaviate-production-70aa.up.railway.app"
        )
    )
    notion_api_key: str = field(default_factory=lambda: os.getenv("NOTION_API_KEY", ""))
    # 처리할 카테고리 식별자 목록 (예: ["domain_1", "domain_2"])
    categories: list[str] = field(default_factory=list)
    # 카테고리 → Notion Database ID 매핑
    databases: dict[str, str] = field(default_factory=dict)
    # 카테고리 → source_file 매핑 (Weaviate 저장용)
    source_file_names: dict[str, str] = field(default_factory=dict)
    dry_run: bool = False  # True면 Weaviate 업로드 건너뜀


# ============================================================================
# Notion 배치 프로세서
# ============================================================================


class NotionBatchProcessor:
    """
    Notion API 기반 일배치 프로세서

    주요 기능:
    - Notion 데이터베이스에서 페이지 조회
    - 페이지 콘텐츠를 텍스트로 추출
    - 텍스트 청킹 (RecursiveCharacterTextSplitter)
    - Weaviate 업서트 (기존 데이터 삭제 → 새 데이터 업로드)

    사용 예시:
        >>> processor = NotionBatchProcessor()
        >>> results = await processor.run_batch()
        >>> for result in results:
        ...     print(f"{result.category}: {result.total_chunks}개 청크")
    """

    def __init__(self, config: NotionBatchConfig | None = None):
        """
        프로세서 초기화

        Args:
            config: 배치 설정 (None이면 환경변수에서 로드)
        """
        self.config = config or self._load_config_from_env()
        self.notion_client: NotionAPIClient | None = None
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.config.chunk_size,
            chunk_overlap=self.config.chunk_overlap,
            separators=["\n\n", "\n", ". ", " ", ""],
        )
        self._http_client: httpx.AsyncClient | None = None

        logger.info(
            "NotionBatchProcessor 초기화 완료",
            extra={
                "chunk_size": self.config.chunk_size,
                "categories": self.config.categories
            }
        )

    def _load_config_from_env(self) -> NotionBatchConfig:
        """
        환경변수 + 애플리케이션 설정에서 배치 설정 로드

        NOTE:
        - weaviate_url/notion_api_key/청킹 파라미터는 환경변수 우선
        - 카테고리/DB 매핑은 app/config/features/domain.yaml의 domain.batch.categories에서 로드
        """
        cfg = NotionBatchConfig(
            weaviate_url=os.getenv(
                "WEAVIATE_URL", "https://weaviate-production-70aa.up.railway.app"
            ),
            notion_api_key=os.getenv("NOTION_API_KEY", ""),
            chunk_size=int(os.getenv("CHUNK_SIZE", str(DEFAULT_CHUNK_SIZE))),
            chunk_overlap=int(os.getenv("CHUNK_OVERLAP", str(DEFAULT_CHUNK_OVERLAP))),
        )
        try:
            app_config = load_config(validate=False)
            categories_cfg = (
                app_config.get("domain", {}).get("batch", {}).get("categories", {}) or {}
            )

            if isinstance(categories_cfg, dict) and categories_cfg:
                cfg.categories = list(categories_cfg.keys())

                for category_key, cat in categories_cfg.items():
                    if not isinstance(cat, dict):
                        continue

                    db_id = str(cat.get("db_id") or "").strip()
                    if db_id:
                        cfg.databases[category_key] = db_id

                    source_file = str(cat.get("source_file") or "").strip()
                    cfg.source_file_names[category_key] = source_file or f"notion_{category_key}"

                logger.info(
                    "Notion 배치 카테고리 로드",
                    extra={
                        "category_count": len(cfg.categories),
                        "db_mapped_count": len(cfg.databases)
                    }
                )
            else:
                logger.warning(
                    "domain.batch.categories 설정이 비어있습니다. "
                    "Notion 배치를 사용하려면 domain.yaml에 카테고리/DB ID를 설정하세요."
                )

        except Exception as e:
            logger.warning(
                "Notion 배치 카테고리 설정 로드 실패. "
                "domain.yaml 설정을 확인하세요.",
                extra={
                    "error": str(e),
                    "error_type": type(e).__name__
                }
            )

        return cfg

    async def _get_http_client(self) -> httpx.AsyncClient:
        """HTTP 클라이언트 지연 초기화"""
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(timeout=60.0)
        return self._http_client

    async def close(self) -> None:
        """리소스 정리"""
        if self.notion_client:
            await self.notion_client.close()
        if self._http_client and not self._http_client.is_closed:
            await self._http_client.aclose()
        logger.debug("NotionBatchProcessor 리소스 정리 완료")

    # ========================================================================
    # 메인 배치 처리
    # ========================================================================

    async def run_batch(self, categories: list[str] | None = None) -> list[BatchResult]:
        """
        전체 배치 실행

        Args:
            categories: 처리할 카테고리 목록 (None이면 설정값 사용)

        Returns:
            카테고리별 배치 결과 리스트
        """
        import time

        start_time = time.time()
        categories = categories or self.config.categories
        results: list[BatchResult] = []

        # 환경변수에서 weaviate_url/notion_api_key 다시 로드 (런타임 환경변수 지원)
        if not self.config.weaviate_url:
            self.config.weaviate_url = os.getenv(
                "WEAVIATE_URL", "https://weaviate-production-70aa.up.railway.app"
            )
        if not self.config.notion_api_key:
            self.config.notion_api_key = os.getenv("NOTION_API_KEY", "")

        logger.info("=" * 60)
        logger.info("Notion API 배치 처리 시작")
        logger.info(
            "대상 카테고리 확인",
            extra={"categories": categories}
        )
        logger.info(
            "Weaviate URL 확인",
            extra={"weaviate_url": self.config.weaviate_url[:50] + "..."}
        )
        logger.info("=" * 60)

        # Notion 클라이언트 초기화
        self.notion_client = NotionAPIClient(api_key=self.config.notion_api_key)

        try:
            for category in categories:
                logger.info(f"\n{'─' * 40}")
                logger.info(f"📁 [{category.upper()}] 처리 시작")
                logger.info(f"{'─' * 40}")

                result = await self.process_category(category)
                results.append(result)

                if result.success:
                    logger.info(
                        "카테고리 처리 완료",
                        extra={
                            "category": category,
                            "total_pages": result.total_pages,
                            "uploaded_chunks": result.uploaded_chunks
                        }
                    )
                else:
                    logger.error(
                        "카테고리 처리 실패",
                        extra={
                            "category": category,
                            "error_message": result.error_message
                        }
                    )

        except Exception as e:
            logger.error(
                "배치 처리 중 예외 발생",
                extra={
                    "error": str(e),
                    "error_type": type(e).__name__
                },
                exc_info=True
            )
            raise
        finally:
            await self.close()

        total_time = time.time() - start_time
        total_chunks = sum(r.uploaded_chunks for r in results)

        logger.info("\n" + "=" * 60)
        logger.info("Notion API 배치 처리 완료")
        logger.info(
            "배치 처리 결과",
            extra={
                "total_chunks": total_chunks,
                "total_time_seconds": total_time
            }
        )
        logger.info("=" * 60)

        return results

    async def process_category(self, category: str) -> BatchResult:
        """
        단일 카테고리 처리

        Args:
            category: 카테고리 식별자 (설정 파일 키)

        Returns:
            BatchResult: 처리 결과
        """
        import time

        start_time = time.time()

        try:
            # 1. 데이터베이스 ID 확인
            database_id = self.config.databases.get(category)
            if not database_id:
                return BatchResult(
                    category=category,
                    total_pages=0,
                    total_chunks=0,
                    uploaded_chunks=0,
                    deleted_chunks=0,
                    success=False,
                    error_message=f"Notion DB ID가 설정되지 않았습니다: {category}",
                )

            source_file = self.config.source_file_names.get(category) or f"notion_{category}"

            # 2. Notion에서 페이지 목록 조회
            logger.info(
                "Notion DB 조회 중",
                extra={"database_id_prefix": database_id[:8]}
            )
            db_result = await self.notion_client.query_database(database_id)

            if not db_result.pages:
                logger.warning(
                    "페이지가 없습니다",
                    extra={"category": category}
                )
                return BatchResult(
                    category=category,
                    total_pages=0,
                    total_chunks=0,
                    uploaded_chunks=0,
                    deleted_chunks=0,
                    success=True,
                )

            logger.info(
                "페이지 발견",
                extra={"page_count": db_result.total_count}
            )

            # 3. 각 페이지 콘텐츠 추출 및 청킹
            all_chunks: list[ChunkData] = []
            for i, page in enumerate(db_result.pages):
                logger.debug(f"  [{i + 1}/{db_result.total_count}] {page.title}")

                chunks = await self._process_page(page, source_file)
                all_chunks.extend(chunks)

            logger.info(
                "청크 생성 완료",
                extra={"total_chunks": len(all_chunks)}
            )

            # 4. Weaviate 업서트
            if self.config.dry_run:
                logger.info("Dry-run 모드: Weaviate 업로드 건너뜀")
                deleted_count = 0
                uploaded_count = len(all_chunks)
            else:
                deleted_count = await self._delete_existing_data(source_file)
                uploaded_count = await self._upload_chunks(all_chunks)

            elapsed = time.time() - start_time

            return BatchResult(
                category=category,
                total_pages=db_result.total_count,
                total_chunks=len(all_chunks),
                uploaded_chunks=uploaded_count,
                deleted_chunks=deleted_count,
                success=True,
                processing_time_seconds=elapsed,
            )

        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(
                "카테고리 처리 실패",
                extra={
                    "category": category,
                    "error": str(e),
                    "error_type": type(e).__name__
                },
                exc_info=True
            )
            return BatchResult(
                category=category,
                total_pages=0,
                total_chunks=0,
                uploaded_chunks=0,
                deleted_chunks=0,
                success=False,
                error_message=str(e),
                processing_time_seconds=elapsed,
            )

    async def _process_page(self, page: NotionPage, source_file: str) -> list[ChunkData]:
        """
        단일 페이지 처리: 콘텐츠 추출 → 청킹

        Notion 데이터베이스의 경우:
        - 페이지 블록(본문)이 비어있을 수 있음
        - 대신 Properties(속성)에 데이터가 저장됨
        - 따라서 블록 + 속성 모두에서 텍스트 추출

        Args:
            page: NotionPage 객체
            source_file: source_file 명

        Returns:
            ChunkData 리스트
        """
        try:
            # 1. 페이지 본문 텍스트 가져오기 (블록)
            block_content = await self.notion_client.get_page_content(page.id)

            # 2. 속성(Properties)에서 텍스트 추출
            properties_content = self._extract_properties_text(page.properties)

            # 3. 블록 + 속성 콘텐츠 결합
            content_parts = []
            if properties_content.strip():
                content_parts.append(properties_content)
            if block_content.strip():
                content_parts.append(block_content)

            content = "\n\n".join(content_parts)

            if not content.strip():
                logger.warning(
                    "빈 콘텐츠 발견",
                    extra={"page_title": page.title}
                )
                return []

            # 제목 prefix 추가 (엔티티명 포함)
            full_content = f"[{page.title}]\n\n{content}"

            # 청킹
            chunks = self.text_splitter.split_text(full_content)

            return [
                ChunkData(
                    content=chunk,
                    source_file=source_file,
                    chunk_index=i,
                    page_title=page.title,
                    page_id=page.id,
                    metadata={
                        "notion_url": page.url,
                        "created_time": page.created_time,
                        "last_edited_time": page.last_edited_time,
                    },
                )
                for i, chunk in enumerate(chunks)
            ]

        except Exception as e:
            logger.error(
                "페이지 처리 실패",
                extra={
                    "page_title": page.title,
                    "error": str(e),
                    "error_type": type(e).__name__
                },
                exc_info=True
            )
            return []

    def _extract_properties_text(self, properties: dict) -> str:
        """
        Notion 페이지 속성(Properties)에서 텍스트 추출

        Notion 데이터베이스의 경우 페이지 블록(본문)이 비어있고,
        실제 데이터가 속성에 저장된 경우가 많음 (특히 구조화된 DB)

        Args:
            properties: NotionPage.properties 딕셔너리

        Returns:
            속성 값들을 결합한 텍스트
        """
        lines = []

        # 중요 속성 순서대로 처리 (엔티티명은 제목으로 이미 포함되므로 제외)
        skip_keys = {"업체명", "이름", "Name"}

        for prop_name, value in properties.items():
            if prop_name in skip_keys:
                continue

            # 값 변환
            text_value = self._property_value_to_text(value)

            if text_value:
                lines.append(f"[{prop_name}]\n{text_value}")

        return "\n\n".join(lines)

    def _property_value_to_text(self, value) -> str:
        """
        속성 값을 텍스트로 변환

        Args:
            value: 속성 값 (다양한 타입)

        Returns:
            문자열 표현
        """
        if value is None:
            return ""

        if isinstance(value, str):
            return value.strip()

        if isinstance(value, bool):
            return "예" if value else "아니오"

        if isinstance(value, int | float):
            return str(value)

        if isinstance(value, list):
            # multi_select 등 리스트 타입
            if not value:
                return ""
            items = [self._property_value_to_text(item) for item in value]
            return ", ".join(filter(None, items))

        if isinstance(value, dict):
            # 중첩된 딕셔너리 (예: relation)
            return str(value) if value else ""

        return str(value)

    # ========================================================================
    # Weaviate 연동
    # ========================================================================

    async def _delete_existing_data(self, source_file: str) -> int:
        """
        Weaviate에서 기존 데이터 삭제

        Args:
            source_file: 삭제할 source_file 값

        Returns:
            삭제된 청크 수
        """
        client = await self._get_http_client()

        # 먼저 개수 확인
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
                f"{self.config.weaviate_url}/v1/graphql",
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
        except Exception as e:
            logger.warning(
                "기존 데이터 개수 확인 실패",
                extra={
                    "error": str(e),
                    "error_type": type(e).__name__
                }
            )
            existing_count = 0

        if existing_count == 0:
            logger.info(
                "기존 데이터 없음",
                extra={"source_file": source_file}
            )
            return 0

        # 삭제 실행
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
                f"{self.config.weaviate_url}/v1/batch/objects",
                json=delete_payload,
            )

            if response.status_code in (200, 204):
                logger.info(
                    "기존 데이터 삭제 완료",
                    extra={
                        "source_file": source_file,
                        "deleted_count": existing_count
                    }
                )
                return existing_count
            else:
                logger.error(
                    "삭제 실패",
                    extra={
                        "status_code": response.status_code,
                        "response_text": response.text
                    }
                )
                return 0

        except Exception as e:
            logger.error(
                "삭제 요청 실패",
                extra={
                    "error": str(e),
                    "error_type": type(e).__name__
                },
                exc_info=True
            )
            return 0

    async def _upload_chunks(self, chunks: list[ChunkData]) -> int:
        """
        청크를 Weaviate에 업로드

        Args:
            chunks: 업로드할 청크 리스트

        Returns:
            업로드된 청크 수
        """
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

            payload = {"objects": objects}

            try:
                response = await client.post(
                    f"{self.config.weaviate_url}/v1/batch/objects",
                    json=payload,
                )

                if response.status_code == 200:
                    result = response.json()
                    # 성공한 개체 수 확인
                    success_count = sum(
                        1 for obj in result if obj.get("result", {}).get("status") == "SUCCESS"
                    )
                    uploaded += success_count
                    logger.debug(
                        "배치 업로드",
                        extra={
                            "success_count": success_count,
                            "batch_size": len(batch)
                        }
                    )
                else:
                    logger.error(
                        "업로드 실패",
                        extra={"status_code": response.status_code}
                    )

            except Exception as e:
                logger.error(
                    "업로드 요청 실패",
                    extra={
                        "error": str(e),
                        "error_type": type(e).__name__
                    },
                    exc_info=True
                )

        logger.info(
            "Weaviate 업로드 완료",
            extra={
                "uploaded_count": uploaded,
                "total_chunks": len(chunks)
            }
        )
        return uploaded


# ============================================================================
# 편의 함수
# ============================================================================


async def run_notion_batch(
    categories: list[str] | None = None,
    dry_run: bool = False,
) -> list[BatchResult]:
    """
    Notion 배치 실행 편의 함수

    Args:
        categories: 처리할 카테고리 (None이면 전체)
        dry_run: True면 Weaviate 업로드 건너뜀

    Returns:
        배치 결과 리스트

    사용 예시:
        >>> results = await run_notion_batch()
        >>> results = await run_notion_batch(["domain_1"], dry_run=True)
    """
    config = NotionBatchConfig(dry_run=dry_run)
    if categories:
        config.categories = categories

    processor = NotionBatchProcessor(config=config)
    return await processor.run_batch()


# ============================================================================
# 메인 실행
# ============================================================================


async def main():
    """메인 실행 함수"""
    import argparse

    parser = argparse.ArgumentParser(description="Notion API 배치 프로세서")
    parser.add_argument(
        "--category",
        "-c",
        default="all",
        help="처리할 카테고리 키 (domain.yaml의 domain.batch.categories 키) 또는 all",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Weaviate 업로드 건너뜀 (테스트용)",
    )

    args = parser.parse_args()

    categories = None if args.category == "all" else [args.category]

    results = await run_notion_batch(categories=categories, dry_run=args.dry_run)

    # 결과 요약 출력
    print("\n" + "=" * 60)
    print("📊 배치 처리 결과 요약")
    print("=" * 60)

    for result in results:
        status = "✅" if result.success else "❌"
        print(
            f"{status} {result.category}: "
            f"{result.total_pages}페이지 → {result.uploaded_chunks}청크 "
            f"({result.processing_time_seconds:.1f}초)"
        )

    total_chunks = sum(r.uploaded_chunks for r in results)
    print(f"\n총 업로드: {total_chunks}개 청크")


if __name__ == "__main__":
    asyncio.run(main())
