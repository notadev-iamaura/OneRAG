"""
Weaviate BM25 토크나이저 config 배선 테스트 (11차 범용화)

content 필드 토크나이저가 WORD 하드코딩 + weaviate.yaml의
use_korean_tokenizer 데드 키였던 것을 weaviate.schema.bm25_tokenization으로
실제 배선한 변경을 검증한다(미설정 시 WORD 폴백 → 회귀 0).
"""

from unittest.mock import patch

from weaviate.classes.config import Tokenization

from app.lib import weaviate_setup

_LOAD_CONFIG = "app.lib.config_loader.load_config"


class TestResolveBm25Tokenization:
    def test_default_word_when_unset(self):
        """미설정 시 WORD로 폴백한다 (회귀 0)."""
        with patch(_LOAD_CONFIG, return_value={}):
            assert weaviate_setup._resolve_bm25_tokenization() == Tokenization.WORD

    def test_korean_tokenizer_from_config(self):
        """config kagome_kr → KAGOME_KR enum."""
        cfg = {"weaviate": {"schema": {"bm25_tokenization": "kagome_kr"}}}
        with patch(_LOAD_CONFIG, return_value=cfg):
            assert weaviate_setup._resolve_bm25_tokenization() == Tokenization.KAGOME_KR

    def test_japanese_tokenizer_from_config(self):
        cfg = {"weaviate": {"schema": {"bm25_tokenization": "kagome_ja"}}}
        with patch(_LOAD_CONFIG, return_value=cfg):
            assert weaviate_setup._resolve_bm25_tokenization() == Tokenization.KAGOME_JA

    def test_unknown_value_falls_back_to_word(self):
        cfg = {"weaviate": {"schema": {"bm25_tokenization": "nonsense"}}}
        with patch(_LOAD_CONFIG, return_value=cfg):
            assert weaviate_setup._resolve_bm25_tokenization() == Tokenization.WORD

    def test_config_load_failure_falls_back_to_word(self):
        with patch(_LOAD_CONFIG, side_effect=RuntimeError("boom")):
            assert weaviate_setup._resolve_bm25_tokenization() == Tokenization.WORD
