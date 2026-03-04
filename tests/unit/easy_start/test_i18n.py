"""
easy_start i18n 모듈 테스트

Translator 싱글톤, t() 함수, 언어 감지, 프롬프트 로드,
샘플 데이터 경로 등을 검증합니다.
"""

import os
from pathlib import Path
from unittest.mock import patch

import pytest


class TestTranslator:
    """Translator 싱글톤 클래스 테스트"""

    def setup_method(self) -> None:
        """각 테스트 전 싱글톤 초기화"""
        from easy_start.i18n import Translator

        Translator._instance = None

    def test_default_language_is_korean(self) -> None:
        """기본 언어가 한국어(ko)인지 확인"""
        from easy_start.i18n import Translator

        with patch.dict(os.environ, {}, clear=True):
            # EASY_START_LANG, LANG 모두 없으면 기본 ko
            translator = Translator.get_instance("ko")
            assert translator._lang == "ko"

    def test_easy_start_lang_env(self) -> None:
        """EASY_START_LANG 환경변수로 언어 설정"""
        from easy_start.i18n import Translator

        with patch.dict(os.environ, {"EASY_START_LANG": "en"}):
            translator = Translator.get_instance()
            assert translator._lang == "en"

    def test_singleton_pattern(self) -> None:
        """싱글톤 패턴 검증 - 동일 언어 시 같은 인스턴스 반환"""
        from easy_start.i18n import Translator

        t1 = Translator.get_instance("ko")
        t2 = Translator.get_instance("ko")
        assert t1 is t2

    def test_singleton_reset_on_language_change(self) -> None:
        """언어 변경 시 새 인스턴스 생성"""
        from easy_start.i18n import Translator

        t1 = Translator.get_instance("ko")
        t2 = Translator.get_instance("en")
        assert t1 is not t2
        assert t2._lang == "en"

    def test_translate_existing_key(self) -> None:
        """존재하는 키 번역 확인"""
        from easy_start.i18n import Translator

        translator = Translator.get_instance("ko")
        result = translator.translate("run.title")
        # ko.yaml에 정의된 키여야 함
        assert result != "run.title"
        assert len(result) > 0

    def test_translate_missing_key_returns_key(self) -> None:
        """존재하지 않는 키는 키 자체를 반환"""
        from easy_start.i18n import Translator

        translator = Translator.get_instance("ko")
        result = translator.translate("nonexistent.key.path")
        assert result == "nonexistent.key.path"

    def test_translate_with_format_args(self) -> None:
        """포맷 인자 치환 확인"""
        from easy_start.i18n import Translator

        translator = Translator.get_instance("ko")
        # load.docs_loaded 키는 {count}를 포함
        result = translator.translate("load.docs_loaded", count=25)
        assert "25" in result


class TestConvenienceFunctions:
    """t(), get_lang(), load_prompt(), get_sample_data_path() 테스트"""

    def setup_method(self) -> None:
        """각 테스트 전 싱글톤 초기화"""
        from easy_start.i18n import Translator

        Translator._instance = None

    def test_t_function(self) -> None:
        """t() 편의 함수 동작 확인"""
        from easy_start.i18n import t

        with patch.dict(os.environ, {"EASY_START_LANG": "ko"}):
            result = t("run.title")
            assert result != "run.title"

    def test_get_lang(self) -> None:
        """get_lang() 현재 언어 반환"""
        from easy_start.i18n import Translator, get_lang

        Translator.get_instance("en")
        assert get_lang() == "en"

    def test_load_prompt_korean(self) -> None:
        """한국어 시스템 프롬프트 로드"""
        from easy_start.i18n import Translator, load_prompt

        Translator.get_instance("ko")
        prompt = load_prompt("system_prompt")
        assert prompt is not None
        assert len(prompt) > 100

    def test_load_prompt_english(self) -> None:
        """영어 시스템 프롬프트 로드"""
        from easy_start.i18n import Translator, load_prompt

        Translator.get_instance("en")
        prompt = load_prompt("system_prompt")
        assert prompt is not None
        assert "OneRAG" in prompt

    def test_load_prompt_nonexistent(self) -> None:
        """존재하지 않는 프롬프트는 빈 문자열 반환"""
        from easy_start.i18n import Translator, load_prompt

        Translator.get_instance("ko")
        prompt = load_prompt("nonexistent_prompt")
        assert prompt == ""

    def test_get_sample_data_path_korean(self) -> None:
        """한국어 샘플 데이터 경로"""
        from easy_start.i18n import Translator, get_sample_data_path

        Translator.get_instance("ko")
        path = get_sample_data_path()
        assert isinstance(path, Path)
        assert "sample_data_ko.json" in str(path)

    def test_get_sample_data_path_english(self) -> None:
        """영어 샘플 데이터 경로"""
        from easy_start.i18n import Translator, get_sample_data_path

        Translator.get_instance("en")
        path = get_sample_data_path()
        assert "sample_data_en.json" in str(path)


class TestAllLanguageFiles:
    """모든 번역 파일 존재 및 키 일관성 확인"""

    LANGUAGES = ["ko", "en", "ja", "zh"]

    def test_all_yaml_files_exist(self) -> None:
        """4개 언어 YAML 파일 존재 확인"""
        i18n_dir = Path(__file__).parent.parent.parent.parent / "easy_start" / "i18n"
        for lang in self.LANGUAGES:
            yaml_path = i18n_dir / f"{lang}.yaml"
            assert yaml_path.exists(), f"{lang}.yaml 파일이 없습니다"

    def test_all_prompt_files_exist(self) -> None:
        """4개 언어 프롬프트 파일 존재 확인"""
        prompts_dir = Path(__file__).parent.parent.parent.parent / "easy_start" / "prompts"
        for lang in self.LANGUAGES:
            prompt_path = prompts_dir / f"system_prompt_{lang}.txt"
            assert prompt_path.exists(), f"system_prompt_{lang}.txt 파일이 없습니다"

    def test_all_sample_data_files_exist(self) -> None:
        """4개 언어 샘플 데이터 파일 존재 확인"""
        data_dir = Path(__file__).parent.parent.parent.parent / "easy_start" / "sample_data"
        for lang in self.LANGUAGES:
            data_path = data_dir / f"sample_data_{lang}.json"
            assert data_path.exists(), f"sample_data_{lang}.json 파일이 없습니다"

    def test_key_consistency_across_languages(self) -> None:
        """모든 언어 파일의 최상위 키가 일치하는지 확인"""
        import yaml

        i18n_dir = Path(__file__).parent.parent.parent.parent / "easy_start" / "i18n"

        # 기준: 한국어 키
        with open(i18n_dir / "ko.yaml", encoding="utf-8") as f:
            ko_data = yaml.safe_load(f)

        ko_keys = set(ko_data.keys())

        for lang in ["en", "ja", "zh"]:
            with open(i18n_dir / f"{lang}.yaml", encoding="utf-8") as f:
                lang_data = yaml.safe_load(f)

            lang_keys = set(lang_data.keys())
            assert ko_keys == lang_keys, (
                f"{lang}.yaml의 최상위 키가 ko.yaml과 다릅니다: "
                f"누락={ko_keys - lang_keys}, 초과={lang_keys - ko_keys}"
            )
