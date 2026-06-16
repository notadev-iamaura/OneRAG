"""FAQ 질문/답변 컬럼 별칭 config 외부화 + 중복 단일화 테스트

SimpleChunker와 FAQProcessor에 중복 하드코딩돼 있던 질문/답변 컬럼명을
단일 소스(SimpleChunker.column_aliases)로 통합하고, config로 임의 언어
컬럼명을 추가할 수 있게 한 변경을 검증한다.

핵심 요구사항:
1. (회귀 0) 별칭 미설정 시 코드 내장 ko+en 기본 별칭을 사용한다.
2. (오버라이드) 별칭 주입 시 그 외 언어(일본어 質問/回答)도 인식된다.
3. (DRY) FAQProcessor가 청커와 동일한 단일 소스 별칭을 재사용한다.
4. 부분 지정 시 미지정 키는 기본값으로 보강된다.
"""

from __future__ import annotations

import pytest

from app.modules.core.documents.chunking.simple_chunker import SimpleChunker
from app.modules.core.documents.models import Document
from app.modules.core.documents.processors.faq_processor import FAQProcessor


def _faq_doc(item: dict) -> Document:
    return Document(source="x", doc_type="FAQ", data=[item])


def test_chunker_default_ko_en_aliases() -> None:
    """별칭 미설정 시 ko+en 기본 별칭이 동작한다(회귀 0)."""
    chunker = SimpleChunker()
    ko = chunker.chunk(_faq_doc({"질문": "q1", "답변": "a1"}))
    assert len(ko) == 1 and "q1" in ko[0].content and "a1" in ko[0].content
    en = chunker.chunk(_faq_doc({"question": "q2", "answer": "a2"}))
    assert len(en) == 1 and "q2" in en[0].content


def test_chunker_aliases_override_japanese() -> None:
    """별칭 주입 시 일본어 컬럼명도 인식된다."""
    chunker = SimpleChunker(
        column_aliases={"question": ["質問"], "answer": ["回答"]}
    )
    ja = chunker.chunk(_faq_doc({"質問": "qj", "回答": "aj"}))
    assert len(ja) == 1 and "qj" in ja[0].content and "aj" in ja[0].content


def test_chunker_partial_alias_keeps_default_for_missing_key() -> None:
    """질문만 지정하면 답변은 기본값(ko+en)으로 보강된다."""
    chunker = SimpleChunker(column_aliases={"question": ["質問"]})
    # 답변은 기본 'answer' 별칭으로 인식
    doc = chunker.chunk(_faq_doc({"質問": "qj", "answer": "aj"}))
    assert len(doc) == 1 and "qj" in doc[0].content


def test_faq_processor_shares_single_source_aliases() -> None:
    """FAQProcessor가 청커와 동일한 단일 소스 별칭을 재사용한다(DRY)."""
    processor = FAQProcessor()
    # 기본 별칭이 청커와 공유됨
    assert processor.column_aliases["question"] == SimpleChunker.DEFAULT_QUESTION_KEYS
    assert processor.column_aliases["answer"] == SimpleChunker.DEFAULT_ANSWER_KEYS


def test_faq_processor_column_aliases_override() -> None:
    """FAQProcessor에 별칭 주입 시 검증과 청킹이 동일 별칭을 쓴다."""
    processor = FAQProcessor(
        column_aliases={"question": ["質問"], "answer": ["回答"]}
    )
    assert processor.column_aliases["question"] == ["質問"]
    # 검증 단계도 주입 별칭을 사용해야 함(중복 제거 확인)
    import pandas as pd

    df = pd.DataFrame([{"質問": "q", "回答": "a"}])
    # 예외 없이 통과해야 한다(주입 별칭으로 필수 컬럼 인식)
    processor._validate_columns(df)


def test_faq_processor_validate_rejects_missing_columns() -> None:
    """주입 별칭에 없는 컬럼만 있으면 검증 실패한다(회귀 안전)."""
    import pandas as pd

    processor = FAQProcessor(
        column_aliases={"question": ["質問"], "answer": ["回答"]}
    )
    df = pd.DataFrame([{"질문": "q", "답변": "a"}])  # ko 컬럼은 주입 별칭에 없음
    with pytest.raises(ValueError):
        processor._validate_columns(df)
