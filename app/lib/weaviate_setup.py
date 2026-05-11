"""
Weaviate 스키마 초기화 모듈

주요 기능:
- Documents 스키마(Collection) 생성
- 기존 스키마 존재 확인
- Railway 배포 시 자동 초기화 지원

의존성:
- app.lib.weaviate_client: Weaviate 연결
- app.lib.logger: 로깅
"""

from typing import Any

from app.lib.logger import get_logger
from app.lib.weaviate_client import get_weaviate_client

logger = get_logger(__name__)


def _document_schema_properties() -> list[Any]:
    """Return the canonical Documents collection properties."""
    from weaviate.classes.config import DataType, Property, Tokenization

    return [
        Property(
            name="content",
            data_type=DataType.TEXT,
            description="문서 내용",
            skip_vectorization=False,
            tokenization=Tokenization.WORD,
        ),
        Property(
            name="document_id",
            data_type=DataType.TEXT,
            description="업로드/원문 문서 식별자",
        ),
        Property(
            name="source_file",
            data_type=DataType.TEXT,
            description="출처 파일명",
        ),
        Property(
            name="filename",
            data_type=DataType.TEXT,
            description="파일명 별칭",
        ),
        Property(
            name="file_name",
            data_type=DataType.TEXT,
            description="파일명 별칭",
        ),
        Property(
            name="file_type",
            data_type=DataType.TEXT,
            description="파일 타입",
        ),
        Property(
            name="file_path",
            data_type=DataType.TEXT,
            description="원본 파일 경로",
        ),
        Property(
            name="file_hash",
            data_type=DataType.TEXT,
            description="원본 파일 해시",
        ),
        Property(
            name="file_size",
            data_type=DataType.INT,
            description="파일 크기(bytes)",
        ),
        Property(
            name="original_file_size",
            data_type=DataType.INT,
            description="업로드 원본 파일 크기(bytes)",
        ),
        Property(
            name="chunk_index",
            data_type=DataType.INT,
            description="청크 인덱스",
        ),
        Property(
            name="page",
            data_type=DataType.INT,
            description="페이지 번호 별칭",
        ),
        Property(
            name="page_number",
            data_type=DataType.INT,
            description="페이지 번호",
        ),
        Property(
            name="total_chunks",
            data_type=DataType.INT,
            description="전체 청크 수",
        ),
        Property(
            name="char_count",
            data_type=DataType.INT,
            description="청크 문자 수",
        ),
        Property(
            name="word_count",
            data_type=DataType.INT,
            description="청크 단어 수",
        ),
        Property(
            name="load_timestamp",
            data_type=DataType.NUMBER,
            description="로드 시각 타임스탬프",
        ),
        Property(
            name="splitter_type",
            data_type=DataType.TEXT,
            description="문서 분할 방식",
        ),
        Property(
            name="sheet_name",
            data_type=DataType.TEXT,
            description="스프레드시트 시트명",
        ),
        Property(
            name="format",
            data_type=DataType.TEXT,
            description="문서 포맷",
        ),
        Property(
            name="json_type",
            data_type=DataType.TEXT,
            description="JSON 로딩 타입",
        ),
        Property(
            name="item_index",
            data_type=DataType.INT,
            description="JSON 항목 인덱스",
        ),
        Property(
            name="total_items",
            data_type=DataType.INT,
            description="JSON 전체 항목 수",
        ),
        Property(
            name="keys",
            data_type=DataType.TEXT_ARRAY,
            description="JSON 키 목록",
        ),
        Property(
            name="json_loader",
            data_type=DataType.TEXT,
            description="JSON 로더 종류",
        ),
        Property(
            name="jq_schema",
            data_type=DataType.TEXT,
            description="JSONLoader jq schema",
        ),
        Property(
            name="content_key",
            data_type=DataType.TEXT,
            description="JSONLoader content key",
        ),
        Property(
            name="entity_name",
            data_type=DataType.TEXT,
            description="엔티티 이름",
        ),
        Property(
            name="location",
            data_type=DataType.TEXT,
            description="위치/장소",
        ),
        Property(
            name="numeric_value",
            data_type=DataType.TEXT,
            description="수치 데이터 (범용)",
        ),
        Property(
            name="price",
            data_type=DataType.TEXT,
            description="가격/비용",
        ),
        Property(
            name="capacity",
            data_type=DataType.TEXT,
            description="수용 인원/한도",
        ),
        Property(
            name="rating",
            data_type=DataType.TEXT,
            description="평점/등급",
        ),
        Property(
            name="source",
            data_type=DataType.TEXT,
            description="데이터 출처",
        ),
        Property(
            name="created_at",
            data_type=DataType.TEXT,
            description="생성 일시",
        ),
        Property(
            name="metadata_json",
            data_type=DataType.TEXT,
            description="스키마에 없는 원본 메타데이터 JSON",
        ),
    ]


