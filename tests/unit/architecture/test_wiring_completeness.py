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
    - 1차: AST 의 import 구문 기준으로 wiring 의존 모듈을 판별한다.
    - 2차(보수적 텍스트 폴백): `import dependency_injector` 후 속성 접근
      (dependency_injector.wiring.Provide[...]) 스타일은 AST import 검사가
      놓치므로, 주석을 제외한 소스 텍스트에 "Provide[" / "wiring.inject" 가
      보이면 소비자로 간주한다. 문자열 리터럴 오탐 가능성은 감수한다 —
      wire 범위(WIRED_PACKAGES) 안이면 어차피 통과하고, 범위 밖이면
      사람이 확인하도록 실패시키는 편이 조용한 누락보다 안전하다.
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

# 텍스트 폴백 마커: 속성 접근 스타일(wiring.Provide[...]) 사용 흔적
_TEXT_WIRING_MARKERS = ("Provide[", "wiring.inject")


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


def _has_textual_wiring_marker(source: str) -> bool:
    """주석을 제외한 소스 라인에서 wiring 마커 텍스트 사용 흔적을 찾습니다.

    `import dependency_injector` 후 속성 접근(...wiring.Provide[...]) 스타일은
    AST import 검사(_imports_wiring_markers)가 놓치므로 보수적 텍스트 폴백으로
    보강한다. 라인 단위로 `#` 이후(주석)를 잘라낸 뒤 검색하므로 설명 주석
    (main.py 의 WIRED_PACKAGES 주석 등)에는 오탐하지 않는다. 문자열 리터럴
    내 마커는 오탐 가능하지만, covered 검사에서 걸러진다(모듈 docstring 참고).

    Args:
        source: 대상 모듈의 소스 텍스트

    Returns:
        주석 제외 코드 텍스트에 마커가 있으면 True
    """
    for line in source.splitlines():
        code_part = line.split("#", 1)[0]
        if any(marker in code_part for marker in _TEXT_WIRING_MARKERS):
            return True
    return False


