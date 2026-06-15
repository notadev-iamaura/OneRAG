"""Vertex AI Discovery Engine Ranking API 리랭커 (선택적/ADC 기반).

기능:
- cross-encoder approach의 ADC(키리스) provider. Discovery Engine
  ``rankingConfigs.rank`` 엔드포인트를 httpx로 직접 호출(무거운 SDK 비의존)해
  검색 결과를 재정렬한다.
- 생산 방어로직: record id 충돌 시 suffix 유일화, 401 토큰 재발급 1회 재시도,
  재시도 가능 상태코드({429,500,502,503,504}) 처리.

의존성:
- google-auth(ADC 토큰 발급)는 코어 의존성이 아닌 선택적 extra(`vertex`)다.
  미설치 환경에서도 본 모듈 import는 성공하며, 인증 시점에 친절한 설치 안내 에러를
  던진다(_refresh_access_token 내부 지연 import + 가드).

사용:
- RerankerFactoryV2에서 approach="cross-encoder", provider="vertex"로 선택한다.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

import httpx

from .....lib.logger import get_logger
from ..interfaces import SearchResult

logger = get_logger(__name__)

VERTEX_RANKING_AUTH_SCOPES = ("https://www.googleapis.com/auth/cloud-platform",)
DEFAULT_VERTEX_RANKING_LOCATION = "global"
DEFAULT_VERTEX_RANKING_CONFIG = "default_ranking_config"
DEFAULT_VERTEX_RANKING_MODEL = "semantic-ranker-default-004"
RETRYABLE_VERTEX_RANKING_STATUS_CODES = {429, 500, 502, 503, 504}

# google-auth 미설치 시 사용자에게 보여줄 설치 안내 메시지.
_VERTEX_INSTALL_HINT = (
    "Vertex AI 리랭킹을 사용하려면 google-auth가 필요합니다. "
    "설치: uv sync --extra vertex"
)


def _env_project_id() -> str | None:
    """GCP 프로젝트 ID를 Vertex/Google Cloud 표준 환경변수에서 조회한다.

    (OneRAG에는 Document AI가 없으므로 ONERAG_DOCUMENT_AI_PROJECT_ID 폴백은 제외)
    """
    return (
        os.getenv("VERTEX_RERANK_PROJECT_ID")
        or os.getenv("VERTEX_AI_PROJECT_ID")
        or os.getenv("GOOGLE_CLOUD_PROJECT")
        or os.getenv("GCLOUD_PROJECT")
    )


def _coerce_int(value: Any, default: int, *, minimum: int = 1) -> int:
    """값을 int로 변환하되 최소값을 보장하고, 잘못된 값이면 기본값을 사용한다."""
    if value is None or value == "":
        return max(minimum, default)
    try:
        return max(minimum, int(value))
    except (TypeError, ValueError):
        logger.warning("Invalid integer config value %r; using %s", value, default)
        return max(minimum, default)


def _coerce_float(value: Any, default: float, *, minimum: float = 0.1) -> float:
    """값을 float로 변환하되 최소값을 보장하고, 잘못된 값이면 기본값을 사용한다."""
    if value is None or value == "":
        return max(minimum, default)
    try:
        return max(minimum, float(value))
    except (TypeError, ValueError):
        logger.warning("Invalid float config value %r; using %s", value, default)
        return max(minimum, default)


def _coerce_bool(value: Any, default: bool) -> bool:
    """다양한 표현(문자열/숫자)을 bool로 변환한다."""
    if isinstance(value, bool):
        return value
    if value is None or value == "":
        return default
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "y", "on"}:
            return True
        if normalized in {"0", "false", "no", "n", "off"}:
            return False
    return bool(value)


@dataclass(frozen=True)
class VertexRankingRerankerConfig:
    """Discovery Engine Ranking API 런타임 설정."""

    project_id: str
    location: str = DEFAULT_VERTEX_RANKING_LOCATION
    ranking_config: str = DEFAULT_VERTEX_RANKING_CONFIG
    model: str = DEFAULT_VERTEX_RANKING_MODEL
    top_n: int = 10
    max_documents: int = 16
    timeout: float = 1.5
    max_retries: int = 1
    ignore_record_details_in_response: bool = True
    user_labels: dict[str, str] = field(default_factory=dict)


class VertexRankingReranker:
    """Discovery Engine ``rankingConfigs.rank`` 기반 리랭커."""

    def __init__(
        self,
        *,
        project_id: str | None = None,
        location: str = DEFAULT_VERTEX_RANKING_LOCATION,
        ranking_config: str = DEFAULT_VERTEX_RANKING_CONFIG,
        model: str = DEFAULT_VERTEX_RANKING_MODEL,
        top_n: int | str = 10,
        max_documents: int | str = 16,
        timeout: float | str = 1.5,
        max_retries: int | str = 1,
        ignore_record_details_in_response: bool | str = True,
        user_labels: dict[str, str] | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        """Vertex Ranking 리랭커를 초기화한다.

        Args:
            project_id: GCP 프로젝트 ID. None이면 표준 환경변수에서 조회한다.
            location: Discovery Engine ranking config 위치.
            ranking_config: rankingConfigs 리소스 이름 또는 전체 경로.
            model: Discovery Engine ranking 모델명.
            top_n: 반환할 상위 결과 수.
            max_documents: 점수화할 최대 후보 문서 수.
            timeout: HTTP 타임아웃(초).
            max_retries: 일시적 오류 재시도 횟수.
            ignore_record_details_in_response: 응답에서 record 본문 생략 여부.
            user_labels: Discovery Engine request userLabels.
            http_client: 주입용 httpx.AsyncClient(테스트/커넥션 재사용).

        Raises:
            ValueError: project_id를 어디서도 해석할 수 없는 경우.
        """
        resolved_project_id = project_id or _env_project_id()
        if not resolved_project_id:
            raise ValueError(
                "Vertex Ranking project ID is required. "
                "Set reranking.vertex.project_id, VERTEX_RERANK_PROJECT_ID, "
                "VERTEX_AI_PROJECT_ID, GOOGLE_CLOUD_PROJECT, or GCLOUD_PROJECT."
            )

        self.config = VertexRankingRerankerConfig(
            project_id=str(resolved_project_id),
            location=location or DEFAULT_VERTEX_RANKING_LOCATION,
            ranking_config=ranking_config or DEFAULT_VERTEX_RANKING_CONFIG,
            model=model or DEFAULT_VERTEX_RANKING_MODEL,
            top_n=_coerce_int(top_n, 10),
            max_documents=_coerce_int(max_documents, 16),
            timeout=_coerce_float(timeout, 1.5),
            max_retries=_coerce_int(max_retries, 1, minimum=0),
            ignore_record_details_in_response=_coerce_bool(
                ignore_record_details_in_response,
                True,
            ),
            user_labels=dict(user_labels or {}),
        )
        self.project_id = self.config.project_id
        self.location = self.config.location
        self.ranking_config = self.config.ranking_config
        self.model = self.config.model
        self.top_n = self.config.top_n
        self.max_documents = self.config.max_documents
        self.timeout = self.config.timeout
        self.max_retries = self.config.max_retries
        self.ignore_record_details_in_response = (
            self.config.ignore_record_details_in_response
        )
        self.user_labels = self.config.user_labels
        self._credentials: Any | None = None
        self._owns_client = http_client is None
        self._client = http_client or httpx.AsyncClient(
            timeout=httpx.Timeout(self.timeout, connect=min(10.0, self.timeout)),
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
        )
        self.stats = {
            "total_requests": 0,
            "successful_requests": 0,
            "failed_requests": 0,
            "total_documents_scored": 0,
        }

        logger.info(
            "VertexRankingReranker initialized",
            extra={
                "project_id": self.project_id,
                "location": self.location,
                "ranking_config": self.ranking_config,
                "model": self.model,
                "top_n": self.top_n,
                "max_documents": self.max_documents,
                "timeout": self.timeout,
            },
        )

    @property
    def ranking_config_path(self) -> str:
        """rankingConfigs 전체 리소스 경로를 구성한다."""
        if self.ranking_config.startswith("projects/"):
            return self.ranking_config
        return (
            f"projects/{self.project_id}/locations/{self.location}/"
            f"rankingConfigs/{self.ranking_config}"
        )

    @property
    def endpoint(self) -> str:
        """Discovery Engine rank REST 엔드포인트 URL."""
        return (
            f"https://discoveryengine.googleapis.com/v1/{self.ranking_config_path}:rank"
        )

    async def initialize(self) -> None:
        """HTTP API 클라이언트는 사전 네트워크 초기화가 필요 없다."""
        logger.debug("VertexRankingReranker initialization complete")

    async def close(self) -> None:
        """소유한 HTTP 클라이언트를 종료한다."""
        if self._owns_client:
            await self._client.aclose()
        logger.info("VertexRankingReranker closed")

    def _refresh_access_token(self) -> str:
        """ADC 토큰을 발급/갱신한다(만료 시 자동 refresh).

        google-auth가 선택적 의존성이므로 지연 import + 가드로 처리한다.

        Returns:
            유효한 OAuth2 액세스 토큰 문자열.

        Raises:
            RuntimeError: google-auth 미설치(설치 안내 포함).
            ValueError: 토큰을 해석하지 못한 경우.
        """
        try:
            from google.auth import default as google_auth_default
            from google.auth.transport.requests import Request
        except ImportError as error:  # google-auth 미설치(vertex extra 없음)
            raise RuntimeError(_VERTEX_INSTALL_HINT) from error

        if self._credentials is None:
            self._credentials, _ = google_auth_default(
                scopes=VERTEX_RANKING_AUTH_SCOPES
            )
        if not self._credentials.valid:
            self._credentials.refresh(Request())
        token = getattr(self._credentials, "token", None)
        if not token:
            raise ValueError("Discovery Engine ADC token could not be resolved.")
        return str(token)

    def _record_id_map(self, results: list[SearchResult]) -> dict[str, SearchResult]:
        """record id 충돌 시 인덱스 suffix로 유일화해 결과를 매핑한다."""
        seen: set[str] = set()
        id_map: dict[str, SearchResult] = {}
        for index, result in enumerate(results):
            base_id = str(result.id or index)
            record_id = base_id if base_id not in seen else f"{base_id}:{index}"
            seen.add(record_id)
            id_map[record_id] = result
        return id_map

    def _build_records(self, id_map: dict[str, SearchResult]) -> list[dict[str, str]]:
        """Discovery Engine rank 요청용 record 목록을 구성한다."""
        records = []
        for record_id, result in id_map.items():
            metadata = result.metadata or {}
            title = (
                metadata.get("title")
                or metadata.get("document_title")
                or metadata.get("filename")
                or metadata.get("file_name")
                or metadata.get("source")
                or record_id
            )
            records.append(
                {
                    "id": record_id,
                    "title": str(title),
                    "content": result.content or "",
                }
            )
        return records

    def _build_payload(
        self,
        query: str,
        records: list[dict[str, str]],
        top_n: int,
    ) -> dict[str, Any]:
        """rank API 요청 페이로드를 구성한다."""
        payload: dict[str, Any] = {
            "model": self.model,
            "topN": top_n,
            "query": query,
            "records": records,
            "ignoreRecordDetailsInResponse": self.ignore_record_details_in_response,
        }
        if self.user_labels:
            payload["userLabels"] = self.user_labels
        return payload

    async def rerank(
        self,
        query: str,
        results: list[SearchResult],
        top_n: int | None = None,
    ) -> list[SearchResult]:
        """검색 결과를 Discovery Engine Ranking API로 재정렬한다.

        Args:
            query: 원본 쿼리 문자열.
            results: 초기 검색 결과 리스트.
            top_n: 반환할 최대 결과 수(None이면 인스턴스 기본값).

        Returns:
            재정렬된 결과 리스트(점수 재조정됨).

        Raises:
            httpx.HTTPStatusError: API 호출 실패(stats 기록 후 전파).
        """
        if not results:
            return []

        self.stats["total_requests"] += 1
        requested_top_n = max(1, top_n or self.top_n)
        candidates = results[: min(len(results), self.max_documents)]
        id_map = self._record_id_map(candidates)
        records = self._build_records(id_map)
        payload = self._build_payload(
            query=query,
            records=records,
            top_n=min(requested_top_n, len(records)),
        )

        try:
            headers = {
                "Authorization": f"Bearer {self._refresh_access_token()}",
                "Content-Type": "application/json",
            }
            response = await self._post_rank(headers, payload)
            response_payload = response.json()
            reranked = self._parse_response(response_payload, id_map, requested_top_n)
            self.stats["successful_requests"] += 1
            self.stats["total_documents_scored"] += len(records)
            logger.info(
                "Vertex ranking completed",
                extra={
                    "input_count": len(results),
                    "scored_count": len(records),
                    "returned_count": len(reranked),
                    "model": self.model,
                },
            )
            return reranked
        except httpx.HTTPStatusError as exc:
            self.stats["failed_requests"] += 1
            logger.warning(
                "Vertex ranking HTTP error",
                extra={
                    "status_code": exc.response.status_code,
                    "response": exc.response.text[:1000],
                },
                exc_info=True,
            )
            raise
        except Exception as exc:
            self.stats["failed_requests"] += 1
            logger.warning(
                "Vertex ranking failed",
                extra={"error": str(exc)},
                exc_info=True,
            )
            raise

    async def _post_rank(
        self,
        headers: dict[str, str],
        payload: dict[str, Any],
    ) -> httpx.Response:
        """rank API에 POST하며 401 재인증·재시도 가능 상태코드를 처리한다."""
        last_response: httpx.Response | None = None
        for attempt in range(self.max_retries + 1):
            response = await self._client.post(
                self.endpoint,
                headers=headers,
                json=payload,
                timeout=self.timeout,
            )
            if response.status_code == 401 and attempt == 0:
                # 토큰 만료 가능성 → 자격증명 폐기 후 1회 재인증.
                self._credentials = None
                headers["Authorization"] = f"Bearer {self._refresh_access_token()}"
                response = await self._client.post(
                    self.endpoint,
                    headers=headers,
                    json=payload,
                    timeout=self.timeout,
                )
            if (
                response.status_code in RETRYABLE_VERTEX_RANKING_STATUS_CODES
                and attempt < self.max_retries
            ):
                last_response = response
                continue
            response.raise_for_status()
            return response

        if last_response is not None:
            last_response.raise_for_status()
        raise RuntimeError("Vertex ranking request failed without a response")

    def _parse_response(
        self,
        response_payload: dict[str, Any],
        id_map: dict[str, SearchResult],
        requested_top_n: int,
    ) -> list[SearchResult]:
        """rank API 응답을 SearchResult 목록으로 변환한다(점수/메타데이터 매핑)."""
        ranked_records = response_payload.get("records", [])
        if not isinstance(ranked_records, list):
            raise ValueError("Vertex ranking response missing records list")

        reranked: list[SearchResult] = []
        for record in ranked_records[:requested_top_n]:
            if not isinstance(record, dict):
                continue
            record_id = str(record.get("id", ""))
            if record_id not in id_map:
                continue
            score = float(record.get("score", 0.0))
            original = id_map[record_id]
            metadata = dict(original.metadata)
            metadata.update(
                {
                    "rerank_method": f"vertex-ranking:{self.model}",
                    "reranker_score": score,
                    "original_score": original.score,
                }
            )
            reranked.append(
                SearchResult(
                    id=original.id,
                    content=original.content,
                    score=score,
                    metadata=metadata,
                )
            )

        if not reranked:
            raise ValueError("Vertex ranking response did not match any input records")
        return reranked

    def supports_caching(self) -> bool:
        """리랭킹 결과 캐싱 지원 여부."""
        return True

    def get_stats(self) -> dict[str, Any]:
        """리랭킹 호출 통계를 반환한다."""
        total = self.stats["total_requests"]
        success_rate = (
            self.stats["successful_requests"] / total * 100 if total > 0 else 0.0
        )
        return {
            **self.stats,
            "success_rate": round(success_rate, 2),
            "project_id": self.project_id,
            "location": self.location,
            "ranking_config": self.ranking_config,
            "model": self.model,
            "top_n": self.top_n,
            "max_documents": self.max_documents,
        }
