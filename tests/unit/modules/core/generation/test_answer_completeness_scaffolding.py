"""답변 완전성 프롬프트 스캐폴딩 테스트 (GAP #3)

목적:
    검색 컨텍스트에서 URL/이메일/연락처/규격번호/모델번호(정규식)와 인용구,
    문서 메타를 추출해 <source_signals>/<answer_checklist>/<source_metadata>
    블록으로 프롬프트 상단에 재배치, RAG 답변 누락(1개 보고 끝내기)을 방지한다.

범용화:
    정규식 패턴은 도메인 중립(URL/email/contact/spec/model)만 사용한다.
    일본어 シート 마커·mojibake decoded_hint는 차용하지 않는다.

회귀 안전판:
    config opt-in(generation.answer_completeness.enabled, 기본 false).
    비활성 시 기존 프롬프트 구조 그대로(블록 미삽입).
"""

from __future__ import annotations

from typing import Any

import pytest

from app.modules.core.generation.generator import GenerationModule


class _FakePromptManager:
    async def get_prompt_content(self, *args: Any, **kwargs: Any) -> str:
        return "You are a helpful assistant"


def _make_gen(gen_config: dict[str, Any] | None = None) -> GenerationModule:
    gen = GenerationModule.__new__(GenerationModule)
    gen.gen_config = gen_config or {}  # type: ignore[attr-defined]
    gen.prompt_manager = _FakePromptManager()  # type: ignore[attr-defined]
    return gen


class TestContentSignalExtraction:
    """도메인 중립 신호 추출 단위 테스트"""

    def test_extracts_url_email_contact_standard_model(self) -> None:
        """URL/이메일/연락처/규격번호/모델번호를 신호로 추출한다."""
        gen = _make_gen()
        content = (
            "문의: https://example.com/support 이메일 help@example.com\n"
            "TEL: 02-123-4567 규격 ISO 9001 모델 Model AB-1200X"
        )
        signals = gen._format_content_signals(content)
        assert "url:" in signals
        assert "https://example.com/support" in signals
        assert "email:" in signals
        assert "help@example.com" in signals
        assert "contact:" in signals
        assert "standard:" in signals
        assert "ISO 9001" in signals or "ISO9001" in signals.replace(" ", "")
        assert "model_or_code:" in signals

    def test_no_signals_returns_empty(self) -> None:
        """추출할 신호가 없으면 빈 문자열을 반환한다."""
        gen = _make_gen()
        assert gen._format_content_signals("그냥 평범한 본문 텍스트입니다") == ""
        assert gen._format_content_signals("") == ""

    def test_signals_are_deduplicated(self) -> None:
        """동일 신호는 중복 제거된다."""
        gen = _make_gen()
        content = "URL https://a.com 다시 https://a.com"
        signals = gen._format_content_signals(content)
        assert signals.count("https://a.com") == 1


class TestQuotedPhraseExtraction:
    """인용구 추출 단위 테스트"""

    def test_extracts_double_and_single_quotes(self) -> None:
        gen = _make_gen()
        phrases = gen._extract_quoted_phrases('"중요한 항목"과 \'핵심 조건\'을 알려줘')
        assert "중요한 항목" in phrases
        assert "핵심 조건" in phrases

    def test_no_quotes_returns_empty(self) -> None:
        gen = _make_gen()
        assert gen._extract_quoted_phrases("따옴표 없는 질문") == []


class TestSourceMetadataFormatting:
    """source metadata 포맷 단위 테스트"""

    def test_formats_safe_metadata_fields(self) -> None:
        gen = _make_gen()
        metadata = {
            "source_file": "/path/to/규정집.pdf",
            "page_number": 12,
            "document_id": "doc-1",
        }
        lines = gen._format_source_metadata(metadata)
        assert "규정집.pdf" in lines  # basename만
        assert "/path/to/" not in lines  # 전체 경로 노출 금지
        assert "page" in lines
        assert "doc-1" in lines

    def test_empty_metadata_returns_empty(self) -> None:
        gen = _make_gen()
        assert gen._format_source_metadata({}) == ""


