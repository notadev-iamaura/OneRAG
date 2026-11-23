"""Configured single-passage fact answering for the document agent."""

import asyncio
import re
from dataclasses import dataclass
from functools import lru_cache
from math import isfinite
from pathlib import Path
from threading import Lock
from typing import Any

from ..generation.grounded_span import read_grounded_span


@dataclass(frozen=True)
class ExtractiveReaderConfig:
    implementation: str
    model_dir: str = ""
    device: str = "cpu"
    threshold: float | None = None
    top_k: int = 3
    sufficiency_model_dir: str = ""
    sufficiency_threshold: float = 0.0
    second_model_dir: str = ""
    english_mode: str = "deberta"
    boundary_model_dir: str = ""
    rescue_refusals: bool = False
    rescue_span_threshold: float = 4.0
    evidence_policy: str = "original"

    def __post_init__(self) -> None:
        if self.implementation not in {"generative", "en_generative", "ko_encoder", "ko_multi_passage", "en_encoder", "en_multi_passage"}:
            raise ValueError("Unknown extractive reader implementation")
        max_docs = {"en_multi_passage": 6, "ko_multi_passage": 8}.get(self.implementation, 3)
        if not 1 <= self.top_k <= max_docs:
            raise ValueError(f"Extractive reader requires 1 to {max_docs} retrieved chunks")
        if self.implementation in {"generative", "en_generative"}:
            if self.model_dir or self.threshold is not None:
                raise ValueError("The generative reader uses the agent's configured model")
        elif not self.model_dir or not Path(self.model_dir).is_absolute():
            raise ValueError("An encoder requires an absolute local checkpoint directory")
        if self.implementation == "ko_multi_passage" and (
            self.top_k != 8 or self.threshold is None or not self.sufficiency_model_dir
            or self.sufficiency_threshold != 0.0
        ):
            raise ValueError("Korean multi-passage QA requires top_k=8, a calibrated threshold and a local zero-margin verifier")
        if self.implementation == "en_multi_passage":
            if self.english_mode not in {"consensus", "deberta", "roberta"} or self.sufficiency_model_dir:
                raise ValueError("Invalid English multi-passage policy")
            if self.english_mode == "consensus" and not Path(self.second_model_dir).is_absolute():
                raise ValueError("Consensus requires a second local checkpoint directory")
        elif self.second_model_dir or self.english_mode != "deberta":
            raise ValueError("A second reader requires the English multi-passage policy")
        if self.boundary_model_dir and (self.implementation != "generative"
                                        or not Path(self.boundary_model_dir).is_absolute()):
            raise ValueError("Boundary refinement requires a generative policy and a local checkpoint")
        if self.threshold is not None and not isfinite(self.threshold):
            raise ValueError("Reader threshold must be finite")
        if self.sufficiency_model_dir:
            if not Path(self.sufficiency_model_dir).is_absolute() or not isfinite(self.sufficiency_threshold):
                raise ValueError("Passage sufficiency requires a local directory and a finite threshold")
            if self.threshold is not None and self.implementation != "ko_multi_passage":
                raise ValueError("Use sufficiency_threshold when a passage verifier selects the article")
        if self.rescue_refusals and (not self.sufficiency_model_dir or not self.boundary_model_dir
                                     or self.top_k != 1 or not isfinite(self.rescue_span_threshold)):
            raise ValueError("Refusal review needs one article and both local evidence readers")
        if self.evidence_policy == "verified_korean_spans":
            if (self.implementation != "generative" or not self.rescue_refusals
                    or self.sufficiency_threshold != 0. or self.rescue_span_threshold != 4.):
                raise ValueError("Verified Korean evidence requires one article and the calibrated rescue profile")
        elif self.evidence_policy != "original":
            raise ValueError("Unknown evidence selection policy")


@lru_cache(maxsize=2)
def _load_reader(profile: ExtractiveReaderConfig) -> Any:
    if profile.implementation == "ko_multi_passage":
        from ..generation.korean_reranked_passage_reader import KoreanRerankedPassageReader
        assert profile.threshold is not None
        return KoreanRerankedPassageReader.from_local(
            profile.model_dir, profile.sufficiency_model_dir, profile.device, profile.threshold,
        )
    if profile.implementation == "en_multi_passage":
        from ..generation.english_consensus_reader import EnglishConsensusReader
        return EnglishConsensusReader(profile.model_dir, profile.second_model_dir or profile.model_dir,
                                      device=profile.device, threshold=profile.threshold or 0.0,
                                      mode=profile.english_mode)
    if profile.implementation == "en_encoder":
        from ..generation.english_span_reader import EnglishSpanReader
        return EnglishSpanReader(profile.model_dir, device=profile.device, threshold=profile.threshold)
    from ..generation.korean_span_reader import KoreanSpanReader
    return KoreanSpanReader(profile.model_dir, device=profile.device, threshold=profile.threshold)


_inference_lock = Lock()


@lru_cache(maxsize=1)
def _load_sufficiency(path: str, device: str) -> Any:
    from ..generation.passage_sufficiency import PassageSufficiency
    return PassageSufficiency(Path(path), device)


