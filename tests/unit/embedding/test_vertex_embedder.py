"""VertexAIEmbedder(app/modules/core/embedding/vertex_embedder.py) 단위 테스트.

목적: ADC(Application Default Credentials) 기반 선택적 Vertex AI 임베딩 provider의
핵심 동작을 vertex extra 미설치 환경에서도 검증한다. 모든 HTTP 호출은 fake client로,
토큰 갱신(google.auth)은 monkeypatch/mock으로 대체한다.

검증 범위:
- 모델명 정규화(models/·google/ 접두사 제거)
- 쿼리/문서 task_type 구분(RETRIEVAL_QUERY / RETRIEVAL_DOCUMENT)
- 429 재시도(Retry-After 존중) 백오프
- 배치(instances 묶음) 호출 + 순서 보존
- predictions 개수 불일치 시 즉시 실패(잘못된 임베딩 짝 방지)
- 토큰 갱신 race lock 직렬화(병렬 임베딩 안전성)
"""

import math
import threading
from unittest.mock import MagicMock

import pytest

from app.modules.core.embedding import vertex_embedder as vertex_embedder_module
from app.modules.core.embedding.vertex_embedder import (
    VertexAIEmbedder,
    _normalize_model_name,
)


class _FakeResponse:
    def __init__(
        self,
        values: list[float] | None = None,
        status_code: int = 200,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self.headers = headers or {}
        self._values = values or [3.0, 4.0, 0.0]

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self) -> dict:
        return {"predictions": [{"embeddings": {"values": self._values}}]}


class _FakeClient:
    def __init__(self) -> None:
        self.posts: list[dict] = []

    def post(self, url: str, headers: dict, json: dict) -> _FakeResponse:
        self.posts.append({"url": url, "headers": headers, "json": json})
        return _FakeResponse([3.0, 4.0, 0.0])


class _SequenceClient:
    def __init__(self, responses: list[_FakeResponse]) -> None:
        self.responses = responses
        self.posts: list[dict] = []

    def post(self, url: str, headers: dict, json: dict) -> _FakeResponse:
        self.posts.append({"url": url, "headers": headers, "json": json})
        return self.responses.pop(0)


def _norm(vector: list[float]) -> float:
    return math.sqrt(sum(value * value for value in vector))


def test_normalize_model_name_accepts_google_and_models_prefixes() -> None:
    assert _normalize_model_name("models/gemini-embedding-001") == "gemini-embedding-001"
    assert _normalize_model_name("google/gemini-embedding-001") == "gemini-embedding-001"
    assert _normalize_model_name("gemini-embedding-001") == "gemini-embedding-001"


def test_vertex_embedder_requires_project_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """project_id/관련 환경변수가 전혀 없으면 명확한 안내 에러를 던진다."""
    for env_var in (
        "VERTEX_AI_PROJECT_ID",
        "GOOGLE_CLOUD_PROJECT",
        "GCLOUD_PROJECT",
    ):
        monkeypatch.delenv(env_var, raising=False)

    with pytest.raises(ValueError, match="VERTEX_AI_PROJECT_ID"):
        VertexAIEmbedder(output_dimensionality=3)


def test_vertex_embedder_uses_query_task_type() -> None:
    client = _FakeClient()
    embedder = VertexAIEmbedder(
        project_id="ragtest-project",
        location="us-central1",
        output_dimensionality=3,
        http_client=client,  # type: ignore[arg-type]
    )
    embedder._refresh_access_token = lambda: "test-token"  # type: ignore[method-assign]

    vector = embedder.embed_query("질문")

    assert pytest.approx(_norm(vector), abs=0.01) == 1.0
    assert client.posts[0]["json"]["instances"][0]["task_type"] == "RETRIEVAL_QUERY"
    assert "ragtest-project" in client.posts[0]["url"]
    assert client.posts[0]["headers"]["Authorization"] == "Bearer test-token"


