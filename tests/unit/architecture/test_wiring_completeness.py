"""
DI wiring 완전성 가드 테스트 (P2 구조 개선)

목적:
    main.py 의 container.wire() 가 수동 모듈 열거 방식일 때, 신규 라우터가
    Provide[]/@inject 를 사용해도 wire 대상에서 조용히 누락되어 엔드포인트가
    raw Provide 마커를 주입받아 프로덕션 500 을 내는 결함이 있었다
    (과거 app.api.ingest 누락 사례). 이를 구조적으로 방지하기 위해:

    1) main.py 는 WIRED_PACKAGES 상수를 선언하고 패키지 단위로 wire 해야 한다.
    2) 저장소에서 dependency_injector.wiring 의 Provide/@inject 를 사용하는
       모든 모듈은 WIRED_PACKAGES 중 하나의 하위여야 한다.

검사 방식:
    - 무거운 모듈 import 를 피하기 위해 파일 시스템 스캔 + AST 분석만 사용한다
      (main.py 나 app.* 모듈을 import 하지 않음).
    - 주석/문자열 내 "Provide[" 텍스트에 오탐하지 않도록 AST 의 import 구문을
      기준으로 wiring 의존 모듈을 판별한다.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

# 저장소 루트: tests/unit/architecture/ 에서 3단계 상위
REPO_ROOT = Path(__file__).resolve().parents[3]
MAIN_PY = REPO_ROOT / "main.py"
APP_DIR = REPO_ROOT / "app"

# dependency_injector wiring 마커로 간주하는 import 대상
WIRING_MODULE = "dependency_injector.wiring"
WIRING_MARKER_NAMES = {"Provide", "Provider", "inject"}


def _imports_wiring_markers(tree: ast.Module) -> bool:
    """모듈 AST 가 dependency_injector wiring 마커를 import 하는지 판별합니다.

    Args:
        tree: 대상 모듈의 파싱된 AST

    Returns:
        Provide/Provider/inject 를 import 하면 True (wiring 필요 모듈로 간주)
    """
    for node in ast.walk(tree):
        # from dependency_injector.wiring import Provide, inject [as ...]
        if isinstance(node, ast.ImportFrom):
            if node.module == WIRING_MODULE and any(
                alias.name in WIRING_MARKER_NAMES for alias in node.names
            ):
                return True
            # from dependency_injector import wiring → wiring.Provide 사용 가능성
            if node.module == "dependency_injector" and any(
                alias.name == "wiring" for alias in node.names
            ):
                return True
        # import dependency_injector.wiring → 보수적으로 wiring 필요로 간주
        elif isinstance(node, ast.Import):
            if any(alias.name == WIRING_MODULE for alias in node.names):
                return True
    return False


def _path_to_module(py_file: Path) -> str:
    """저장소 루트 기준 파일 경로를 점(.) 구분 모듈 경로로 변환합니다.

    예: app/api/ingest.py → app.api.ingest, app/api/__init__.py → app.api

    Args:
        py_file: 저장소 루트 하위의 .py 파일 절대 경로

    Returns:
        점 구분 모듈 경로 문자열
    """
    relative = py_file.relative_to(REPO_ROOT)
    parts = list(relative.with_suffix("").parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _collect_wiring_consumer_modules() -> set[str]:
    """app/ 패키지와 main.py 에서 wiring 마커를 사용하는 모듈을 전수 수집합니다.

    Returns:
        wiring 마커(Provide/@inject)를 import 하는 모듈 경로 집합
    """
    consumers: set[str] = set()
    candidates = sorted(APP_DIR.rglob("*.py")) + [MAIN_PY]
    for py_file in candidates:
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8"))
        except SyntaxError as exc:  # 파싱 불가 파일은 가드가 침묵하면 안 됨
            pytest.fail(f"{py_file} AST 파싱 실패: {exc}")
        if _imports_wiring_markers(tree):
            consumers.add(_path_to_module(py_file))
    return consumers


def _load_wired_packages() -> list[str]:
    """main.py 의 WIRED_PACKAGES 상수를 import 없이 AST 로 추출합니다.

    Returns:
        WIRED_PACKAGES 에 선언된 패키지 경로 리스트

    Raises:
        Failed: 상수가 없거나 리터럴 리스트가 아니면 테스트 실패
    """
    tree = ast.parse(MAIN_PY.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        # 일반 할당(Assign)과 타입 주석 할당(AnnAssign) 모두 지원
        if isinstance(node, ast.AnnAssign):
            targets = [node.target]
            value = node.value
        elif isinstance(node, ast.Assign):
            targets = list(node.targets)
            value = node.value
        else:
            continue
        for target in targets:
            if isinstance(target, ast.Name) and target.id == "WIRED_PACKAGES":
                if value is None:
                    pytest.fail("main.py 의 WIRED_PACKAGES 에 값이 없습니다.")
                try:
                    packages = ast.literal_eval(value)
                except ValueError:
                    pytest.fail(
                        "main.py 의 WIRED_PACKAGES 는 정적 리터럴 리스트여야 합니다."
                    )
                if not isinstance(packages, list) or not all(
                    isinstance(pkg, str) for pkg in packages
                ):
                    pytest.fail(
                        "main.py 의 WIRED_PACKAGES 는 list[str] 이어야 합니다."
                    )
                return packages
    pytest.fail(
        "main.py 에 WIRED_PACKAGES 상수가 없습니다. "
        "container.wire(packages=WIRED_PACKAGES) 패턴으로 패키지 단위 wiring 을 "
        "선언해야 합니다 (수동 모듈 열거 금지)."
    )


def _is_covered(module: str, packages: list[str]) -> bool:
    """모듈이 wire 대상 패키지 중 하나의 하위인지 판별합니다.

    Args:
        module: 점 구분 모듈 경로 (예: app.api.ingest)
        packages: WIRED_PACKAGES 패키지 목록

    Returns:
        포함되면 True
    """
    return any(module == pkg or module.startswith(f"{pkg}.") for pkg in packages)


class TestWiringCompleteness:
    """main.py 패키지 단위 wiring 의 완전성 검증"""

    def test_wired_packages_constant_exists(self) -> None:
        """main.py 에 비어 있지 않은 WIRED_PACKAGES: list[str] 가 선언되어야 한다."""
        packages = _load_wired_packages()
        assert packages, "WIRED_PACKAGES 가 비어 있습니다 — 최소 'app.api' 가 필요합니다."

    def test_main_wires_by_packages_constant(self) -> None:
        """main.py 는 container.wire(packages=WIRED_PACKAGES) 를 호출해야 한다.

        상수만 선언하고 실제 wire 에 사용하지 않는 회귀를 방지한다.
        """
        tree = ast.parse(MAIN_PY.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "wire"
            ):
                for keyword in node.keywords:
                    if (
                        keyword.arg == "packages"
                        and isinstance(keyword.value, ast.Name)
                        and keyword.value.id == "WIRED_PACKAGES"
                    ):
                        return
        pytest.fail(
            "main.py 에서 container.wire(packages=WIRED_PACKAGES) 호출을 찾지 "
            "못했습니다. 수동 모듈 열거(wire(modules=[...]))는 신규 라우터 누락 시 "
            "프로덕션 500 을 유발하므로 패키지 단위 wiring 을 유지해야 합니다."
        )

    def test_scanner_detects_known_consumer(self) -> None:
        """스캐너 자체 건전성: 알려진 wiring 사용 모듈(app.api.ingest)을 탐지해야 한다.

        스캐너가 망가져 아무 모듈도 찾지 못하면 완전성 검사가 공허하게 통과하므로,
        실제 Provide[] 사용이 확인된 모듈을 기준점으로 검증한다.
        """
        consumers = _collect_wiring_consumer_modules()
        assert "app.api.ingest" in consumers, (
            "wiring 스캐너가 app.api.ingest 를 탐지하지 못했습니다 — "
            "탐지 로직 회귀 여부를 확인하십시오."
        )

    def test_all_wiring_consumers_covered_by_wired_packages(self) -> None:
        """Provide/@inject 를 사용하는 모든 모듈이 WIRED_PACKAGES 하위여야 한다.

        신규 모듈이 wire 범위 밖에서 Provide 를 쓰면 이 테스트가 실패한다.
        해결 방법: 해당 모듈을 WIRED_PACKAGES 내 패키지 하위로 옮기거나,
        main.py 의 WIRED_PACKAGES 에 상위 패키지를 추가한다.
        """
        packages = _load_wired_packages()
        consumers = _collect_wiring_consumer_modules()

        uncovered = sorted(
            module for module in consumers if not _is_covered(module, packages)
        )
        assert not uncovered, (
            "다음 모듈이 dependency_injector wiring 마커(Provide/@inject)를 "
            f"사용하지만 WIRED_PACKAGES{packages} 의 wire 범위 밖에 있습니다: "
            f"{uncovered}. 이대로 배포되면 해당 엔드포인트는 raw Provide 마커를 "
            "주입받아 500 을 반환합니다. main.py 의 WIRED_PACKAGES 에 상위 패키지를 "
            "추가하십시오 (개별 모듈 수동 열거 금지)."
        )
