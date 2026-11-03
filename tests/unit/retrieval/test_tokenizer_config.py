"""
BM25 토크나이저 범용화 테스트 (Phase 3.1 - 토크나이저)

목적:
    BM25 토크나이저가 한국어 형태소 분석기로 고정되지 않고, 설정으로 언어
    중립 토크나이저를 선택할 수 있는지 검증한다. 비한국어 외주 프로젝트가
    코드 수정 없이 적절한 토크나이저를 쓸 수 있어야 한다.
"""

from __future__ import annotations

import pytest

from app.modules.core.retrieval.bm25_engine.tokenizer import (
    Tokenizer,
    WhitespaceTokenizer,
)


def test_whitespace_tokenizer_tokenize() -> None:
    """공백 토크나이저는 소문자화 + 공백 분리를 수행해야 한다."""
    t = WhitespaceTokenizer()
    assert t.tokenize("Hello World FOO") == ["hello", "world", "foo"]
    assert t.tokenize_batch(["a b", "c"]) == [["a", "b"], ["c"]]


def test_whitespace_tokenizer_satisfies_protocol() -> None:
    """WhitespaceTokenizer는 Tokenizer Protocol을 만족해야 한다."""
    assert isinstance(WhitespaceTokenizer(), Tokenizer)


def test_bm25_index_accepts_protocol_tokenizer() -> None:
    """BM25Index가 Protocol 토크나이저(WhitespaceTokenizer)를 받아들여야 한다."""
    from app.modules.core.retrieval.bm25_engine.index import BM25Index

    # 생성만으로 타입 호환 검증 (rank-bm25 미설치 환경에서도 생성자는 동작)
    idx = BM25Index(tokenizer=WhitespaceTokenizer())
    assert idx is not None


@pytest.mark.parametrize(
    ("tokenizer_setting", "expected_cls"),
    [("korean", "KoreanTokenizer"), ("whitespace", "WhitespaceTokenizer")],
)
def test_retriever_wiring_selects_tokenizer_by_config(
    monkeypatch: pytest.MonkeyPatch, tokenizer_setting: str, expected_cls: str
) -> None:
    """bm25.tokenizer 설정에 따라 BM25 전처리기의 토크나이저 클래스가 선택되어야 한다.

    (예전에는 di_container 소스 문자열을 grep 하던 테스트였다. 배선 로직이
    retrievers/wiring.py 로 옮겨졌으므로 실제 동작으로 검증한다.)
    """
    pytest.importorskip("kiwipiepy")
    pytest.importorskip("rank_bm25")
    from unittest.mock import MagicMock

    from app.modules.core.retrieval.retrievers import wiring
    from app.modules.core.retrieval.retrievers.factory import RetrieverFactory

    captured: dict[str, object] = {}

    def fake_create(provider: str, embedder: object, config: dict, bm25_preprocessors=None):  # type: ignore[no-untyped-def]
        captured["provider"] = provider
        captured["bm25"] = bm25_preprocessors
        return MagicMock()

    monkeypatch.setattr(RetrieverFactory, "create", fake_create)
    wiring.build_retriever_from_config(
        {"vector_db": {"provider": "chroma"}, "bm25": {"tokenizer": tokenizer_setting}},
        embedder=MagicMock(),
        vector_store=MagicMock(),
    )
    assert captured["provider"] == "chroma"
    bm25 = captured["bm25"]
    assert isinstance(bm25, dict) and "bm25_index" in bm25
    assert type(bm25["bm25_index"]._tokenizer).__name__ == expected_cls
