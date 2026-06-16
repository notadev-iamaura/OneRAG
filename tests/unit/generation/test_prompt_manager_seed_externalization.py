"""PromptManager 시드 프롬프트 외부화 회귀/오버라이드 테스트.

빈 저장소(fresh 배포)에 삽입되는 기본 프롬프트(system/detailed) 본문을 코드 내장
한국어 기본값(DEFAULT_SEED_PROMPTS)에서 생성자 인자(default_prompts)로 오버라이드
가능하게 외부화한 것이 다음을 만족하는지 검증한다:

(a) 미설정 시 코드 내장 한국어 시드 사용 (회귀 0)
(b) 오버라이드 시 코드 변경 없이 시드 본문이 바뀜 (데드 키 아님)
(c) 시드 본문에서 도메인/언어 누출(シート, '한국어로 답변/소통')이 제거됨
"""

from __future__ import annotations

import tempfile
from typing import Any

import pytest

from app.modules.core.generation.prompt_manager import (
    DEFAULT_SEED_PROMPTS,
    PromptManager,
)


@pytest.mark.unit
class TestSeedPromptExternalization:
    """시드 프롬프트 외부화"""

    def test_default_seeds_builtin_korean_prompts(self) -> None:
        """(a) 미설정 시 코드 내장 한국어 시드(system/detailed)가 삽입됨"""
        with tempfile.TemporaryDirectory() as storage:
            pm = PromptManager(storage_path=storage, use_database=False)
            names = {p["name"] for p in pm.prompts.values()}
            assert {"system", "detailed"} <= names

    def test_override_seeds_via_constructor(self) -> None:
        """(b) default_prompts 인자로 시드 본문 교체 (데드 키 아님)"""
        custom: list[dict[str, Any]] = [
            {
                "name": "system",
                "content": "You are a helpful domain assistant.",
                "description": "en system",
                "category": "system",
                "is_active": False,
            },
        ]
        with tempfile.TemporaryDirectory() as storage:
            pm = PromptManager(
                storage_path=storage, use_database=False, default_prompts=custom
            )
            contents = {p["name"]: p["content"] for p in pm.prompts.values()}
            assert contents["system"] == "You are a helpful domain assistant."
            # detailed는 오버라이드 목록에 없으므로 시드되지 않음
            assert "detailed" not in contents

    def test_seed_bodies_have_no_locale_or_domain_leak(self) -> None:
        """(c) 코드 시드 본문에 언어 강제·일본어 가나 누출이 없음"""
        bodies = "\n".join(p["content"] for p in DEFAULT_SEED_PROMPTS)
        # 하드코딩된 언어 강제 지시가 제거되어야 한다(출력 언어는 외부 설정이 제어)
        assert "한국어로 답변" not in bodies
        assert "한국어로 소통" not in bodies
        # 일본어 가나(シート 등) 잔재가 없어야 한다
        assert "シート" not in bodies
        # 범용 플레이스홀더는 보존되어 도메인 주입이 가능해야 한다
        assert "{domain_context}" in bodies
        assert "{domain_examples}" in bodies