def test_vertex_embedder_uses_document_task_type() -> None:
    client = _FakeClient()
    embedder = VertexAIEmbedder(
        project_id="ragtest-project",
        output_dimensionality=3,
        batch_size=1,
        http_client=client,  # type: ignore[arg-type]
    )
    embedder._refresh_access_token = lambda: "test-token"  # type: ignore[method-assign]

    vectors = embedder.embed_documents(["문서1", "문서2"])

    assert len(vectors) == 2
    assert all(pytest.approx(_norm(vector), abs=0.01) == 1.0 for vector in vectors)
    assert [post["json"]["instances"][0]["task_type"] for post in client.posts] == [
        "RETRIEVAL_DOCUMENT",
        "RETRIEVAL_DOCUMENT",
    ]


def test_vertex_embedder_retries_rate_limited_predict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _SequenceClient(
        [
            _FakeResponse(status_code=429, headers={"Retry-After": "2.5"}),
            _FakeResponse([3.0, 4.0, 0.0]),
        ]
    )
    sleeps: list[float] = []
    embedder = VertexAIEmbedder(
        project_id="ragtest-project",
        output_dimensionality=3,
        max_retries=2,
        retry_base_seconds=0.5,
        retry_max_seconds=10.0,
        http_client=client,  # type: ignore[arg-type]
    )
    embedder._refresh_access_token = lambda: "test-token"  # type: ignore[method-assign]
    monkeypatch.setattr(vertex_embedder_module.time, "sleep", sleeps.append)

    vector = embedder.embed_query("질문")

    assert pytest.approx(_norm(vector), abs=0.01) == 1.0
    assert len(client.posts) == 2
    assert sleeps == [2.5]


class _BatchResponse:
    """instances 개수만큼 predictions 를 돌려주는 다중(배치) 응답 Fake."""

    def __init__(
        self,
        vectors: list[list[float]],
        status_code: int = 200,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self.headers = headers or {}
        self._vectors = vectors

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self) -> dict:
        return {
            "predictions": [
                {"embeddings": {"values": values}} for values in self._vectors
            ]
        }


class _BatchEchoClient:
    """요청의 instances 를 식별 가능한 벡터로 되돌려주는 Fake.

    content "t{idx}" → raw 벡터 [idx+1, idx+2, idx+3] 으로 인코딩해, 배치 응답이
    입력 순서대로 정확히 매핑되는지(순서 보장)를 검증할 수 있게 한다.
    """

    def __init__(self) -> None:
        self.posts: list[dict] = []

    def post(self, url: str, headers: dict, json: dict) -> _BatchResponse:
        self.posts.append({"url": url, "headers": headers, "json": json})
        vectors = []
        for instance in json["instances"]:
            idx = int(str(instance["content"])[1:])  # "t5" → 5
            vectors.append([float(idx) + 1.0, float(idx) + 2.0, float(idx) + 3.0])
        return _BatchResponse(vectors)


def _expected_unit_vector(idx: int) -> list[float]:
    """_BatchEchoClient 가 content idx 에 대해 반환할 정규화된 기대 벡터."""
    raw = [float(idx) + 1.0, float(idx) + 2.0, float(idx) + 3.0]
    norm = math.sqrt(sum(value * value for value in raw))
    return [value / norm for value in raw]


def test_embed_documents_sends_one_batched_request() -> None:
    """여러 문서를 단 한 번의 요청(instances 묶음)으로 보내고 순서를 보존한다."""
    client = _BatchEchoClient()
    embedder = VertexAIEmbedder(
        project_id="ragtest-project",
        output_dimensionality=3,
        batch_size=16,
        http_client=client,  # type: ignore[arg-type]
    )
    embedder._refresh_access_token = lambda: "test-token"  # type: ignore[method-assign]

    vectors = embedder.embed_documents([f"t{i}" for i in range(5)])

    # 5개 문서가 단 한 번의 요청으로 묶여 전송된다(왕복 5회 → 1회).
    assert len(client.posts) == 1
    assert len(client.posts[0]["json"]["instances"]) == 5
    # 순서 보장: 결과가 입력 순서와 정확히 일치한다.
    assert len(vectors) == 5
    for i, vector in enumerate(vectors):
        assert vector == pytest.approx(_expected_unit_vector(i), abs=1e-9)


