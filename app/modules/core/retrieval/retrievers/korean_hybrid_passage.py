"""Offline Korean passage retrieval with body-only BM25 and a local multilingual E5."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from app.modules.core.retrieval.bm25_engine import BM25Index, KoreanTokenizer

from .local_span_retriever import LocalSpanRetriever


class KoreanHybridPassageRetriever(LocalSpanRetriever):
    def __init__(
        self,
        docs: Sequence[Mapping[str, Any]],
        embedding_dir: str | Path,
        device: str = "cpu",
    ):
        records = {}
        for d in docs:
            if not all(isinstance(d.get(k), str) for k in ("id", "title", "content")):
                raise ValueError("Passages require string id, title and content")
            if not d["id"].strip() or not d["content"].strip() or d["id"] in records:
                raise ValueError("Passages require unique nonempty IDs and nonempty bodies")
            records[d["id"]] = dict(d)
        self.ids = sorted(records)
        self.docs = {k: records[k] for k in self.ids}
        self.device = device
        if not self.ids:
            return

        import numpy as np
        import torch
        from transformers import AutoModel, AutoTokenizer

        # A title may cover hundreds of passages. Only its body earns lexical credit.
        self.bm25 = BM25Index(KoreanTokenizer())
        self.bm25.build([{"id": k, "content": self.docs[k]["content"]} for k in self.ids])
        self.torch = torch
        self.tokenizer = AutoTokenizer.from_pretrained(embedding_dir, local_files_only=True)
        self.encoder = AutoModel.from_pretrained(embedding_dir, local_files_only=True, use_safetensors=True).eval()
        if device == "mps":
            self.encoder.half()
        self.encoder.to(device)
        inputs = [
            "passage: " + (d["title"] + ". " if d["title"] else "") + d["content"]
            for d in self.docs.values()
        ]
        self.vectors = np.concatenate([self.encode(inputs[i : i + 12]) for i in range(0, len(inputs), 12)])

    def rank(self, question: str, top_k: int = 8) -> list[str]:
        if top_k < 0:
            raise ValueError("top_k must be nonnegative")
        if not self.ids or top_k == 0 or not question.strip():
            return []
        _, ranked, _ = self.rankings(question, max(40, top_k))
        return ranked[:top_k]

    def rankings(self, question: str, depth: int = 40) -> tuple[list[str], list[str], dict[str, float]]:
        import numpy as np

        if not self.ids or not question.strip() or depth <= 0:
            return [], [], {}
        lexical = [d["id"] for d in self.bm25.search(question, depth)]
        vector = self.encode(["query: " + question])[0]
        dense = [self.ids[i] for i in np.argsort(-(self.vectors @ vector), kind="stable")[:depth]]
        scores: dict[str, float] = {}
        for ranking in (lexical, dense):
            for position, key in enumerate(ranking):
                scores[key] = scores.get(key, 0.0) + 1 / (60 + position)
        return lexical, sorted(scores, key=lambda key: (-scores[key], key)), scores
