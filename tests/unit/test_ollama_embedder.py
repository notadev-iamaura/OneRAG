"""
OllamaEmbedder 단위 테스트

OllamaEmbedder의 초기화 및 기본 동작을 검증합니다.
OpenRouterEmbedder 상속 관계와 Ollama 기본 설정을 확인합니다.
"""

from unittest.mock import MagicMock


class TestOllamaEmbedderInit:
    """OllamaEmbedder 초기화 테스트"""

    def test_default_config(self) -> None:
        """기본 설정으로 초기화"""
        from app.modules.core.embedding.ollama_embedder import OllamaEmbedder

        embedder = OllamaEmbedder()
        assert embedder.model_name == "nomic-embed-text"
        assert embedder.output_dimensionality == 768
        assert embedder.batch_size == 32

    def test_custom_model(self) -> None:
        """커스텀 모델로 초기화"""
        from app.modules.core.embedding.ollama_embedder import OllamaEmbedder

        embedder = OllamaEmbedder(
            model_name="mxbai-embed-large",
            output_dimensionality=1024,
        )
        assert embedder.model_name == "mxbai-embed-large"
        assert embedder.output_dimensionality == 1024

    def test_custom_base_url(self) -> None:
        """커스텀 Ollama 서버 URL"""
        from app.modules.core.embedding.ollama_embedder import OllamaEmbedder

        embedder = OllamaEmbedder(base_url="http://remote:11434/v1")
        # 클라이언트가 생성되었는지 확인
        assert embedder.client is not None

    def test_inherits_from_openrouter_embedder(self) -> None:
        """OpenRouterEmbedder 상속 확인"""
        from app.modules.core.embedding.ollama_embedder import OllamaEmbedder
        from app.modules.core.embedding.openai_embedder import OpenRouterEmbedder

        embedder = OllamaEmbedder()
        assert isinstance(embedder, OpenRouterEmbedder)

    def test_client_created_with_not_needed_api_key(self) -> None:
        """API 키 없이 클라이언트 생성 (not-needed 사용)"""
        from app.modules.core.embedding.ollama_embedder import OllamaEmbedder

        embedder = OllamaEmbedder()
        # 'not-needed' API 키로 클라이언트가 생성되어야 함
        assert embedder.client is not None


class TestOllamaEmbedderMethods:
    """OllamaEmbedder 메서드 테스트"""

    def test_embed_documents_empty(self) -> None:
        """빈 리스트 입력 시 빈 결과 반환"""
        from app.modules.core.embedding.ollama_embedder import OllamaEmbedder

        embedder = OllamaEmbedder()
        result = embedder.embed_documents([])
        assert result == []

    def test_embed_documents_with_mock(self) -> None:
        """Mock 클라이언트로 문서 임베딩 생성"""
        from app.modules.core.embedding.ollama_embedder import OllamaEmbedder

        embedder = OllamaEmbedder()

        # OpenAI 클라이언트 Mock
        mock_response = MagicMock()
        mock_item = MagicMock()
        mock_item.embedding = [0.1] * 768
        mock_response.data = [mock_item]
        embedder.client = MagicMock()
        embedder.client.embeddings.create.return_value = mock_response

        result = embedder.embed_documents(["테스트 문서"])
        assert len(result) == 1
        assert len(result[0]) == 768

    def test_embed_query_with_mock(self) -> None:
        """Mock 클라이언트로 쿼리 임베딩 생성"""
        from app.modules.core.embedding.ollama_embedder import OllamaEmbedder

        embedder = OllamaEmbedder()

        mock_response = MagicMock()
        mock_item = MagicMock()
        mock_item.embedding = [0.2] * 768
        mock_response.data = [mock_item]
        embedder.client = MagicMock()
        embedder.client.embeddings.create.return_value = mock_response

        result = embedder.embed_query("테스트 쿼리")
        assert len(result) == 768
