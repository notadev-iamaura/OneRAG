"""
OneRAG Application Package

버전의 단일 진실원은 pyproject.toml 이다. 설치된 패키지 메타데이터에서 읽고,
소스 체크아웃에서 직접 실행할 때(메타데이터 없음)는 pyproject.toml을 파싱한다.
"""

from __future__ import annotations

import tomllib
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _dist_version
from pathlib import Path

_FALLBACK_VERSION = "0.0.0+unknown"


def _read_version() -> str:
    # 소스 체크아웃에서는 pyproject.toml 이 진실원이다(설치 메타데이터는 uv sync 시점에 고정되어
    # 버전만 올리고 재설치하지 않으면 /health 가 옛 값을 보고한다). 배포된 휠처럼 pyproject 가
    # 없을 때만 설치 메타데이터를 쓴다.
    pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
    try:
        with pyproject.open("rb") as handle:
            data = tomllib.load(handle)
        return str(data["project"]["version"])
    except (OSError, KeyError, ValueError, tomllib.TOMLDecodeError):
        pass
    try:
        return _dist_version("onerag")
    except PackageNotFoundError:
        return _FALLBACK_VERSION


__version__ = _read_version()
__description__ = "모듈형 오픈소스 RAG 시스템 / Modular open-source RAG system"
