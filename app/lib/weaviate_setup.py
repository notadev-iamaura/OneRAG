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

from app.lib.logger import get_logger
from app.lib.weaviate_client import get_weaviate_client

logger = get_logger(__name__)


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
            logger.info(f"✅ {collection_name} 스키마 이미 존재 - 스킵")
            return True

        logger.info(f"🔧 {collection_name} 스키마 생성 중...")

        # Documents Collection 생성
        # Weaviate v4 방식 사용
        from weaviate.classes.config import Configure, DataType, Property, Tokenization

        client.collections.create(
            name=collection_name,
            description="RAG 챗봇을 위한 문서 저장소",
            # 벡터화 설정 (OpenAI Embedding 직접 사용)
            vectorizer_config=None,  # 수동 벡터 입력
            # 속성 정의 (Flat structure - nested object 제거)
            properties=[
                Property(
                    name="content",
                    data_type=DataType.TEXT,
                    description="문서 내용",
                    skip_vectorization=False,  # 벡터화 대상
                    tokenization=Tokenization.WORD,  # 단어 단위 토큰화
                ),
                # Metadata를 flat properties로 변경 (OBJECT 타입 제거)
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
                    data_type=DataType.TEXT,  # INT → TEXT (클라이언트 호환성)
                    description="수치 데이터 (범용)",
                ),
                Property(
                    name="capacity",
                    data_type=DataType.TEXT,  # INT → TEXT (클라이언트 호환성)
                    description="수용 인원/한도",
                ),
                Property(
                    name="rating",
                    data_type=DataType.TEXT,  # NUMBER → TEXT (호환성 문제)
                    description="평점/등급",
                ),
                Property(
                    name="source",
                    data_type=DataType.TEXT,
                    description="데이터 출처",
                ),
                Property(
                    name="created_at",
                    data_type=DataType.TEXT,  # DATE → TEXT (호환성 문제 해결)
                    description="생성 일시",
                ),
            ],
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
