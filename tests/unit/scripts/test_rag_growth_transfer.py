from dataclasses import asdict
from unittest.mock import AsyncMock, Mock

import pytest

from app.modules.core.generation import english_calibrated_spans as calibrated
from app.modules.core.generation.english_consensus_reader import select_answer
from app.modules.core.generation.english_evidence_selection import select_evidence
from app.modules.core.generation.english_span_proposals import window_spans
from app.modules.core.generation.english_span_reader import EnglishSpanReader
from app.modules.core.generation.english_span_review import review_spans
from app.modules.core.generation.korean_span_reader import SpanAnswer
from app.modules.core.retrieval.retrievers.local_span_retriever import LocalSpanRetriever
from scripts import rag_growth_transfer as transfer
from scripts.rag_growth_transfer_arms import predict_arm
from scripts.rag_growth_transfer_cross_domain import eligible, predict
from scripts.rag_growth_transfer_finetune import encode as training_window
from scripts.rag_growth_transfer_finetune_eval import output as guarded_tuned_answer
from scripts.rag_growth_transfer_fit import model as fit_linear_model
from scripts.rag_growth_transfer_tydi import annotation


def test_article_panels_are_disjoint_and_each_question_has_its_own_paragraph():
    articles = []
    for n in range(9):
        paragraphs = []
        for impossible in (False, True):
            body = f"Article {n} and condition {impossible}."
            paragraphs.append({"context": body, "qas": [{"id": f"q{n}-{impossible}",
                "question": f"Who {n}-{impossible}?", "is_impossible": impossible,
                "answers": [] if impossible else [{"text": "Article", "answer_start": 0}]}]})
        articles.append({"title": str(n), "paragraphs": paragraphs})
    sizes = dict.fromkeys(("development", "final", "confirmation"), 2)
    panels = transfer.panels(articles, sizes)
    assert panels == transfer.panels(articles[::-1], sizes)
    for docs, cases in panels.values():
        assert len(docs) == 6 and len({c["source"] for c in cases}) == len(cases) == 4
        assert sum(c["impossible"] for c in cases) == 2


def test_product_and_evaluation_use_identical_top_three_rank_penalty_and_threshold(monkeypatch):
    reader = EnglishSpanReader.__new__(EnglishSpanReader)
    reader.threshold, reader.rank_penalty = 2.0, 0.5
    candidates = [SpanAnswer(i, str(i), "score", 0, 5, "score.", 0, 6, margin)
                  for i, margin in enumerate((1.5, 3.0, 0.0, 30))]
    monkeypatch.setattr(reader, "predict_spans", lambda q, docs: candidates[:len(docs)])
    selected = reader.read("what?", [{}] * 4)
    row = {"lexical": ["3"], "hybrid": ["0", "1", "2"], "spans": {s.source_id: asdict(s) for s in candidates}}
    assert selected is not None and selected.source_id == "1"
    assert transfer.predict(row, 2.0, "candidate") == {"status": "answered", **asdict(selected)}
    assert transfer.predict(row, 2.5, "candidate") == {"status": "abstained"}
    assert transfer.predict(row | {"oracle_error": "ValueError"}, 0, "oracle") == {"status": "error"}


def test_correct_text_requires_exact_passage_and_official_offset_inside_quote():
    body = "John sold it. John bought it."
    docs = {"d": {"content": body}}
    case = {"impossible": False, "source": "d", "answers": [{"text": "John", "answer_start": 14}]}
    pred = {"status": "answered", "source_id": "d", "answer": "John", "start": 14, "end": 18,
            "quote_start": 14, "quote_end": len(body), "quote": body[14:]}
    assert transfer.grade(case, pred, docs)
    assert not transfer.grade(case, pred | {"quote": "invented"}, docs)
    assert not transfer.grade(case, pred | {"source_id": "wrong"}, docs)
    assert not transfer.grade(case, pred | {"start": 0, "end": 4, "quote_start": 0, "quote_end": 13, "quote": body[:13]}, docs)
    assert not transfer.grade({"impossible": True}, {"status": "error"}, docs)


