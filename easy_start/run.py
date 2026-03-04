#!/usr/bin/env python3
"""
Docker-Free 로컬 퀵스타트 원클릭 실행

1단계: 의존성 확인
2단계: 데이터 로드 (미적재 시)
3단계: CLI 챗봇 실행

다국어 지원: EASY_START_LANG 환경변수로 언어 선택 (ko, en, ja, zh)

사용법:
    uv run python easy_start/run.py
    EASY_START_LANG=en uv run python easy_start/run.py
"""

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

# 프로젝트 루트
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from easy_start.i18n import t  # noqa: E402

# 상수
REQUIRED_PACKAGES = ["chromadb", "sentence_transformers", "rich"]
OPTIONAL_PACKAGES = ["kiwipiepy", "rank_bm25"]
CHROMA_DATA_DIR = str(project_root / "easy_start" / ".chroma_data")
ENV_FILE_PATH = str(project_root / ".env")


def check_dependencies() -> tuple[bool, list[str]]:
    """
    필수 의존성 설치 여부 확인

    Returns:
        (모두 설치됨 여부, 누락된 패키지 리스트)
    """
    missing = []
    for pkg in REQUIRED_PACKAGES:
        if importlib.util.find_spec(pkg) is None:
            missing.append(pkg)

    return len(missing) == 0, missing


def check_optional_dependencies() -> list[str]:
    """
    선택적 의존성 확인 (BM25 하이브리드 검색용)

    Returns:
        누락된 선택적 패키지 리스트
    """
    missing = []
    for pkg in OPTIONAL_PACKAGES:
        if importlib.util.find_spec(pkg) is None:
            missing.append(pkg)
    return missing


def check_env_file(path: str = ENV_FILE_PATH) -> bool:
    """
    .env 파일 존재 여부 확인

    Args:
        path: .env 파일 경로

    Returns:
        파일 존재 여부
    """
    return Path(path).exists()


def check_data_loaded(chroma_dir: str = CHROMA_DATA_DIR) -> bool:
    """
    ChromaDB 데이터 적재 여부 확인

    Args:
        chroma_dir: ChromaDB 데이터 디렉토리 경로

    Returns:
        데이터가 적재되었는지 여부
    """
    chroma_path = Path(chroma_dir)
    if not chroma_path.exists():
        return False
    # ChromaDB는 sqlite3 파일을 생성함
    return any(chroma_path.iterdir())


def main() -> None:
    """메인 실행 함수"""
    # EASY_START_LANG 환경변수 전파 (서브프로세스에서도 사용)
    lang_env = os.environ.get("EASY_START_LANG", "")

    print("=" * 50)
    print(f"🚀 {t('run.title')}")
    print("=" * 50)
    print()

    # Step 1: 의존성 확인
    print(t("run.step1"))
    ok, missing = check_dependencies()
    if not ok:
        print(f"❌ {t('run.missing_packages', packages=', '.join(missing))}")
        print(f"   {t('run.install_hint')}")
        sys.exit(1)
    print(f"  ✅ {t('run.deps_ok')}")

    optional_missing = check_optional_dependencies()
    if optional_missing:
        print(f"  ⚠️  {t('run.bm25_missing', packages=', '.join(optional_missing))}")
        print(f"     {t('run.bm25_install_hint')}")
        print(f"     {t('run.bm25_note')}")
    else:
        print(f"  ✅ {t('run.bm25_active')}")
    print()

    # Step 2: .env 파일 확인
    if not check_env_file():
        print(t("run.step2_create"))
        local_env = project_root / "easy_start" / ".env.local"
        if local_env.exists():
            import shutil
            shutil.copy(str(local_env), ENV_FILE_PATH)
            print(f"  ✅ {t('run.env_copied')}")
            print(f"  ⚠️  {t('run.env_warning')}")
            print(f"     {t('run.env_option1')}")
            print(f"     {t('run.env_option2')}")
            print()
        else:
            print(f"  ❌ {t('run.env_not_found')}")
            sys.exit(1)
    else:
        print(t("run.step2_ok"))
        print()

    # Step 3: 데이터 로드 (미적재 시)
    # 서브프로세스에 언어 설정 전파
    env = os.environ.copy()
    if lang_env:
        env["EASY_START_LANG"] = lang_env

    if not check_data_loaded():
        print(t("run.step3_loading"))
        print()
        load_script = project_root / "easy_start" / "load_data.py"
        result = subprocess.run(
            [sys.executable, str(load_script)],
            cwd=str(project_root),
            env=env,
        )
        if result.returncode != 0:
            print(f"❌ {t('run.load_failed')}")
            sys.exit(1)
        print()
    else:
        print(t("run.step3_skip"))
        print()

    # Step 4: CLI 챗봇 실행
    print("=" * 50)
    print(f"💬 {t('run.starting_chat')}")
    print("=" * 50)
    print()
    chat_script = project_root / "easy_start" / "chat.py"
    result = subprocess.run(
        [sys.executable, str(chat_script)],
        cwd=str(project_root),
        env=env,
    )
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
