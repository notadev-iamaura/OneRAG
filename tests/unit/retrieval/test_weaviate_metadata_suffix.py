"""
Weaviate 메타데이터 source 접미사 외부화 테스트 (16차 범용화)

엔티티 기반 검색결과의 source_file 표시 접미사 "(메타데이터)"가
코드 인라인 하드코딩이던 것을 모듈 상수 + 생성자 파라미터로 외부화한
변경을 검증한다(미설정 시 한국어 기본=회귀 0).
"""

from app.modules.core.retrieval.retrievers.weaviate_retriever import (
    _DEFAULT_METADATA_SOURCE_SUFFIX,
)


class TestMetadataSourceSuffix:
    def test_default_korean_suffix(self):
        assert _DEFAULT_METADATA_SOURCE_SUFFIX == " (메타데이터)"

    def test_constructor_stores_default(self):
        """미설정 시 인스턴스가 한국어 기본 접미사를 보관(회귀 0)."""
        from unittest.mock import MagicMock

        from app.modules.core.retrieval.retrievers.weaviate_retriever import (
            WeaviateRetriever,
        )

        r = WeaviateRetriever(embedder=MagicMock(), weaviate_client=MagicMock())
        assert r._metadata_source_suffix == " (메타데이터)"

    def test_constructor_override(self):
        from unittest.mock import MagicMock

        from app.modules.core.retrieval.retrievers.weaviate_retriever import (
            WeaviateRetriever,
        )

        r = WeaviateRetriever(
            embedder=MagicMock(),
            weaviate_client=MagicMock(),
            metadata_source_suffix=" (metadata)",
        )
        assert r._metadata_source_suffix == " (metadata)"
