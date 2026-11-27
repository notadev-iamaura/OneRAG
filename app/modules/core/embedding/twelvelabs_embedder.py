"""
TwelveLabs (Marengo) 멀티모달 임베더 구현체

TwelveLabs Marengo 모델을 사용하여 텍스트/이미지/오디오/비디오를 동일한
512차원 벡터 공간으로 임베딩합니다. 텍스트와 비디오 프레임이 같은 공간에
매핑되므로, 텍스트 쿼리로 영상 콘텐츠를 검색하는 멀티모달 RAG가 가능합니다.

이 모듈은 다른 임베더와 동일한 IEmbedder 계약(embed_documents/embed_query 등)을
구현하므로, EmbedderFactory의 provider="twelvelabs" 설정만으로 교체할 수 있습니다.

SDK는 지연 import 하며, 미설치 시 초기화 시점에 설치 안내 에러를 발생시킵니다
(코어 동작 영향 0):

    uv pip install "onerag[twelvelabs]"   # 또는 pip install "twelvelabs>=1.2.8"

사용 예시:
    embedder = TwelveLabsEmbedder(api_key="tlk_...")
    query_vector = embedder.embed_query("a red car driving on a highway")
    doc_vectors = embedder.embed_documents(["scene description 1", "scene 2"])

참고: https://docs.twelvelabs.io  (무료 티어 API 키: https://twelvelabs.io)
"""

from __future__ import annotations

import asyncio
from typing import Any

from ....lib.logger import get_logger
from .interfaces import BaseEmbedder

logger = get_logger(__name__)

# TwelveLabs Marengo 멀티모달 임베딩 모델 (텍스트/이미지/오디오/비디오 공통 공간)
TWELVELABS_DEFAULT_MODEL = "marengo3.0"
# Marengo 임베딩은 512차원 고정 (모델이 차원 파라미터를 받지 않음)
TWELVELABS_EMBEDDING_DIM = 512


class TwelveLabsEmbedder(BaseEmbedder):
    """
    TwelveLabs Marengo 멀티모달 임베더

    공식 SDK(twelvelabs>=1.2.8)의 embed.create()를 사용해 텍스트를 512차원
    벡터로 변환합니다. 동일 모델이 비디오/이미지/오디오도 같은 공간에 임베딩하므로,
    이 임베더로 인덱싱한 텍스트 코퍼스를 영상 검색 쿼리와 함께 사용할 수 있습니다.

    Attributes:
        model_name: Marengo 모델 이름 (기본: marengo3.0)
        output_dimensionality: 출력 벡터 차원 (Marengo 고정값 512)
    """

    def __init__(
        self,
        api_key: str | None = None,
        model_name: str = TWELVELABS_DEFAULT_MODEL,
        output_dimensionality: int = TWELVELABS_EMBEDDING_DIM,
        **kwargs: Any,
    ) -> None:
        """
        TwelveLabsEmbedder 초기화

        Args:
            api_key: TwelveLabs API 키 (미지정 시 TWELVELABS_API_KEY 환경변수 사용)
            model_name: Marengo 모델 이름 (기본: marengo3.0)
            output_dimensionality: 출력 차원 (Marengo는 512 고정)

        Raises:
            ImportError: twelvelabs SDK 미설치 시
            ValueError: API 키가 없을 때
        """
        super().__init__(
            model_name=model_name,
            output_dimensionality=output_dimensionality,
            api_key=api_key,
        )

        try:
            from twelvelabs import TwelveLabs
        except ImportError as exc:  # pragma: no cover - 환경 의존
            raise ImportError(
                "TwelveLabs 임베더를 사용하려면 twelvelabs SDK가 필요합니다. "
                'uv pip install "onerag[twelvelabs]" '
                '또는 pip install "twelvelabs>=1.2.8"로 설치하세요.'
            ) from exc

        if not api_key:
            raise ValueError(
                "TwelveLabs API 키가 필요합니다. embeddings.twelvelabs.api_key 설정 "
                "또는 TWELVELABS_API_KEY 환경변수를 지정하세요. "
                "무료 API 키: https://twelvelabs.io"
            )

        self._client = TwelveLabs(api_key=api_key)

        logger.info(
            f"✅ TwelveLabsEmbedder 초기화 완료: model={model_name}, "
            f"dim={output_dimensionality}"
        )

    def _embed_text(self, text: str) -> list[float]:
        """단일 텍스트를 Marengo 임베딩 벡터로 변환한다.

        Returns:
            512차원 임베딩 벡터. 실패 시 영벡터(graceful degradation).
        """
        if not text:
            return [0.0] * self._output_dimensionality

        try:
            response = self._client.embed.create(
                model_name=self._model_name,
                text=text,
            )
            segments = response.text_embedding.segments or []
            vector = segments[0].float_ if segments else None
            if not vector:
                logger.error("❌ TwelveLabs 임베딩 응답에 벡터가 없습니다")
                return [0.0] * self._output_dimensionality
            return list(vector)
        except Exception as e:
            logger.error(f"❌ TwelveLabs 임베딩 실패: {e}")
            return [0.0] * self._output_dimensionality

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """
        문서 리스트를 임베딩 벡터로 변환

        Marengo embed API는 텍스트당 단일 호출이므로 순차 처리합니다.

        Args:
            texts: 임베딩할 텍스트 리스트

        Returns:
            임베딩 벡터 리스트 (list[list[float]])
        """
        if not texts:
            return []
        return [self._embed_text(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        """
        단일 쿼리를 임베딩 벡터로 변환

        Args:
            text: 임베딩할 쿼리 텍스트

        Returns:
            임베딩 벡터 (list[float])
        """
        return self._embed_text(text)

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        """
        비동기 문서 임베딩 (동기 메서드를 스레드로 오프로드)

        Note:
            SDK가 네이티브 async를 노출하지 않으므로 to_thread로 래핑하여
            이벤트 루프를 블로킹하지 않는다.
        """
        return await asyncio.to_thread(self.embed_documents, texts)

    async def aembed_query(self, text: str) -> list[float]:
        """비동기 쿼리 임베딩 (동기 메서드를 스레드로 오프로드)"""
        return await asyncio.to_thread(self.embed_query, text)

    def validate_embedding(self, embedding: list[float]) -> bool:
        """
        임베딩 벡터 유효성 검증 (차원 일치 여부)

        Args:
            embedding: 검증할 임베딩 벡터

        Returns:
            유효 여부 (True/False)
        """
        if not embedding:
            return False
        if len(embedding) != self._output_dimensionality:
            logger.warning(
                f"⚠️ 임베딩 차원 불일치: "
                f"expected={self._output_dimensionality}, got={len(embedding)}"
            )
            return False
        return True
