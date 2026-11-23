"""Generate Korean source-anchored span alternatives from the existing QA weights."""

from pathlib import Path

from .english_span_proposals import EnglishSpanProposer
from .korean_span_reader import KoreanSpanReader


class KoreanEvidenceProposer(EnglishSpanProposer):
    """Reuse the windowed n-best algorithm with the Korean checkpoint's own length and tokenizer."""

    def __init__(self, model_path: str | Path, device: str = "cpu"):
        KoreanSpanReader.__init__(self, model_path, device=device)
        if self.model.config.type_vocab_size == 1:
            # Paired overflow encodings can emit segment ID 1 even when the checkpoint
            # owns only row 0. RoBERTa supplies all-zero type IDs by default. The fast
            # tokenizer's sequence_ids still distinguish the question from the passage.
            self.tokenizer.model_input_names = [key for key in self.tokenizer.model_input_names if key != "token_type_ids"]
