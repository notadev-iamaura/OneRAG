"""기존 Self-RAG 평가기를 감싸는 선택적 Jev 근거성 사전 판정."""

import asyncio
import math
import time
from collections import Counter
from dataclasses import replace
from typing import Any, Literal, Protocol

import structlog
from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from app.modules.core.decision import DecisionProvider, NoulResult, create_decision_provider

from .evaluator import EvalStatus, QualityEvaluation, QualityScore

logger = structlog.get_logger(__name__)


class PrecheckSettings(BaseModel):
    """검증되지 않은 DI 설정도 실패 시 off로 해석하는 런타임 설정."""

    # schemas/ 패키지가 legacy schemas.py를 가리므로 런타임은 독립적으로 검증한다.
    mode: Literal["off", "shadow", "enforce"] = "off"
    provider: Literal["jev", "mock"] = "jev"
    instructions: str = "Is the answer fully supported by the provided context?"
    threshold: float = Field(default=0.35, ge=0.0, le=1.0)
    timeout_ms: int = Field(default=500, ge=1, le=10000)
    max_context_chars: int = Field(default=8000, ge=1)
    api_base: str = "https://api.typesafe.ai"
    systemone_path: str = "/v1/systemone"
    model: str = "jev-latest"
    api_key: str | None = Field(default=None, repr=False)

    @field_validator("mode", mode="before")
    @classmethod
    def normalize_mode(cls, value: Any) -> str:
        if value is False or value is None:
            return "off"
        if isinstance(value, str) and value in ("off", "shadow", "enforce"):
            return value
        logger.warning("self_rag_precheck_unknown_mode", decision="off")
        return "off"

    @model_validator(mode="before")
    @classmethod
    def normalize_provider(cls, value: Any) -> Any:
        if isinstance(value, dict) and value.get("provider", "jev") not in ("jev", "mock"):
            logger.warning("self_rag_precheck_unknown_provider", decision="off")
            return {**value, "mode": "off", "provider": "jev"}
        return value

    @classmethod
    def from_mapping(cls, raw: Any) -> "PrecheckSettings":
        if raw is None:
            return cls()
        if isinstance(raw, BaseModel):
            raw = raw.model_dump()
        elif isinstance(raw, str):
            raw = {"mode": raw}
        try:
            settings: PrecheckSettings = cls.model_validate(raw)
            return settings
        except (ValidationError, TypeError, ValueError):
            # 검증 오류 원문에는 api_key가 포함될 수 있다.
            logger.warning("self_rag_precheck_invalid_config", decision="off")
            return cls()


class _QualityEvaluator(Protocol):
    """오케스트레이터가 사용하는 평가기 duck surface."""

    @property
    def quality_threshold(self) -> float: ...

    async def evaluate(self, query: str, answer: str, context: list[str]) -> QualityEvaluation: ...

    def requires_regeneration(self, quality: QualityScore) -> bool: ...


