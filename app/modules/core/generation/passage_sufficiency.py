"""Offline relevance scoring for the Korean typed-decision checkpoint."""

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


class PassageSufficiency:
    def __init__(self, path: Path, device: str):
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        self.tokenizer = AutoTokenizer.from_pretrained(path, local_files_only=True)
        self.device = torch.device(device)
        self.model = AutoModelForSequenceClassification.from_pretrained(
            path, local_files_only=True, use_safetensors=True
        ).to(self.device).eval()

    def scores(self, question: str, docs: Sequence[Mapping[str, Any]]) -> list[float]:
        import torch

        if not docs:
            return []
        instruction = "Does the passage contain information useful for the query?"
        choices = ("A: Relevant information for the query", "B: Unrelated or insufficient information")
        states = [f"Query: {question}\nNote: {d['title']}\nTitle: {d['title']}\nPassage:\n{d['content']}" for d in docs]
        batch = self.tokenizer(
            [f"{instruction} {choice}" for _ in docs for choice in choices], [s for s in states for _ in choices],
            truncation="only_second", max_length=512, padding=True, return_tensors="pt",
        ).to(self.device)
        with torch.inference_mode():
            logits = self.model(**batch).logits
            if logits.shape != (len(docs) * 2, 1) or not torch.isfinite(logits).all():
                raise ValueError("Invalid passage sufficiency scores")
            pairs = logits.float().reshape(-1, 2)
            margins: list[float] = (pairs[:, 0] - pairs[:, 1]).tolist()
            return margins
