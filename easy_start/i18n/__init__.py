"""
다국어 번역 시스템 (easy_start 전용)

YAML 기반 경량 i18n 모듈입니다. easy_start/ 모듈의 모든 UI 텍스트를 다국어로 제공합니다.

지원 언어: ko (한국어, 기본), en (영어), ja (일본어), zh (중국어)

언어 감지 우선순위:
    1. EASY_START_LANG 환경변수 (명시적 설정)
    2. LANG 환경변수의 언어 부분 (시스템 기본)
    3. 기본값 "ko"

사용법:
    from easy_start.i18n import t, get_lang

    # 기본 번역
    print(t("run.title"))  # "OneRAG Docker-Free 로컬 퀵스타트"

    # 변수 치환
    print(t("load.docs_loaded", count=25))  # "25개 문서 로드"

    # 현재 언어 확인
    print(get_lang())  # "ko"
"""

import os
from pathlib import Path
from typing import Any

import yaml


class Translator:
    """
    YAML 기반 다국어 번역 싱글톤 클래스

    dot-notation 키로 중첩 YAML 값에 접근하고, format 치환을 지원합니다.
    """

    _instance: "Translator | None" = None
    _lang: str = "ko"
    _translations: dict[str, Any] = {}

    def __init__(self, lang: str | None = None) -> None:
        """
        번역기 초기화

        Args:
            lang: 사용할 언어 코드 (None이면 자동 감지)
        """
        self._lang = lang or self._detect_lang()
        self._translations = self._load_translations()

    @classmethod
    def get_instance(cls, lang: str | None = None) -> "Translator":
        """
        싱글톤 인스턴스 반환

        Args:
            lang: 언어 코드 (None이면 기존 인스턴스 반환, 지정 시 재생성)

        Returns:
            Translator 인스턴스
        """
        if cls._instance is None or (lang and lang != cls._instance._lang):
            cls._instance = cls(lang)
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """싱글톤 인스턴스 초기화 (테스트용)"""
        cls._instance = None

    @staticmethod
    def _detect_lang() -> str:
        """
        환경변수에서 언어 코드 감지

        우선순위: EASY_START_LANG > LANG의 언어 부분 > 기본값 "ko"

        Returns:
            2자리 언어 코드 (ko, en, ja, zh)
        """
        # 1. 명시적 설정
        easy_lang = os.environ.get("EASY_START_LANG", "").strip()
        if easy_lang:
            return easy_lang[:2].lower()

        # 2. 시스템 LANG (예: "en_US.UTF-8" → "en")
        sys_lang = os.environ.get("LANG", "").strip()
        if sys_lang:
            lang_part = sys_lang.split("_")[0].split(".")[0].lower()
            if lang_part and len(lang_part) >= 2:
                return lang_part[:2]

        # 3. 기본값
        return "ko"

    def _load_translations(self) -> dict[str, Any]:
        """
        언어별 YAML 번역 파일 로드

        해당 언어 파일이 없으면 ko.yaml로 폴백합니다.

        Returns:
            번역 딕셔너리
        """
        i18n_dir = Path(__file__).parent
        yaml_path = i18n_dir / f"{self._lang}.yaml"

        # 언어 파일이 없으면 한국어 폴백
        if not yaml_path.exists():
            yaml_path = i18n_dir / "ko.yaml"
            if not yaml_path.exists():
                return {}

        with open(yaml_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)

        return data if isinstance(data, dict) else {}

    def translate(self, key: str, **kwargs: Any) -> str:
        """
        dot-notation 키로 번역 문자열 반환

        Args:
            key: 번역 키 (예: "chat.header.title")
            **kwargs: format 치환 변수

        Returns:
            번역된 문자열. 키가 없으면 키 자체를 반환합니다.
        """
        parts = key.split(".")
        value: Any = self._translations

        for part in parts:
            if isinstance(value, dict):
                value = value.get(part)
            else:
                return key

        if value is None:
            return key

        result = str(value)
        if kwargs:
            try:
                result = result.format(**kwargs)
            except (KeyError, IndexError):
                pass

        return result

    @property
    def lang(self) -> str:
        """현재 설정된 언어 코드"""
        return self._lang


def t(key: str, **kwargs: Any) -> str:
    """
    번역 편의 함수

    Args:
        key: 번역 키 (예: "chat.header.title")
        **kwargs: format 치환 변수

    Returns:
        번역된 문자열
    """
    return Translator.get_instance().translate(key, **kwargs)


def get_lang() -> str:
    """
    현재 설정된 언어 코드 반환

    Returns:
        2자리 언어 코드 (ko, en, ja, zh)
    """
    return Translator.get_instance().lang


def get_prompt_path(name: str) -> Path:
    """
    언어별 프롬프트 파일 경로 반환

    Args:
        name: 프롬프트 파일 기본 이름 (예: "system_prompt")

    Returns:
        프롬프트 파일 경로 (없으면 한국어 폴백)
    """
    lang = get_lang()
    prompts_dir = Path(__file__).parent.parent / "prompts"
    prompt_path = prompts_dir / f"{name}_{lang}.txt"

    if not prompt_path.exists():
        prompt_path = prompts_dir / f"{name}_ko.txt"

    return prompt_path


def load_prompt(name: str) -> str:
    """
    언어별 프롬프트 파일 내용 로드

    Args:
        name: 프롬프트 파일 기본 이름 (예: "system_prompt")

    Returns:
        프롬프트 텍스트. 파일이 없으면 빈 문자열 반환.
    """
    path = get_prompt_path(name)
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    return ""


def get_sample_data_path() -> Path:
    """
    언어별 샘플 데이터 파일 경로 반환

    Returns:
        샘플 데이터 JSON 파일 경로 (없으면 한국어 폴백)
    """
    lang = get_lang()
    sample_dir = Path(__file__).parent.parent / "sample_data"
    data_path = sample_dir / f"sample_data_{lang}.json"

    if not data_path.exists():
        data_path = sample_dir / "sample_data_ko.json"

    return data_path