def test_consensus_keeps_source_offsets_and_uses_null_evidence_from_both_readers():
    body = "Service was launched in 1969 and continued."
    a = SpanAnswer(0, "d", body[:28], 0, 28, body, 0, len(body), 8)
    b = SpanAnswer(0, "d", "1969", 24, 28, body, 0, len(body), 5)
    result = select_answer("When did it launch?", [a], [b], "consensus", 0)
    assert result is not None
    assert result.quote == body and result.answer == body[result.start:result.end] == "1969"
    assert select_answer("When did it launch?", [a], [b], "consensus", 20) is None
    assert select_answer("What happened?", [a], [], "deberta", 0) == a


@pytest.mark.asyncio
async def test_hybrid_adapter_exposes_ordered_product_search_results(monkeypatch):
    search = LocalSpanRetriever.__new__(LocalSpanRetriever)
    search.docs = {"a": {"title": "First", "content": "A"}, "b": {"title": "Second", "content": "B"}}
    monkeypatch.setattr(search, "rankings", lambda q: (["a", "b"], ["b", "a"], {"a": .01, "b": .02}))
    hits = await search.search("example", top_k=1)
    assert [(h.id, h.content, h.score, h.metadata["document_id"]) for h in hits] == [("b", "B", .02, "b")]
    assert await search.search("example", top_k=0) == []


@pytest.mark.asyncio
async def test_review_validates_verbatim_output_and_skips_agreement():
    body = "Audrey saw her sister Ruth."
    d = SpanAnswer(0, "d", "Audrey", 0, 6, body, 0, len(body), 8)
    r = SpanAnswer(0, "d", "Ruth", 22, 26, body, 0, len(body), 8)
    docs = [{"id": "d", "content": body}]
    model = Mock(generate_text=AsyncMock(return_value='{"excerpt":1,"answer":"Ruth"}'))
    found, called = await review_spans("Whom did Audrey see?", docs, [d], [d], 0, model)
    assert found == d and not called
    model.generate_text.assert_not_awaited()
    found, called = await review_spans("Whom did Audrey see?", docs, [d], [r], 0, model)
    assert called and found is not None and found.answer == body[found.start:found.end] == "Ruth"
    assert found.quote == body and found.source_id == "d"
    model.generate_text.return_value = '{"excerpt":1,"answer":"invented"}'
    with pytest.raises(ValueError, match="verbatim"):
        await review_spans("Whom did Audrey see?", docs, [d], [r], 0, model)
    model.generate_text.return_value = '{"excerpt":0,"answer":""}'
    assert await review_spans("Whom did Audrey see?", docs, [d], [r], 0, model) == (None, True)


def test_comparator_reader_error_cannot_change_actual_selected_arm_or_baseline():
    reader = Mock(choose=EnglishSpanReader.choose)
    body = "A local source."
    docs = {d: {"id": d, "content": body} for d in ("1", "2")}

    def measure(_question, batch):
        if any(d["id"] == "2" for d in batch):
            raise ValueError("malformed second passage")
        return [SpanAnswer(i, d["id"], "local", 2, 7, body, 0, len(body), 5) for i,d in enumerate(batch)]

    reader.predict_spans.side_effect = measure
    same_question = {}
    assert predict_arm("What?", ["1", "2"], docs, reader, -2, cached=same_question)["status"] == "error"
    assert predict_arm("What?", ["1"], docs, reader, 0, mode="baseline", cached=same_question)["status"] == "answered"
    assert predict_arm("What?", ["1"], docs, reader, -2, cached=same_question)["source_id"] == "1"
    assert reader.predict_spans.call_count == 2


def test_unanswerable_tydi_requires_every_annotator_to_find_no_passage_and_no_short_answer():
    a = {"passage_answer_candidate_index": [-1, -1, -1], "minimal_answers_start_byte": [-1, -1, -1],
         "minimal_answers_end_byte": [-1, -1, -1], "yes_no_answer": ["NONE", "NONE", "NONE"]}
    assert annotation(a) == (True, ())
    assert annotation(a | {"passage_answer_candidate_index": [-1, -1, 6]}) is None
    assert annotation(a | {"yes_no_answer": ["NONE", "NONE", "NO"]}) is None
    answer = a | {"passage_answer_candidate_index": [6, 6, 6],
                  "minimal_answers_start_byte": [10, 10, 12], "minimal_answers_end_byte": [15, 15, 15]}
    assert annotation(answer) == (False, ((6, 10, 15), (6, 12, 15)))
    assert annotation(answer | {"minimal_answers_start_byte": [10, 11, 12]}) is None


