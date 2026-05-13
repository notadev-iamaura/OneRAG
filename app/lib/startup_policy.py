"""
Startup policy helpers for operational readiness.

These helpers keep startup and readiness behavior consistent across the
application without coupling health endpoints to DI internals.
"""

from __future__ import annotations

import os

from app.lib.environment import is_production_environment

RETRIEVAL_STARTUP_POLICY_ENV = "RETRIEVAL_STARTUP_POLICY"
RETRIEVAL_STARTUP_POLICY_REQUIRED = "required"
RETRIEVAL_STARTUP_POLICY_DEGRADED = "degraded"
VALID_RETRIEVAL_STARTUP_POLICIES = {
    RETRIEVAL_STARTUP_POLICY_REQUIRED,
    RETRIEVAL_STARTUP_POLICY_DEGRADED,
}


def get_retrieval_startup_policy() -> str:
    """Return the retrieval startup policy for the current environment."""
    raw_policy = os.getenv(RETRIEVAL_STARTUP_POLICY_ENV, "").strip().lower()
    if raw_policy:
        if raw_policy not in VALID_RETRIEVAL_STARTUP_POLICIES:
            valid = ", ".join(sorted(VALID_RETRIEVAL_STARTUP_POLICIES))
            raise ValueError(
                f"{RETRIEVAL_STARTUP_POLICY_ENV} must be one of: {valid}. "
                f"Got: {raw_policy!r}"
            )
        return raw_policy

    return (
        RETRIEVAL_STARTUP_POLICY_REQUIRED
        if is_production_environment()
        else RETRIEVAL_STARTUP_POLICY_DEGRADED
    )


def is_retrieval_required() -> bool:
    """Return whether retrieval dependency failures should block readiness."""
    return get_retrieval_startup_policy() == RETRIEVAL_STARTUP_POLICY_REQUIRED
