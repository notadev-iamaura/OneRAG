"""Lexical evidence windows shared by ordinary chat and document agents."""

import re
from math import sqrt


def evidence_terms(text: str) -> set[str]:
    words = set(re.findall(r"\w+", text.casefold()))
    for word in re.findall(r"[가-힣]{2,}", text):
        words.update(word[i : i + 2] for i in range(len(word) - 1))
    return words


def sentence_window(segments: list[str], query_terms: set[str], limit: int = 6) -> list[int]:
    """Preserve original positions and nearby context for the most relevant sentences."""
    if len(segments) <= limit:
        return list(range(len(segments)))

    def relevance(i: int) -> float:
        terms = evidence_terms(segments[i])
        return len(terms & query_terms) / sqrt(max(1, len(terms)))

    best = sorted(range(len(segments)), key=relevance, reverse=True)
    selected = {0, *best[:3]}
    for i in (best[0] - 1, best[0] + 1, *best):
        if 0 <= i < len(segments):
            selected.add(i)
        if len(selected) >= limit:
            break
    return sorted(selected)


_REFERENCE_GROUP = re.compile(r"\[(S\d+\.\d+(?:\s*,\s*S\d+\.\d+)*)\]")


def read_citations(
    response: str, sentences: dict[str, tuple[str, str]], *, fact_fields: bool
) -> tuple[str, list[str]]:
    """Accept individual or grouped markers, requiring every marker to be syntactically valid."""
    if fact_fields and response.upper().startswith("FACT:"):
        proof, sep, answer = response.partition("\nANSWER:")
        if not sep:
            return "", []
        fact_lines = []
        for line in proof.splitlines():
            if not line.startswith("FACT:") or not _REFERENCE_GROUP.search(line):
                return "", []
            evidence = line.removeprefix("FACT:").strip()
            if _REFERENCE_GROUP.sub("", evidence).strip():
                return "", []
            fact_lines.append(evidence)
        response = "EVIDENCE: " + " ".join(fact_lines) + "\nANSWER:" + answer
    # A local model may translate the field heading differently. Only the
    # server-resolved sentence labels and any verbatim quote establish evidence.
    fields = re.fullmatch(
        r"(?:[^\W\d_][\w -]{0,20}:\s*)?(\[.*?)\n(?:ANSWER|답변|정답|답):\s*(.+)",
        response,
        re.S | re.I,
    )
    if fields:
        markers, answer = fields.groups()
        groups = list(_REFERENCE_GROUP.finditer(markers))
        if not groups or markers[: groups[0].start()].strip():
            return "", []
        for i, group in enumerate(groups):
            end = groups[i + 1].start() if i + 1 < len(groups) else len(markers)
            quote = " ".join(markers[group.end() : end].strip(" \t\r\n`'\"“”,;:").split())
            refs = [label.strip() for label in group[1].split(",")]
            if quote and not any(
                label in sentences and quote in " ".join(sentences[label][1].split())
                for label in refs
            ):
                return "", []
        response = answer.strip() + "\n" + " ".join(g[0] for g in groups)
    if not re.search(r"\]\s*[.!。]?\s*$", response):
        return "", []
    reference_groups = _REFERENCE_GROUP.findall(response)
    answer = _REFERENCE_GROUP.sub("", response).strip()
    if not reference_groups or not answer or re.search(r"\[\s*S\d", answer):
        return "", []
    # Removing inline evidence can leave punctuation on a line of its own.
    answer = re.sub(r"\s+([.!?。])", r"\1", answer).strip()
    return answer, [label.strip() for group in reference_groups for label in group.split(",")]