def test_evidence_selection_preserves_offsets_and_handles_close_conflicting_answers():
    a = SpanAnswer(0, "a", "Alpha", 0, 5, "Alpha.", 0, 6, 2)
    b = SpanAnswer(1, "b", "Beta", 0, 4, "Beta.", 0, 5, 3)
    decision = select_evidence("Name?", [a,b], [], [.035,.017], "source_support", 0)
    assert decision is not None and decision.source_id == "a" and decision.quote == "Alpha."
    assert select_evidence("Name?", [a,b], [], [.03,.03], "source_support", 2) is None
    with pytest.raises(ValueError, match="source"):
        select_evidence("Name?", [a,b], [b,a], [.02,.02], "agreement", -2)
    pred = predict("Name?", {"original": [asdict(a)], "scores": [.03], "multidomain": {"error":"x"}}, "source_support", -2)
    assert pred["status"] == "answered"


def test_cross_domain_requires_one_gain_and_no_losses_in_each_development_domain():
    def m(p,n):
        return {"errors": 0, "metrics":{"positive":{"passed":p}, "negative":{"passed":n}}}
    base = {"squad": m(12,10), "development": m(10,10)}
    assert eligible(base, {"squad":m(12,11), "development":m(11,10)})
    assert not eligible(base, {"squad":m(12,11), "development":m(10,10)})
    assert not eligible(base, {"squad":m(11,12), "development":m(11,10)})


def test_top_spans_recover_multiple_verbatim_alternatives_including_whitespace_runner_up():
    import numpy as np

    text = "A B"
    proposed = window_spans(np.array([0,4,6,5],dtype=float),np.array([0,4,6,5],dtype=float),
                            [[0,0],[0,1],[1,2],[2,3]],[None,1,1,1],text,4)
    values=[text[a:b] for _,a,b in proposed]
    assert len(values)==len(set(values))
    assert "B" in values and "A" in values
    assert all(s == s.strip() and s for s in values)


def test_candidate_features_add_incumbent_and_trained_coefficients_respond_to_supervision():
    text="Alpha saw Beta."
    a=SpanAnswer(0,"d","Alpha",0,5,text,0,len(text),4)
    b=SpanAnswer(0,"d","Beta",10,14,text,0,len(text),5)
    ans,v=calibrated.features("Who did Alpha see?",[{"id":"d","title":"Example","content":text}],[.03],[[a]],[b])
    assert [x.answer for x in ans]==["Alpha","Beta"] and all(len(x)==len(calibrated.NAMES) for x in v)
    rank=fit_linear_model([[-2.0],[-1.0],[1.0],[2.0]],[0,0,1,1],[1]*4)
    assert calibrated.probability(rank,[1.0]) > .5 > calibrated.probability(rank,[-1.0])
    assert calibrated.decide(b,.51,a,"guarded",.5)==a
    assert calibrated.decide(b,.9,a,"guarded",.5)==b
    assert calibrated.decide(b,.1,a,"guarded",.5) is None


def test_supervised_token_targets_use_cls_for_native_negative_and_context_tokens_for_positive():
    class Encoding(dict):
        def sequence_ids(self, index):
            return [None, 0, None, 1, 1, None]

    class Tokenizer:
        cls_token_id=1
        model_input_names=["input_ids"]

        def __call__(self,question,body=None,**kwargs):
            if body is None:
                return {"offset_mapping":[(0,len(question))]}
            return Encoding(input_ids=[[1,2,3,4,5,3]],offset_mapping=[[(0,0),(0,4),(0,0),(0,5),(6,10),(0,0)]])

    raw={"question":"Who?","content":"Alpha Beta","impossible":False,"answers":[{"text":"Beta","answer_start":6}]}
    assert training_window(Tokenizer(),raw)[1:]==(4,4)
    assert training_window(Tokenizer(),raw|{"impossible":True,"answers":[]})[1:]==(0,0)


def test_finetuned_guard_defers_only_in_registered_margin_band():
    a=SpanAnswer(0,"doc","Alpha",0,5,"Alpha Beta",0,10,8.)
    b=SpanAnswer(0,"doc","Beta",6,10,"Alpha Beta",0,10,1.)
    case={"question":"Who?"}
    row={"original":[asdict(a)],"tuned":[[asdict(b)]]}
    assert guarded_tuned_answer(case,row,0)["answer"]=="Alpha"
    assert guarded_tuned_answer(case,row,-3)["answer"]=="Beta"
    assert guarded_tuned_answer(case,row,4)["status"]=="abstained"
