"""문서 로더 본문 라벨 (config 외부화)

CSV/XLSX/PPTX 로더가 인덱싱 본문(page_content)에 prepend하는 구조 라벨
(컬럼/시트/슬라이드/노트)을 config(uploads.yaml의 uploads.loaders.labels)에서
로드한다. 미설정 시 한국어 기본값으로 폴백한다(회귀 0).

이 라벨들은 검색/리트리벌 대상 텍스트에 그대로 들어가므로, 비한국어 배포에서는
자국어/영어로 오버라이드하거나 빈 문자열로 둘 수 있어 한국어 라벨이 인덱싱
콘텐츠에 혼입되는 문제를 코드 수정 없이 해소한다.
"""

from __future__ import annotations

from .....lib.logger import get_logger

logger = get_logger(__name__)

# 한국어 기본 라벨 (회귀 0 안전판). 키는 로더가 참조하는 라벨 식별자.
DEFAULT_LOADER_LABELS: dict[str, str] = {
    "column": "컬럼",
    "sheet": "시트",
    "slide": "슬라이드",
    "notes": "노트",
}


def get_loader_labels() -> dict[str, str]:
    """uploads.loaders.labels에서 로더 본문 라벨을 로드한다.

    미설정/로드 실패 시 한국어 기본값으로 폴백한다(회귀 0). config의 라벨 중
    문자열인 항목만 반영하고, 알 수 없는 키는 무시한다.
    """
    labels = dict(DEFAULT_LOADER_LABELS)
    try:
        # 지연 임포트: 모듈 임포트 시 config 로딩 부작용을 피한다.
        from .....lib.config_loader import load_config

        config = load_config()
    except Exception as e:  # 설정 로드 실패는 치명적이지 않다 — 기본 라벨 사용
        logger.warning(f"로더 라벨 config 로드 실패(기본값 사용): {e}")
        return labels

    raw = config.get("uploads", {}).get("loaders", {}).get("labels", None)
    if isinstance(raw, dict):
        for key in labels:
            value = raw.get(key)
            if isinstance(value, str):
                labels[key] = value
    return labels
