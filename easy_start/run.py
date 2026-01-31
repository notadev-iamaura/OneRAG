#!/usr/bin/env python3
"""
Docker-Free 로컬 퀵스타트 원클릭 실행

1단계: 의존성 확인
2단계: 데이터 로드 (미적재 시)
3단계: CLI 챗봇 실행

사용법:
    uv run python easy_start/run.py
"""

import importlib.util
import subprocess
import sys
from pathlib import Path

# 프로젝트 루트
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

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
    print("=" * 50)
    print("🚀 OneRAG Docker-Free 로컬 퀵스타트")
    print("=" * 50)
    print()

    # Step 1: 의존성 확인
    print("[1/3] 의존성 확인 중...")
    ok, missing = check_dependencies()
    if not ok:
        print(f"❌ 필수 패키지 미설치: {', '.join(missing)}")
        print("   설치: uv sync")
        sys.exit(1)
    print("  ✅ 필수 의존성 확인 완료")

    optional_missing = check_optional_dependencies()
    if optional_missing:
        print(f"  ⚠️  BM25 의존성 미설치: {', '.join(optional_missing)}")
        print("     하이브리드 검색을 위해 설치 권장: uv sync --extra bm25")
        print("     (Dense 검색만으로도 동작합니다)")
    else:
        print("  ✅ BM25 하이브리드 검색 활성화")
    print()

    # Step 2: .env 파일 확인
    if not check_env_file():
        print("[2/3] .env 파일 생성 중...")
        local_env = project_root / "easy_start" / ".env.local"
        if local_env.exists():
            import shutil
            shutil.copy(str(local_env), ENV_FILE_PATH)
            print("  ✅ .env 파일 복사 완료")
            print("  ⚠️  .env 파일을 열어 API 키를 하나 설정하세요!")
            print("     Option 1: GOOGLE_API_KEY - https://aistudio.google.com/apikey (무료)")
            print("     Option 2: OPENROUTER_API_KEY - https://openrouter.ai/keys")
            print()
        else:
            print("  ❌ easy_start/.env.local 파일을 찾을 수 없습니다")
            sys.exit(1)
    else:
        print("[2/3] .env 파일 확인 완료")
        print()

    # Step 3: 데이터 로드 (미적재 시)
    if not check_data_loaded():
        print("[3/3] 샘플 데이터 로드 중...")
        print()
        load_script = project_root / "easy_start" / "load_data.py"
        result = subprocess.run(
            [sys.executable, str(load_script)],
            cwd=str(project_root),
        )
        if result.returncode != 0:
            print("❌ 데이터 로드 실패")
            sys.exit(1)
        print()
    else:
        print("[3/3] 데이터 이미 적재됨 (건너뜀)")
        print()

    # Step 4: CLI 챗봇 실행
    print("=" * 50)
    print("💬 CLI 챗봇을 시작합니다...")
    print("=" * 50)
    print()
    chat_script = project_root / "easy_start" / "chat.py"
    result = subprocess.run([sys.executable, str(chat_script)], cwd=str(project_root))
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