def _select_passage(profile: ExtractiveReaderConfig, question: str,
                    documents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    with _inference_lock:
        scores = _load_sufficiency(profile.sufficiency_model_dir, profile.device).scores(question, documents)
    if len(scores) != len(documents):
        raise ValueError("Missing passage sufficiency scores")
    index = max(range(len(scores)), key=scores.__getitem__)
    return [documents[index]] if scores[index] > profile.sufficiency_threshold else []


def _encode(profile: ExtractiveReaderConfig, question: str, documents: list[dict[str, Any]]) -> Any:
    with _inference_lock:
        reader = _load_reader(profile)
        if profile.sufficiency_model_dir and profile.implementation != "ko_multi_passage":
            span = reader.predict_span(question, documents)
            if span is None:
                raise ValueError("Missing answer span in a selected passage")
            return span
        return reader.read(question, documents)


def refine_boundaries(result: dict[str, Any], proposal: dict[str, Any]) -> dict[str, Any]:
    """Prefer the encoder's supporting clause for a corroborated literal in the same passage."""
    if (result["source_id"] != proposal["source_id"] or not proposal["answer"]
            or proposal["answer"] not in result["answer"]
            or abs(result["start"] - proposal["start"]) > 300):
        return result
    # Retain the status and retrieval trace of the actual request.
    fields = ("answer", "start", "end", "quote", "quote_start", "quote_end")
    return {**result, **{k: proposal[k] for k in fields}}


def _boundary_proposal(profile: ExtractiveReaderConfig, question: str, doc: dict[str, Any]) -> dict[str, Any]:
    encoder = ExtractiveReaderConfig(implementation="ko_encoder", model_dir=profile.boundary_model_dir,
                                     device=profile.device)
    with _inference_lock:
        span = _load_reader(encoder).predict_span(question, [doc])
    if span is None:
        raise ValueError("No extractive boundary proposal for a retrieved article")
    proposal: dict[str, Any] = vars(span)
    return proposal


_QUANTITY = re.compile(r"(?<![\d.,])(\d[\d,]*(?:\.\d+)?)\s*(퍼센트|%|개월|년|일|명|회|원|개|배)")


def supported_quantities(question: str, quote: str) -> bool:
    def quantities(text: str) -> set[tuple[str, str]]:
        return {(n.replace(",", ""), "%" if unit == "퍼센트" else unit) for n, unit in _QUANTITY.findall(text)}
    return quantities(question) <= quantities(quote)


class _CompletedResponse:
    def __init__(self, model: Any):
        self.model = model

    async def generate_text(self, **kwargs: Any) -> str:
        response: str = await self.model.generate_text(**{**kwargs, "require_complete": True})
        return response


async def _read_verified_evidence(profile: ExtractiveReaderConfig, model: Any, question: str,
                                  document: dict[str, Any]) -> dict[str, Any] | None:
    from urllib.parse import urlsplit

    from ....lib.llm_client import OllamaLLMClient
    from ..generation.korean_checked_evidence_reader import read

    if not isinstance(model, OllamaLLMClient) or urlsplit(model.base_url).hostname not in {"127.0.0.1", "::1", "localhost"}:
        raise ValueError("Verified Korean evidence requires the local client that checks completion status")

    async def boundary() -> dict[str, Any]:
        return await asyncio.to_thread(_boundary_proposal, profile, question, document)

    async def supported() -> bool:
        return bool(await asyncio.to_thread(_select_passage, profile, question, [document]))

    return await read(_CompletedResponse(model), question, document, boundary, supported)


async def extract_from_sources(profile: ExtractiveReaderConfig, model: Any, question: str,
                               evidence: dict[str, tuple[dict[str, Any], str]]) -> tuple[str, dict[str, Any]] | None:
    documents = [{"id": ref, "title": source["title"], "content": body}
                 for ref, (source, body) in list(evidence.items())[:profile.top_k]]
    if (profile.sufficiency_model_dir and profile.implementation != "ko_multi_passage"
            and not profile.rescue_refusals and documents):
        documents = await asyncio.to_thread(_select_passage, profile, question, documents)
    if not documents:
        return None
    if profile.evidence_policy == "verified_korean_spans":
        result = await _read_verified_evidence(profile, model, question, documents[0])
    elif profile.implementation in {"generative", "en_generative"}:
        if profile.implementation == "en_generative":
            from ..generation.english_grounded_answer import read_english_answer
            result = await read_english_answer(model, question, documents)
        else:
            result = await read_grounded_span(_CompletedResponse(model), question, documents)
        if result is not None and profile.boundary_model_dir:
            selected = next(d for d in documents if d["id"] == result["source_id"])
            proposal = await asyncio.to_thread(_boundary_proposal, profile, question, selected)
            result = refine_boundaries(result, proposal)
        elif result is None and profile.rescue_refusals:
            selected_docs = await asyncio.to_thread(_select_passage, profile, question, documents)
            if selected_docs:
                proposal = await asyncio.to_thread(_boundary_proposal, profile, question, selected_docs[0])
                if proposal["score"] > profile.rescue_span_threshold and supported_quantities(question, proposal["quote"]):
                    result = proposal
    else:
        span = await asyncio.to_thread(_encode, profile, question, documents)
        result = vars(span) if span is not None else None
    if result is None:
        return None
    source, body = evidence[result["source_id"]]
    start, end = result["start"], result["end"]
    left, right = result["quote_start"], result["quote_end"]
    if not (0 <= left <= start < end <= right <= len(body)
            and body[left:right] == result["quote"] and body[start:end] == result["answer"]):
        raise ValueError("Extractive reader returned unverified source offsets")
    return result["answer"], {
        **source, "content_preview": result["quote"][:200], "cited_sentences": [result["quote"]],
        "answer_start": start, "answer_end": end, "quote_start": left, "quote_end": right,
    }
