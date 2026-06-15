"""임베딩 API 재시도(429/5xx + Retry-After + 지수 backoff) 회귀 테스트.

검증 대상(차용 #17):
- gemini/openai 임베더가 일시적 429/5xx에 재시도하고, 1회 실패 후 성공하면
  정상 임베딩을 반환한다.
- Retry-After 헤더가 있으면 그 값을 우선 존중한다.
- 재시도 소진 시 RuntimeError를 전파한다(zero-vector로 오류를 숨기지 않음).
- OpenAI 임베더는 더 이상 예외 시 zero-vector를 반환하지 않는다.

재시도 백오프 자체는 monkeypatch로 sleep을 무력화해 빠르게 실행한다.
"""

from typing import Any

import pytest

from app.modules.core.embedding import _retry as retry_mod


class _FakeResourceExhausted(Exception):
    """google.api_core ResourceExhausted 흉내 (429 매핑 대상)."""

    grpc_status_code = 8  # RESOURCE_EXHAUSTED


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """재시도 지연을 즉시 통과시킨다(테스트 속도)."""
    monkeypatch.setattr(retry_mod.time, "sleep", lambda _seconds: None)


# ---------------------------------------------------------------------------
# 공용 헬퍼: retry_embed 직접 검증
# ---------------------------------------------------------------------------
def test_retry_embed_retries_on_retryable_status_then_succeeds() -> None:
    """retryable 상태코드(429)로 1회 실패 후 성공하면 결과를 반환해야 한다."""
    calls = {"n": 0}

    def _call() -> str:
        calls["n"] += 1
        if calls["n"] == 1:
            raise retry_mod.EmbeddingRetryableError(status_code=429)
        return "ok"

    result = retry_mod.retry_embed(_call, max_retries=3, base_seconds=0.01, max_seconds=0.1)
    assert result == "ok"
    assert calls["n"] == 2


def test_retry_embed_raises_after_exhaustion() -> None:
    """재시도 소진 시 마지막 예외를 전파해야 한다(숨기지 않음)."""
    def _always_fail() -> str:
        raise retry_mod.EmbeddingRetryableError(status_code=503)

    with pytest.raises(retry_mod.EmbeddingRetryableError):
        retry_mod.retry_embed(_always_fail, max_retries=2, base_seconds=0.01, max_seconds=0.1)


def test_retry_embed_does_not_retry_non_retryable() -> None:
    """비재시도 예외는 즉시 전파해야 한다(재시도 없음)."""
    calls = {"n": 0}

    def _call() -> str:
        calls["n"] += 1
        raise ValueError("non-retryable")

    with pytest.raises(ValueError):
        retry_mod.retry_embed(_call, max_retries=3, base_seconds=0.01, max_seconds=0.1)
    assert calls["n"] == 1


def test_retry_delay_honors_retry_after_header() -> None:
    """Retry-After 헤더가 있으면 그 값을 우선(상한 clamp) 사용해야 한다."""
    delay = retry_mod._retry_delay(
        attempt=1, retry_after="5", base_seconds=1.0, max_seconds=30.0
    )
    assert delay == 5.0
    # 상한 초과 시 clamp
    clamped = retry_mod._retry_delay(
        attempt=1, retry_after="100", base_seconds=1.0, max_seconds=30.0
    )
    assert clamped == 30.0


def test_retry_delay_exponential_without_header() -> None:
    """Retry-After가 없으면 지수 backoff(base*2^(attempt-1))를 max로 clamp한다."""
    # attempt=1 → base*1, attempt=2 → base*2, attempt=3 → base*4
    assert retry_mod._retry_delay(1, None, base_seconds=2.0, max_seconds=30.0) == 2.0
    assert retry_mod._retry_delay(2, None, base_seconds=2.0, max_seconds=30.0) == 4.0
    assert retry_mod._retry_delay(3, None, base_seconds=2.0, max_seconds=30.0) == 8.0
    # max 상한 적용
    assert retry_mod._retry_delay(10, None, base_seconds=2.0, max_seconds=30.0) == 30.0


def test_status_from_google_resource_exhausted_maps_to_429() -> None:
    """google ResourceExhausted류 예외가 429로 매핑되어야 한다."""
    # google SDK 미설치 환경에서도 grpc_status_code 속성으로 매핑 가능해야 한다
    status = retry_mod._status_from_exception(_FakeResourceExhausted())
    assert status == 429


