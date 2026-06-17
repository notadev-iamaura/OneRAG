"""데모 컨텍스트 라벨 config(환경변수) 외부화 테스트

demo_pipeline.py의 _build_context가 LLM 프롬프트({context})에 주입하는
한국어 컨텍스트 라벨이 환경 변수로 외부화됐는지 검증한다.

대상 환경 변수:
- DEMO_CONTEXT_DOC_LABEL: 문서 라벨 템플릿 ({index} 자리표시자)
- DEMO_UNKNOWN_SOURCE: 출처 미상 시 표기할 기본 출처명
- DEMO_NO_DOCS_MESSAGE: 검색 결과 없음 메시지

핵심 요구사항:
1. (회귀 0) 환경 변수 미설정 시 기존 한국어 출력과 byte 동치.
2. (오버라이드) 환경 변수 주입 후 모듈 재로딩 시 라벨이 반영된다.
"""

from __future__ import annotations

import importlib
from typing import Any
from unittest.mock import MagicMock

import app.api.demo.demo_pipeline as demo_pipeline
from app.api.demo.demo_pipeline import (
    DEFAULT_CONTEXT_DOC_LABEL,
    DEFAULT_NO_DOCS_MESSAGE,
    DEFAULT_UNKNOWN_SOURCE,
    _resolve_prompt,
)


def _make_pipeline(module: Any = demo_pipeline) -> Any:
    """라벨 로직만 검증하므로 모든 의존성을 Mock으로 채운 파이프라인 생성."""
    return module.DemoPipeline(
        session_manager=MagicMock(),
        embedder=MagicMock(),
        chroma_client=MagicMock(),
        llm_client=MagicMock(),
    )


# =============================================================================
# (a) 미설정 시 한국어 기본값 — 회귀 0
# =============================================================================


def test_resolver_returns_korean_defaults_when_env_unset(monkeypatch) -> None:
    """환경 변수 미설정 시 _resolve_prompt가 한국어 기본값을 반환(회귀 0)."""
    monkeypatch.delenv("DEMO_CONTEXT_DOC_LABEL", raising=False)
    monkeypatch.delenv("DEMO_UNKNOWN_SOURCE", raising=False)
    monkeypatch.delenv("DEMO_NO_DOCS_MESSAGE", raising=False)

    assert _resolve_prompt("DEMO_CONTEXT_DOC_LABEL", DEFAULT_CONTEXT_DOC_LABEL) == (
        "[문서 {index}]"
    )
    assert _resolve_prompt("DEMO_UNKNOWN_SOURCE", DEFAULT_UNKNOWN_SOURCE) == (
        "알 수 없는 출처"
    )
    assert _resolve_prompt("DEMO_NO_DOCS_MESSAGE", DEFAULT_NO_DOCS_MESSAGE) == (
        "관련 문서를 찾을 수 없습니다."
    )


def test_build_context_byte_identical_to_legacy_when_env_unset() -> None:
    """env 미설정 상태에서 _build_context 출력이 기존 하드코딩 포맷과 byte 동치."""
    pipeline = _make_pipeline()
    sources = [
        {"source": "doc_a.pdf", "content": "첫 번째 내용"},
        {"source": "doc_b.txt", "content": "두 번째 내용"},
    ]
    expected = (
        "[문서 1] (doc_a.pdf)\n첫 번째 내용"
        "\n\n---\n\n"
        "[문서 2] (doc_b.txt)\n두 번째 내용"
    )
    assert pipeline._build_context(sources) == expected


def test_build_context_no_docs_message_default() -> None:
    """검색 결과가 없으면 한국어 기본 '없음' 메시지를 반환(회귀 0)."""
    pipeline = _make_pipeline()
    assert pipeline._build_context([]) == "관련 문서를 찾을 수 없습니다."


def test_build_context_missing_source_uses_unknown_default() -> None:
    """source 키가 없으면 기본 '알 수 없는 출처'를 사용(기존 .get 기본값 의미 보존)."""
    pipeline = _make_pipeline()
    # source 키가 아예 없는 경우 — 기존 dict.get(key, default) 의미와 동일해야 함
    result = pipeline._build_context([{"content": "내용만 있음"}])
    assert result == "[문서 1] (알 수 없는 출처)\n내용만 있음"


# =============================================================================
# (b) env 주입 시 오버라이드
# =============================================================================


def test_env_override_reflected_after_reload(monkeypatch) -> None:
    """환경 변수 주입 후 모듈 재로딩 시 라벨/출처/없음 메시지가 영어로 전환."""
    monkeypatch.setenv("DEMO_CONTEXT_DOC_LABEL", "[Doc {index}]")
    monkeypatch.setenv("DEMO_UNKNOWN_SOURCE", "unknown source")
    monkeypatch.setenv("DEMO_NO_DOCS_MESSAGE", "No relevant documents found.")
    reloaded = importlib.reload(demo_pipeline)
    try:
        assert reloaded.CONTEXT_DOC_LABEL == "[Doc {index}]"
        assert reloaded.UNKNOWN_SOURCE == "unknown source"
        assert reloaded.NO_DOCS_MESSAGE == "No relevant documents found."

        pipeline = _make_pipeline(reloaded)
        # 없음 메시지 오버라이드
        assert pipeline._build_context([]) == "No relevant documents found."
        # 라벨 + 출처 미상 오버라이드
        result = pipeline._build_context([{"content": "body"}])
        assert result == "[Doc 1] (unknown source)\nbody"
    finally:
        # 다른 테스트에 영향 없도록 원복
        importlib.reload(demo_pipeline)


def test_blank_env_falls_back_to_korean_default(monkeypatch) -> None:
    """공백 환경 변수는 기본값으로 폴백(회귀 0)."""
    monkeypatch.setenv("DEMO_CONTEXT_DOC_LABEL", "   ")
    monkeypatch.setenv("DEMO_NO_DOCS_MESSAGE", "")
    reloaded = importlib.reload(demo_pipeline)
    try:
        assert reloaded.CONTEXT_DOC_LABEL == "[문서 {index}]"
        assert reloaded.NO_DOCS_MESSAGE == "관련 문서를 찾을 수 없습니다."
    finally:
        importlib.reload(demo_pipeline)