def test_embed_documents_respects_batch_size_boundary() -> None:
    """batch_size 경계에서 요청이 나뉘어도 전체 순서가 보존된다."""
    client = _BatchEchoClient()
    embedder = VertexAIEmbedder(
        project_id="ragtest-project",
        output_dimensionality=3,
        batch_size=2,
        http_client=client,  # type: ignore[arg-type]
    )
    embedder._refresh_access_token = lambda: "test-token"  # type: ignore[method-assign]

    vectors = embedder.embed_documents([f"t{i}" for i in range(5)])

    # batch_size=2 → 5개 = [2, 2, 1] 세 번의 요청.
    assert [len(post["json"]["instances"]) for post in client.posts] == [2, 2, 1]
    for i, vector in enumerate(vectors):
        assert vector == pytest.approx(_expected_unit_vector(i), abs=1e-9)


def test_embed_documents_raises_on_prediction_count_mismatch() -> None:
    """predictions 개수가 입력과 다르면 순서 매핑이 깨진 것이므로 즉시 실패한다."""

    class _ShortClient:
        def post(self, url: str, headers: dict, json: dict) -> _BatchResponse:
            # instances 3개를 보냈는데 predictions 2개만 반환 → 매핑 불가.
            return _BatchResponse([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])

    embedder = VertexAIEmbedder(
        project_id="ragtest-project",
        output_dimensionality=3,
        batch_size=16,
        http_client=_ShortClient(),  # type: ignore[arg-type]
    )
    embedder._refresh_access_token = lambda: "test-token"  # type: ignore[method-assign]

    with pytest.raises(RuntimeError, match="predictions"):
        embedder.embed_documents(["t0", "t1", "t2"])


def test_embed_documents_empty_returns_empty() -> None:
    """빈 입력은 요청 없이 빈 리스트를 반환한다."""
    client = _BatchEchoClient()
    embedder = VertexAIEmbedder(
        project_id="ragtest-project",
        output_dimensionality=3,
        http_client=client,  # type: ignore[arg-type]
    )
    embedder._refresh_access_token = lambda: "test-token"  # type: ignore[method-assign]

    assert embedder.embed_documents([]) == []
    assert client.posts == []


def test_refresh_access_token_serializes_concurrent_refresh() -> None:
    """여러 스레드가 동시에 토큰을 갱신해도 race 없이 같은 토큰을 반환한다.

    병렬 임베딩(embed_chunks_parallel)에서 여러 워커 스레드가 같은 embedder의
    _refresh_access_token 을 동시 호출할 때, 자격증명 공유/갱신이 lock으로
    직렬화되어 토큰이 순간 None 이 되는 race가 없어야 한다.
    """
    client = _FakeClient()
    embedder = VertexAIEmbedder(
        project_id="ragtest-project",
        output_dimensionality=3,
        http_client=client,  # type: ignore[arg-type]
    )

    credentials = MagicMock()
    credentials.valid = False

    def _do_refresh(_request: object) -> None:
        credentials.token = "tok-xyz"
        credentials.valid = True

    credentials.refresh = MagicMock(side_effect=_do_refresh)
    embedder._credentials = credentials

    results: list[str] = []
    errors: list[Exception] = []

    def worker() -> None:
        try:
            results.append(embedder._refresh_access_token())
        except Exception as error:  # noqa: BLE001 - 테스트에서 모든 실패 수집
            errors.append(error)

    threads = [threading.Thread(target=worker) for _ in range(16)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors
    assert results == ["tok-xyz"] * 16
    # lock 으로 직렬화되어 refresh 는 최초 1회만 일어난다(이후 valid=True 로 skip).
    assert credentials.refresh.call_count == 1
