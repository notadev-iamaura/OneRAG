"""TwelveLabsEmbedder(app/modules/core/embedding/twelvelabs_embedder.py) 단위 테스트.

목적: TwelveLabs Marengo 멀티모달 임베딩 provider의 핵심 동작을 SDK 네트워크
호출 없이 검증한다. SDK 클라이언트는 fake로 대체하며, 실제 API 호출이 필요한
스모크 테스트는 TWELVELABS_API_KEY가 있을 때만 실행한다.

검증 범위:
- IEmbedder 계약(embed_documents/embed_query/aembed_*/validate_embedding)
- 응답 파싱(text_embedding.segments[0].float_ → 512차원 벡터)
- 빈 입력/실패 시 graceful degradation(영벡터)
- EmbedderFactory의 provider="twelvelabs" 라우팅
"""

import importlib.util
import os
from unittest.mock import MagicMock

import pytest

# twelvelabs는 선택적 extra(onerag[twelvelabs])이므로, SDK 미설치 환경(기본 릴리스
# 게이트)에서는 이 파일 전체를 skip한다. SDK + 키 동시 설치 시 라이브 테스트도 실행.
pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("twelvelabs") is None,
    reason="twelvelabs SDK not installed; run with onerag[twelvelabs] extra",
)


def _fake_embed_response(vector: list[float]) -> MagicMock:
    """SDK embed.create() 응답 형태(text_embedding.segments[0].float_)를 흉내낸다."""
    segment = MagicMock()
    segment.float_ = vector
    response = MagicMock()
    response.text_embedding.segments = [segment]
    return response


def _make_embedder() -> "object":
    """SDK 클라이언트가 mock된 TwelveLabsEmbedder를 생성한다(네트워크 없음)."""
    from app.modules.core.embedding.twelvelabs_embedder import TwelveLabsEmbedder

    embedder = TwelveLabsEmbedder(api_key="test-key")
    embedder._client = MagicMock()
    return embedder


class TestTwelveLabsEmbedderInit:
    """초기화 및 기본 속성 테스트."""

    def test_default_config(self) -> None:
        embedder = _make_embedder()
        assert embedder.model_name == "marengo3.0"
        assert embedder.output_dimensionality == 512

    def test_missing_api_key_raises(self) -> None:
        from app.modules.core.embedding.twelvelabs_embedder import TwelveLabsEmbedder

        with pytest.raises(ValueError, match="API"):
            TwelveLabsEmbedder(api_key=None)


class TestTwelveLabsEmbedderMethods:
    """임베딩 메서드 테스트(mock 클라이언트)."""

    def test_embed_query_parses_segment_vector(self) -> None:
        embedder = _make_embedder()
        embedder._client.embed.create.return_value = _fake_embed_response([0.1] * 512)

        result = embedder.embed_query("a red car driving on a highway")
        assert len(result) == 512
        assert embedder.validate_embedding(result)

    def test_embed_documents_sequential(self) -> None:
        embedder = _make_embedder()
        embedder._client.embed.create.return_value = _fake_embed_response([0.2] * 512)

        result = embedder.embed_documents(["scene 1", "scene 2"])
        assert len(result) == 2
        assert all(len(v) == 512 for v in result)
        assert embedder._client.embed.create.call_count == 2

    def test_embed_documents_empty(self) -> None:
        embedder = _make_embedder()
        assert embedder.embed_documents([]) == []

    def test_embed_query_empty_returns_zero_vector(self) -> None:
        embedder = _make_embedder()
        result = embedder.embed_query("")
        assert result == [0.0] * 512

    def test_embed_query_failure_degrades_gracefully(self) -> None:
        embedder = _make_embedder()
        embedder._client.embed.create.side_effect = RuntimeError("boom")

        result = embedder.embed_query("query")
        assert result == [0.0] * 512

    @pytest.mark.asyncio
    async def test_aembed_query_offloads_to_thread(self) -> None:
        embedder = _make_embedder()
        embedder._client.embed.create.return_value = _fake_embed_response([0.3] * 512)

        result = await embedder.aembed_query("async query")
        assert len(result) == 512

    def test_validate_embedding_dimension_mismatch(self) -> None:
        embedder = _make_embedder()
        assert embedder.validate_embedding([0.0] * 256) is False
        assert embedder.validate_embedding([]) is False


class TestEmbedderFactoryTwelveLabs:
    """EmbedderFactory의 twelvelabs provider 라우팅 테스트."""

    def test_factory_creates_twelvelabs_embedder(self) -> None:
        from app.modules.core.embedding.factory import EmbedderFactory
        from app.modules.core.embedding.twelvelabs_embedder import TwelveLabsEmbedder

        config = {
            "embeddings": {
                "provider": "twelvelabs",
                "twelvelabs": {"model": "marengo3.0", "api_key": "test-key"},
            }
        }
        embedder = EmbedderFactory.create(config)
        assert isinstance(embedder, TwelveLabsEmbedder)
        assert embedder.output_dimensionality == 512

    def test_twelvelabs_in_supported_models(self) -> None:
        from app.modules.core.embedding.factory import EmbedderFactory

        info = EmbedderFactory.get_model_info("marengo3.0")
        assert info is not None
        assert info["provider"] == "twelvelabs"
        assert info["default_dimensions"] == 512


@pytest.mark.skipif(
    not os.getenv("TWELVELABS_API_KEY"),
    reason="TWELVELABS_API_KEY not set; skipping live Marengo smoke test",
)
class TestTwelveLabsEmbedderLive:
    """실제 Marengo API 호출 스모크 테스트(키가 있을 때만)."""

    def test_live_query_returns_512_dim_vector(self) -> None:
        from app.modules.core.embedding.twelvelabs_embedder import TwelveLabsEmbedder

        embedder = TwelveLabsEmbedder(api_key=os.environ["TWELVELABS_API_KEY"])
        vector = embedder.embed_query("a red car driving on a highway")
        assert len(vector) == 512
        assert embedder.validate_embedding(vector)
