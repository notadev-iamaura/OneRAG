"""
BAAI BGE reranker implementation.

Uses the Hugging Face Transformers sequence-classification path documented for
BAAI/bge-reranker-v2-m3. The model scores query/passage pairs directly; higher
scores are more relevant, and sigmoid normalization maps logits into [0, 1].
"""

from __future__ import annotations

import asyncio
import threading
from contextlib import nullcontext
from dataclasses import dataclass
from typing import Any

from .....lib.logger import get_logger
from ..interfaces import SearchResult

logger = get_logger(__name__)

# 무거운 의존성(torch/transformers)은 import 가드로 보호한다.
# local-embedding extra 미설치 환경(기본 dev/CI)에서도 모듈 import 자체는
# 성공하며, 실제 사용(런타임 검증/모델 로드) 시점에 명확한 안내 에러를 낸다.
try:
    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    HAS_BGE_RUNTIME = True
except ImportError:
    torch = None  # type: ignore[assignment]
    AutoModelForSequenceClassification = None  # type: ignore[assignment]
    AutoTokenizer = None  # type: ignore[assignment]
    HAS_BGE_RUNTIME = False


@dataclass(frozen=True)
class BGERerankerConfig:
    """BGE 리랭커 런타임 설정."""

    model_name: str = "BAAI/bge-reranker-v2-m3"
    top_n: int = 10
    max_documents: int = 16
    batch_size: int = 8
    max_length: int = 384
    normalize_scores: bool = True
    use_fp16: bool = False
    device: str | None = None
    # 점수 계산 timeout(초). None이면 무제한(기존 동작). P1-B에서 추가:
    # CPU 바운드 추론이 무한정 이벤트 루프를 점유하지 않도록 별도 스레드 +
    # asyncio.wait_for로 deadline을 건다.
    timeout: float | None = None


