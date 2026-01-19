"""
로컬 임베더 단위 테스트

Qwen3-Embedding-0.6B 기반 로컬 임베더의 동작을 검증합니다.
sentence-transformers 라이브러리를 사용하여 로컬에서 임베딩을 생성합니다.
"""

from unittest.mock import MagicMock, patch

import numpy as np
import pytest


class TestLocalEmbedderInterface:
    """IEmbedder 인터페이스 준수 테스트"""

    def test_local_embedder_implements_iembedder(self):
        """LocalEmbedder가 IEmbedder 인터페이스를 구현하는지 확인"""
        from app.modules.core.embedding.interfaces import IEmbedder
        from app.modules.core.embedding.local_embedder import LocalEmbedder

        # Mock SentenceTransformer to avoid actual model loading
        with patch('app.modules.core.embedding.local_embedder.SentenceTransformer'):
            embedder = LocalEmbedder()
            assert isinstance(embedder, IEmbedder)

    def test_has_required_methods(self):
        """필수 메서드가 존재하는지 확인"""
        from app.modules.core.embedding.local_embedder import LocalEmbedder

        with patch('app.modules.core.embedding.local_embedder.SentenceTransformer'):
            embedder = LocalEmbedder()

            assert hasattr(embedder, 'embed_documents')
            assert hasattr(embedder, 'embed_query')
            assert hasattr(embedder, 'aembed_documents')
            assert hasattr(embedder, 'aembed_query')
            assert hasattr(embedder, 'validate_embedding')
            assert hasattr(embedder, 'output_dimensionality')
            assert hasattr(embedder, 'model_name')


class TestLocalEmbedderProperties:
    """속성 테스트"""

    def test_model_name_property(self):
        """model_name 속성이 올바른 값을 반환하는지 확인"""
        from app.modules.core.embedding.local_embedder import LocalEmbedder

        with patch('app.modules.core.embedding.local_embedder.SentenceTransformer'):
            embedder = LocalEmbedder(model_name="Qwen/Qwen3-Embedding-0.6B")
            assert embedder.model_name == "Qwen/Qwen3-Embedding-0.6B"

    def test_output_dimensionality_default(self):
        """기본 출력 차원이 1024인지 확인"""
        from app.modules.core.embedding.local_embedder import LocalEmbedder

        with patch('app.modules.core.embedding.local_embedder.SentenceTransformer'):
            embedder = LocalEmbedder()
            assert embedder.output_dimensionality == 1024

    def test_output_dimensionality_custom(self):
        """커스텀 차원 설정이 동작하는지 확인"""
        from app.modules.core.embedding.local_embedder import LocalEmbedder

        with patch('app.modules.core.embedding.local_embedder.SentenceTransformer'):
            embedder = LocalEmbedder(output_dimensionality=512)
            assert embedder.output_dimensionality == 512


class TestLocalEmbedderEmbedDocuments:
    """embed_documents 메서드 테스트"""

    def test_embed_documents_returns_list_of_lists(self):
        """embed_documents가 list[list[float]]를 반환하는지 확인"""
        from app.modules.core.embedding.local_embedder import LocalEmbedder

        mock_model = MagicMock()
        # 2개 문서, 1024차원 벡터 반환
        mock_model.encode.return_value = np.random.rand(2, 1024).astype(np.float32)

        with patch('app.modules.core.embedding.local_embedder.SentenceTransformer', return_value=mock_model):
            embedder = LocalEmbedder()
            result = embedder.embed_documents(["문서1", "문서2"])

            assert isinstance(result, list)
            assert len(result) == 2
            assert isinstance(result[0], list)
            assert len(result[0]) == 1024

    def test_embed_documents_empty_list(self):
        """빈 리스트 입력 시 빈 리스트 반환"""
        from app.modules.core.embedding.local_embedder import LocalEmbedder

        mock_model = MagicMock()
        mock_model.encode.return_value = np.array([]).reshape(0, 1024)

        with patch('app.modules.core.embedding.local_embedder.SentenceTransformer', return_value=mock_model):
            embedder = LocalEmbedder()
            result = embedder.embed_documents([])

            assert result == []

    def test_embed_documents_korean_text(self):
        """한국어 텍스트 임베딩이 동작하는지 확인"""
        from app.modules.core.embedding.local_embedder import LocalEmbedder

        mock_model = MagicMock()
        mock_model.encode.return_value = np.random.rand(1, 1024).astype(np.float32)

        with patch('app.modules.core.embedding.local_embedder.SentenceTransformer', return_value=mock_model):
            embedder = LocalEmbedder()
            result = embedder.embed_documents(["안녕하세요, RAG 시스템입니다."])

            assert len(result) == 1
            assert len(result[0]) == 1024

    def test_embed_documents_batch_processing(self):
        """배치 처리가 올바르게 동작하는지 확인"""
        from app.modules.core.embedding.local_embedder import LocalEmbedder

        mock_model = MagicMock()
        # 배치 크기보다 큰 입력
        mock_model.encode.return_value = np.random.rand(150, 1024).astype(np.float32)

        with patch('app.modules.core.embedding.local_embedder.SentenceTransformer', return_value=mock_model):
            embedder = LocalEmbedder(batch_size=100)
            texts = [f"문서 {i}" for i in range(150)]
            result = embedder.embed_documents(texts)

            assert len(result) == 150


