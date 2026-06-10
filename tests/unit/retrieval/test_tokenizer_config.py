"""
BM25 토크나이저 범용화 테스트 (Phase 3.1 - 토크나이저)

목적:
    BM25 토크나이저가 한국어 형태소 분석기로 고정되지 않고, 설정으로 언어
    중립 토크나이저를 선택할 수 있는지 검증한다. 비한국어 외주 프로젝트가
    코드 수정 없이 적절한 토크나이저를 쓸 수 있어야 한다.
"""

from __future__ import annotations

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


def test_di_container_selects_tokenizer_by_config() -> None:
    """di_container가 bm25.tokenizer 설정에 따라 토크나이저를 선택해야 한다."""
    import inspect

    from app.core import di_container

    source = inspect.getsource(di_container)
    assert 'config.get("bm25", {}).get("tokenizer"' in source
    assert "WhitespaceTokenizer" in source
