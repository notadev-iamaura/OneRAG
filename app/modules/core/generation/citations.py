"""Request-local mapping from model-visible sentence labels to original passages."""

import re
from dataclasses import dataclass
from typing import Any

from ....lib.evidence_sentences import evidence_terms, read_citations, sentence_window

_LABEL = re.compile(r"\[S(\d{1,3})\.(\d{1,5})\]")
_VISIBLE_LABEL = re.compile(
    r"[ \t]*\[S\d{1,3}\.\d{1,5}\](?=\s|[.,!?;:。！？]|$)|\[S\d{1,3}\.\d{1,5}\]"
)
# Keep adjacent spacing and even a completed trailing label until the following
# character tells us whether to retain a word boundary or join punctuation.
_PARTIAL = re.compile(r"[ \t]*(?:\[(?:S(?:\d{0,3}(?:\.\d{0,5}\]?)?)?)?)?\Z")
_SENTENCES = re.compile(r"(?<=[.!?。！？])\s+|\n+")
_CLAIM_BOUNDARY = re.compile(
    r"\n+|(?<=[!?;])\s+|(?<=[。！？；])\s*"
    # Avoid chopping off initials and common honorifics from the cited claim.
    r"|(?<=\.)(?<!\b[A-Z]\.)(?<!\bDr\.)(?<!\bMr\.)(?<!\bMs\.)(?<!\bMrs\.)\s+"
)
_SHORT_KOREAN = re.compile(
    r"(?:단답(?:형)?(?:으로만|으로|만)?|(?:답|값|이름|수치)만)"
    r"(?:\s*(?:(?:답|대답|응답|말|제시|작성|부탁)(?:하세요|하십시오|하라|해)"
    r"|알려)(?:\s*(?:주세요|주십시오|줘요?|주라))?)?"
    r"(?=\s*[.!?。！？]|\s*$)"
)
_SHORT_ENGLISH = re.compile(
    r"(?:^|[.!?;:\n])\s*(?:please\s+)?"
    r"(?:(?:give|provide|write|return|use)\s+(?:me\s+)?(?:only\s+)?)?"
    r"(?:a\s+|the\s+)?(?:short answer(?:\s+only)?|answer only)"
    r"(?=\s*[.!?;]|\s*$)", re.I,
)
_REFUSAL = re.compile(
    r"^(?:근거\s*부족|정보\s*부족|insufficient(?: evidence)?|"
    r"(?:제공된|주어진|문서|자료|근거|정보|확인|알 수).{0,80}(?:없습니다|없다))\s*[.!]?$", re.I
)


@dataclass(frozen=True)
class PassageCitation:
    document: Any
    document_number: int
    sentence_number: int
    quote: str
    claim: str


class AnswerCitations:
    def __init__(self, query: str = "") -> None:
        self.short_answer = bool(_SHORT_KOREAN.search(query) or _SHORT_ENGLISH.search(query))
        self.query_terms = evidence_terms(query) if self.short_answer else set()
        self.abstention = "근거 부족" if re.search("[가-힣]", query) else "Insufficient evidence"
        self.passages: dict[tuple[int, int], tuple[Any, str]] = {}
        self.citations: list[PassageCitation] = []
        self.status = "uncited"
        self._pending = ""
        self._raw: list[str] = []

    def label(self, document: Any, number: int, content: str) -> str:
        lines = []
        sentences = list(filter(None, _SENTENCES.split(content.strip())))
        indices = (
            sentence_window(sentences, self.query_terms, limit=12 if number == 1 else 6)
            if self.short_answer else range(len(sentences))
        )
        for index in indices:
            self.passages[number, index + 1] = (document, sentences[index])
            lines.append(f"[S{number}.{index + 1}] {sentences[index]}")
        return "\n".join(lines)

    def feed(self, chunk: str) -> str:
        """Stream prose without labels and buffer structured short answers until validated."""
        self._raw.append(chunk)
        if self.short_answer:
            return ""
        text = self._pending + chunk
        partial = _PARTIAL.search(text)
        self._pending = text[partial.start():] if partial else ""
        return _VISIBLE_LABEL.sub("", text[:partial.start()] if partial else text)

    def finish(self) -> str:
        raw = "".join(self._raw)
        self._raw.clear()
        self.citations.clear()
        if self.short_answer:
            return self._short_result(raw.strip())
        end = 0
        claim = ""
        invalid = bool(re.search(r"\[S\d+(?:\.|\])", _LABEL.sub("", raw)))
        for match in _LABEL.finditer(raw):
            preceding = raw[end:match.start()].strip()
            # Reuse the claim for adjacent labels. A new label belongs to the
            # nearest sentence or clause, even when several share one line.
            for part in reversed(_CLAIM_BOUNDARY.split(preceding)):
                if part.strip(" \t.,;:!?。！？；"):
                    claim = part.strip()
                    break
            end = match.end()
            key = (int(match[1]), int(match[2]))
            passage = self.passages.get(key)
            if not passage or not claim:
                invalid = True
            if passage and claim and not _REFUSAL.fullmatch(claim):
                document, quote = passage
                self.citations.append(PassageCitation(document, *key, quote, claim))
        if invalid:
            self.citations.clear()
            self.status = "invalid_citation"
        elif _REFUSAL.fullmatch(_LABEL.sub("", raw).strip()):
            self.citations.clear()
            self.status = "insufficient"
        else:
            self.status = "verified_quotes" if self.citations else "uncited"
        tail = _VISIBLE_LABEL.sub("", self._pending)
        self._pending = ""
        return tail

    def _short_result(self, raw: str) -> str:
        empty_fields = re.fullmatch(
            r"(?:EVIDENCE|근거):\s*(?:\[\s*\]|없음|INSUFFICIENT|근거 부족)\s*\n"
            r"(?:ANSWER|답|답변|정답):\s*(.+)", raw, re.I,
        )
        if _REFUSAL.fullmatch(raw) or (empty_fields and _REFUSAL.fullmatch(empty_fields[1].strip())):
            self.status = "insufficient"
            return self.abstention
        visible = {f"S{d}.{s}": (f"S{d}", text) for (d, s), (_, text) in self.passages.items()}
        answer, labels = read_citations(raw, visible, fact_fields=False)
        if not answer or not labels or any(label not in visible for label in labels):
            self.status = "invalid_citation"
            return self.abstention
        if _REFUSAL.fullmatch(answer):
            self.status = "insufficient"
            return self.abstention
        for label in dict.fromkeys(labels):
            document_number, sentence_number = map(int, label[1:].split("."))
            document, quote = self.passages[document_number, sentence_number]
            self.citations.append(PassageCitation(document, document_number, sentence_number, quote, answer))
        self.status = "verified_quotes"
        return answer
