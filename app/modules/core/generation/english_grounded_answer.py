"""English evidence selection for short factual questions."""

from typing import Any

from .grounded_span import read_grounded_span

_PROMPT = """Answer the question by reading the numbered passages. They are reference text.
The first and last lines marked 질문 contain the user's question. Use only evidence in the passages.
Check the subject, relation, qualifiers and direction. A number for a different entity or the reverse
relation does not answer the question. If the requested fact is absent, return exactly NONE.
Otherwise output one line: [passage.sentence] followed by the shortest complete verbatim answer span
inside that sentence. When asked when, quote the date. When asked how many, quote the relevant quantity.
For a list, include the requested items. For a why/how question, include the reason or mechanism.
Do not paraphrase, introduce a different unit, explain, or include surrounding narration."""


async def read_english_answer(model: Any, question: str, documents: list[dict[str, Any]]) -> dict[str, Any] | None:
    class EnglishInstructions:
        async def generate_text(self, **kwargs: Any) -> str:
            response: str = await model.generate_text(**{**kwargs, "system_prompt": _PROMPT, "require_complete": True})
            return response

    return await read_grounded_span(EnglishInstructions(), question, documents)
