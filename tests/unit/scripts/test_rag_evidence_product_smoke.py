from copy import deepcopy

import pytest

from scripts import rag_evidence_product_smoke as smoke


@pytest.mark.asyncio
async def test_real_chat_and_factories_with_synthetic_search_and_generation():
    report = await smoke.exercise({"implementation": "generative", "top_k": 1}, smoke.DEFAULT_HOOK,
                                  smoke.RecordedModel(), smoke.FakeSearch(), include_fault=True)
    assert report["passed"], report["rows"]
    assert [r["actual"]["status"] for r in report["rows"]] == ["verified_quotes", "insufficient", "error"]
    assert all(r["http_status"] == 200 and r["calls"] and "library" in r["retrieved_ids"][0] for r in report["rows"])
    returned = report["rows"][0]["actual"]
    assert smoke.NOTICE[slice(*returned["answer_range"])] == "수요일"
    assert returned["answer_range"][0] == smoke.NOTICE.rindex("수요일")


def test_wrong_occurrence_or_unexecuted_selected_policy_cannot_pass_smoke():
    a = smoke.NOTICE.index("수요일")
    source = {"document_id": "library", "additional_metadata": {"cited_sentences": [smoke.NOTICE],
              "offset_basis": "retrieved_chunk", "offset_unit": "unicode_codepoint",
              "answer_start": a, "answer_end": a + 3, "quote_start": 0, "quote_end": len(smoke.NOTICE)}}
    body = {"metadata": {"mode": "agent", "success": True, "grounding_status": "verified_quotes",
                         "tools_used": ["search_weaviate"]}, "sources": [source], "answer": "수요일"}
    hits = [{"query": smoke.ANSWER_QUERY, "ids": ["library"], "content": {"library": smoke.NOTICE}}]
    with pytest.raises(ValueError, match="actual occurrence"):
        smoke.verify_response(body, 200, hits, [{"outcome": "returned"}], smoke.ANSWER_QUERY, "answered")
    corrected = deepcopy(body)
    expected = smoke.NOTICE.rindex("수요일")
    corrected["sources"][0]["additional_metadata"].update(answer_start=expected, answer_end=expected+3)
    with pytest.raises(ValueError, match="did not both run"):
        smoke.verify_response(corrected, 200, hits, [], smoke.ANSWER_QUERY, "answered")