class BGEReranker:
    """
    BAAI/bge-reranker-v2-m3 기반 로컬 다국어 리랭커.

    sentence-transformers의 CrossEncoder가 아니라 Transformers를 직접 사용한다.
    BGE reranker 모델 카드는 query/passage 쌍 점수화를 Transformers 또는
    FlagEmbedding으로 문서화하므로, 추가 프로덕션 의존성(FlagEmbedding)을
    피하기 위해 Transformers 경로를 택했다.
    """

    def __init__(
        self,
        model_name: str = "BAAI/bge-reranker-v2-m3",
        *,
        top_n: int = 10,
        max_documents: int = 16,
        batch_size: int = 8,
        max_length: int = 384,
        normalize_scores: bool = True,
        use_fp16: bool = False,
        device: str | None = None,
        timeout: float | None = None,
        validate_runtime: bool = True,
    ) -> None:
        """
        BGE 리랭커를 초기화한다(모델은 lazy 로드).

        Args:
            model_name: HuggingFace 모델명(다국어 기본값).
            top_n: 리랭킹 후 반환할 최대 결과 수.
            max_documents: 점수화할 최대 후보 문서 수.
            batch_size: 추론 배치 크기.
            max_length: 토크나이저 최대 토큰 길이.
            normalize_scores: sigmoid로 [0,1] 정규화 여부.
            use_fp16: CUDA에서 fp16 추론 사용 여부.
            device: 실행 디바이스(None이면 자동 감지: cuda > mps > cpu).
            timeout: 점수 계산 deadline(초). None/0 이하면 무제한.
            validate_runtime: True면 torch/transformers 미설치 시 ImportError.

        Raises:
            ImportError: validate_runtime이 True인데 의존성이 없는 경우.
        """
        if validate_runtime and not HAS_BGE_RUNTIME:
            raise ImportError(
                "BGEReranker requires torch and transformers. "
                "Build or install with the local-embedding extra."
            )

        # timeout은 양수만 유효. 0 이하/숫자 아님이면 무제한(None)으로 폴백한다.
        resolved_timeout: float | None
        try:
            resolved_timeout = float(timeout) if timeout is not None else None
        except (TypeError, ValueError):
            resolved_timeout = None
        if resolved_timeout is not None and resolved_timeout <= 0:
            resolved_timeout = None

        self.config = BGERerankerConfig(
            model_name=model_name,
            top_n=max(1, top_n),
            max_documents=max(1, max_documents),
            batch_size=max(1, batch_size),
            max_length=max(32, max_length),
            normalize_scores=normalize_scores,
            use_fp16=use_fp16,
            device=device,
            timeout=resolved_timeout,
        )
        self.model_name = self.config.model_name
        self.top_n = self.config.top_n
        self.max_documents = self.config.max_documents
        self.batch_size = self.config.batch_size
        self.max_length = self.config.max_length
        self.normalize_scores = self.config.normalize_scores
        self.use_fp16 = self.config.use_fp16
        self.timeout = self.config.timeout
        self.device = self._resolve_device(device)
        self._tokenizer: Any | None = None
        self._model: Any | None = None
        self.stats = {
            "total_requests": 0,
            "successful_requests": 0,
            "failed_requests": 0,
            "total_documents_scored": 0,
        }

        logger.info(
            "BGEReranker initialized",
            extra={
                "model": self.model_name,
                "device": self.device,
                "top_n": self.top_n,
                "max_documents": self.max_documents,
                "batch_size": self.batch_size,
                "max_length": self.max_length,
                "normalize_scores": self.normalize_scores,
                "use_fp16": self.use_fp16,
            },
        )

    def _resolve_device(self, requested_device: str | None) -> str:
        """실행 디바이스를 결정한다(요청값 우선, 없으면 cuda > mps > cpu)."""
        if requested_device:
            return requested_device
        if torch is None:
            return "cpu"
        if torch.cuda.is_available():
            return "cuda"
        mps_backend = getattr(getattr(torch, "backends", None), "mps", None)
        if mps_backend is not None and mps_backend.is_available():
            return "mps"
        return "cpu"

    async def initialize(self) -> None:
        """토크나이저와 sequence-classification 모델을 lazy 로드한다."""
        if self._tokenizer is not None and self._model is not None:
            return
        if (
            not HAS_BGE_RUNTIME
            or AutoTokenizer is None
            or AutoModelForSequenceClassification is None
        ):
            raise ImportError(
                "BGEReranker requires torch and transformers. "
                "Build or install with the local-embedding extra."
            )

        logger.info("Loading BGE reranker model", extra={"model": self.model_name})
        self._tokenizer = AutoTokenizer.from_pretrained(self.model_name)

        model_kwargs: dict[str, Any] = {}
        if self.use_fp16 and self.device == "cuda" and torch is not None:
            model_kwargs["torch_dtype"] = torch.float16
        elif self.use_fp16:
            logger.info(
                "BGE fp16 disabled because the selected device is not CUDA",
                extra={"device": self.device},
            )

        self._model = AutoModelForSequenceClassification.from_pretrained(
            self.model_name,
            **model_kwargs,
        )
        self._model.to(self.device)
        self._model.eval()
        logger.info("BGE reranker model loaded", extra={"model": self.model_name})

    async def close(self) -> None:
        """모델 참조를 해제해 런타임이 메모리를 회수하도록 한다."""
        self._tokenizer = None
        self._model = None
        if torch is not None and self.device == "cuda":
            torch.cuda.empty_cache()
        logger.info("BGEReranker resources released")

    async def rerank(
        self,
        query: str,
        results: list[SearchResult],
        top_n: int | None = None,
    ) -> list[SearchResult]:
        """
        query/document 쌍을 점수화해 가장 관련성 높은 문서를 반환한다.

        Args:
            query: 사용자 쿼리.
            results: 하이브리드 검색 후보 문서.
            top_n: 리랭킹 후 반환할 최대 문서 수.

        Returns:
            점수 내림차순으로 정렬된 상위 문서 리스트.

        Raises:
            TimeoutError: timeout 설정 시 deadline 초과.
            Exception: 점수 계산 중 발생한 예외(숨기지 않고 전파).
        """
        if not results:
            return []

        await self.initialize()
        self.stats["total_requests"] += 1

        requested_top_n = max(1, top_n or self.top_n)
        candidate_limit = min(len(results), self.max_documents)
        candidates = results[:candidate_limit]

        # I1: 협조적 중단(cooperative cancellation) 신호. timeout으로 wait_for를
        #     끊어도 백그라운드 스레드는 즉시 멈추지 않으므로, 배치 경계마다 이
        #     이벤트를 검사해 좀비 스레드를 빠르게 회수한다(워커 고갈 방지).
        cancel_event = threading.Event()
        try:
            pairs = [[query, result.content or ""] for result in candidates]
            # CPU 바운드 추론을 별도 스레드에서 실행해 이벤트 루프를 막지 않고,
            # timeout이 설정돼 있으면 wait_for로 deadline을 건다(무한 대기 방지, P1-B).
            # timeout이 None이면 기존처럼 스레드에서 그대로 완료를 기다린다.
            score_task = asyncio.to_thread(self._compute_scores, pairs, cancel_event)
            if self.timeout is not None:
                try:
                    scores = await asyncio.wait_for(score_task, timeout=self.timeout)
                except TimeoutError:
                    # I1: timeout 발동 → 협조적 중단 신호를 set. 스레드는 다음 배치
                    #     경계에서 RuntimeError로 빠져나와 회수된다(좀비 방지).
                    cancel_event.set()
                    logger.warning(
                        "BGE reranking timeout — 협조적 중단 신호 전송",
                        extra={"timeout_seconds": self.timeout},
                    )
                    raise
            else:
                scores = await score_task
            reranked = [
                SearchResult(
                    id=result.id,
                    content=result.content,
                    score=float(score),
                    metadata=dict(result.metadata),
                )
                for result, score in zip(candidates, scores, strict=True)
            ]
            reranked.sort(key=lambda item: item.score, reverse=True)
            reranked = reranked[: min(requested_top_n, len(reranked))]

            self.stats["successful_requests"] += 1
            self.stats["total_documents_scored"] += len(candidates)
            logger.info(
                "BGE reranking completed",
                extra={
                    "input_count": len(results),
                    "scored_count": len(candidates),
                    "returned_count": len(reranked),
                    "model": self.model_name,
                },
            )
            return reranked
        except Exception:
            self.stats["failed_requests"] += 1
            logger.warning("BGE reranking failed", exc_info=True)
            raise

    def _compute_scores(
        self,
        pairs: list[list[str]],
        cancel_event: threading.Event | None = None,
    ) -> list[float]:
        """배치 단위로 query/passage 쌍의 점수를 계산한다(별도 스레드 실행).

        I1: cancel_event가 주어지면 각 배치 경계에서 이를 검사해, set돼 있으면
        남은 배치를 건너뛰고 즉시 빠져나온다. timeout 시 호출 측이 이 이벤트를
        set하므로, 백그라운드 스레드가 전체 배치를 끝까지 돌지 않고 다음 배치
        경계(batch_size 단위 지연)에서 회수된다(좀비 스레드/워커 고갈 방지).

        Args:
            pairs: [query, passage] 쌍 리스트.
            cancel_event: 협조적 중단 신호(선택). set되면 배치 경계에서 중단.

        Returns:
            각 쌍의 점수 리스트(정상 완료 시).

        Raises:
            RuntimeError: 미초기화 상태이거나 cancel_event가 set돼 중단된 경우.
        """
        # I1: 협조적 중단을 최우선 검사 — 이미 취소 신호가 set돼 있으면 init
        #     상태와 무관하게 즉시 빠져나온다. timeout으로 호출 측이 cancel_event를
        #     set한 직후 스레드가 본 루프에 진입하기 전이라도 좀비로 남지 않도록
        #     보장하며, torch 미설치 환경에서도 중단 의미를 일관되게 유지한다.
        if cancel_event is not None and cancel_event.is_set():
            raise RuntimeError("BGE reranking cancelled (timeout)")

        if self._tokenizer is None or self._model is None or torch is None:
            raise RuntimeError("BGE reranker is not initialized")

        scores: list[float] = []
        inference_context = getattr(torch, "inference_mode", None)
        context_factory = (
            inference_context if inference_context is not None else nullcontext
        )

        for start in range(0, len(pairs), self.batch_size):
            # I1: 배치 경계 협조적 중단 검사 — timeout으로 취소 요청 시 조기 종료.
            if cancel_event is not None and cancel_event.is_set():
                raise RuntimeError("BGE reranking cancelled (timeout)")
            batch_pairs = pairs[start : start + self.batch_size]
            inputs = self._tokenizer(
                batch_pairs,
                padding=True,
                truncation=True,
                return_tensors="pt",
                max_length=self.max_length,
            )
            inputs = {key: value.to(self.device) for key, value in inputs.items()}

            with context_factory():
                logits = self._model(**inputs, return_dict=True).logits.view(-1).float()
                if self.normalize_scores:
                    logits = torch.sigmoid(logits)
                scores.extend(logits.cpu().tolist())

        return [float(score) for score in scores]

    def supports_caching(self) -> bool:
        """고정 모델/입력에 대해 결정론적이므로 캐싱을 지원한다."""
        return True

    def get_stats(self) -> dict[str, Any]:
        """리랭커 통계를 반환한다(success_rate 포함)."""
        total = self.stats["total_requests"]
        success_rate = (
            self.stats["successful_requests"] / total * 100 if total > 0 else 0.0
        )
        return {
            **self.stats,
            "success_rate": round(success_rate, 2),
            "model_name": self.model_name,
            "device": self.device,
            "top_n": self.top_n,
            "max_documents": self.max_documents,
            "batch_size": self.batch_size,
            "max_length": self.max_length,
            "normalize_scores": self.normalize_scores,
        }
