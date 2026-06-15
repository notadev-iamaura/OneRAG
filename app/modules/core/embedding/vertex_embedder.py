"""Vertex AI 텍스트 임베딩 provider (선택적/ADC 기반).

기능:
- Application Default Credentials(ADC, 서비스 계정/워크로드 ID)로 인증해
  GOOGLE_API_KEY 없이 GCP 운영 환경에서 임베딩을 생성한다.
- Vertex AI Text Embeddings predict REST API를 httpx로 직접 호출(무거운
  vertexai SDK 비의존)하며, 배치(instances 묶음) 호출·429/5xx 지수 backoff·
  토큰 갱신 race lock·predictions 개수 검증을 포함한다.

의존성:
- google-auth(ADC 토큰 발급)는 코어 의존성이 아닌 선택적 extra(`vertex`)다.
  미설치 환경에서도 본 모듈 import 자체는 성공하며, 실제 인증 시점에 친절한
  설치 안내 에러를 던진다(_refresh_access_token 내부 지연 import + 가드).

사용:
- EmbedderFactory.create(config)에서 provider="vertex"로 선택한다.
"""

from __future__ import annotations

import asyncio
import math
import os
import threading
import time
from typing import Any, Literal

import httpx

from ....lib.logger import get_logger
from .interfaces import BaseEmbedder

logger = get_logger(__name__)

VERTEX_AUTH_SCOPES = ("https://www.googleapis.com/auth/cloud-platform",)
DEFAULT_VERTEX_EMBEDDING_LOCATION = "us-central1"
DEFAULT_VERTEX_EMBEDDING_MODEL = "gemini-embedding-001"
DEFAULT_VERTEX_EMBEDDING_DIMENSIONS = 3072
RETRYABLE_VERTEX_STATUS_CODES = {429, 500, 502, 503, 504}

# google-auth 미설치 시 사용자에게 보여줄 설치 안내 메시지.
_VERTEX_INSTALL_HINT = (
    "Vertex AI 임베딩을 사용하려면 google-auth가 필요합니다. "
    "설치: uv sync --extra vertex"
)


def _l2_norm(vector: list[float]) -> float:
    """벡터의 L2 노름(유클리드 길이)을 계산한다."""
    return math.sqrt(sum(value * value for value in vector))


def _normalize_model_name(model_name: str) -> str:
    """`models/`·`google/` 접두사를 제거해 Vertex predict 경로용 모델명으로 정규화한다."""
    if model_name.startswith("models/"):
        return model_name.removeprefix("models/")
    if model_name.startswith("google/"):
        return model_name.removeprefix("google/")
    return model_name


def _env_int(name: str, default: int) -> int:
    """환경변수를 정수로 파싱하되, 비어있거나 잘못된 값이면 기본값을 사용한다."""
    value = os.getenv(name)
    if value is None or value == "":
        return default
    try:
        return int(value)
    except ValueError:
        logger.warning("Invalid integer for %s=%r; using %s", name, value, default)
        return default


def _env_float(name: str, default: float) -> float:
    """환경변수를 실수로 파싱하되, 비어있거나 잘못된 값이면 기본값을 사용한다."""
    value = os.getenv(name)
    if value is None or value == "":
        return default
    try:
        return float(value)
    except ValueError:
        logger.warning("Invalid float for %s=%r; using %s", name, value, default)
        return default


