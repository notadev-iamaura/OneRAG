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


class TestMetadataSourceSuffixFactoryWiring:
    """DI 팩토리(create_retriever_via_factory)가 config 값을 생성자까지 배선하는지 검증.

    생성자/상수 단위 테스트만으로는 'config 키가 팩토리에서 누락되어 오버라이드가
    런타임에 도달하지 못하는' 데드 경로를 잡지 못한다(배선 트랩). 이 테스트는
    weaviate.metadata_source_suffix가 실제 생성자까지 전달됨을 보장한다.
    """

    def test_factory_wires_config_suffix(self):
        """config에 설정한 접미사가 팩토리 경유로 생성자에 도달한다."""
        from unittest.mock import MagicMock

        from app.core.di_container import create_retriever_via_factory

        retriever = create_retriever_via_factory(
            config={
                "vector_db": {"provider": "weaviate"},
                "weaviate": {"metadata_source_suffix": " (metadata)"},
            },
            embedder=MagicMock(),
            weaviate_client=MagicMock(),
        )
        assert retriever._metadata_source_suffix == " (metadata)"

    def test_factory_defaults_to_korean_when_unset(self):
        """config 미설정 시 팩토리 경유로도 한국어 기본 폴백(회귀 0)."""
        from unittest.mock import MagicMock

        from app.core.di_container import create_retriever_via_factory

        retriever = create_retriever_via_factory(
            config={"vector_db": {"provider": "weaviate"}, "weaviate": {}},
            embedder=MagicMock(),
            weaviate_client=MagicMock(),
        )
        assert retriever._metadata_source_suffix == " (메타데이터)"
