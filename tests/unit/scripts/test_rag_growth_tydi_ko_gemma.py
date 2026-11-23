from typing import Any

import pytest

from app.modules.core.agent.extractive_reader import ExtractiveReaderConfig, extract_from_sources
from scripts.rag_growth_tydi_ko_gemma import checked_inputs, target


def test_target_is_exact_and_never_ignores_errors() -> None:
    def valid(p: int, n: int, e: int = 0) -> bool:
        return target({"answerable": {"n": 16, "correct": p}, "unanswerable": {"n": 16, "correct": n},
                       "statuses": {"error": e}})
    assert valid(10, 15) and valid(13, 13) and not valid(9, 16)
    assert not valid(12, 14) and not valid(16, 16, 1)


def test_inference_ranking_cannot_carry_gold_or_repeated_documents() -> None:
    docs = [{"id": k, "title": "제목", "content": "공개 원문"} for k in "abc"]
    qs = [{"id": "q", "question": "담당 부서는?"}]
    ranks = [{"id": "q", "passages": list("abc")}]
    assert set(checked_inputs(qs, docs, ranks, 1)) == set("abc")
    with pytest.raises(ValueError):
        checked_inputs([{**qs[0], "answers": ["추정 답"]}], docs, ranks, 1)
    with pytest.raises(ValueError):
        checked_inputs(qs, docs, [{**ranks[0], "answer": "기존 후보"}], 1)
    with pytest.raises(ValueError):
        checked_inputs(qs, docs, [{"id": "q", "passages": list("aab")}], 1)


@pytest.mark.asyncio
async def test_real_parser_requires_complete_and_explicit_none() -> None:
    class Fake:
        def __init__(self, text: str) -> None:
            self.text = text
        async def generate_text(self, **options: Any) -> str:
            assert options["require_complete"] and options["max_tokens"] == 100
            assert "우리 팀은 검토팀이다." in options["prompt"]
            if self.text == "partial":
                raise ValueError("Incomplete local model response")
            return self.text
    docs = {"doc": ({"title": "부서", "document_id": "doc"}, "우리 팀은 검토팀이다.")}
    profile = ExtractiveReaderConfig(implementation="generative", top_k=3)
    assert await extract_from_sources(profile, Fake("NONE"), "담당이 누구인가?", docs) is None
    answer = await extract_from_sources(profile, Fake("[1.1] 검토팀"), "담당이 누구인가?", docs)
    assert answer and answer[0] == "검토팀"
    for invalid in ("", "NONE...", "[1.1] 없는 팀", "partial"):
        with pytest.raises(ValueError):
            await extract_from_sources(profile, Fake(invalid), "담당이 누구인가?", docs)
