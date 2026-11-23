"""
BM25 검색 인덱스

rank-bm25 라이브러리를 래핑하여 Python 기반 BM25 키워드 검색을 제공합니다.
Weaviate/Qdrant 등 DB 내장 BM25가 없는 환경에서 사용됩니다.

의존성:
- rank-bm25: pip install rank-bm25 (선택적)
- KoreanTokenizer: 한국어 형태소 분석 (Task 1에서 구현)
"""

from __future__ import annotations

import math
from array import array
from heapq import nsmallest
from threading import Lock
from typing import Any

from app.lib.logger import get_logger
from app.modules.core.retrieval.bm25_engine.linked_titles import prioritize_linked_titles
from app.modules.core.retrieval.bm25_engine.tokenizer import Tokenizer

logger = get_logger(__name__)


class BM25Index:
    """
    rank-bm25 기반 BM25 검색 인덱스

    문서를 토큰화하여 BM25 인덱스를 구축하고,
    쿼리에 대한 키워드 기반 점수를 계산합니다.

    Args:
        tokenizer: BM25 토크나이저 (Tokenizer Protocol — 언어별 구현 주입)
    """

    def __init__(self, tokenizer: Tokenizer, *, linked_titles: bool = False) -> None:
        self._tokenizer = tokenizer
        self._linked_titles = linked_titles
        self._bm25 = None
        self._documents: list[dict[str, Any]] = []
        self._tokenized_corpus: list[list[str]] = []
        self._snapshot_lock = Lock()
        self._postings: dict[str, tuple[array, array]] = {}

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
            self._postings = {}
            self._documents = []
            self._tokenized_corpus = []
            self._bm25 = None
            logger.info("BM25Index: 빈 인덱스 구축")
            return

        # Index human-readable titles as a separate field. The text returned
        # to the generator stays identical to the stored document content.
        contents = []
        for doc in documents:
            title = (doc.get("metadata") or {}).get("title")
            contents.append(f"{title}\n{doc['content']}" if isinstance(title, str) and title else doc["content"])
        self.restore_tokenized(documents, self._tokenizer.tokenize_batch(contents))

    def restore_tokenized(self, documents: list[dict[str, Any]], tokens: list[list[str]]) -> None:
        """Build every scoring structure from a persisted or freshly tokenized corpus."""
        if len(documents) != len(tokens):
            raise ValueError("Each BM25 document needs one token list")
        try:
            from rank_bm25 import BM25Plus
        except ImportError as e:
            raise ImportError(
                "BM25Index를 사용하려면 rank-bm25가 필요합니다. "
                "설치: uv add rank-bm25 또는 pip install rank-bm25"
            ) from e

        # BM25Plus: BM25Okapi 대비 IDF 하한선(delta)이 있어
        # 소규모 코퍼스에서도 안정적인 점수를 반환합니다.
        index = BM25Plus(tokens) if any(tokens) else None
        postings: dict[str, tuple[array, array]] = {}
        if index is not None:
            # The length normalization and IDF contribution only depend on the
            # corpus. Keep compact posting lists for the documents that match.
            for position, frequencies in enumerate(index.doc_freqs):
                norm = index.k1 * (1 - index.b + index.b * index.doc_len[position] / index.avgdl)
                for term, frequency in frequencies.items():
                    if term not in postings:
                        postings[term] = (array("I"), array("d"))
                    positions, weights = postings[term]
                    positions.append(position)
                    weights.append(index.idf[term] * (frequency * (index.k1 + 1) / (norm + frequency)))
        self._postings = postings
        self._bm25 = index
        self._tokenized_corpus = tokens
        self._documents = documents
        logger.info(f"BM25Index: {len(documents)}개 문서 인덱싱 완료")

    def search_snapshot(
        self, documents: list[dict[str, Any]], query: str, top_k: int
    ) -> list[dict[str, Any]]:
        """Score exactly the visible Chroma snapshot, reusing tokens on repeated reads."""
        with self._snapshot_lock:
            if documents != self._documents:
                self.build(documents)
            return self.search(query, top_k)

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

        scores: dict[int, float] = {}
        baseline = 0.0
        for term in query_tokens:
            if term not in self._postings:
                continue
            baseline += self._bm25.idf[term] * self._bm25.delta
            positions, weights = self._postings[term]
            for i, weight in zip(positions, weights, strict=True):
                scores[i] = scores.get(i, 0.0) + weight
        # Sigmoid saturates at 1.0 for long queries. Normalize only after ranking.
        candidate_k = max(top_k, 10) if self._linked_titles and top_k > 3 else top_k
        ranked = nsmallest(candidate_k, scores, key=lambda i: (-scores[i], self._documents[i]["id"]))
        hits = [
            {
                "id": self._documents[i]["id"],
                "content": self._documents[i]["content"],
                "score": self._normalize_score(baseline + scores[i]),
                "metadata": self._documents[i].get("metadata", {}),
            }
            for i in ranked
        ]
        if self._linked_titles and top_k > 3:
            hits = prioritize_linked_titles(hits[:10]) + hits[10:]
        return hits[:top_k]

    @staticmethod
    def _normalize_score(raw_score: float) -> float:
        """BM25 원시 점수를 0~1 범위로 정규화 (sigmoid 함수)"""
        return 1.0 / (1.0 + math.exp(-raw_score))