class PrecheckQualityEvaluator:
    """shadow는 점수를 보존하고 enforce는 확실한 저근거성만 단축 판정한다."""

    def __init__(
        self,
        base_evaluator: _QualityEvaluator,
        provider: DecisionProvider,
        settings: PrecheckSettings,
    ) -> None:
        self.base_evaluator = base_evaluator
        self.provider = provider
        self.settings = settings
        self.stats: Counter[str] = Counter()

    @property
    def quality_threshold(self) -> float:
        return self.base_evaluator.quality_threshold

    def requires_regeneration(self, quality: QualityScore) -> bool:
        return self.base_evaluator.requires_regeneration(quality)

    def __getattr__(self, name: str) -> Any:
        if name == "base_evaluator":
            raise AttributeError(name)
        return getattr(self.base_evaluator, name)

    async def evaluate(self, query: str, answer: str, context: list[str]) -> QualityEvaluation:
        """provider 오류는 기존 평가기로 fail-open하며 기본 평가 오류는 보존한다."""
        if self.settings.mode == "off":
            return await self.base_evaluator.evaluate(query, answer, context)

        if self.settings.mode == "shadow":
            result, evaluation = await asyncio.gather(
                self._safe_noul(query, answer, context),
                self.base_evaluator.evaluate(query, answer, context),
            )
            return self._annotate(evaluation, result, "shadow")

        result = await self._safe_noul(query, answer, context)
        if (
            result.status == "ok"
            and result.probability is not None
            and result.probability < self.settings.threshold
        ):
            quality = QualityScore(
                relevance=0.5,
                grounding=result.probability,
                completeness=0.5,
                confidence=0.5,
                overall=max(0.0, min(float(result.probability), self.quality_threshold - 1e-6)),
                reasoning=f"jev_precheck: ungrounded (p={result.probability:.4f})",
                raw_response={"source": "jev_precheck"},
            )
            return self._annotate(
                QualityEvaluation(EvalStatus.OK, quality), result, "short_circuit"
            )

        evaluation = await self.base_evaluator.evaluate(query, answer, context)
        decision = "fallthrough" if result.status == "ok" else "fail_open"
        return self._annotate(evaluation, result, decision)

    async def _safe_noul(self, query: str, answer: str, context: list[str]) -> NoulResult:
        started = time.perf_counter()
        try:
            state = {
                "query": query,
                "context": "\n\n".join(context)[: self.settings.max_context_chars],
                "answer": answer,
            }
            timeout_s = self.settings.timeout_ms / 1000
            result = await asyncio.wait_for(
                self.provider.noul(
                    instructions=self.settings.instructions, state=state, timeout_s=timeout_s
                ),
                timeout=timeout_s,
            )
            if result.status == "ok" and (
                isinstance(result.probability, bool)
                or not isinstance(result.probability, (int, float))
                or not math.isfinite(result.probability)
                or not 0 <= result.probability <= 1
            ):
                return replace(result, status="parse_error", probability=None)
            return result
        except TimeoutError:
            return NoulResult(
                probability=None,
                status="timeout",
                latency_ms=(time.perf_counter() - started) * 1000,
                provider=self.provider.name,
            )
        except Exception as exc:
            return NoulResult(
                probability=None,
                status="error",
                latency_ms=(time.perf_counter() - started) * 1000,
                provider=self.provider.name,
                error=type(exc).__name__,
            )

    def _annotate(
        self, evaluation: QualityEvaluation, result: NoulResult, decision: str
    ) -> QualityEvaluation:
        metadata = {
            "mode": self.settings.mode,
            "provider": result.provider,
            "status": result.status,
            "p_grounded": result.probability,
            "threshold": self.settings.threshold,
            "latency_ms": result.latency_ms,
            "decision": decision,
        }
        self.stats["calls"] += 1
        self.stats[decision] += 1
        self.stats[f"status_{result.status}"] += 1
        logger.debug("self_rag_precheck", **metadata)
        if evaluation.score is None:
            return evaluation
        annotated = replace(
            evaluation.score,
            raw_response={**evaluation.score.raw_response, "precheck": metadata},
        )
        return replace(evaluation, score=annotated)


def build_self_rag_evaluator(
    base_evaluator: _QualityEvaluator, precheck_config: Any = None
) -> _QualityEvaluator:
    """off는 provider/HTTP 클라이언트를 만들지 않고 기존 평가기 자체를 반환한다."""
    settings = PrecheckSettings.from_mapping(precheck_config)
    if settings.mode == "off":
        return base_evaluator
    if settings.provider == "jev" and not settings.api_key:
        logger.warning("self_rag_precheck_missing_api_key", mode=settings.mode, has_key=False)
    try:
        provider = create_decision_provider(settings.model_dump())
    except Exception:
        logger.warning("self_rag_precheck_provider_failed", decision="off")
        return base_evaluator
    logger.info("self_rag_precheck_enabled", mode=settings.mode, provider=settings.provider)
    return PrecheckQualityEvaluator(base_evaluator, provider, settings)
