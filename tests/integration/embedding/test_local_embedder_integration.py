"""
LocalEmbedder 통합 테스트

실제 모델을 로드하여 임베딩이 제대로 생성되는지 검증합니다.
이 테스트는 모델 다운로드가 필요하므로 첫 실행 시 시간이 걸릴 수 있습니다.

pytest -m integration tests/integration/embedding/ -v
"""

import numpy as np
import pytest

# sentence-transformers는 선택 의존성(extra: local-embedding)이다. 미설치 환경에서는
# 모듈 전체를 건너뛰어 ERROR가 아닌 SKIP으로 보고한다.
pytest.importorskip("sentence_transformers")


@pytest.mark.integration
class TestLocalEmbedderIntegration:
    """LocalEmbedder 실제 모델 통합 테스트"""

    @pytest.fixture(scope="class")
    def embedder(self):
        """
        클래스 범위 fixture로 임베더 초기화
        모델 로딩 시간을 줄이기 위해 한 번만 초기화
        """
        from app.modules.core.embedding.local_embedder import LocalEmbedder

        return LocalEmbedder(
            model_name="Qwen/Qwen3-Embedding-0.6B",
            output_dimensionality=1024,
            normalize=True,
        )

    def test_embed_single_document(self, embedder):
        """단일 문서 임베딩 테스트"""
        text = "RAG_Standard는 최신 RAG 기술을 통합한 시스템입니다."
        embeddings = embedder.embed_documents([text])

        assert len(embeddings) == 1
        assert len(embeddings[0]) == 1024
        # 정규화된 벡터의 L2 norm은 1에 가까워야 함
        norm = np.linalg.norm(embeddings[0])
        assert 0.99 < norm < 1.01

    def test_embed_multiple_documents(self, embedder):
        """다중 문서 배치 임베딩 테스트"""
        texts = [
            "첫 번째 문서입니다.",
            "두 번째 문서입니다.",
            "세 번째 문서입니다.",
        ]
        embeddings = embedder.embed_documents(texts)

        assert len(embeddings) == 3
        for emb in embeddings:
            assert len(emb) == 1024

    def test_embed_query(self, embedder):
        """쿼리 임베딩 테스트"""
        query = "RAG 시스템이란 무엇인가요?"
        embedding = embedder.embed_query(query)

        assert len(embedding) == 1024
        # 정규화 확인
        norm = np.linalg.norm(embedding)
        assert 0.99 < norm < 1.01

    def test_semantic_similarity(self, embedder):
        """의미적 유사도 테스트"""
        # 유사한 문장
        text1 = "인공지능은 컴퓨터가 인간처럼 학습하는 기술입니다."
        text2 = "AI는 기계가 사람처럼 배우는 기술입니다."
        # 다른 주제의 문장
        text3 = "오늘 날씨가 매우 좋습니다."

        embeddings = embedder.embed_documents([text1, text2, text3])

        # 코사인 유사도 계산
        def cosine_similarity(a, b):
            return np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))

        sim_1_2 = cosine_similarity(embeddings[0], embeddings[1])
        sim_1_3 = cosine_similarity(embeddings[0], embeddings[2])

        # text1과 text2는 유사해야 함 (> 0.7)
        assert sim_1_2 > 0.7, f"유사한 문장의 유사도가 너무 낮음: {sim_1_2}"
        # text1과 text3는 덜 유사해야 함 (< sim_1_2)
        assert sim_1_3 < sim_1_2, "다른 주제의 유사도가 더 높음"

    def test_korean_text_embedding(self, embedder):
        """한국어 텍스트 임베딩 테스트"""
        korean_texts = [
            "안녕하세요, 만나서 반갑습니다.",
            "RAG 시스템은 검색 증강 생성을 의미합니다.",
            "대한민국 서울은 아름다운 도시입니다.",
        ]
        embeddings = embedder.embed_documents(korean_texts)

        assert len(embeddings) == 3
        for emb in embeddings:
            assert len(emb) == 1024
            # 각 임베딩이 고유해야 함 (완전히 동일하지 않음)
            assert not np.allclose(embeddings[0], emb) or emb is embeddings[0]

    def test_english_text_embedding(self, embedder):
        """영어 텍스트 임베딩 테스트"""
        english_texts = [
            "Hello, nice to meet you.",
            "RAG stands for Retrieval-Augmented Generation.",
            "Seoul is a beautiful city in South Korea.",
        ]
        embeddings = embedder.embed_documents(english_texts)

        assert len(embeddings) == 3
        for emb in embeddings:
            assert len(emb) == 1024

    def test_multilingual_similarity(self, embedder):
        """다국어 의미 유사도 테스트"""
        # 같은 의미의 한국어/영어 문장
        korean = "인공지능은 미래 기술입니다."
        english = "Artificial intelligence is the technology of the future."
        # 다른 주제
        different = "오늘 점심은 김치찌개입니다."

        embeddings = embedder.embed_documents([korean, english, different])

        def cosine_similarity(a, b):
            return np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))

        sim_kr_en = cosine_similarity(embeddings[0], embeddings[1])
        sim_kr_diff = cosine_similarity(embeddings[0], embeddings[2])

        # 한국어-영어 같은 의미 문장은 유사해야 함
        assert sim_kr_en > 0.5, f"다국어 유사도가 너무 낮음: {sim_kr_en}"
        # 다른 주제와의 유사도보다 높아야 함
        assert sim_kr_en > sim_kr_diff, "다국어 유사도가 다른 주제보다 낮음"

    def test_empty_string_handling(self, embedder):
        """빈 문자열 처리 테스트"""
        texts = ["정상 텍스트", "", "또 다른 텍스트"]
        # 빈 문자열도 처리 가능해야 함
        embeddings = embedder.embed_documents(texts)
        assert len(embeddings) == 3

    def test_long_text_embedding(self, embedder):
        """긴 텍스트 임베딩 테스트"""
        # 긴 텍스트 생성 (약 1000자)
        long_text = "RAG 시스템은 검색 증강 생성의 약자입니다. " * 50
        embeddings = embedder.embed_documents([long_text])

        assert len(embeddings) == 1
        assert len(embeddings[0]) == 1024

    @pytest.mark.asyncio
    async def test_async_embed_query(self, embedder):
        """비동기 쿼리 임베딩 테스트"""
        query = "비동기 임베딩 테스트"
        embedding = await embedder.aembed_query(query)

        assert len(embedding) == 1024
        # 정규화 확인
        norm = np.linalg.norm(embedding)
        assert 0.99 < norm < 1.01