class VertexAIEmbedder(BaseEmbedder):
    """ADC 기반 Vertex AI Text Embeddings 클라이언트."""

    def __init__(
        self,
        project_id: str | None = None,
        location: str = DEFAULT_VERTEX_EMBEDDING_LOCATION,
        model_name: str = DEFAULT_VERTEX_EMBEDDING_MODEL,
        output_dimensionality: int = DEFAULT_VERTEX_EMBEDDING_DIMENSIONS,
        batch_size: int = 16,
        auto_truncate: bool = True,
        timeout: float = 60.0,
        max_retries: int | None = None,
        retry_base_seconds: float | None = None,
        retry_max_seconds: float | None = None,
        document_request_delay_seconds: float | None = None,
        http_client: httpx.Client | None = None,
    ) -> None:
        """Vertex AI 임베더를 초기화한다.

        Args:
            project_id: GCP 프로젝트 ID. None이면 표준 환경변수에서 조회한다.
            location: Vertex AI 리전(예: us-central1).
            model_name: 임베딩 모델명(접두사 자동 정규화).
            output_dimensionality: 출력 벡터 차원.
            batch_size: 한 요청에 묶을 텍스트 수.
            auto_truncate: 긴 입력 자동 절단 여부.
            timeout: HTTP 타임아웃(초).
            max_retries: 재시도 횟수(None이면 환경변수/기본값 사용).
            retry_base_seconds: 지수 backoff 기본 지연.
            retry_max_seconds: backoff 상한 지연.
            document_request_delay_seconds: 문서 배치 요청 사이 pacing 지연.
            http_client: 주입용 httpx.Client(테스트/커넥션 재사용).

        Raises:
            ValueError: project_id를 어디서도 해석할 수 없는 경우.
        """
        # project_id 폴백: 인자 → Vertex/Google Cloud 표준 환경변수.
        # (OneRAG에는 Document AI가 없으므로 ONERAG_DOCUMENT_AI_PROJECT_ID 폴백은 제외)
        resolved_project_id = (
            project_id
            or os.getenv("VERTEX_AI_PROJECT_ID")
            or os.getenv("GOOGLE_CLOUD_PROJECT")
            or os.getenv("GCLOUD_PROJECT")
        )
        if not resolved_project_id:
            raise ValueError(
                "Vertex AI project ID is required for embeddings. "
                "Set VERTEX_AI_PROJECT_ID, GOOGLE_CLOUD_PROJECT, or GCLOUD_PROJECT."
            )

        self.project_id = str(resolved_project_id)
        self.location = location or DEFAULT_VERTEX_EMBEDDING_LOCATION
        self.batch_size = batch_size
        self.auto_truncate = auto_truncate
        self.timeout = timeout
        self.max_retries = max(
            0,
            max_retries
            if max_retries is not None
            else _env_int("VERTEX_AI_EMBEDDING_MAX_RETRIES", 5),
        )
        self.retry_base_seconds = max(
            0.0,
            retry_base_seconds
            if retry_base_seconds is not None
            else _env_float("VERTEX_AI_EMBEDDING_RETRY_BASE_SECONDS", 1.0),
        )
        self.retry_max_seconds = max(
            self.retry_base_seconds,
            retry_max_seconds
            if retry_max_seconds is not None
            else _env_float("VERTEX_AI_EMBEDDING_RETRY_MAX_SECONDS", 30.0),
        )
        self.document_request_delay_seconds = max(
            0.0,
            document_request_delay_seconds
            if document_request_delay_seconds is not None
            else _env_float("VERTEX_AI_DOCUMENT_EMBEDDING_DELAY_SECONDS", 0.0),
        )
        self._credentials: Any | None = None
        # 병렬 임베딩(embed_chunks_parallel)에서 여러 스레드가 토큰을 동시 갱신할 때의
        # race(동시 refresh 중 token 이 순간 None) 를 방지하는 lock.
        self._token_lock = threading.Lock()
        self._client = http_client or httpx.Client(
            timeout=httpx.Timeout(timeout, connect=10.0),
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
        )

        normalized_model_name = _normalize_model_name(model_name)
        super().__init__(
            model_name=normalized_model_name,
            output_dimensionality=output_dimensionality,
            api_key=None,
        )

        logger.info(
            "Initialized VertexAIEmbedder: model=%s, dim=%s, location=%s",
            normalized_model_name,
            output_dimensionality,
            self.location,
        )

    @property
    def _predict_url(self) -> str:
        """Vertex predict REST 엔드포인트 URL을 구성한다."""
        return (
            f"https://{self.location}-aiplatform.googleapis.com/v1/"
            f"projects/{self.project_id}/locations/{self.location}/publishers/google/"
            f"models/{self.model_name}:predict"
        )

    def _refresh_access_token(self) -> str:
        """ADC 토큰을 발급/갱신한다(만료 시 자동 refresh).

        google-auth가 선택적 의존성이므로 지연 import + 가드로 처리한다. 미설치
        환경에서는 ImportError를 잡아 친절한 설치 안내 에러로 변환한다.

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

        # 여러 스레드가 동시 호출해도 자격증명 공유/갱신이 안전하도록 직렬화한다.
        with self._token_lock:
            if self._credentials is None:
                self._credentials, _ = google_auth_default(scopes=VERTEX_AUTH_SCOPES)
            if not self._credentials.valid:
                self._credentials.refresh(Request())
            token = getattr(self._credentials, "token", None)
            if not token:
                raise ValueError(
                    "Vertex AI ADC token could not be resolved for embeddings."
                )
            return str(token)

    def _retry_delay(self, attempt: int, response: httpx.Response) -> float:
        """재시도 지연을 계산한다(Retry-After 우선, 없으면 지수 backoff 상한)."""
        retry_base_seconds: float = float(self.retry_base_seconds)
        retry_max_seconds: float = float(self.retry_max_seconds)
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                return min(float(retry_after), retry_max_seconds)
            except ValueError:
                pass
        exponential_delay: float = retry_base_seconds * float(2 ** max(0, attempt - 1))
        return min(
            exponential_delay,
            retry_max_seconds,
        )

    def _normalize_and_validate(self, embedding: list[float]) -> list[float]:
        """임베딩을 L2 정규화하고 차원이 기대와 일치하는지 검증한다."""
        norm = _l2_norm(embedding)
        normalized = [value / norm for value in embedding] if norm > 0 else embedding
        if len(normalized) != self.output_dimensionality:
            raise RuntimeError(
                f"Unexpected Vertex embedding dimension: {len(normalized)} != "
                f"{self.output_dimensionality}"
            )
        return normalized

    def _predict_embeddings(
        self,
        texts: list[str],
        task_type: Literal["RETRIEVAL_DOCUMENT", "RETRIEVAL_QUERY"],
    ) -> list[list[float]]:
        """여러 텍스트를 한 번의 Vertex 요청으로 임베딩한다(배치 호출).

        Vertex predict API 는 instances 리스트를 받아 같은 순서로 predictions 를
        반환하므로, 입력 순서를 그대로 신뢰해 매핑한다. predictions 개수가 입력과
        다르면 순서 매핑이 깨진 것이므로 즉시 실패해 잘못된 임베딩 짝을 방지한다.

        Args:
            texts: 한 요청에 묶어 임베딩할 텍스트 목록.
            task_type: RETRIEVAL_DOCUMENT(색인) 또는 RETRIEVAL_QUERY(질의).

        Returns:
            입력과 동일한 순서의 정규화된 임베딩 벡터 목록.

        Raises:
            RuntimeError: predictions 개수 불일치 또는 응답 형식 이상.
        """
        if not texts:
            return []
        payload: dict[str, Any] = {
            "instances": [{"content": text, "task_type": task_type} for text in texts],
            "parameters": {
                "autoTruncate": self.auto_truncate,
                "outputDimensionality": self.output_dimensionality,
            },
        }
        headers = {
            "Authorization": f"Bearer {self._refresh_access_token()}",
            "Content-Type": "application/json; charset=utf-8",
        }

        for attempt in range(self.max_retries + 1):
            response = self._client.post(
                self._predict_url, headers=headers, json=payload
            )
            if response.status_code == 401:
                # 토큰 만료 가능성 → 자격증명 폐기 후 1회 재인증.
                self._credentials = None
                headers["Authorization"] = f"Bearer {self._refresh_access_token()}"
                response = self._client.post(
                    self._predict_url, headers=headers, json=payload
                )
            if (
                response.status_code in RETRYABLE_VERTEX_STATUS_CODES
                and attempt < self.max_retries
            ):
                delay = self._retry_delay(attempt + 1, response)
                logger.warning(
                    "Vertex embedding request failed with retryable status %s; "
                    "retrying in %.1fs (%s/%s)",
                    response.status_code,
                    delay,
                    attempt + 1,
                    self.max_retries,
                )
                time.sleep(delay)
                continue
            response.raise_for_status()
            break

        body = response.json()
        predictions = body.get("predictions") or []
        if len(predictions) != len(texts):
            raise RuntimeError(
                f"Vertex embedding response returned {len(predictions)} predictions "
                f"for {len(texts)} inputs; cannot map embeddings to inputs safely."
            )
        embeddings: list[list[float]] = []
        for prediction in predictions:
            values = prediction.get("embeddings", {}).get("values", [])
            if not isinstance(values, list) or not values:
                raise RuntimeError(
                    "Vertex embedding response did not include embeddings.values."
                )
            embeddings.append(
                self._normalize_and_validate([float(value) for value in values])
            )
        return embeddings

    def _predict_embedding(
        self,
        text: str,
        task_type: Literal["RETRIEVAL_DOCUMENT", "RETRIEVAL_QUERY"],
    ) -> list[float]:
        """단일 텍스트 임베딩(배치 호출의 1건짜리 래퍼)."""
        return self._predict_embeddings([text], task_type)[0]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """문서 리스트를 RETRIEVAL_DOCUMENT 타입으로 임베딩한다(배치 + pacing)."""
        if not texts:
            return []

        embeddings: list[list[float]] = []
        # batch_size 만큼 묶어 한 번의 요청으로 전송한다(HTTP 왕복 N → N/batch_size).
        # pacing delay 는 텍스트마다가 아니라 요청(배치) 사이에만 적용한다.
        for index in range(0, len(texts), self.batch_size):
            batch = texts[index : index + self.batch_size]
            if embeddings and self.document_request_delay_seconds > 0:
                time.sleep(self.document_request_delay_seconds)
            embeddings.extend(self._predict_embeddings(batch, "RETRIEVAL_DOCUMENT"))
        return embeddings

    def embed_query(self, text: str) -> list[float]:
        """단일 쿼리를 RETRIEVAL_QUERY 타입으로 임베딩한다."""
        if not text:
            return [0.0] * self.output_dimensionality
        return self._predict_embedding(text, "RETRIEVAL_QUERY")

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        """문서 임베딩 비동기 래퍼(블로킹 호출을 스레드로 위임)."""
        return await asyncio.to_thread(self.embed_documents, texts)

    async def aembed_query(self, text: str) -> list[float]:
        """쿼리 임베딩 비동기 래퍼(블로킹 호출을 스레드로 위임)."""
        return await asyncio.to_thread(self.embed_query, text)

    def validate_embedding(self, embedding: list[float]) -> bool:
        """임베딩 차원과 정규화(단위 벡터) 상태를 검증한다."""
        if not self._validate_dimension(embedding):
            return False
        norm = _l2_norm(embedding)
        return abs(norm - 1.0) <= 0.01 or norm == 0
