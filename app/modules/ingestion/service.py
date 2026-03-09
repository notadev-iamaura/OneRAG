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
        self.chunker = chunker or MetadataChunker()

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

            for page in pages:
                # Metadata Extraction
                entity_name = page.title.replace("★", "").strip()
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
