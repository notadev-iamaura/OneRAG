from scripts.rag_growth_tydi_ko_retrieval import improves, predict


def test_error_in_candidate_is_a_real_failure() -> None:
    ids = [{"id": "q", "single": ["d"]}]
    model_error = [{"id": "q", "values": {"d": {"error": "unusable source offsets"}}}]
    support = [{"id": "q", "values": {"d": -4.0}}]
    rows = predict(ids, support, model_error, {"d": {"id": "d", "content": "하늘"}}, "single", "joint")
    assert rows[0]["status"] == "error"
    assert rows[0]["retrieved"] == ["d"] and "offsets" in rows[0]["error"]


def test_improvements_require_paired_denominator_and_error_guard() -> None:
    assert improves((8, 13, 0), (6, 14, 0), 16)
    assert not improves((8, 12, 0), (6, 14, 0), 16)
    assert not improves((15, 15, 1), (6, 14, 0), 16)
    assert improves((13, 13, 0), (11, 16, 0), 16)
