"""VertexRankingReranker(Vertex AI Discovery Engine Ranking API) 단위 테스트.

목적: cross-encoder approach의 ADC(키리스) provider인 VertexRankingReranker의 핵심
동작을 vertex extra 미설치 환경에서도 검증한다(httpx fake client + google.auth 모킹).

검증 범위:
- Discovery Engine rank 엔드포인트 호출 + 점수 매핑/정렬
- 재시도 가능 상태코드(503) 발생 시 stats 기록 후 예외 전파
- RerankerFactoryV2가 cross-encoder/vertex 조합을 ADC(키 불필요)로 생성
"""

from __future__ import annotations

from unittest.mock import patch

import httpx
import pytest

from app.modules.core.retrieval.interfaces import SearchResult
from app.modules.core.retrieval.rerankers.vertex_ranking_reranker import (
    VertexRankingReranker,
)


class FakeCredentials:
    def __init__(self, token: str = "ya29.vertex-rank-token") -> None:
        self.token = token
        self.valid = False
        self.refresh_count = 0

    def refresh(self, _request: object) -> None:
        self.valid = True
        self.refresh_count += 1


class FakeAsyncClient:
    def __init__(self, response: httpx.Response) -> None:
        self.response = response
        self.requests: list[dict[str, object]] = []
        self.closed = False

    async def post(
        self,
        url: str,
        *,
        headers: dict[str, str],
        json: dict[str, object],
        timeout: float,
    ) -> httpx.Response:
        self.requests.append(
            {
                "url": url,
                "headers": headers,
                "json": json,
                "timeout": timeout,
            }
        )
        return self.response

    async def aclose(self) -> None:
        self.closed = True


def _response(status_code: int, payload: dict[str, object]) -> httpx.Response:
    request = httpx.Request(
        "POST",
        "https://discoveryengine.googleapis.com/v1/projects/p/locations/global/"
        "rankingConfigs/default_ranking_config:rank",
    )
    return httpx.Response(status_code, json=payload, request=request)


def _search_result(doc_id: str, content: str, score: float = 0.1) -> SearchResult:
    return SearchResult(
        id=doc_id,
        content=content,
        score=score,
        metadata={"source": f"{doc_id}.pdf"},
    )


def test_vertex_ranking_reranker_requires_project_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """project_id/관련 환경변수가 전혀 없으면 명확한 안내 에러를 던진다."""
    for env_var in (
        "VERTEX_RERANK_PROJECT_ID",
        "VERTEX_AI_PROJECT_ID",
        "GOOGLE_CLOUD_PROJECT",
        "GCLOUD_PROJECT",
    ):
        monkeypatch.delenv(env_var, raising=False)

    with pytest.raises(ValueError, match="project ID"):
        VertexRankingReranker()


@pytest.mark.asyncio
async def test_vertex_ranking_reranker_calls_discovery_engine_and_maps_scores() -> None:
    credentials = FakeCredentials()
    client = FakeAsyncClient(
        _response(
            200,
            {
                "records": [
                    {"id": "b", "score": 0.93},
                    {"id": "a", "score": 0.41},
                ]
            },
        )
    )
    reranker = VertexRankingReranker(
        project_id="infra-test-bed-2026",
        model="semantic-ranker-default-004",
        top_n=10,
        max_documents=3,
        timeout=1.5,
        http_client=client,  # type: ignore[arg-type]
    )

    with patch(
        "google.auth.default", return_value=(credentials, "infra-test-bed-2026")
    ):
        reranked = await reranker.rerank(
            "후보 문서 재정렬",
            [
                _search_result("a", "first candidate", 0.2),
                _search_result("b", "best candidate", 0.3),
                _search_result("c", "not returned", 0.4),
            ],
            top_n=2,
        )

    assert [item.id for item in reranked] == ["b", "a"]
    assert [item.score for item in reranked] == [0.93, 0.41]
    assert reranked[0].metadata["rerank_method"] == (
        "vertex-ranking:semantic-ranker-default-004"
    )
    assert reranked[0].metadata["original_score"] == 0.3
    assert credentials.refresh_count == 1

    request = client.requests[0]
    assert request["url"] == (
        "https://discoveryengine.googleapis.com/v1/projects/infra-test-bed-2026/"
        "locations/global/rankingConfigs/default_ranking_config:rank"
    )
    assert request["headers"]["Authorization"] == "Bearer ya29.vertex-rank-token"
    assert request["json"]["model"] == "semantic-ranker-default-004"
    assert request["json"]["topN"] == 2
    assert request["json"]["ignoreRecordDetailsInResponse"] is True
    assert request["json"]["records"] == [
        {"id": "a", "title": "a.pdf", "content": "first candidate"},
        {"id": "b", "title": "b.pdf", "content": "best candidate"},
        {"id": "c", "title": "c.pdf", "content": "not returned"},
    ]


@pytest.mark.asyncio
async def test_vertex_ranking_reranker_records_and_raises_api_failure() -> None:
    credentials = FakeCredentials()
    client = FakeAsyncClient(_response(503, {"error": {"message": "unavailable"}}))
    reranker = VertexRankingReranker(
        project_id="infra-test-bed-2026",
        top_n=2,
        max_documents=2,
        max_retries=0,
        http_client=client,  # type: ignore[arg-type]
    )
    results = [
        _search_result("a", "first candidate", 0.2),
        _search_result("b", "second candidate", 0.3),
        _search_result("c", "not requested", 0.4),
    ]

    with patch(
        "google.auth.default", return_value=(credentials, "infra-test-bed-2026")
    ):
        with pytest.raises(httpx.HTTPStatusError):
            await reranker.rerank("query", results)

    assert reranker.stats["failed_requests"] == 1


def test_factory_creates_vertex_cross_encoder_reranker_without_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RerankerFactoryV2가 cross-encoder/vertex 조합을 ADC(키 불필요)로 생성한다."""
    from app.modules.core.retrieval.rerankers.factory import RerankerFactoryV2

    # API 키 부재여도 vertex는 ADC 인증이라 생성되어야 한다.
    monkeypatch.delenv("COHERE_API_KEY", raising=False)
    monkeypatch.delenv("JINA_API_KEY", raising=False)

    config = {
        "reranking": {
            "approach": "cross-encoder",
            "provider": "vertex",
            "vertex": {
                "project_id": "infra-test-bed-2026",
                "location": "global",
                "model": "semantic-ranker-default-004",
            },
        }
    }
    reranker = RerankerFactoryV2.create(config)
    assert reranker.__class__.__name__ == "VertexRankingReranker"


def test_factory_lists_vertex_under_cross_encoder() -> None:
    """vertex가 cross-encoder approach의 유효 provider로 노출된다."""
    from app.modules.core.retrieval.rerankers.factory import RerankerFactoryV2

    providers = RerankerFactoryV2.get_providers_for_approach("cross-encoder")
    assert "vertex" in providers