def _collection_property_names(collection: Any) -> set[str]:
    """Read property names from a Weaviate v4 collection config."""
    config = collection.config.get(simple=True)
    properties = getattr(config, "properties", {})
    if isinstance(properties, dict):
        return set(properties)
    return {prop.name for prop in properties if getattr(prop, "name", None)}


def _ensure_document_schema_properties(client: Any, collection_name: str) -> int:
    """Add missing Documents properties to an existing collection."""
    collection = client.collections.get(collection_name)
    existing_names = _collection_property_names(collection)
    added_count = 0

    for prop in _document_schema_properties():
        if prop.name in existing_names:
            continue
        collection.config.add_property(prop)
        existing_names.add(prop.name)
        added_count += 1
        logger.info(f"✅ {collection_name} 누락 프로퍼티 추가: {prop.name}")

    return added_count


async def create_schema() -> bool:
    """
    Weaviate에 Documents 스키마(Collection) 생성

    이미 스키마가 존재하면 스킵합니다.

    Returns:
        bool: 생성 성공 시 True, 실패 시 False

    사용 예시:
        >>> from app.infrastructure.persistence.weaviate_setup import create_schema
        >>> await create_schema()
        ✅ Documents 스키마 생성 완료!
    """
    try:
        # Weaviate 클라이언트 가져오기
        weaviate_client = get_weaviate_client()

        if weaviate_client.client is None:
            logger.error("❌ Weaviate 클라이언트 연결 실패 - 스키마 생성 불가")
            return False

        client = weaviate_client.client

        # 기존 스키마(Collection) 확인
        collection_name = "Documents"

        # Collection이 이미 존재하는지 확인
        if client.collections.exists(collection_name):
            added_count = _ensure_document_schema_properties(client, collection_name)
            if added_count:
                logger.info(
                    f"✅ {collection_name} 스키마 보강 완료: {added_count}개 프로퍼티 추가"
                )
            else:
                logger.info(f"✅ {collection_name} 스키마 이미 최신 상태")
            return True

        logger.info(f"🔧 {collection_name} 스키마 생성 중...")

        # Documents Collection 생성
        # Weaviate v4 방식 사용
        from weaviate.classes.config import Configure

        client.collections.create(
            name=collection_name,
            description="RAG 챗봇을 위한 문서 저장소",
            # 벡터화 설정 (OpenAI Embedding 직접 사용)
            vectorizer_config=None,  # 수동 벡터 입력
            # 속성 정의 (Flat structure - nested object 제거)
            properties=_document_schema_properties(),
            # 인덱싱 설정
            inverted_index_config=Configure.inverted_index(
                bm25_b=0.75,
                bm25_k1=1.2,
            ),
        )

        logger.info(f"✅ {collection_name} 스키마 생성 완료!")
        return True

    except Exception as e:
        logger.error(f"❌ Weaviate 스키마 생성 실패: {e}", exc_info=True)
        return False


def get_schema_info() -> dict | None:
    """
    현재 Weaviate 스키마 정보 조회

    Returns:
        dict: 스키마 정보 또는 None (연결 실패 시)
    """
    try:
        weaviate_client = get_weaviate_client()

        if weaviate_client.client is None:
            return None

        # Collection 목록 가져오기
        collections = weaviate_client.client.collections.list_all()

        return {
            "collections": [c.name for c in collections.values()],
            "total_count": len(collections),
        }

    except Exception as e:
        logger.error(f"스키마 정보 조회 실패: {e}")
        return None
