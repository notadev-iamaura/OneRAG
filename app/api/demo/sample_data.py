"""
샘플 데이터 로더

easy_start/sample_data/ 디렉토리의 다국어 FAQ 데이터를 로드합니다.
데모 서비스 시작 시 샘플 세션을 사전 생성하는 데 사용됩니다.

지원 언어: ko (한국어), en (영어), ja (일본어), zh (중국어)
"""

import json
from pathlib import Path
from typing import Any

from app.lib.logger import get_logger

logger = get_logger(__name__)

# 프로젝트 루트 기준 샘플 데이터 경로
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
SAMPLE_DATA_DIR = PROJECT_ROOT / "easy_start" / "sample_data"

# 언어별 파일 매핑
LANGUAGE_FILES: dict[str, str] = {
    "ko": "sample_data_ko.json",
    "en": "sample_data_en.json",
    "ja": "sample_data_ja.json",
    "zh": "sample_data_zh.json",
}

DEFAULT_LANGUAGE = "ko"


def load_sample_documents(language: str = DEFAULT_LANGUAGE) -> list[dict[str, Any]]:
    """
    샘플 FAQ 문서를 로드합니다.

    Args:
        language: 언어 코드 (ko, en, ja, zh)

    Returns:
        문서 리스트 [{"id": str, "title": str, "content": str, "metadata": dict}]
    """
    filename = LANGUAGE_FILES.get(language)
    if filename is None:
        logger.warning(f"지원하지 않는 언어: {language}, 기본 언어(ko)로 폴백")
        filename = LANGUAGE_FILES[DEFAULT_LANGUAGE]

    file_path = SAMPLE_DATA_DIR / filename
    if not file_path.exists():
        logger.warning(f"샘플 데이터 파일이 없습니다: {file_path}")
        return []

    with open(file_path, encoding="utf-8") as f:
        data = json.load(f)

    documents = data.get("documents", [])
    logger.info(f"샘플 데이터 로드 완료: {language} ({len(documents)}개 문서)")
    return documents


def get_available_languages() -> list[str]:
    """사용 가능한 샘플 데이터 언어 목록 반환"""
    available = []
    for lang, filename in LANGUAGE_FILES.items():
        if (SAMPLE_DATA_DIR / filename).exists():
            available.append(lang)
    return available
