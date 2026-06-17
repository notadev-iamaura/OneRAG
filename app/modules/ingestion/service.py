"""
Ingestion Service

데이터 적재(Ingestion)를 담당하는 서비스 모듈.
다양한 소스(외부 API, File 등)로부터 데이터를 추출하여
벡터 저장소(Vector Store)와 메타데이터 저장소(Metadata Store)에 저장합니다.
"""
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.batch.metadata_chunker import MetadataChunker
from app.core.interfaces.storage import IMetadataStore, IVectorStore
from app.lib.logger import get_logger
from app.modules.ingestion.interfaces import IIngestionConnector

# 선택적 모듈: Notion 클라이언트
try:
    from app.batch.notion_client import NotionAPIClient
except ImportError:
    NotionAPIClient = None  # type: ignore[assignment,misc]

logger = get_logger(__name__)

@dataclass
class IngestionResult:
    """적재 작업 결과"""
    source: str
    total_items: int = 0
    vector_saved: int = 0
    metadata_saved: int = 0
    errors: list[str] = field(default_factory=list)
    duration_seconds: float = 0.0

class IngestionService:
    def __init__(
        self,
        vector_store: IVectorStore,
        metadata_store: IMetadataStore,
        config: dict[str, Any] | None = None,
        notion_client: Any | None = None,
        chunker: MetadataChunker | None = None
    ):
        self.vector_store = vector_store
        self.metadata_store = metadata_store
        self.config = config or {}
        self.notion_client = notion_client
        # 청커를 명시적으로 주입받지 않으면 config의 도메인 배치 설정으로 생성한다.
        # domain.yaml의 `domain.batch.section_keywords`/`target_fields`를 읽어 주입하므로
        # 더 이상 데드 config 키가 아니다(미설정 시 도메인 중립 기본값 사용).
        self.chunker = chunker if chunker is not None else self._build_chunker_from_config()

    def _build_chunker_from_config(self) -> MetadataChunker:
        """
        config의 도메인 배치 설정으로 MetadataChunker를 생성

        domain.yaml의 `domain.batch.section_keywords`/`target_fields`와 미분류
        폴백 라벨(`default_section_label`/`default_section_header`)을 읽어 청커에
        주입한다. 설정이 없으면 MetadataChunker 내부의 도메인 중립/한국어 기본값을
        사용한다(OSS 기본 배포 = 도메인 중립, 회귀 0).

        Returns:
            도메인 설정이 반영된 MetadataChunker 인스턴스
        """
        batch_config = self.config.get("domain", {}).get("batch", {})

        # 미설정(None)이면 청커 기본값을 쓰도록 None을 그대로 전달한다.
        section_keywords = batch_config.get("section_keywords")
        target_fields = batch_config.get("target_fields")

        # 섹션 폴백 라벨은 문자열 기본값이라 None이면 청커 기본을 쓰도록 분기 주입한다.
        chunker_kwargs: dict[str, Any] = {
            "section_keywords": section_keywords,
            "target_fields": target_fields,
        }
        default_section_label = batch_config.get("default_section_label")
        if isinstance(default_section_label, str) and default_section_label.strip():
            chunker_kwargs["default_section_label"] = default_section_label
        default_section_header = batch_config.get("default_section_header")
        if isinstance(default_section_header, str) and default_section_header.strip():
            chunker_kwargs["default_section_header"] = default_section_header

        return MetadataChunker(**chunker_kwargs)

    def _get_title_strip_chars(self) -> list[str]:
        """
        제목 정제 문자 목록 로드 (domain.batch.title_strip_chars)

        Notion 페이지 제목에서 제거할 접두/마커 문자를 config에서 읽는다.
        특정 워크스페이스의 명명 규칙(예: '★' 접두)에 종속되지 않도록 외부화한다.
        미설정/빈 목록이면 정제를 수행하지 않아 notion_extractor.py와 동작이 일치한다(회귀 0).

        Returns:
            제거할 문자 목록. 미설정 시 빈 목록.
        """
        batch_config = self.config.get("domain", {}).get("batch", {})
        strip_chars = batch_config.get("title_strip_chars")

        if isinstance(strip_chars, list) and strip_chars:
            return [str(c) for c in strip_chars]

        return []

    @staticmethod
    def _clean_title(title: str, strip_chars: list[str]) -> str:
        """
        페이지 제목 정제 (옵트인 문자 제거 + 양끝 공백 제거)

        strip_chars가 비어 있으면 양끝 공백만 제거한다(★ 등 마커 미제거 → 회귀 0).

        Args:
            title: 원본 페이지 제목
            strip_chars: 제거할 문자 목록 (config 주입)

        Returns:
            정제된 제목
        """
        cleaned = title
        for ch in strip_chars:
            cleaned = cleaned.replace(ch, "")
        return cleaned.strip()

    async def ingest_from_connector(self, connector: IIngestionConnector, category_name: str) -> IngestionResult:
        """
        범용 커넥터로부터 데이터를 읽어와 적재 수행
        """
        start_time = time.time()
        result = IngestionResult(source=type(connector).__name__)

        try:
            logger.info(f"🚀 Ingestion started via connector: {result.source} ({category_name})")

            all_chunks = []
            metadata_list = []

            # 1. Fetch & standard documents
            async for doc in connector.fetch_documents():
                try:
                    result.total_items += 1

                    # Metadata Store용 데이터 준비
                    meta = {
                        "id": doc.source_url,
                        "source_url": doc.source_url,
                        "category": category_name,
                        "synced_at": datetime.now(UTC).isoformat(),
                        **doc.metadata
                    }
                    metadata_list.append(meta)

                    # Chunking (Text split)
                    chunks = self.chunker.chunk_entity_data(
                        entity_id=doc.source_url,
                        entity_name=doc.metadata.get("title", doc.source_url),
                        category=category_name,
                        properties={"content": doc.content}
                    )

                    if chunks.total_chunks > 0:
                        for chunk in chunks.chunks:
                            all_chunks.append({
                                "content": chunk.content,
                                "metadata": {
                                    "source_url": doc.source_url,
                                    "category": category_name,
                                    **chunk.metadata.__dict__
                                }
                            })
                    else:
                        error_msg = f"Document {doc.source_url} produced 0 chunks (empty content?)"
                        logger.warning(error_msg)
                        result.errors.append(error_msg)
                except Exception as doc_error:
                    error_msg = f"Failed to process document {doc.source_url}: {doc_error}"
                    logger.error(error_msg)
                    result.errors.append(error_msg)

            # 2. Batch Save (Stability: Only save if there are chunks)
            if all_chunks:
                try:
                    result.vector_saved = await self.vector_store.add_documents("Documents", all_chunks)
                except Exception as vector_error:
                    logger.error(f"Vector storage failed: {vector_error}")
                    result.errors.append(f"Vector storage failed: {vector_error}")

            if metadata_list:
                success_count = 0
                for meta in metadata_list:
                    try:
                        if await self.metadata_store.save(f"{category_name}_metadata", meta):
                            success_count += 1
                    except Exception as meta_error:
                        logger.error(f"Metadata save failed for {meta['id']}: {meta_error}")
                result.metadata_saved = success_count

        except Exception as e:
            logger.critical(f"Critical failure in ingestion from connector: {e}")
            result.errors.append(f"CRITICAL: {str(e)}")

        finally:
            result.duration_seconds = time.time() - start_time
            logger.info(f"📊 Ingestion finished: {result}")

        return result

    async def ingest_notion_database(self, db_id: str, category_name: str) -> IngestionResult:
        """
        Notion 데이터베이스를 통째로 적재
        """
        if not self.notion_client:
            raise ValueError("Notion Client가 설정되지 않았습니다.")

        start_time = time.time()
        result = IngestionResult(source=f"notion:{db_id}")

        try:
            logger.info(f"🚀 Ingestion started for Notion DB: {db_id} ({category_name})")

            # 1. Fetch from Notion
            db_result = await self.notion_client.query_database(db_id)
            pages = db_result.pages
            result.total_items = len(pages)

            if not pages:
                logger.info("No pages found.")
                return result

            # 2. Process & Save
            all_chunks = []
            metadata_list = []

            # 컬렉션 이름 설정 로드 (기본값: Documents)
            vector_collection = self.config.get("weaviate", {}).get("collection_name", "Documents")

            # 제목 정제 문자 외부화: domain.batch.title_strip_chars
            # 기본 빈 목록 = 정제 안 함(notion_extractor.py와 동작 통일, 회귀 0).
            # 특정 워크스페이스 명명 규칙(예: ★ 접두)을 쓰면 yaml로 옵트인한다.
            title_strip_chars = self._get_title_strip_chars()

            for page in pages:
                # Metadata Extraction
                entity_name = self._clean_title(page.title, title_strip_chars)
                metadata = {
                    "id": page.id, # Common ID
                    "notion_page_id": page.id,
                    "entity_name": entity_name,
                    "category": category_name,
                    "last_edited": page.last_edited_time,
                    "synced_at": datetime.now(UTC).isoformat()
                }
                # Properties flattening
                for k, v in page.properties.items():
                    if v is not None and v != "":
                        metadata[k] = v
                metadata_list.append(metadata)

                # Chunking
                chunk_result = self.chunker.chunk_entity_data(
                    entity_id=page.id,
                    entity_name=entity_name,
                    category=category_name,
                    properties=page.properties
                )
                if chunk_result.total_chunks > 0:
                    for chunk in chunk_result.chunks:
                        # Vector Store용 문서 구조로 변환
                        doc = {
                            "content": chunk.content,
                            "metadata": {
                                "source_id": page.id,
                                "chunk_index": chunk.metadata.chunk_index,
                                "category": category_name,
                                **chunk.metadata.__dict__ # 기타 메타데이터
                            }
                        }
                        all_chunks.append(doc)

            # 3. Save to Stores (Batch)
            if all_chunks:
                saved_vectors = await self.vector_store.add_documents(
                    collection=vector_collection,
                    documents=all_chunks
                )
                result.vector_saved = saved_vectors

            if metadata_list:
                # Save item by item or batch if supported
                success_count = 0
                for meta in metadata_list:
                    if await self.metadata_store.save(collection=f"{category_name}_metadata", data=meta):
                        success_count += 1
                result.metadata_saved = success_count

        except Exception as e:
            logger.error(f"Ingestion failed: {e}")
            result.errors.append(str(e))
            import traceback
            traceback.print_exc()

        finally:
            result.duration_seconds = time.time() - start_time
            logger.info(f"📊 Ingestion finished: {result}")

        return result