class TestLocalEmbedderEmbedQuery:
    """embed_query 메서드 테스트"""

    def test_embed_query_returns_list_of_floats(self):
        """embed_query가 list[float]를 반환하는지 확인"""
        from app.modules.core.embedding.local_embedder import LocalEmbedder

        mock_model = MagicMock()
        mock_model.encode.return_value = np.random.rand(1024).astype(np.float32)

        with patch('app.modules.core.embedding.local_embedder.SentenceTransformer', return_value=mock_model):
            embedder = LocalEmbedder()
            result = embedder.embed_query("검색 쿼리")

            assert isinstance(result, list)
            assert len(result) == 1024
            assert all(isinstance(x, float) for x in result)

    def test_embed_query_empty_string(self):
        """빈 문자열 입력 시 영벡터 반환"""
        from app.modules.core.embedding.local_embedder import LocalEmbedder

        mock_model = MagicMock()

        with patch('app.modules.core.embedding.local_embedder.SentenceTransformer', return_value=mock_model):
            embedder = LocalEmbedder()
            result = embedder.embed_query("")

            assert isinstance(result, list)
            assert len(result) == 1024
            assert all(x == 0.0 for x in result)


class TestLocalEmbedderValidation:
    """validate_embedding 메서드 테스트"""

    def test_validate_embedding_correct_dimension(self):
        """올바른 차원의 임베딩 검증 통과"""
        from app.modules.core.embedding.local_embedder import LocalEmbedder

        with patch('app.modules.core.embedding.local_embedder.SentenceTransformer'):
            embedder = LocalEmbedder(output_dimensionality=1024)
            embedding = [0.1] * 1024

            assert embedder.validate_embedding(embedding) is True

    def test_validate_embedding_wrong_dimension(self):
        """잘못된 차원의 임베딩 검증 실패"""
        from app.modules.core.embedding.local_embedder import LocalEmbedder

        with patch('app.modules.core.embedding.local_embedder.SentenceTransformer'):
            embedder = LocalEmbedder(output_dimensionality=1024)
            embedding = [0.1] * 512  # 잘못된 차원

            assert embedder.validate_embedding(embedding) is False


class TestLocalEmbedderAsync:
    """비동기 메서드 테스트"""

    @pytest.mark.asyncio
    async def test_aembed_documents(self):
        """비동기 문서 임베딩이 동작하는지 확인"""
        from app.modules.core.embedding.local_embedder import LocalEmbedder

        mock_model = MagicMock()
        mock_model.encode.return_value = np.random.rand(2, 1024).astype(np.float32)

        with patch('app.modules.core.embedding.local_embedder.SentenceTransformer', return_value=mock_model):
            embedder = LocalEmbedder()
            result = await embedder.aembed_documents(["문서1", "문서2"])

            assert len(result) == 2
            assert len(result[0]) == 1024

    @pytest.mark.asyncio
    async def test_aembed_query(self):
        """비동기 쿼리 임베딩이 동작하는지 확인"""
        from app.modules.core.embedding.local_embedder import LocalEmbedder

        mock_model = MagicMock()
        mock_model.encode.return_value = np.random.rand(1024).astype(np.float32)

        with patch('app.modules.core.embedding.local_embedder.SentenceTransformer', return_value=mock_model):
            embedder = LocalEmbedder()
            result = await embedder.aembed_query("검색 쿼리")

            assert len(result) == 1024


class TestLocalEmbedderNormalization:
    """L2 정규화 테스트"""

    def test_embeddings_are_normalized(self):
        """임베딩이 L2 정규화되어 있는지 확인"""
        from app.modules.core.embedding.local_embedder import LocalEmbedder

        mock_model = MagicMock()
        # 정규화되지 않은 벡터 (sentence-transformers가 정규화하므로 이미 정규화된 값 반환)
        normalized_vector = np.array([0.1] * 1024)
        normalized_vector = normalized_vector / np.linalg.norm(normalized_vector)
        mock_model.encode.return_value = normalized_vector.astype(np.float32)

        with patch('app.modules.core.embedding.local_embedder.SentenceTransformer', return_value=mock_model):
            embedder = LocalEmbedder(normalize=True)
            result = embedder.embed_query("테스트")

            # L2 norm이 1에 가까운지 확인
            norm = np.linalg.norm(result)
            assert abs(norm - 1.0) < 0.01, f"L2 norm should be ~1.0, got {norm}"


class TestLocalEmbedderErrorHandling:
    """에러 처리 테스트"""

    def test_model_loading_error_raises_exception(self):
        """모델 로딩 실패 시 적절한 예외 발생"""
        from app.modules.core.embedding.local_embedder import LocalEmbedder

        with patch('app.modules.core.embedding.local_embedder.SentenceTransformer') as mock_st:
            mock_st.side_effect = Exception("Model not found")

            with pytest.raises(Exception) as exc_info:
                LocalEmbedder()

            assert "Model not found" in str(exc_info.value)

    def test_graceful_degradation_on_encode_error(self):
        """encode 실패 시 graceful degradation (영벡터 반환)"""
        from app.modules.core.embedding.local_embedder import LocalEmbedder

        mock_model = MagicMock()
        mock_model.encode.side_effect = Exception("Encoding failed")

        with patch('app.modules.core.embedding.local_embedder.SentenceTransformer', return_value=mock_model):
            embedder = LocalEmbedder()
            result = embedder.embed_documents(["테스트"])

            # 영벡터 반환
            assert len(result) == 1
            assert len(result[0]) == 1024
            assert all(x == 0.0 for x in result[0])
