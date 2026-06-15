"""
Gemini Embedding 구현체

Google Gemini Embedding API를 사용한 임베딩 생성
models/gemini-embedding-001 모델로 벡터 생성 및 L2 정규화 수행
"""

import asyncio
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    class Embeddings:  # pragma: no cover - type-checking shim
        pass
else:
    from langchain.embeddings.base import Embeddings

from ....lib.logger import get_logger
from ._retry import resolve_retry_settings, retry_embed
from .interfaces import BaseEmbedder
from .vector_ops import l2_norm as _l2_norm

logger = get_logger(__name__)

genai: Any | None = None


def _get_genai() -> Any:
    global genai
    if genai is None:
        import google.generativeai as _genai

        genai = _genai
    return genai


class GeminiEmbedder(BaseEmbedder, Embeddings):
    """
    Google Gemini Embedding 001 모델 래퍼

    BaseEmbedder와 LangChain Embeddings를 모두 구현하여
    기존 코드와의 호환성 유지 및 확장 가능성 확보
    """

    def __init__(
        self,
        google_api_key: str,
        model_name: str = "models/gemini-embedding-001",
        output_dimensionality: int = 1536,
        batch_size: int = 100,
        task_type: Literal["RETRIEVAL_DOCUMENT", "RETRIEVAL_QUERY"] | None = None,
    ):
        """
        Gemini Embedder 초기화

        Args:
            google_api_key: Google API 키
            model_name: 모델 이름 (기본: models/gemini-embedding-001)
            output_dimensionality: 출력 차원 (기본: 1536)
            batch_size: 배치 임베딩 생성 시 배치 크기
            task_type: 기본 태스크 타입 (메서드에서 오버라이드 가능)
        """
        # BaseEmbedder 초기화
        super().__init__(
            model_name=model_name,
            output_dimensionality=output_dimensionality,
            api_key=google_api_key,
        )

        # Gemini API 설정
        _get_genai().configure(api_key=google_api_key)

        self.batch_size = batch_size
        self.default_task_type = task_type or "RETRIEVAL_DOCUMENT"

        # 임베딩 API 재시도 설정(환경변수 폴백). 429/5xx + Retry-After 지수 backoff.
        (
            self._retry_max_retries,
            self._retry_base_seconds,
            self._retry_max_seconds,
        ) = resolve_retry_settings()

        logger.info(f"Initialized GeminiEmbedder: model={model_name}, dim={output_dimensionality}")

    def _normalize_vector(self, vector: list[float]) -> list[float]:
        """
        L2 정규화 수행 (필수)

        1536차원 출력은 정규화되지 않은 상태로 반환되므로 반드시 정규화 필요

        Args:
            vector: 정규화할 벡터

        Returns:
            L2 정규화된 벡터
        """
        # ⚠️ OpenAI 임베더와 정규화 본체가 의도적으로 다름:
        # Gemini는 정규화되지 않은 벡터를 반환하므로 norm>0이면 "항상" 재계산한다.
        # (OpenAI는 이미 정규화된 벡터를 반환해 norm≈1이면 재계산을 생략 — 통합 금지)
        norm = _l2_norm(vector)

        if norm > 0:
            return [value / norm for value in vector]

        logger.warning("Zero norm vector encountered, returning as-is")
        return vector

    def _normalize_and_validate(self, embedding: list[float]) -> list[float]:
        """임베딩을 정규화하고 기대 차원과 일치하는지 확인."""
        normalized = self._normalize_vector(embedding)
        if len(normalized) != self.output_dimensionality:
            raise RuntimeError(
                f"Unexpected embedding dimension: {len(normalized)} != "
                f"{self.output_dimensionality}"
            )
        return normalized

    def _batch_embed(self, texts: list[str], task_type: str) -> list[list[float]]:
        """
        배치 단위로 임베딩 생성 (동기 버전)

        Args:
            texts: 임베딩할 텍스트 리스트
            task_type: Gemini API task type (RETRIEVAL_DOCUMENT or RETRIEVAL_QUERY)

        Returns:
            정규화된 임베딩 벡터 리스트
        """
        embeddings = []

        # 배치 처리
        for i in range(0, len(texts), self.batch_size):
            batch = texts[i : i + self.batch_size]

            # batch를 인자로 받는 지역 함수로 루프 변수 캡처 문제(B023)를 차단한다.
            def _embed_batch(batch: list[str] = batch) -> Any:
                return _get_genai().embed_content(
                    model=self.model_name,
                    content=batch,
                    task_type=task_type,
                    output_dimensionality=self.output_dimensionality,
                )

            try:
                # Gemini API 호출 (429/5xx 일시적 오류는 지수 backoff로 재시도)
                result = retry_embed(
                    _embed_batch,
                    max_retries=self._retry_max_retries,
                    base_seconds=self._retry_base_seconds,
                    max_seconds=self._retry_max_seconds,
                )

                # 결과가 단일 임베딩인 경우와 리스트인 경우 처리
                if "embedding" in result:
                    # 배치가 1개인 경우와 여러 개인 경우 구분
                    if len(batch) == 1:
                        # 단일 텍스트 처리
                        normalized = self._normalize_and_validate(result["embedding"])
                        embeddings.append(normalized)
                    else:
                        # 여러 텍스트를 한 번에 처리한 경우
                        # result['embedding']은 리스트의 리스트
                        for embedding in result["embedding"]:
                            if isinstance(embedding, list):
                                normalized = self._normalize_and_validate(embedding)
                                embeddings.append(normalized)
                elif "embeddings" in result:
                    # 이 경우는 실제로 발생하지 않지만 안전을 위해 유지
                    for embedding in result["embeddings"]:
                        normalized = self._normalize_and_validate(embedding)
                        embeddings.append(normalized)
                else:
                    raise RuntimeError(f"Unexpected result format: {result.keys()}")

            except Exception as e:
                logger.error(f"Error generating embeddings for batch {i//self.batch_size}: {e}")
                raise RuntimeError(
                    f"Google Gemini embedding generation failed for batch "
                    f"{i // self.batch_size}"
                ) from e

        return embeddings

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """
        문서 임베딩 생성 (RETRIEVAL_DOCUMENT 타입)

        Args:
            texts: 임베딩할 문서 텍스트 리스트

        Returns:
            L2 정규화된 1536차원 임베딩 벡터 리스트
        """
        if not texts:
            return []

        logger.info(f"Embedding {len(texts)} documents with task_type=RETRIEVAL_DOCUMENT")

        # 배치 처리로 임베딩 생성
        embeddings = self._batch_embed(texts, "RETRIEVAL_DOCUMENT")

        logger.info(f"Generated {len(embeddings)} document embeddings")
        return embeddings

    def embed_query(self, text: str) -> list[float]:
        """
        쿼리 임베딩 생성 (RETRIEVAL_QUERY 타입)

        Args:
            text: 임베딩할 쿼리 텍스트

        Returns:
            L2 정규화된 1536차원 임베딩 벡터
        """
        logger.debug("Embedding query with task_type=RETRIEVAL_QUERY")

        try:
            # 단일 쿼리 임베딩 (429/5xx 일시적 오류는 지수 backoff로 재시도)
            result = retry_embed(
                lambda: _get_genai().embed_content(
                    model=self.model_name,
                    content=text,
                    task_type="RETRIEVAL_QUERY",
                    output_dimensionality=self.output_dimensionality,
                ),
                max_retries=self._retry_max_retries,
                base_seconds=self._retry_base_seconds,
                max_seconds=self._retry_max_seconds,
            )

            # L2 정규화 수행
            embedding = result.get("embedding", [])
            return self._normalize_and_validate(embedding)

        except Exception as e:
            logger.error(f"Error generating query embedding: {e}")
            raise RuntimeError("Google Gemini query embedding generation failed") from e

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        """
        비동기 문서 임베딩 생성

        Args:
            texts: 임베딩할 문서 텍스트 리스트

        Returns:
            L2 정규화된 1536차원 임베딩 벡터 리스트
        """
        # 동기 메서드를 비동기로 실행
        return await asyncio.to_thread(self.embed_documents, texts)

    async def aembed_query(self, text: str) -> list[float]:
        """
        비동기 쿼리 임베딩 생성

        Args:
            text: 임베딩할 쿼리 텍스트

        Returns:
            L2 정규화된 1536차원 임베딩 벡터
        """
        # 동기 메서드를 비동기로 실행
        return await asyncio.to_thread(self.embed_query, text)

    def validate_embedding(self, embedding: list[float]) -> bool:
        """
        임베딩 벡터 검증

        Args:
            embedding: 검증할 임베딩 벡터

        Returns:
            검증 성공 여부
        """
        # 차원 확인
        if not self._validate_dimension(embedding):
            logger.error(f"Invalid dimension: {len(embedding)} != {self.output_dimensionality}")
            return False

        # L2 norm 확인 (정규화 여부)
        norm = _l2_norm(embedding)
        if abs(norm - 1.0) > 0.01:  # 허용 오차
            logger.warning(f"Vector not normalized: norm={norm}")
            return False

        return True
