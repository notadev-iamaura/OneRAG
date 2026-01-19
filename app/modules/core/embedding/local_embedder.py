"""
로컬 임베더 구현

sentence-transformers를 사용하여 로컬에서 임베딩을 생성합니다.
API 키 없이 동작하며, Quickstart 환경에서 사용됩니다.

지원 모델:
- Qwen/Qwen3-Embedding-0.6B (기본): 1024차원, 32K 컨텍스트, 100+ 언어
- intfloat/multilingual-e5-small: 384차원, 경량

사용 예시:
    embedder = LocalEmbedder()
    vectors = embedder.embed_documents(["문서1", "문서2"])
    query_vector = embedder.embed_query("검색 쿼리")
"""

from __future__ import annotations

import logging
from typing import Any

from sentence_transformers import SentenceTransformer

from app.modules.core.embedding.interfaces import BaseEmbedder

logger = logging.getLogger(__name__)


# 지원 모델 정보
SUPPORTED_LOCAL_MODELS: dict[str, dict[str, Any]] = {
    "Qwen/Qwen3-Embedding-0.6B": {
        "dimensions": 1024,
        "max_seq_length": 32768,
        "description": "Qwen3 임베딩 모델 (0.6B 파라미터, 다국어 지원)",
    },
    "intfloat/multilingual-e5-small": {
        "dimensions": 384,
        "max_seq_length": 512,
        "description": "경량 다국어 임베딩 모델",
    },
}

# 기본 모델
DEFAULT_LOCAL_MODEL = "Qwen/Qwen3-Embedding-0.6B"


class LocalEmbedder(BaseEmbedder):
    """
    로컬 임베더 클래스

    sentence-transformers를 사용하여 로컬에서 임베딩을 생성합니다.
    첫 실행 시 HuggingFace Hub에서 모델을 자동 다운로드합니다.

    Attributes:
        model: SentenceTransformer 모델 인스턴스
        normalize: L2 정규화 여부 (기본: True)
        batch_size: 배치 처리 크기 (기본: 32)
    """

    def __init__(
        self,
        model_name: str = DEFAULT_LOCAL_MODEL,
        output_dimensionality: int | None = None,
        batch_size: int = 32,
        normalize: bool = True,
        device: str | None = None,
        **kwargs: Any,
    ) -> None:
        """
        LocalEmbedder 초기화

        Args:
            model_name: HuggingFace 모델 이름 (기본: Qwen/Qwen3-Embedding-0.6B)
            output_dimensionality: 출력 벡터 차원 (None이면 모델 기본값 사용)
            batch_size: 배치 처리 크기 (기본: 32)
            normalize: L2 정규화 여부 (기본: True)
            device: 연산 디바이스 (None이면 자동 선택, "cpu" 또는 "cuda")

        Raises:
            Exception: 모델 로딩 실패 시
        """
        # 모델 정보 확인
        model_info = SUPPORTED_LOCAL_MODELS.get(model_name, {})
        default_dim = model_info.get("dimensions", 1024)

        # 차원 설정 (명시적 지정 > 모델 기본값)
        actual_dim = output_dimensionality or default_dim

        # 부모 클래스 초기화
        super().__init__(
            model_name=model_name,
            output_dimensionality=actual_dim,
            api_key=None,  # 로컬 모델은 API 키 불필요
        )

        self._batch_size = batch_size
        self._normalize = normalize
        self._device = device

        # 모델 로드 (첫 실행 시 자동 다운로드)
        logger.info(f"🔄 로컬 임베딩 모델 로딩 중: {model_name}")
        try:
            self._model = SentenceTransformer(
                model_name,
                device=device,
                trust_remote_code=True,  # Qwen 모델 필요
            )
            logger.info(
                f"✅ 로컬 임베더 초기화 완료: model={model_name}, "
                f"dim={actual_dim}, device={self._model.device}"
            )
        except Exception as e:
            logger.error(f"❌ 로컬 임베딩 모델 로딩 실패: {e}")
            raise

    @property
    def batch_size(self) -> int:
        """배치 처리 크기"""
        return self._batch_size

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """
        문서 리스트를 임베딩 벡터로 변환

        Args:
            texts: 임베딩할 텍스트 리스트

        Returns:
            임베딩 벡터 리스트 (list[list[float]])
        """
        if not texts:
            return []

        try:
            # sentence-transformers로 임베딩 생성
            embeddings = self._model.encode(
                texts,
                batch_size=self._batch_size,
                normalize_embeddings=self._normalize,
                show_progress_bar=False,
                convert_to_numpy=True,
            )

            # numpy array → list[list[float]] 변환
            result: list[list[float]] = embeddings.tolist()

            logger.debug(f"📊 문서 {len(texts)}개 임베딩 완료 (dim={len(result[0])})")
            return result

        except Exception as e:
            logger.error(f"❌ 문서 임베딩 실패: {e}")
            # graceful degradation: 영벡터 반환
            return [[0.0] * self._output_dimensionality for _ in texts]

    def embed_query(self, text: str) -> list[float]:
        """
        단일 쿼리를 임베딩 벡터로 변환

        Args:
            text: 임베딩할 쿼리 텍스트

        Returns:
            임베딩 벡터 (list[float])
        """
        if not text:
            return [0.0] * self._output_dimensionality

        try:
            # 단일 쿼리 임베딩
            embedding = self._model.encode(
                text,
                normalize_embeddings=self._normalize,
                show_progress_bar=False,
                convert_to_numpy=True,
            )

            # numpy array → list[float] 변환
            result: list[float] = embedding.tolist()

            logger.debug(f"📊 쿼리 임베딩 완료 (dim={len(result)})")
            return result

        except Exception as e:
            logger.error(f"❌ 쿼리 임베딩 실패: {e}")
            return [0.0] * self._output_dimensionality

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        """
        비동기 문서 임베딩 (동기 메서드 래핑)

        Note:
            sentence-transformers는 네이티브 비동기를 지원하지 않으므로
            동기 메서드를 래핑합니다.
        """
        return self.embed_documents(texts)

    async def aembed_query(self, text: str) -> list[float]:
        """
        비동기 쿼리 임베딩 (동기 메서드 래핑)
        """
        return self.embed_query(text)

    def validate_embedding(self, embedding: list[float]) -> bool:
        """
        임베딩 벡터 유효성 검증

        Args:
            embedding: 검증할 임베딩 벡터

        Returns:
            유효 여부 (True/False)
        """
        if not embedding:
            return False

        # 차원 검증
        if len(embedding) != self._output_dimensionality:
            logger.warning(
                f"⚠️ 임베딩 차원 불일치: "
                f"expected={self._output_dimensionality}, got={len(embedding)}"
            )
            return False

        return True
