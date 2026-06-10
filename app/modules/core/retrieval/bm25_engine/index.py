"""
BM25 검색 인덱스

rank-bm25 라이브러리를 래핑하여 Python 기반 BM25 키워드 검색을 제공합니다.
Weaviate/Qdrant 등 DB 내장 BM25가 없는 환경에서 사용됩니다.

의존성:
- rank-bm25: pip install rank-bm25 (선택적)
- KoreanTokenizer: 한국어 형태소 분석 (Task 1에서 구현)
"""

from __future__ import annotations

import logging
import math
from typing import Any

from app.modules.core.retrieval.bm25_engine.tokenizer import Tokenizer

logger = logging.getLogger(__name__)


class BM25Index:
    """
    rank-bm25 기반 BM25 검색 인덱스

    문서를 토큰화하여 BM25 인덱스를 구축하고,
    쿼리에 대한 키워드 기반 점수를 계산합니다.

    Args:
        tokenizer: BM25 토크나이저 (Tokenizer Protocol — 언어별 구현 주입)
    """

    def __init__(self, tokenizer: Tokenizer) -> None:
        self._tokenizer = tokenizer
        self._bm25 = None
        self._documents: list[dict[str, Any]] = []
        self._tokenized_corpus: list[list[str]] = []

        logger.info("BM25Index 초기화 완료")

    @property
    def document_count(self) -> int:
        """인덱싱된 문서 수"""
        return len(self._documents)

    def build(self, documents: list[dict[str, Any]]) -> None:
        """
        문서 리스트로 BM25 인덱스 구축

        Args:
            documents: 인덱싱할 문서 리스트 (id, content, metadata 필드)
        """
        if not documents:
            self._documents = []
            self._tokenized_corpus = []
            self._bm25 = None
            logger.info("BM25Index: 빈 인덱스 구축")
            return

        try:
            from rank_bm25 import BM25Plus
        except ImportError as e:
            raise ImportError(
                "BM25Index를 사용하려면 rank-bm25가 필요합니다. "
                "설치: uv add rank-bm25 또는 pip install rank-bm25"
            ) from e

        self._documents = documents
        contents = [doc["content"] for doc in documents]
        self._tokenized_corpus = self._tokenizer.tokenize_batch(contents)
        # BM25Plus: BM25Okapi 대비 IDF 하한선(delta)이 있어
        # 소규모 코퍼스에서도 안정적인 점수를 반환합니다.
        self._bm25 = BM25Plus(self._tokenized_corpus)
        logger.info(f"BM25Index: {len(documents)}개 문서 인덱싱 완료")

    def search(self, query: str, top_k: int = 10) -> list[dict[str, Any]]:
        """
        BM25 키워드 검색 수행

        Args:
            query: 검색 쿼리
            top_k: 반환할 최대 결과 수

        Returns:
            검색 결과 리스트 (id, content, score, metadata 포함)
        """
        if self._bm25 is None or not self._documents:
            return []

        query_tokens = self._tokenizer.tokenize(query)
        if not query_tokens:
            return []

        raw_scores = self._bm25.get_scores(query_tokens)

        results: list[dict[str, Any]] = []
        for idx, raw_score in enumerate(raw_scores):
            if raw_score > 0:
                normalized_score = self._normalize_score(raw_score)
                doc = self._documents[idx]
                results.append({
                    "id": doc["id"],
                    "content": doc["content"],
                    "score": normalized_score,
                    "metadata": doc.get("metadata", {}),
                })

        # 점수 기준 내림차순 정렬
        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:top_k]

    @staticmethod
    def _normalize_score(raw_score: float) -> float:
        """BM25 원시 점수를 0~1 범위로 정규화 (sigmoid 함수)"""
        return 1.0 / (1.0 + math.exp(-raw_score))
