import sys
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

from app.modules.core.retrieval.retrievers import korean_hybrid_passage as ko


def test_body_only_lexical_scoring_and_offline_e5_merge(monkeypatch):
    records = [
        {"id": "z", "title": "공통", "content": "관련 문단"},
        {"id": "a", "title": "공통", "content": "나머지"},
    ]
    bm25 = Mock()
    bm25.search.return_value = [{"id": "z"}]
    monkeypatch.setattr(ko, "KoreanTokenizer", lambda: "korean")
    monkeypatch.setattr(ko, "BM25Index", lambda tokenizer: bm25)
    model, tokenizer = Mock(), Mock()
    monkeypatch.setitem(sys.modules, "transformers", SimpleNamespace(AutoModel=model, AutoTokenizer=tokenizer))
    inputs = []

    def encode(self, texts):
        inputs.extend(texts)
        return np.array([[1., 0.], [0., 1.]]) if len(texts) == 2 else np.array([[1., 0.]])

    monkeypatch.setattr(ko.KoreanHybridPassageRetriever, "encode", encode)
    r = ko.KoreanHybridPassageRetriever(records, "/local/encoder")
    assert r.rank("질문", 1) == ["z"]
    assert r.rank("질문", 80) == ["z", "a"]
    assert inputs[:2] == ["passage: 공통. 나머지", "passage: 공통. 관련 문단"]
    assert inputs[2:] == ["query: 질문", "query: 질문"]
    bm25.build.assert_called_once_with([{"id": "a", "content": "나머지"}, {"id": "z", "content": "관련 문단"}])
    model.from_pretrained.assert_called_once_with("/local/encoder", local_files_only=True, use_safetensors=True)
    tokenizer.from_pretrained.assert_called_once_with("/local/encoder", local_files_only=True)


def test_empty_and_duplicate_ids_do_not_load_an_encoder():
    r = ko.KoreanHybridPassageRetriever([], "/not-used")
    assert r.rank("무엇?") == [] and r.rankings("무엇?") == ([], [], {})
    with pytest.raises(ValueError, match="nonnegative"):
        r.rank("무엇?", -1)
    d = {"id": "one", "title": "하나", "content": "두 문단"}
    with pytest.raises(ValueError, match="unique"):
        ko.KoreanHybridPassageRetriever([d, d], "/not-used")
