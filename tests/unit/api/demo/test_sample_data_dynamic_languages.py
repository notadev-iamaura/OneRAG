"""
샘플 데이터 로더 언어 동적 발견 테스트 (7차 범용화)

LANGUAGE_FILES 하드코딩 dict를 파일명 컨벤션(sample_data_{lang}.json)
기반 동적 발견으로 교체한 변경을 검증한다:
- 코드에 언어 목록을 박지 않으므로 새 언어 파일을 추가만 하면 지원된다.
- 기존 ko/en/ja/zh 동작은 회귀 0으로 유지된다.
"""

import json

import pytest

from app.api.demo import sample_data


@pytest.fixture()
def sample_dir(tmp_path, monkeypatch):
    """임시 샘플 데이터 디렉토리로 SAMPLE_DATA_DIR를 교체한다."""
    monkeypatch.setattr(sample_data, "SAMPLE_DATA_DIR", tmp_path)
    return tmp_path


def _write_sample(directory, lang, docs):
    path = directory / f"sample_data_{lang}.json"
    path.write_text(json.dumps({"documents": docs}), encoding="utf-8")
    return path


class TestGetAvailableLanguages:
    def test_discovers_languages_from_filenames(self, sample_dir):
        """파일명에서 언어 코드를 동적 파생한다 (하드코딩 dict 없음)."""
        _write_sample(sample_dir, "ko", [{"id": "1"}])
        _write_sample(sample_dir, "en", [{"id": "2"}])
        _write_sample(sample_dir, "ja", [{"id": "3"}])
        _write_sample(sample_dir, "zh", [{"id": "4"}])

        assert sample_data.get_available_languages() == ["en", "ja", "ko", "zh"]

    def test_new_language_supported_without_code_change(self, sample_dir):
        """코드 수정 없이 새 언어 파일 추가만으로 지원된다 (범용화 핵심)."""
        _write_sample(sample_dir, "ko", [{"id": "1"}])
        _write_sample(sample_dir, "fr", [{"id": "2"}])  # 코드 어디에도 'fr' 리터럴 없음

        assert "fr" in sample_data.get_available_languages()

    def test_empty_when_dir_missing(self, tmp_path, monkeypatch):
        missing = tmp_path / "nope"
        monkeypatch.setattr(sample_data, "SAMPLE_DATA_DIR", missing)
        assert sample_data.get_available_languages() == []


class TestLoadSampleDocuments:
    def test_loads_requested_language(self, sample_dir):
        _write_sample(sample_dir, "en", [{"id": "e1"}, {"id": "e2"}])
        docs = sample_data.load_sample_documents("en")
        assert len(docs) == 2

    def test_unknown_language_falls_back_to_default(self, sample_dir):
        """요청 언어 파일이 없으면 기본 언어(ko)로 폴백한다 (회귀 0)."""
        _write_sample(sample_dir, "ko", [{"id": "k1"}])
        docs = sample_data.load_sample_documents("de")  # de 파일 없음
        assert len(docs) == 1
        assert docs[0]["id"] == "k1"

    def test_returns_empty_when_no_file_and_no_default(self, sample_dir):
        docs = sample_data.load_sample_documents("ja")  # 아무 파일도 없음
        assert docs == []

    def test_no_hardcoded_language_dict(self):
        """언어 목록을 코드 상수로 박지 않았음을 보장한다 (하드코딩 회귀 방지)."""
        assert not hasattr(sample_data, "LANGUAGE_FILES")
