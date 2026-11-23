"""Promote candidates explicitly linked to top passages without replacing the first three hits."""

import re
import unicodedata
from typing import Any


def _words(text: str) -> str:
    return " " + " ".join(re.findall(r"\w+", unicodedata.normalize("NFKC", text).casefold())) + " "


def prioritize_linked_titles(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if len(candidates) < 5:
        return candidates
    titles = []
    bodies = []
    for doc in candidates:
        title = (doc.get("metadata") or {}).get("title") or ""
        title = _words(str(title).partition(" (")[0])
        titles.append(title if len(title.strip()) >= 4 else "")
        bodies.append(_words(doc["content"]))

    def priority(i: int) -> int:
        if i < 3:
            return i
        for j in range(3):
            if (titles[i] and titles[i] in bodies[j]) or (titles[j] and titles[j] in bodies[i]):
                return max(3, i - 3)
        return i

    return [candidates[i] for i in sorted(range(len(candidates)), key=priority)]
