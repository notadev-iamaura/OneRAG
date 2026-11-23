"""In-memory lexical/E5 search over locally supplied passages for extractive QA."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from app.modules.core.retrieval.interfaces import SearchResult


class LocalSpanRetriever:
    """Build one local corpus index and expose retrieval through the ordinary asynchronous search interface."""
    def __init__(self, docs: dict[str, dict[str, Any]], embed_dir: str | Path, device: str = "cpu"):
        import numpy as np
        import torch
        from transformers import AutoModel, AutoTokenizer

        from app.modules.core.retrieval.bm25_engine import BM25Index
        from app.modules.core.retrieval.bm25_engine.tokenizer import WhitespaceTokenizer

        self.docs = docs
        self.ids = list(docs)
        self.bm25 = BM25Index(WhitespaceTokenizer())
        self.bm25.build([{"id": k, "content": d["content"], "metadata": {"title": d["title"]}} for k, d in docs.items()])
        self.tokenizer = AutoTokenizer.from_pretrained(embed_dir, local_files_only=True)
        self.encoder = AutoModel.from_pretrained(embed_dir, local_files_only=True, use_safetensors=True).eval()
        if device == "mps":
            self.encoder.half()
        self.encoder.to(device)
        self.device = device
        self.torch = torch
        inputs = ["passage: " + doc["title"] + ". " + doc["content"] for doc in docs.values()]
        self.vectors = np.concatenate([self.encode(inputs[i:i+12]) for i in range(0, len(inputs), 12)])

    def encode(self, texts: list[str]) -> Any:
        batch = self.tokenizer(texts, padding=True, truncation=True, max_length=512, return_tensors="pt").to(self.device)
        with self.torch.inference_mode():
            output = self.encoder(**batch).last_hidden_state.float()
            mask = batch["attention_mask"].unsqueeze(-1)
            vectors = (output * mask).sum(1) / mask.sum(1)
            return self.torch.nn.functional.normalize(vectors).cpu().numpy()

    def rankings(self, question: str) -> tuple[list[str], list[str], dict[str, float]]:
        import numpy as np

        lexical = [r["id"] for r in self.bm25.search(question, 40)]
        embedding = self.encode(["query: " + question])[0]
        dense = [self.ids[i] for i in np.argsort(-(self.vectors @ embedding), kind="stable")[:40]]
        scores: dict[str, float] = {}
        for ranking in (lexical, dense):
            for rank, doc in enumerate(ranking):
                scores[doc] = scores.get(doc, 0) + 1 / (60 + rank)
        return lexical, sorted(scores, key=lambda doc: (-scores[doc], doc)), scores

    async def search(self, query: str, top_k: int = 5, **kwargs: Any) -> list[SearchResult]:
        _, order, scores = await asyncio.to_thread(self.rankings, query)
        return [SearchResult(id=doc_id, content=self.docs[doc_id]["content"], score=scores[doc_id],
                             metadata={"document_id": doc_id, "title": self.docs[doc_id]["title"],
                                       "source_file": self.docs[doc_id]["title"]})
                for doc_id in order[:max(0, top_k)]]