class TestBuildPromptScaffolding:
    """_build_prompt 통합 — opt-in 동작 및 회귀 검증"""

    @pytest.mark.asyncio
    async def test_disabled_by_default_no_scaffolding(self) -> None:
        """기본(설정 없음) 시 스캐폴딩 블록을 삽입하지 않는다(회귀 0)."""
        gen = _make_gen({})
        context = "연락처 02-123-4567 자세히는 https://example.com 참고"
        _, user = await gen._build_prompt('"중요 항목" 알려줘', context, {})
        assert "<source_signals>" not in user
        assert "<answer_checklist>" not in user
        assert "<source_metadata>" not in user

    @pytest.mark.asyncio
    async def test_enabled_inserts_source_signals(self) -> None:
        """활성화 시 컨텍스트 신호를 <source_signals> 블록으로 재배치한다."""
        gen = _make_gen({"answer_completeness": {"enabled": True}})
        context = "지원 문의 https://example.com/help 전화 02-123-4567"
        _, user = await gen._build_prompt("문의 방법 알려줘", context, {})
        assert "<source_signals>" in user
        assert "https://example.com/help" in user

    @pytest.mark.asyncio
    async def test_enabled_inserts_answer_checklist_for_quoted_query(self) -> None:
        """활성화 + 인용구 질문이면 <answer_checklist> 블록을 삽입한다."""
        gen = _make_gen({"answer_completeness": {"enabled": True}})
        context = (
            "제품 사양: 모델 Model AB-1200X 가격 50000원 출시 2024년 1월\n"
            "문의 https://example.com/spec"
        )
        _, user = await gen._build_prompt('"Model AB-1200X" 사양 알려줘', context, {})
        assert "<answer_checklist>" in user

    @pytest.mark.asyncio
    async def test_enabled_no_signals_no_block(self) -> None:
        """활성화돼도 추출할 신호가 없으면 빈 블록을 만들지 않는다."""
        gen = _make_gen({"answer_completeness": {"enabled": True}})
        _, user = await gen._build_prompt("평범한 질문", "평범한 본문입니다", {})
        assert "<source_signals>" not in user

    @pytest.mark.asyncio
    async def test_enabled_preserves_language_profile(self) -> None:
        """스캐폴딩 활성화는 다국어 프로파일(#2)과 충돌 없이 공존한다."""
        gen = _make_gen({"answer_completeness": {"enabled": True}})
        context = "support https://example.com/help"
        system, user = await gen._build_prompt(
            "how to contact", context, {"response_language": "en"}
        )
        assert "Important Rules" in system
        assert "<source_signals>" in user
        # 영어 source_signals 안내가 포함되어야 한다.
        assert "must not be dropped" in user or "include the relevant" in user.lower()


class TestSignalPatternExternalization:
    """source_signals 라벨 패턴(연락처/규격/모델) 외부화 회귀/오버라이드 (#4).

    언어/규격 의존 라벨을 generation.answer_completeness.signal_patterns로 외부화한다.
    (a) 미설정 시 코드 기본(ko 최소셋 라벨 + 국제규격 ISO/IEC)으로 동작 (회귀 0)
    (b) config 오버라이드 시 외국어 라벨/자국 규격기관으로 교체 (데드 키 아님, 대체 의미)

    JP 잔재 청소: 기본 규격셋에서 JIS(일본공업규격)를 제거했다. 자국 규격기관은
    signal_patterns.standard_orgs로 코드 포크 없이 추가/교체한다.
    """

    def test_default_keeps_korean_labels_and_iso(self) -> None:
        """(a) 미설정 시 한국어 라벨·국제규격(ISO)이 기존대로 매칭됨 (회귀 0)"""
        gen = _make_gen()
        content = "전화: 02-123-4567 규격 ISO 9001 모델: GP-1200X"
        signals = gen._format_content_signals(content)
        assert "contact:" in signals  # 한국어 '전화' 라벨 매칭
        assert "standard:" in signals  # 국제규격(ISO) 매칭 유지
        assert "model_or_code:" in signals  # 한국어 '모델' 라벨 매칭

    def test_jis_removed_from_default_standard_orgs(self) -> None:
        """JP 잔재 제거: JIS는 더 이상 기본 규격셋에 없어 단독으로는 매칭되지 않는다."""
        gen = _make_gen()
        # 다른 신호(연락처/모델/URL 등)가 전혀 없는 JIS 단독 본문은 빈 신호여야 한다.
        signals = gen._format_content_signals("규격 JIS B 7512 입니다")
        assert "standard:" not in signals

    def test_jis_can_be_re_added_via_config(self) -> None:
        """JIS가 필요한 운영자는 standard_orgs config로 다시 추가할 수 있다(범용화)."""
        gen = _make_gen(
            {
                "answer_completeness": {
                    "signal_patterns": {"standard_orgs": ["ISO", "JIS"]}
                }
            }
        )
        signals = gen._format_content_signals("규격 JIS B 7512 입니다")
        assert "standard:" in signals  # config로 추가하면 다시 매칭

    def test_override_swaps_labels(self) -> None:
        """(b) config 오버라이드 시 외국어 라벨/자국 규격기관으로 교체 (대체 의미)"""
        gen = _make_gen(
            {
                "answer_completeness": {
                    "signal_patterns": {
                        "contact_labels": ["Tél"],
                        "standard_orgs": ["KS"],
                        "model_labels": ["Réf"],
                    }
                }
            }
        )
        # 프랑스어 라벨/KS 규격이 매칭됨
        fr_signals = gen._format_content_signals(
            "Tél: 01-23-45-67 KS A 0001 Réf: ABC-123"
        )
        assert "contact:" in fr_signals
        assert "standard:" in fr_signals
        assert "model_or_code:" in fr_signals
        # 오버라이드는 '대체'이므로 한국어 라벨은 더 이상 매칭되지 않는다(병합 아님)
        ko_signals = gen._format_content_signals("전화: 02-1 모델: AB-12")
        assert "contact:" not in ko_signals
        assert "model_or_code:" not in ko_signals
