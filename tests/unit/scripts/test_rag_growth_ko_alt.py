from scripts import rag_growth_ko_alt as alt


def test_fitted_threshold_scores_only_opposite_fold_and_uses_retrieved_span(monkeypatch):
    doc = {"id": "source", "title": "공개 일정", "content": "올해 5일"}
    raw, gold = [], []
    for i in range(8):
        positive = i % 2 == 0
        span = {"source_id": "source", "document_index": 0, "answer": "5일", "start": 3, "end": 5,
                "quote": "올해 5일", "quote_start": 0, "quote_end": 5, "score": 3 if positive else -1}
        raw.append({"id": str(i), "retrieved": ["source"], "spans": [span]})
        gold.append({"id": str(i), "source_id": "source", "answerable": positive, "answers": ["5일"] if positive else [],
                     "spans": [{"start": 3, "end": 5, "text": "5일"}] if positive else []})
    fit = alt.fit
    fitted = []

    def captured(raws, labels, docs):
        assert {r["id"] for r in raws} == {label["id"] for label in labels}
        fitted.append({r["id"] for r in raws})
        return fit(raws, labels, docs)

    monkeypatch.setattr(alt, "fit", captured)
    result = alt.score(raw, gold, [doc])
    assert fitted[0].isdisjoint(fitted[1]) and fitted[0] | fitted[1] == fitted[2]
    assert all(result["two_fold_out_of_fold"][g]["correct"] == 4 for g in ("answerable", "unanswerable"))
    assert [setting["train_rows"] for setting in result["fold_settings"]] == [4, 4]
    assert result["zero_threshold"]["overall"]["percent"] == 100
