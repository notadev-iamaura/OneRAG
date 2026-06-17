"""
PrivacyMasker config 배선(데드 키 아님) 테스트

privacy.yaml의 patterns / name_char_class / filename_mask_label 가
di_container를 통해 PrivacyMasker에 실제로 전달되는지 검증한다.
"""

from __future__ import annotations

from app.core.di_container import AppContainer
from app.lib.config_loader import load_config


def _build_masker():
    container = AppContainer()
    container.config.from_dict(load_config())
    return container.privacy_masker()


def test_privacy_patterns_wired_from_yaml() -> None:
    """privacy.yaml patterns가 마스커 정규식으로 전달됨(데드 키 아님)"""
    masker = _build_masker()
    # 기본 한국 패턴이 적용되어 SSN 마스킹이 동작해야 한다
    assert masker.mask_text("990101-1234567") == "990101-*******"


def test_name_suffixes_masking_works_in_di_path() -> None:
    """DI 경로(name_suffixes 주입)에서 이름 마스킹이 실제 동작(버그 회귀 차단)"""
    masker = _build_masker()
    # 과거 f-string 버그로 DI 경로에서 이름 마스킹이 무력화됐었다.
    assert masker.mask_text("홍길동 고객님") == "홍** 고객님"


def test_filename_label_wired_from_yaml() -> None:
    """privacy.yaml filename_mask_label이 파일명 라벨로 전달됨(데드 키 아님)"""
    masker = _build_masker()
    assert masker.mask_filename("홍길동 고객님.txt") == "고객_고객님.txt"
