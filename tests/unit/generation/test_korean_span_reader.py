import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.modules.core.generation.korean_span_reader import KoreanSpanReader, _best_span, _cited_span


def test_span_search_excludes_question_padding_and_backward_pairs() -> None:
    np = pytest.importorskip("numpy")
    offsets = [(0, 0), (0, 20), (0, 2), (3, 6), (7, 10), (0, 0)]
    seq = [None, 0, 1, 1, 1, None]
    starts = np.array([1., 999., 1., 8., 5., 999.])
    ends = np.array([2., 999., 9., 1., 6., 999.])
    assert _best_span(starts, ends, offsets, seq, 2) == (11., 3, 10)
    starts[3] = np.nan
    with pytest.raises(ValueError, match="nonfinite"):
        _best_span(starts, ends, offsets, seq, 2)


def test_highest_whitespace_span_falls_back_to_best_complete_nonempty_span() -> None:
    np = pytest.importorskip("numpy")
    body = "\u00a0\n서울"
    offsets = [(0, 0), (0, 1), (1, 2), (2, 4)]
    ids = [None, 1, 1, 1]
    logits = np.array([0., 18., 16., 12.])

    assert _best_span(logits, logits, offsets, ids, 1, body) == (24., 2, 4)
    # An answer can start in a space token if its full extent also contains text.
    assert _best_span(logits, logits, offsets, ids, 3, body) == (30., 0, 4)


def test_only_whitespace_window_and_invalid_offsets_remain_unusable() -> None:
    np = pytest.importorskip("numpy")
    offsets, ids = [(0, 0), (0, 1)], [None, 1]
    logits = np.array([0., 10.])
    assert _best_span(logits, logits, offsets, ids, 1, " ") is None
    with pytest.raises(ValueError, match="outside"):
        _best_span(logits, logits, [(0, 0), (4, 5)], ids, 1, " ")
    with pytest.raises(ValueError, match="nonfinite"):
        _best_span(logits, np.array([0., np.nan]), offsets, ids, 1, " ")


def test_original_nonblank_winner_keeps_offsets_and_margin() -> None:
    np = pytest.importorskip("numpy")
    body = " Tokyo"
    offsets, ids = [(0, 0), (0, 1), (1, 6)], [None, 1, 1]
    logits = np.array([1., 2., 6.])
    assert _best_span(logits, logits, offsets, ids, 3, body) == (10., 1, 6)


def test_read_recovers_nonempty_text_but_still_applies_abstention_threshold() -> None:
    torch = pytest.importorskip("torch")
    tr = pytest.importorskip("transformers")
    tokenizers = pytest.importorskip("tokenizers")
    tokenizer = tokenizers.Tokenizer(tokenizers.models.WordLevel(
        {"[UNK]": 0, "[CLS]": 1, "[SEP]": 2, "?": 3, " ": 4, "O": 5}, unk_token="[UNK]",
    ))
    tokenizer.pre_tokenizer = tokenizers.pre_tokenizers.Split(" ", behavior="isolated")
    tokenizer.post_processor = tokenizers.processors.TemplateProcessing(
        single="[CLS] $A [SEP]", pair="[CLS] $A [SEP] $B:1 [SEP]:1",
        special_tokens=[("[CLS]", 1), ("[SEP]", 2)],
    )
    reader = KoreanSpanReader.__new__(KoreanSpanReader)
    reader.tokenizer = tr.PreTrainedTokenizerFast(tokenizer_object=tokenizer, pad_token="[SEP]")
    reader.device, reader.max_length, reader.rank_penalty = torch.device("cpu"), 128, 0.

    def logits(**inputs: Any) -> Any:
        ids = inputs["input_ids"]
        values = torch.zeros_like(ids, dtype=torch.float)
        values[ids == 1] = 10.
        values[ids == 4] = 8.
        values[ids == 5] = 6.
        return SimpleNamespace(start_logits=values, end_logits=values)

    reader.model = logits
    doc = {"id": "article", "content": " O"}
    reader.threshold = -7.
    out = reader.read("?", [doc])
    assert out is not None and (out.answer, out.start, out.end, out.score) == ("O", 1, 2, -6.)
    assert out.source_id == "article" and out.quote == doc["content"][out.quote_start:out.quote_end]
    reader.threshold = -2.
    assert reader.read("?", [doc]) is None


def test_offset_quote_can_cross_sentences_and_keep_whitespace() -> None:
    text = "머리말.\n둘째 줄.  다음 문장.\n맺음말."
    start, end = text.index("둘째"), text.index("문장.") + 2
    result = _cited_span(text, 1, "original", start, end, 7.0)
    assert result.answer == "둘째 줄.  다음 문장"
    assert result.quote == "둘째 줄.  다음 문장."
    assert text[result.start:result.end] == result.answer
    assert text[result.quote_start:result.quote_end] == result.quote
    higher_rank = _cited_span(text, 0, "other", start, end, 6.0)
    assert KoreanSpanReader.choose([higher_rank, result], 0.0) == result
    assert KoreanSpanReader.choose([higher_rank, result], 2.0) == higher_rank


def test_local_checkpoint_overflow_and_refusal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    torch = pytest.importorskip("torch")
    tr = pytest.importorskip("transformers")
    vocab = ["[PAD]", "[UNK]", "[CLS]", "[SEP]", "[MASK]", "뉴스", "대전", "역", ".", "?"]
    (tmp_path / "vocab.txt").write_text("\n".join(vocab) + "\n", encoding="utf-8")
    tok = tr.BertTokenizerFast(vocab_file=str(tmp_path / "vocab.txt"), do_lower_case=False)
    tok.save_pretrained(tmp_path)
    model = tr.BertForQuestionAnswering(tr.BertConfig(
        vocab_size=len(vocab), hidden_size=8, num_hidden_layers=1, num_attention_heads=1, intermediate_size=16
    ))
    model.save_pretrained(tmp_path)
    (tmp_path / "reader_config.json").write_text(json.dumps({"max_length": 128, "threshold": 2}))
    reader = KoreanSpanReader(tmp_path)

    def logits(**inputs: Any) -> Any:
        # The same word occurs in the question and only in the last document window.
        scores = (inputs["input_ids"] == vocab.index("대전")).float() * 7.
        return SimpleNamespace(start_logits=scores, end_logits=scores)

    monkeypatch.setattr(reader.model, "forward", logits)
    body = "뉴스 " * 190 + ".\n대전 역."
    doc = {"id": "chunk", "metadata": {"document_id": "article"}, "content": body}
    out = reader.read("대전?", [doc])
    assert out is not None and out.source_id == "article" and out.document_index == 0
    assert out.answer == "대전" and out.start == body.index("대전") and out.quote == "대전 역."
    reader.threshold = 14.0
    assert reader.read("대전?", [doc]) is None
    assert reader.read("대전?", []) is None
    with pytest.raises(ValueError):
        reader.read(" ", [doc])
    with pytest.raises(ValueError):
        reader.read("대전?", [{"id": "empty", "content": ""}])
    monkeypatch.setattr(reader.model, "forward", lambda **kw: SimpleNamespace(
        start_logits=torch.full_like(kw["input_ids"], float("nan"), dtype=torch.float),
        end_logits=kw["input_ids"].float(),
    ))
    with pytest.raises(ValueError, match="nonfinite"):
        reader.read("대전?", [doc])
