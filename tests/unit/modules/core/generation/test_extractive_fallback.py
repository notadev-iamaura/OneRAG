"""빈 생성응답 시 extractive fallback 단위 테스트 (GAP D).

LLM이 빈 답변을 반환했을 때 무응답 대신 상위 3개 문서 발췌(각 ~700자)로 최소
답변을 합성한다. 에러 숨김 금지 + graceful degradation 원칙에 부합한다.
JapanRAG의 RESPONSE_LANGUAGE_PROFILES(전체 i18n)는 차용하지 않고 영어 기본 문자열만.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from app.modules.core.generation.generator import GenerationModule


def _module() -> GenerationModule:
    return GenerationModule(config={}, prompt_manager=MagicMock())


class _Doc:
    """page_content + metadata를 가진 문서 스텁(langchain Document 유사)."""

    def __init__(self, content: str, source_file: str | None = None) -> None:
        self.page_content = content
        self.metadata: dict[str, Any] = {}
        if source_file is not None:
            self.metadata["source_file"] = source_file


def test_extracts_top_three_documents() -> None:
    mod = _module()
    docs = [
        _Doc("첫 번째 근거 내용", source_file="a.pdf"),
        _Doc("두 번째 근거 내용", source_file="b.pdf"),
        _Doc("세 번째 근거 내용", source_file="c.pdf"),
        _Doc("네 번째는 포함되면 안 됨", source_file="d.pdf"),
    ]
    answer = mod._build_extractive_answer_from_documents(docs)
    assert "첫 번째 근거 내용" in answer
    assert "두 번째 근거 내용" in answer
    assert "세 번째 근거 내용" in answer
    # 상위 3개만 사용한다
    assert "네 번째는 포함되면 안 됨" not in answer


def test_truncates_long_content() -> None:
    mod = _module()
    long_content = "가" * 2000
    docs = [_Doc(long_content, source_file="big.pdf")]
    answer = mod._build_extractive_answer_from_documents(docs)
    # 각 발췌는 약 700자로 잘린다(전체 2000자가 그대로 들어가지 않음)
    assert long_content not in answer
    assert "가" * 700 in answer


def test_includes_source_label() -> None:
    mod = _module()
    docs = [_Doc("근거 내용", source_file="/path/to/report.pdf")]
    answer = mod._build_extractive_answer_from_documents(docs)
    # 파일명(basename)이 라벨로 포함된다
    assert "report.pdf" in answer


def test_no_usable_content_returns_message() -> None:
    mod = _module()
    docs = [_Doc(""), _Doc("   ")]
    answer = mod._build_extractive_answer_from_documents(docs)
    # 본문이 없으면 비어있지 않은 안내 메시지를 반환한다(무응답 금지)
    assert answer.strip()


def test_empty_documents_returns_message() -> None:
    mod = _module()
    answer = mod._build_extractive_answer_from_documents([])
    assert answer.strip()


def test_dict_document_supported() -> None:
    mod = _module()
    docs = [{"content": "dict 근거 내용", "metadata": {"source_file": "x.pdf"}}]
    answer = mod._build_extractive_answer_from_documents(docs)
    assert "dict 근거 내용" in answer
    assert "x.pdf" in answer
