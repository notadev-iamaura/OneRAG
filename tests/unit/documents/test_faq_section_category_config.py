"""FAQ 섹션/카테고리 컬럼 별칭 config 외부화 테스트

SimpleChunker가 청크 메타데이터로 인식하는 섹션/카테고리 컬럼명을
question/answer와 동일하게 column_aliases로 외부화한 변경을 검증한다.
(과거: '섹션명'/'카테고리'를 하드코딩 → question/answer와 비대칭)

핵심 요구사항:
1. (회귀 0) 별칭 미설정 시 코드 내장 ko+en 기본 별칭(section/섹션명,
   category/카테고리)으로 메타데이터가 그대로 채워진다.
2. (우선순위 동치) 'section'과 '섹션명'이 동시 존재하면 'section'(앞 항목) 채택.
3. (오버라이드) 별칭 주입 시 그 외 언어(일본어 セクション/カテゴリ)도 인식된다.
4. (FAQProcessor 단일 소스) 청커와 동일한 별칭 맵에 section/category가 노출된다.
5. (미존재 시 미설정) 섹션/카테고리 컬럼이 없으면 메타데이터에 키를 넣지 않는다.
"""

from __future__ import annotations

from app.modules.core.documents.chunking.simple_chunker import SimpleChunker
from app.modules.core.documents.models import Document
from app.modules.core.documents.processors.faq_processor import FAQProcessor


def _faq_doc(item: dict) -> Document:
    return Document(source="x", doc_type="FAQ", data=[item])


def test_default_korean_section_category_recognized() -> None:
    """별칭 미설정 시 한국어 컬럼명(섹션명/카테고리)이 메타에 채워진다(회귀 0)."""
    chunker = SimpleChunker()
    chunks = chunker.chunk(
        _faq_doc({"질문": "q", "답변": "a", "섹션명": "이용안내", "카테고리": "결제"})
    )
    assert len(chunks) == 1
    assert chunks[0].metadata["section"] == "이용안내"
    assert chunks[0].metadata["category"] == "결제"


def test_default_english_section_category_recognized() -> None:
    """별칭 미설정 시 영어 컬럼명(section/category)도 메타에 채워진다(회귀 0)."""
    chunker = SimpleChunker()
    chunks = chunker.chunk(
        _faq_doc({"question": "q", "answer": "a", "section": "billing", "category": "payment"})
    )
    assert chunks[0].metadata["section"] == "billing"
    assert chunks[0].metadata["category"] == "payment"


def test_english_takes_priority_over_korean_when_both_present() -> None:
    """section/섹션명 동시 존재 시 'section'(앞 항목) 우선 — 기존 동작 동치."""
    chunker = SimpleChunker()
    chunks = chunker.chunk(
        _faq_doc(
            {
                "질문": "q",
                "답변": "a",
                "section": "EN",
                "섹션명": "KO",
                "category": "EN_CAT",
                "카테고리": "KO_CAT",
            }
        )
    )
    # 기존 item.get("section", item.get("섹션명"))는 'section'을 우선했다.
    assert chunks[0].metadata["section"] == "EN"
    assert chunks[0].metadata["category"] == "EN_CAT"


def test_missing_section_category_omits_metadata_keys() -> None:
    """섹션/카테고리 컬럼이 없으면 메타데이터에 키를 넣지 않는다(회귀 0)."""
    chunker = SimpleChunker()
    chunks = chunker.chunk(_faq_doc({"질문": "q", "답변": "a"}))
    assert "section" not in chunks[0].metadata
    assert "category" not in chunks[0].metadata


def test_section_present_with_none_value_still_set() -> None:
    """컬럼이 존재하고 값이 None이면 기존 가드처럼 None을 그대로 설정한다(회귀 0)."""
    chunker = SimpleChunker()
    chunks = chunker.chunk(_faq_doc({"질문": "q", "답변": "a", "section": None}))
    # 기존 `if "section" in item ...` 가드는 값이 None이어도 키를 설정했다.
    assert "section" in chunks[0].metadata
    assert chunks[0].metadata["section"] is None


def test_section_category_full_override_with_qa() -> None:
    """질문/답변/섹션/카테고리를 모두 일본어로 주입하면 전부 인식된다."""
    chunker = SimpleChunker(
        column_aliases={
            "question": ["質問"],
            "answer": ["回答"],
            "section": ["セクション"],
            "category": ["カテゴリ"],
        }
    )
    chunks = chunker.chunk(
        _faq_doc({"質問": "qj", "回答": "aj", "セクション": "案内", "カテゴリ": "決済"})
    )
    assert len(chunks) == 1
    assert chunks[0].metadata["section"] == "案内"
    assert chunks[0].metadata["category"] == "決済"


def test_partial_alias_keeps_default_for_missing_section_key() -> None:
    """category만 주입하면 section은 기본값(section/섹션명)으로 보강된다."""
    chunker = SimpleChunker(column_aliases={"category": ["カテゴリ"]})
    chunks = chunker.chunk(
        _faq_doc({"질문": "q", "답변": "a", "섹션명": "이용안내", "カテゴリ": "決済"})
    )
    assert chunks[0].metadata["section"] == "이용안내"  # 기본 별칭으로 인식
    assert chunks[0].metadata["category"] == "決済"  # 주입 별칭으로 인식


def test_faq_processor_exposes_section_category_in_single_source() -> None:
    """FAQProcessor가 청커와 동일한 단일 소스 별칭에 section/category를 노출한다."""
    processor = FAQProcessor()
    assert processor.column_aliases["section"] == SimpleChunker.DEFAULT_SECTION_KEYS
    assert processor.column_aliases["category"] == SimpleChunker.DEFAULT_CATEGORY_KEYS


def test_faq_processor_section_category_override_flows_to_chunker() -> None:
    """FAQProcessor에 section/category 별칭 주입 시 청킹 메타에 반영된다."""
    processor = FAQProcessor(
        column_aliases={
            "section": ["セクション"],
            "category": ["カテゴリ"],
        }
    )
    chunks = processor.chunker.chunk(
        _faq_doc({"질문": "q", "답변": "a", "セクション": "案内", "カテゴリ": "決済"})
    )
    assert chunks[0].metadata["section"] == "案内"
    assert chunks[0].metadata["category"] == "決済"
