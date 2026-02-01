"""
DI Container 구조 검증 테스트

Phase 3 R3.3: di_container.py Provider 구조 단순화 및 문서화
TDD - DI Container의 구조적 일관성 검증
"""

import pytest


@pytest.fixture(autouse=True)
def _cleanup_weaviate_connection():
    """테스트 종료 후 WeaviateClient 싱글톤 연결을 정리하여 ResourceWarning 방지.

    WeaviateClient는 클래스 레벨 싱글톤(__new__)이므로,
    DI 컨테이너와 무관하게 _instance를 직접 정리해야 합니다.
    """
    yield
    try:
        from app.lib.weaviate_client import WeaviateClient

        if WeaviateClient._instance is not None:
            WeaviateClient._instance.close()
    except Exception:
        pass


class TestDIContainerStructure:
    """DI Container 구조 검증"""

    def test_container_has_essential_providers(self) -> None:
        """필수 Provider가 정의되어 있어야 함"""
        from app.core.di_container import AppContainer

        container = AppContainer()

        # 핵심 Provider 존재 확인
        essential_providers = [
            "config",
            "llm_factory",
            "weaviate_client",
            "generation",
            "retrieval_orchestrator",
            "rag_pipeline",
            "chat_service",
        ]

        for provider_name in essential_providers:
            assert hasattr(container, provider_name), (
                f"필수 Provider '{provider_name}'가 없습니다"
            )

    def test_container_provider_count(self) -> None:
        """Provider 수가 관리 가능한 범위 내에 있어야 함"""
        from dependency_injector import providers as di_providers

        from app.core.di_container import AppContainer

        container = AppContainer()

        # Provider 수 계산
        provider_count = 0
        for name in dir(container):
            attr = getattr(container, name, None)
            if isinstance(attr, di_providers.Provider):
                provider_count += 1

        # Provider가 너무 많으면 경고 (50개 이상은 분리 검토 필요)
        assert provider_count <= 60, (
            f"Provider 수가 너무 많습니다: {provider_count}개. "
            f"모듈별 분리를 검토하세요."
        )

        # Provider가 적어도 핵심 요소는 있어야 함
        assert provider_count >= 10, (
            f"Provider 수가 너무 적습니다: {provider_count}개"
        )

    def test_factory_vs_singleton_consistency(self) -> None:
        """Factory와 Singleton Provider가 올바르게 구분되어야 함"""
        from dependency_injector import providers as di_providers

        from app.core.di_container import AppContainer

        container = AppContainer()

        # Factory여야 하는 Provider (요청마다 새 인스턴스)
        expected_factories = ["rag_pipeline", "chat_service"]

        # Singleton이어야 하는 Provider (공유 상태)
        expected_singletons = [
            "config",
            "llm_factory",
            "weaviate_client",
            "generation",
        ]

        for name in expected_factories:
            provider = getattr(container, name, None)
            assert isinstance(provider, di_providers.Factory), (
                f"'{name}'는 Factory Provider여야 합니다"
            )

        for name in expected_singletons:
            provider = getattr(container, name, None)
            # Singleton, Configuration 모두 허용
            assert isinstance(
                provider, (di_providers.Singleton, di_providers.Configuration)
            ), f"'{name}'는 Singleton Provider여야 합니다"


class TestDIContainerDocumentation:
    """DI Container 문서화 검증"""

    def test_container_has_docstring(self) -> None:
        """Container 클래스에 문서가 있어야 함"""
        from app.core.di_container import AppContainer

        assert AppContainer.__doc__ is not None, (
            "AppContainer에 docstring이 없습니다"
        )

    def test_module_has_docstring(self) -> None:
        """모듈에 문서가 있어야 함"""
        import app.core.di_container as di_module

        assert di_module.__doc__ is not None, (
            "di_container 모듈에 docstring이 없습니다"
        )

        # Provider 타입 설명이 있어야 함
        assert "Provider" in di_module.__doc__, (
            "모듈 docstring에 Provider 설명이 필요합니다"
        )


class TestDIContainerProviderGroups:
    """Provider 그룹별 구조 검증"""

    def test_retrieval_providers_exist(self) -> None:
        """검색 관련 Provider가 모두 있어야 함"""
        from app.core.di_container import AppContainer

        container = AppContainer()

        retrieval_providers = [
            "weaviate_retriever",
            "retrieval_orchestrator",
            "base_reranker",
            "memory_cache",
        ]

        for name in retrieval_providers:
            assert hasattr(container, name), (
                f"검색 Provider '{name}'가 없습니다"
            )

    def test_privacy_providers_exist(self) -> None:
        """개인정보 보호 관련 Provider가 모두 있어야 함"""
        from app.core.di_container import AppContainer

        container = AppContainer()

        privacy_providers = [
            "pii_processor",
            "privacy_masker",
            "whitelist_manager",
        ]

        for name in privacy_providers:
            assert hasattr(container, name), (
                f"개인정보 보호 Provider '{name}'가 없습니다"
            )

    def test_generation_providers_exist(self) -> None:
        """답변 생성 관련 Provider가 모두 있어야 함"""
        from app.core.di_container import AppContainer

        container = AppContainer()

        generation_providers = [
            "generation",
            "prompt_manager",
            "llm_factory",
        ]

        for name in generation_providers:
            assert hasattr(container, name), (
                f"생성 Provider '{name}'가 없습니다"
            )

    def test_graph_providers_exist(self) -> None:
        """GraphRAG 관련 Provider가 있어야 함"""
        from app.core.di_container import AppContainer

        container = AppContainer()

        graph_providers = [
            "graph_store",
            "entity_extractor",
            "relation_extractor",
            "knowledge_graph_builder",
        ]

        for name in graph_providers:
            assert hasattr(container, name), (
                f"GraphRAG Provider '{name}'가 없습니다"
            )

    def test_agent_providers_exist(self) -> None:
        """Agentic RAG 관련 Provider가 있어야 함"""
        from app.core.di_container import AppContainer

        container = AppContainer()

        agent_providers = [
            "mcp_server",
            "agent_orchestrator",
        ]

        for name in agent_providers:
            assert hasattr(container, name), (
                f"Agent Provider '{name}'가 없습니다"
            )
