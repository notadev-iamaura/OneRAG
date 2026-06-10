"""
설정 필수 섹션 로드 검증 테스트 (Phase 0.1)

목적:
    base.yaml의 imports 누락으로 privacy/bm25/grok 등 핵심 설정 섹션이
    config에서 통째로 빠지는 "조용한 고장"을 회귀 방지로 차단한다.

배경:
    di_container가 config.privacy.*, config.bm25.* 를 참조하는데 해당 yaml이
    imports에 없으면 dependency-injector가 None을 주입해 PII 마스킹이 꺼지고
    BM25 전처리가 무력화된다. 이 테스트는 mock 없이 실제 load_config()를
    실행해 필수 섹션의 존재를 단언한다.
"""

from __future__ import annotations

import pytest

from app.lib.config_loader import load_config

# di_container가 런타임에 참조하는 핵심 설정 섹션 목록
# 이 중 하나라도 빠지면 의존성이 None으로 주입되어 기능이 조용히 무력화된다.
REQUIRED_TOP_LEVEL_SECTIONS = [
    "privacy",  # PII 마스킹 (di_container.privacy_masker)
    "bm25",  # BM25 전처리 (synonym/stopword/user_dictionary)
    "grok",  # Grok 관리형 RAG (grok_answer_provider)
]


@pytest.fixture(scope="module")
def loaded_config() -> dict:
    """실제 설정 파일을 로드한다 (검증은 끄고 원시 dict 확인)."""
    return load_config(validate=False)


@pytest.mark.parametrize("section", REQUIRED_TOP_LEVEL_SECTIONS)
def test_required_section_present(loaded_config: dict, section: str) -> None:
    """필수 최상위 섹션이 로드된 설정에 존재해야 한다."""
    assert section in loaded_config, (
        f"설정 섹션 '{section}'이(가) 로드되지 않았습니다. "
        f"app/config/base.yaml의 imports에 features/{section}.yaml이 "
        f"포함됐는지 확인하십시오."
    )


def test_privacy_masking_keys_present(loaded_config: dict) -> None:
    """privacy.masking 하위 키가 None이 아닌 실제 값으로 로드돼야 한다."""
    privacy = loaded_config.get("privacy")
    assert privacy is not None, "privacy 섹션 누락"
    masking = privacy.get("masking")
    assert masking is not None, "privacy.masking 누락"
    # di_container가 주입하는 키들이 실제 bool 값이어야 한다 (None이면 마스킹 무력화)
    assert isinstance(masking.get("phone"), bool)
    assert isinstance(masking.get("name"), bool)


def test_bm25_toggle_keys_present(loaded_config: dict) -> None:
    """bm25 하위 enabled 키들이 실제 값으로 로드돼야 한다."""
    bm25 = loaded_config.get("bm25")
    assert bm25 is not None, "bm25 섹션 누락"
    assert isinstance(bm25.get("synonym", {}).get("enabled"), bool)
    assert isinstance(bm25.get("stopword", {}).get("enabled"), bool)


def test_grok_env_placeholder_resolved(loaded_config: dict) -> None:
    """grok.api_key의 ${XAI_API_KEY:} 플레이스홀더가 리터럴로 남지 않아야 한다."""
    grok = loaded_config.get("grok")
    assert grok is not None, "grok 섹션 누락"
    api_key = grok.get("api_key", "")
    # 환경변수 미설정 시 빈 문자열이어야 하며, 치환 실패 리터럴이 남으면 안 됨
    assert "${" not in str(api_key), (
        f"환경변수 치환 실패: api_key에 리터럴 '{api_key}'가 남았습니다. "
        f"config_loader가 ${{VAR:}} 구문을 처리하는지 확인하십시오."
    )