def _collect_wiring_consumer_modules() -> set[str]:
    """app/ 패키지와 main.py 에서 wiring 마커를 사용하는 모듈을 전수 수집합니다.

    AST import 검사와 텍스트 폴백(_has_textual_wiring_marker) 중 하나라도
    걸리면 소비자로 간주한다 (미탐지로 인한 조용한 wiring 누락 방지).

    Returns:
        wiring 마커(Provide/@inject)를 사용하는 모듈 경로 집합
    """
    consumers: set[str] = set()
    candidates = sorted(APP_DIR.rglob("*.py")) + [MAIN_PY]
    for py_file in candidates:
        source = py_file.read_text(encoding="utf-8")
        try:
            tree = ast.parse(source)
        except SyntaxError as exc:  # 파싱 불가 파일은 가드가 침묵하면 안 됨
            pytest.fail(f"{py_file} AST 파싱 실패: {exc}")
        if _imports_wiring_markers(tree) or _has_textual_wiring_marker(source):
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
                    pytest.fail("main.py 의 WIRED_PACKAGES 는 정적 리터럴 리스트여야 합니다.")
                if not isinstance(packages, list) or not all(
                    isinstance(pkg, str) for pkg in packages
                ):
                    pytest.fail("main.py 의 WIRED_PACKAGES 는 list[str] 이어야 합니다.")
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

    def test_text_fallback_detects_attribute_access_style(self) -> None:
        """`import dependency_injector` + 속성 접근 스타일도 소비자로 탐지해야 한다.

        AST import 검사는 `dependency_injector.wiring.Provide[...]` 스타일을
        놓친다(import 구문에 wiring 이 등장하지 않음). 텍스트 폴백이 이 구멍을
        메우는지 자기 검증한다.
        """
        source = (
            "import dependency_injector\n"
            "def handler(svc=dependency_injector.wiring.Provide['svc']):\n"
            "    return svc\n"
        )
        # 전제: AST 검사 단독으로는 미탐지 (이 구멍이 사라지면 폴백 재평가 가능)
        assert not _imports_wiring_markers(ast.parse(source)), (
            "AST 검사가 속성 접근 스타일을 탐지하게 됐습니다 — "
            "텍스트 폴백 유지 필요 여부를 재평가하십시오."
        )
        assert _has_textual_wiring_marker(source), (
            "텍스트 폴백이 속성 접근 스타일(wiring.Provide[...])을 탐지하지 못했습니다."
        )

    def test_text_fallback_ignores_comment_only_mentions(self) -> None:
        """주석 속 'Provide[' 언급(main.py 의 설명 주석 등)은 오탐하지 않아야 한다."""
        source = (
            "# 신규 라우터가 Provide[]/@inject 를 써도 자동 wiring\n"
            "WIRED_PACKAGES: list[str] = ['app.api']\n"
        )
        assert not _has_textual_wiring_marker(source), (
            "텍스트 폴백이 주석 내 마커 언급에 오탐했습니다 — 주석 제거 로직을 확인하십시오."
        )

    def test_wired_packages_contain_no_implicit_namespace_dirs(self) -> None:
        """wired 패키지 하위에서 .py 를 담는 모든 디렉토리에 __init__.py 가 있어야 한다.

        dependency-injector 의 wire(packages=...) 는 pkgutil.walk_packages 기반이라
        __init__.py 없는 디렉토리(implicit namespace package)는 순회하지 않는다.
        반면 이 가드의 _is_covered 는 문자열 prefix 매칭이므로, namespace
        디렉토리가 생기면 '커버됨'으로 오판한 채 실제 wiring 은 누락된다
        (조용한 프로덕션 500). 그 불일치를 구조적으로 차단한다.
        """
        packages = _load_wired_packages()
        missing: set[str] = set()
        for pkg in packages:
            pkg_dir = REPO_ROOT.joinpath(*pkg.split("."))
            assert pkg_dir.is_dir(), (
                f"WIRED_PACKAGES 항목 '{pkg}' 에 해당하는 디렉토리가 없습니다: {pkg_dir}"
            )
            for py_file in sorted(pkg_dir.rglob("*.py")):
                # pkg 루트부터 .py 파일까지 경로상의 모든 디렉토리가 정규 패키지여야 한다
                directory = py_file.parent
                while True:
                    if not (directory / "__init__.py").exists():
                        missing.add(str(directory.relative_to(REPO_ROOT)))
                    if directory == pkg_dir:
                        break
                    directory = directory.parent
        assert not missing, (
            f"다음 디렉토리에 __init__.py 가 없습니다 (implicit namespace): "
            f"{sorted(missing)}. dependency-injector 의 walk_packages 는 이런 "
            "디렉토리를 순회하지 않으므로 하위 모듈의 Provide/@inject 가 "
            "wire 되지 않은 채 배포됩니다. __init__.py 를 추가하십시오."
        )

    def test_all_wiring_consumers_covered_by_wired_packages(self) -> None:
        """Provide/@inject 를 사용하는 모든 모듈이 WIRED_PACKAGES 하위여야 한다.

        신규 모듈이 wire 범위 밖에서 Provide 를 쓰면 이 테스트가 실패한다.
        해결 방법: 해당 모듈을 WIRED_PACKAGES 내 패키지 하위로 옮기거나,
        main.py 의 WIRED_PACKAGES 에 상위 패키지를 추가한다.
        """
        packages = _load_wired_packages()
        consumers = _collect_wiring_consumer_modules()

        uncovered = sorted(module for module in consumers if not _is_covered(module, packages))
        assert not uncovered, (
            "다음 모듈이 dependency_injector wiring 마커(Provide/@inject)를 "
            f"사용하지만 WIRED_PACKAGES{packages} 의 wire 범위 밖에 있습니다: "
            f"{uncovered}. 이대로 배포되면 해당 엔드포인트는 raw Provide 마커를 "
            "주입받아 500 을 반환합니다. main.py 의 WIRED_PACKAGES 에 상위 패키지를 "
            "추가하십시오 (개별 모듈 수동 열거 금지)."
        )
