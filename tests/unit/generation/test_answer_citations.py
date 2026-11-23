from app.modules.core.generation.citations import AnswerCitations


def test_split_markers_resolve_to_the_original_sentence_and_claim():
    reader = AnswerCitations()
    doc = {"id": "calendar"}
    assert reader.label(doc, 2, "문을 엽니다.\n금요일에 닫습니다.") == (
        "[S2.1] 문을 엽니다.\n[S2.2] 금요일에 닫습니다."
    )
    raw = "금요일[S2.2]. 세부 정보는 근거 부족."
    text = "".join(reader.feed(char) for char in raw) + reader.finish()
    assert text == "금요일. 세부 정보는 근거 부족."
    [citation] = reader.citations
    assert (citation.document, citation.sentence_number, citation.quote, citation.claim) == (
        doc, 2, "금요일에 닫습니다.", "금요일"
    )


def test_empty_unknown_or_refusal_markers_do_not_create_sources():
    for answer in ("근거 부족 [S1.1]", "a value [S8.1]", "[S1.1]", "[notes]"):
        reader = AnswerCitations()
        reader.label("doc", 1, "An existing sentence.")
        reader.feed(answer)
        reader.finish()
        assert not reader.citations


def test_each_marker_attributes_only_the_nearest_claim_and_adjacent_markers_share_it():
    reader = AnswerCitations()
    reader.label("hours", 1, "Doors open at nine. Doors close at five.")
    reader.label("calendar", 2, "문은 금요일에 닫습니다.")
    raw = (
        "An unrelated assertion. Dr. Kim opens the doors at nine [S1.1]. "
        "다른 설명입니다; 문은 금요일에 닫습니다 [S2.1] [S1.2]."
    )
    reader.feed(raw)
    reader.finish()
    assert [item.claim for item in reader.citations] == [
        "Dr. Kim opens the doors at nine", "문은 금요일에 닫습니다", "문은 금요일에 닫습니다",
    ]


def test_only_positive_short_format_requests_select_the_structured_reader():
    for query in (
        "마감일은? 짧은 정답만 답하세요. 근거가 부족하면 '근거 부족'이라고 답하세요.",
        "마감일은? 단답형으로 알려 주세요.", "마감일은? 이름만 알려줘.",
        "When is the deadline? Give the short answer only. If unsupported, say so.",
        "Please provide a short answer.", "How many? Answer only.", "Give me the answer only.",
    ):
        assert AnswerCitations(query).short_answer, query
    for query in (
        "단답이 아닌 서술형으로 자세히 설명해 주세요.", "정답만 답하지 말고 이유도 알려 주세요.",
        "정답만 답하면 되는 경우를 알려 주세요.",
        "Please answer only in English and include a detailed explanation.",
        "Answer only if you have enough evidence.", "Do not give a short answer.",
        "What does the phrase short answer mean?",
    ):
        assert not AnswerCitations(query).short_answer, query


def test_streamed_labels_preserve_word_boundaries_and_korean_punctuation():
    text = "마감합니다 [S1.1]. Friday [S1.1]closing [S1.1]"
    for width in range(1, len(text) + 1):
        reader = AnswerCitations()
        reader.label("calendar", 1, "Friday closing.")
        output = "".join(reader.feed(text[i:i + width]) for i in range(0, len(text), width))
        assert output + reader.finish() == "마감합니다. Friday closing"
        assert reader.status == "verified_quotes"
    reader.feed("마감합니다 [S1.1] [S1.")
    reader.finish()
    assert reader.status == "invalid_citation" and not reader.citations


def test_short_response_is_released_after_resolving_its_evidence():
    assert AnswerCitations("마감일은? 정답만.").short_answer
    assert not AnswerCitations("이름만 바꾸면 되는지 설명해주세요.").short_answer
    reader = AnswerCitations("마감일은? 짧은 정답만 답하세요.")
    reader.label("calendar", 1, "The office closes Friday.")
    assert reader.feed("EVIDENCE: [S1.1]\nANS") == reader.feed("WER: 금요일") == ""
    assert reader.finish() == "금요일"
    assert reader.citations[0].quote == "The office closes Friday."
    reader.feed("EVIDENCE: [S9.8]\nANSWER: 월요일")
    assert reader.finish() == "근거 부족" and not reader.citations
    assert reader.status == "invalid_citation"
    reader.feed("근거: 없음\n답: 근거 부족")
    assert reader.finish() == "근거 부족" and reader.status == "insufficient"
    reader.feed("근거: [S98.1]\n답: 근거 부족")
    assert reader.finish() == "근거 부족" and reader.status == "invalid_citation"
