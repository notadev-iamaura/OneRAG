"""
Notion bool 속성 렌더링 라벨 외부화 테스트 (11차 범용화)

Notion 체크박스(bool) 속성을 인덱싱 텍스트로 평탄화할 때 "예"/"아니오"로
하드코딩하던 것을 NotionBatchConfig 필드 + env로 외부화한 변경을 검증한다.
이 라벨은 검색 토큰에 들어가므로 비한국어 코퍼스 오염을 막는다(회귀 0).
"""

import importlib

from app.batch import notion_batch
from app.batch.notion_batch import NotionBatchConfig, NotionBatchProcessor


class TestBooleanLabelDefaults:
    def test_default_korean_labels(self):
        cfg = NotionBatchConfig()
        assert cfg.boolean_true_label == "예"
        assert cfg.boolean_false_label == "아니오"

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("NOTION_BOOLEAN_TRUE_LABEL", "Yes")
        monkeypatch.setenv("NOTION_BOOLEAN_FALSE_LABEL", "No")
        importlib.reload(notion_batch)
        try:
            cfg = notion_batch.NotionBatchConfig()
            assert cfg.boolean_true_label == "Yes"
            assert cfg.boolean_false_label == "No"
        finally:
            monkeypatch.delenv("NOTION_BOOLEAN_TRUE_LABEL", raising=False)
            monkeypatch.delenv("NOTION_BOOLEAN_FALSE_LABEL", raising=False)
            importlib.reload(notion_batch)


class TestBooleanRendering:
    def test_renders_with_config_labels(self):
        proc = NotionBatchProcessor(
            NotionBatchConfig(boolean_true_label="Yes", boolean_false_label="No")
        )
        assert proc._property_value_to_text(True) == "Yes"
        assert proc._property_value_to_text(False) == "No"

    def test_default_rendering_korean(self):
        proc = NotionBatchProcessor(NotionBatchConfig())
        assert proc._property_value_to_text(True) == "예"
        assert proc._property_value_to_text(False) == "아니오"
