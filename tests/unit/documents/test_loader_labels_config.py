"""
문서 로더 본문 라벨 config 외부화 테스트 (8차 범용화)

CSV/XLSX/PPTX 로더가 인덱싱 본문에 prepend하던 한국어 라벨
('컬럼:'/'시트:'/'슬라이드 '/'[노트]')을 uploads.loaders.labels로
외부화한 변경을 검증한다. 미설정 시 한국어 기본값 폴백(회귀 0),
오버라이드 시 비한국어 배포가 검색 텍스트 라벨을 바꿀 수 있다.
"""

import asyncio
from unittest.mock import patch

from app.modules.core.documents.loaders import labels as labels_mod
from app.modules.core.documents.loaders.csv_loader import CSVLoader

_LOAD_CONFIG = "app.lib.config_loader.load_config"


class TestGetLoaderLabels:
    def test_default_labels_are_korean(self):
        """미설정 시 한국어 기본 라벨로 폴백한다 (회귀 0)."""
        with patch(_LOAD_CONFIG, return_value={}):
            got = labels_mod.get_loader_labels()
        assert got == {
            "column": "컬럼",
            "sheet": "시트",
            "slide": "슬라이드",
            "notes": "노트",
        }

    def test_override_from_config(self):
        """config 오버라이드가 반영된다 (비한국어 배포 지원)."""
        cfg = {
            "uploads": {
                "loaders": {
                    "labels": {
                        "column": "Columns",
                        "sheet": "Sheet",
                        "slide": "Slide",
                        "notes": "Notes",
                    }
                }
            }
        }
        with patch(_LOAD_CONFIG, return_value=cfg):
            got = labels_mod.get_loader_labels()
        assert got["column"] == "Columns"
        assert got["slide"] == "Slide"

    def test_partial_override_keeps_defaults(self):
        """일부만 오버라이드하면 나머지는 한국어 기본 유지."""
        cfg = {"uploads": {"loaders": {"labels": {"column": "Cols"}}}}
        with patch(_LOAD_CONFIG, return_value=cfg):
            got = labels_mod.get_loader_labels()
        assert got["column"] == "Cols"
        assert got["sheet"] == "시트"  # 미오버라이드 → 기본

    def test_config_load_failure_falls_back(self):
        with patch(_LOAD_CONFIG, side_effect=RuntimeError("boom")):
            got = labels_mod.get_loader_labels()
        assert got == labels_mod.DEFAULT_LOADER_LABELS


class TestCsvLoaderUsesLabels:
    def _write_csv(self, tmp_path):
        p = tmp_path / "t.csv"
        p.write_text("a,b\n1,2\n", encoding="utf-8")
        return p

    def test_default_korean_label_in_content(self, tmp_path):
        """미설정 시 본문에 한국어 '컬럼:' 라벨 유지 (회귀 0)."""
        csv = self._write_csv(tmp_path)
        with patch(_LOAD_CONFIG, return_value={}):
            docs = asyncio.run(CSVLoader().load(csv))
        assert docs[0].page_content.startswith("컬럼: a, b")

    def test_override_label_in_content(self, tmp_path):
        """오버라이드 시 본문 라벨이 바뀐다 (검색 텍스트 범용화)."""
        csv = self._write_csv(tmp_path)
        cfg = {"uploads": {"loaders": {"labels": {"column": "Columns"}}}}
        with patch(_LOAD_CONFIG, return_value=cfg):
            docs = asyncio.run(CSVLoader().load(csv))
        assert docs[0].page_content.startswith("Columns: a, b")
        assert "컬럼:" not in docs[0].page_content