# ---------------------------------------------------------------------------
# Gemini 임베더 통합: embed_content를 stub해 재시도 검증
# ---------------------------------------------------------------------------
def _make_gemini_embedder(monkeypatch: pytest.MonkeyPatch, dim: int = 4) -> Any:
    from app.modules.core.embedding import gemini_embedder as gem

    # genai.configure를 무력화(키 검증 회피)
    fake_genai = type("_G", (), {})()
    fake_genai.configure = lambda **kwargs: None
    monkeypatch.setattr(gem, "_get_genai", lambda: fake_genai)
    embedder = gem.GeminiEmbedder(
        google_api_key="fake-key",
        model_name="models/gemini-embedding-001",
        output_dimensionality=dim,
    )
    return embedder, fake_genai


def test_gemini_embedder_retries_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    """gemini 임베더가 429 1회 후 성공하면 정상 임베딩을 반환해야 한다."""
    embedder, fake_genai = _make_gemini_embedder(monkeypatch)
    calls = {"n": 0}

    def _embed_content(**kwargs: Any) -> dict[str, Any]:
        calls["n"] += 1
        if calls["n"] == 1:
            raise retry_mod.EmbeddingRetryableError(status_code=429)
        return {"embedding": [1.0, 0.0, 0.0, 0.0]}

    fake_genai.embed_content = _embed_content

    result = embedder.embed_query("질문")
    assert len(result) == 4
    assert calls["n"] == 2  # 1회 재시도 후 성공


def test_gemini_embedder_raises_after_exhaustion(monkeypatch: pytest.MonkeyPatch) -> None:
    """gemini 임베더가 재시도 소진 시 RuntimeError를 전파해야 한다."""
    embedder, fake_genai = _make_gemini_embedder(monkeypatch)

    def _embed_content(**kwargs: Any) -> dict[str, Any]:
        raise retry_mod.EmbeddingRetryableError(status_code=503)

    fake_genai.embed_content = _embed_content

    with pytest.raises(RuntimeError):
        embedder.embed_query("질문")


# ---------------------------------------------------------------------------
# OpenAI 임베더 통합: embeddings.create를 stub해 재시도 + zero-vector 제거 검증
# ---------------------------------------------------------------------------
def _make_openai_embedder(monkeypatch: pytest.MonkeyPatch, dim: int = 4) -> Any:
    from app.modules.core.embedding import openai_embedder as oai

    embedder = oai.OpenAIEmbedder(
        openai_api_key="",  # 클라이언트 없이 생성
        model_name="text-embedding-3-large",
        output_dimensionality=dim,
    )
    # 클라이언트를 stub로 강제 주입
    fake_client = type("_C", (), {})()
    embedder.client = fake_client
    return embedder, fake_client


def _make_embeddings_response(vector: list[float]) -> Any:
    item = type("_Item", (), {"embedding": vector})()
    return type("_Resp", (), {"data": [item]})()


def test_openai_embedder_retries_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    """openai 임베더가 429 1회 후 성공하면 정상 임베딩을 반환해야 한다."""
    embedder, fake_client = _make_openai_embedder(monkeypatch)
    calls = {"n": 0}

    class _Embeddings:
        def create(self, **kwargs: Any) -> Any:
            calls["n"] += 1
            if calls["n"] == 1:
                raise retry_mod.EmbeddingRetryableError(status_code=429)
            return _make_embeddings_response([1.0, 0.0, 0.0, 0.0])

    fake_client.embeddings = _Embeddings()

    result = embedder.embed_query("질문")
    assert len(result) == 4
    assert calls["n"] == 2


def test_openai_embedder_raises_instead_of_zero_vector(monkeypatch: pytest.MonkeyPatch) -> None:
    """openai 임베더는 재시도 소진 시 zero-vector가 아니라 RuntimeError를 내야 한다."""
    embedder, fake_client = _make_openai_embedder(monkeypatch)

    class _Embeddings:
        def create(self, **kwargs: Any) -> Any:
            raise retry_mod.EmbeddingRetryableError(status_code=503)

    fake_client.embeddings = _Embeddings()

    with pytest.raises(RuntimeError):
        embedder.embed_documents(["문서1", "문서2"])
