"""Locate the separately prepared datasets used by the archived local research runs."""

import os
from pathlib import Path


def research_cache() -> Path:
    """Use the original macOS/Linux cache layout unless the caller supplies another root."""
    return Path(os.environ.get("ONERAG_EVAL_CACHE_DIR") or "/tmp").expanduser()


def previous_input(path: Path) -> Path:
    """Resolve a fingerprinted legacy temporary path relative to this run's cache directory."""
    if not os.environ.get("ONERAG_EVAL_CACHE_DIR"):
        return path
    for prefix in (Path("/tmp"), Path("/private/tmp")):
        if path.is_relative_to(prefix):
            return research_cache() / path.relative_to(prefix)
    return path
