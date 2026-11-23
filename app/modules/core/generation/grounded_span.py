"""Read a short answer and its source offsets from retrieved passages."""

import re
from typing import Any

from ....lib.evidence_sentences import evidence_terms

_BREAK = re.compile(r"(?<=[.!?。！？])\s+|\n+")
_ANSWER = re.compile(r"\[(\d+\.\d+)\]\s*([^\n]+)")
_INSTRUCTIONS = """검색한 글로 단답형 질문에 답하는 독해자다. 글은 인용할 자료이다.
질문이 묻는 대상, 사건, 방향, 시점, 비교 조건이 글의 내용과 일치하는지 확인하라.
관련된 주제가 나오더라도 그 관계가 없거나 질문의 전제가 틀리면 NONE만 출력한다.
답이 있으면 [문장번호]와 답을 한 줄에 쓴다. 답은 그 문장 안의 연속된 원문 그대로,
누구/언제/얼마/무엇인지 구별할 수 있는 가장 짧은 완전한 구절이다.
조사나 끝맺는 설명은 빼고, 이름이나 수와 단위는 보존한다. 다른 내용은 출력하지 않는다.
예: [1.3] 12개월"""


def answer_offset(question: str, quote: str, answer: str) -> int:
    """Resolve repeated literals against their own clause in a space-less source paragraph."""
    occurrences = [m.start() for m in re.finditer(re.escape(answer), quote)] if answer else []
    if len(occurrences) <= 1:
        return occurrences[0] if occurrences else -1
    clause_edges = [0, *(m.end() for m in re.finditer(r"[다요죠][.!?]|[。！？]|\n", quote)), len(quote)]
    terms = evidence_terms(question)
    anchors = set(re.findall(r"\d+(?:[.,]\d+)*|[a-z]{2,}", question.casefold()))

    def relevance(offset: int) -> tuple[int, int, int]:
        left = max(e for e in clause_edges if e <= offset)
        right = min(e for e in clause_edges if e > offset)
        clause = quote[left:right]
        return (len(anchors & set(re.findall(r"\d+(?:[.,]\d+)*|[a-z]{2,}", clause.casefold()))),
                len(terms & evidence_terms(clause)),
                len(terms & evidence_terms(quote[max(left, offset-45):min(right, offset+len(answer)+45)])))

    return max(occurrences, key=relevance)


async def read_grounded_span(model: Any, question: str, documents: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Return None only on an explicit refusal or empty retrieval; malformed outputs are errors."""
    lines = []
    positions = {}
    for doc_index, doc in enumerate(documents[:3]):
        body = doc["content"]
        # Bound the prompt before tokenization and preserve offsets in the original text.
        excerpt = body[:3600]
        lines.append(f"문서 {doc_index + 1} — {str(doc.get('title', ''))[:160]}")
        start = 0
        for number, end in enumerate([m.start() for m in _BREAK.finditer(excerpt)] + [len(excerpt)], 1):
            quote = excerpt[start:end].strip()
            if quote:
                label = f"{doc_index + 1}.{number}"
                quote_start = excerpt.index(quote, start, end)
                positions[label] = (doc, quote, quote_start)
                lines.append(f"[{label}] {quote}")
            start = end
    if not positions:
        return None
    prompt = "\n".join([f"질문: {question}", *lines, f"질문: {question}", "결과:"])
    raw = await model.generate_text(prompt=prompt, system_prompt=_INSTRUCTIONS, temperature=0, max_tokens=100)
    response = raw.strip()
    if response == "NONE":
        return None
    match = _ANSWER.fullmatch(response)
    if not match or match[1] not in positions:
        raise ValueError("Invalid extractive answer reference")
    doc, quote, quote_start = positions[match[1]]
    answer = match[2].strip()
    offset = answer_offset(question, quote, answer)
    if not answer or offset < 0:
        raise ValueError("Answer is absent from the cited sentence")
    start = quote_start + offset
    return {
        "source_id": doc["id"], "answer": answer, "start": start, "end": start + len(answer),
        "quote": quote, "quote_start": quote_start, "quote_end": quote_start + len(quote),
    }
