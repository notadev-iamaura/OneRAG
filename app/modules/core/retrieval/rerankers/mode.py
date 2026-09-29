"""Resolve the process's reranker mode without importing provider implementations."""

import argparse
import math
import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, cast

RerankMode = Literal["legacy", "jev"]
Effective = Literal["legacy", "jev", "disabled"]
Source = Literal["env", "yaml", "compat_decision_enforce", "default", "disabled"]


class RerankerModeConfigError(Exception):
    """A reranker configuration error that must prevent startup."""


@dataclass(frozen=True)
class ResolvedRerankMode:
    effective: Effective
    source: Source
    warnings: tuple[str, ...] = ()
    legacy_approach: str | None = None
    legacy_provider: str | None = None


def normalize_mode_value(raw: Any) -> RerankMode | None:
    """Normalize YAML/schema values; only YAML may leave the mode empty."""
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise RerankerModeConfigError("RERANK_MODE 는 문자열 legacy 또는 jev 여야 합니다")
    value = raw.strip().lower()
    if not value:
        return None
    if value == "legacy_observe":
        raise RerankerModeConfigError(
            "legacy_observe 는 예약된 값이며 아직 지원하지 않습니다. legacy 또는 jev 를 쓰세요"
        )
    if value not in ("legacy", "jev"):
        raise RerankerModeConfigError("지원하지 않는 RERANK_MODE 입니다. legacy 또는 jev 를 쓰세요")
    return cast(RerankMode, value)


def resolve_rerank_mode(
    reranking_config: Mapping[str, Any], env: Mapping[str, str]
) -> ResolvedRerankMode:
    """Validate syntax before disabled, then resolve env > YAML > compatibility."""
    yaml_mode = normalize_mode_value(reranking_config.get("mode"))
    env_mode = None
    if "RERANK_MODE" in env:
        env_mode = normalize_mode_value(env["RERANK_MODE"])
        if env_mode is None:
            raise RerankerModeConfigError("RERANK_MODE 가 비어 있습니다. legacy 또는 jev")
    if not reranking_config.get("enabled", True):
        return ResolvedRerankMode("disabled", "disabled")

    warnings: list[str] = []
    mode = env_mode or yaml_mode
    source: Source = "env" if env_mode else "yaml" if yaml_mode else "default"
    if env_mode and yaml_mode and env_mode != yaml_mode:
        warnings.append("rerank_mode_conflict: source=env overrides source=yaml")
    typesafe = reranking_config.get("typesafe") or {}
    old_yaml = typesafe.get("mode") if isinstance(typesafe, Mapping) else None
    if mode:
        if "TYPESAFE_JEV_MODE" in env or old_yaml not in (None, ""):
            warnings.append("rerank_mode_ignored: 옛 typesafe mode 는 무시됨")
        if mode == "jev":
            return ResolvedRerankMode("jev", source, tuple(warnings))
    approach = reranking_config.get("approach", "cross-encoder")
    provider = reranking_config.get("provider", "jina")
    if approach == "decision":
        if mode == "legacy":
            warnings.append("rerank_mode_legacy_decision: decision → llm/google")
            approach, provider = "llm", "google"
        else:
            old = env.get("TYPESAFE_JEV_MODE", old_yaml)
            old = old.strip().lower() if isinstance(old, str) else old
            if old == "enforce":
                return ResolvedRerankMode(
                    "jev", "compat_decision_enforce", ("rerank_mode_deprecated: decision+enforce",)
                )
            # Do not echo arbitrary configuration values (they could contain secrets).
            label = old if old in ("shadow", "off") else "default" if not old else "invalid"
            raise RerankerModeConfigError(
                f"reranking.approach=decision (typesafe mode={label}) 는 더 이상 지원하지 않습니다.\n"
                "  이전 동작: 리랭킹 없이 검색 순서 top_n 사용.\n"
                "  RERANK_MODE 를 명시하세요:\n"
                "    RERANK_MODE=legacy  → 기존 리랭커(approach/provider, decision이면 llm/google) 사용\n"
                "    RERANK_MODE=jev     → Jev 관련성 필터 사용 (TYPESAFE_API_KEY 필요)\n"
                "  그리고 reranking.approach 를 decision 이 아닌 값으로 바꾸세요."
            )
    elif mode is None and "TYPESAFE_JEV_MODE" in env:
        warnings.append("rerank_mode_ignored: approach=decision 이 아니므로 TYPESAFE_JEV_MODE 무시됨")
    return ResolvedRerankMode("legacy", source, tuple(warnings), approach, provider)


def _require_typesafe_key(env: Mapping[str, str]) -> str:
    key = env.get("TYPESAFE_API_KEY", "").strip()
    if not key:
        raise RerankerModeConfigError(
            "RERANK_MODE=jev(또는 호환 decision+enforce)에는 TYPESAFE_API_KEY 가 필요합니다. "
            "Jev를 끄려면 RERANK_MODE=legacy"
        )
    return key


def _validate_jev_options(options: Any) -> None:
    """Check constructor options without constructing a reranker or HTTP client."""
    if options is None:
        return
    if not isinstance(options, Mapping):
        raise RerankerModeConfigError("Invalid Jev options: typesafe must be a mapping")
    positive_ints = {
        "min_keep", "max_documents", "max_passage_chars", "concurrency",
        "circuit_failure_threshold", "recent_maxlen",
    }
    positive_numbers = {
        "timeout", "deadline_seconds", "score_scale_max", "circuit_cooldown_seconds",
    }
    strings = {"model", "endpoint", "instructions"}
    allowed = positive_ints | positive_numbers | strings | {
        "min_relevance", "question_type", "mode", "shadow_background", "client", "decision_sink",
    }
    if options.keys() - allowed:
        raise RerankerModeConfigError("Invalid Jev options: unsupported option")
    for name, value in options.items():
        valid = True
        if name in positive_ints:
            valid = type(value) is int and value >= 1
        elif name in positive_numbers or name == "min_relevance":
            valid = type(value) in (int, float) and math.isfinite(value)
            if name == "min_relevance":
                valid = valid and 0 <= value <= 1
            elif name == "circuit_cooldown_seconds":
                valid = valid and value >= 0
            else:
                valid = valid and value > 0
        elif name in strings:
            valid = isinstance(value, str) or (name == "instructions" and value is None)
        elif name == "question_type":
            valid = value in ("noul", "score")
        if not valid:
            raise RerankerModeConfigError(f"Invalid Jev option: {name}")


def preflight_rerank_mode(
    config: Mapping[str, Any], env: Mapping[str, str]
) -> ResolvedRerankMode:
    rc = config.get("reranking", {})
    resolved = resolve_rerank_mode(rc, env)
    if resolved.effective == "jev":
        _require_typesafe_key(env)
        _validate_jev_options(rc.get("typesafe"))
    return resolved


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", required=True, action="store_true")
    parser.parse_args()
    from app.lib.config_loader import load_config

    try:
        # Mode validation belongs to the resolver, including during schema migration.
        config = load_config(validate=False)
        resolved = preflight_rerank_mode(config, os.environ)
    except RerankerModeConfigError as exc:
        print(f"RerankerModeConfigError: {exc}")
        return 1
    key_status = "present" if os.environ.get("TYPESAFE_API_KEY", "").strip() else "missing"
    print(f"effective={resolved.effective} source={resolved.source} "
          f"typesafe_key={key_status} warnings={len(resolved.warnings)}")
    for warning in resolved.warnings:
        print(warning)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
