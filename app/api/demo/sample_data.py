"""
샘플 데이터 로더

easy_start/sample_data/ 디렉토리의 다국어 FAQ 데이터를 로드합니다.
데모 서비스 시작 시 샘플 세션을 사전 생성하는 데 사용됩니다.

언어는 파일명 컨벤션 `sample_data_{lang}.json`에서 **동적으로 발견**됩니다.
운영자가 새 언어 샘플 파일(예: sample_data_fr.json)만 디렉토리에 추가하면
코드 수정 없이 해당 언어 데모가 지원됩니다(범용화 — 언어 하드코딩 제거).
"""

import json
from pathlib import Path
from typing import Any

from app.lib.logger import get_logger

logger = get_logger(__name__)

# 프로젝트 루트 기준 샘플 데이터 경로
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
SAMPLE_DATA_DIR = PROJECT_ROOT / "easy_start" / "sample_data"

# 파일명 컨벤션: sample_data_{lang}.json — 언어 코드는 파일명에서 파생한다.
# 특정 언어 목록을 코드에 하드코딩하지 않으므로(ja/zh 등 포함) 임의 언어를
# 파일 추가만으로 지원할 수 있다.
SAMPLE_FILE_PREFIX = "sample_data_"
SAMPLE_FILE_SUFFIX = ".json"

DEFAULT_LANGUAGE = "ko"


def _language_file(language: str) -> Path:
    """언어 코드 → 샘플 파일 경로 (컨벤션 기반)"""
    return SAMPLE_DATA_DIR / f"{SAMPLE_FILE_PREFIX}{language}{SAMPLE_FILE_SUFFIX}"


def load_sample_documents(language: str = DEFAULT_LANGUAGE) -> list[dict[str, Any]]:
    """
    샘플 FAQ 문서를 로드합니다.

    Args:
        language: 언어 코드 (파일명 컨벤션 sample_data_{lang}.json에서 발견되는 값)

    Returns:
        문서 리스트 [{"id": str, "title": str, "content": str, "metadata": dict}]
    """
    file_path = _language_file(language)
    if not file_path.exists():
        # 요청 언어 파일이 없으면 기본 언어로 폴백한다.
        fallback = _language_file(DEFAULT_LANGUAGE)
        if file_path != fallback and fallback.exists():
            logger.warning(
                f"지원하지 않는 언어: {language}, 기본 언어({DEFAULT_LANGUAGE})로 폴백"
            )
            file_path = fallback
        else:
            logger.warning(f"샘플 데이터 파일이 없습니다: {file_path}")
            return []

    with open(file_path, encoding="utf-8") as f:
        data = json.load(f)

    documents = data.get("documents", [])
    logger.info(f"샘플 데이터 로드 완료: {language} ({len(documents)}개 문서)")
    return documents


def get_available_languages() -> list[str]:
    """사용 가능한 샘플 데이터 언어 목록 반환 (파일명에서 동적 발견)"""
    if not SAMPLE_DATA_DIR.exists():
        return []
    languages = []
    for path in sorted(SAMPLE_DATA_DIR.glob(f"{SAMPLE_FILE_PREFIX}*{SAMPLE_FILE_SUFFIX}")):
        # 파일명에서 접두/접미를 떼어 언어 코드를 파생한다.
        lang = path.name[len(SAMPLE_FILE_PREFIX) : -len(SAMPLE_FILE_SUFFIX)]
        if lang:
            languages.append(lang)
    return languages
