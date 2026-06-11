"""
설정 생존성 가드 테스트 (파생 기반)

목적(차단하는 결함 클래스):
    base.yaml의 imports 누락 → load_config() 결과에서 해당 yaml의 섹션이
    통째로 빠짐 → 이를 읽는 코드(di_container 등)에 조용히 None/{}가 주입되어
    기능이 소리 없이 무력화되는 "데드 컨피그(dead config)" 결함.

배경:
    과거 privacy/bm25/grok 3종이 imports 누락으로 깨졌고, 하드코딩 목록 기반
    가드는 tools.yaml의 미임포트(에이전트 경로 설정 무효화)를 잡지 못했다.
    이 파일은 하드코딩 대신 파일 시스템과 base.yaml에서 검증 대상을 "파생"하여
    새 yaml 추가 시 import 누락을 자동으로 잡아낸다.

검증 항목:
    1. imports 전수 검증 — app/config/features/*.yaml 전수가 base.yaml의
       imports 목록 또는 명시적 allowlist(사유 필수)에 존재해야 한다.
    2. import 경로 실존 — imports의 각 항목이 실제 파일이어야 한다
       (_load_yaml_file은 파일이 없으면 조용히 {}를 반환하므로 오타도 데드 컨피그가 된다).
    3. 섹션 생존성 — import되는 각 yaml의 최상위 섹션이 실제 load_config()
       결과에 존재하고 None이 아니어야 한다 (섹션명은 yaml 파싱으로 동적 파생).
    4. 환경변수 치환 생존성 — `${VAR:default}` / `${VAR:-default}` 구문이
       치환 실패 리터럴로 남지 않아야 한다 (구 grok 테스트의 일반화).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from app.lib.config_loader import load_config

# 경로 상수: tests/unit/config/ 기준으로 저장소 루트의 app/config 해석
_CONFIG_DIR = Path(__file__).resolve().parents[3] / "app" / "config"
_FEATURES_DIR = _CONFIG_DIR / "features"
_BASE_YAML = _CONFIG_DIR / "base.yaml"

# 정상 설정 파일명 패턴.
# macOS Finder 복제본("xxx 2.yaml" — .gitignore의 `* 2.*` 규칙으로 git에서 무시됨)
# 같은 로컬 아티팩트를 검증 대상에서 제외한다.
_VALID_STEM = re.compile(r"^[a-z0-9_]+$")

# 의도적으로 base.yaml imports에 포함하지 않는 features yaml의 allowlist.
# 형식: {파일명: 사유}. 새 항목 추가 시 반드시 구체적 사유를 적을 것.
# 여기 없는 파일이 imports에도 없으면 테스트가 실패한다(데드 컨피그 차단).
INTENTIONALLY_NOT_IMPORTED: dict[str, str] = {
    # --- 선택형 Vector DB provider 설정 (기본 provider는 weaviate) ---
    # di_container.create_vector_store가 config.get("<provider>", {}) +
    # 환경변수 폴백으로 동작하므로 미임포트 상태에서도 환경변수로 운용 가능.
    # 해당 provider를 기본 채택할 때 import 추가를 검토한다.
    "chroma.yaml": "선택형 provider — CHROMA_PERSIST_DIR 환경변수 폴백으로 동작",
    "pinecone.yaml": "선택형 provider — PINECONE_API_KEY 환경변수 폴백으로 동작",
    "qdrant.yaml": "선택형 provider — QDRANT_URL/QDRANT_API_KEY 환경변수 폴백으로 동작",
    "pgvector.yaml": "선택형 provider — PGVECTOR_CONNECTION_STRING 환경변수 폴백으로 동작",
    "mongodb.yaml": (
        "선택형 provider — MONGODB_URI 등 환경변수 오버라이드 경로 보유 "
        "(config_loader._apply_env_overrides가 mongodb.* 키를 환경변수로 생성)"
    ),
    # --- 현재 런타임 코드가 최상위 섹션을 읽지 않는 템플릿/문서용 yaml ---
    # 활성화(코드에서 섹션 참조 추가) 시 imports 추가가 선행되어야 한다.
    "ollama.yaml": "참조 템플릿 — 최상위 ollama 섹션을 읽는 런타임 코드 없음 (LLM 설정은 llm.yaml 경유)",
    "batch.yaml": "참조 템플릿 — 최상위 batch 섹션을 읽는 런타임 코드 없음 (배치 카테고리는 domain.yaml 경유)",
    "notion_pipeline.yaml": "참조 템플릿 — 최상위 notion_pipeline 섹션을 읽는 런타임 코드 없음",
    # EnrichmentService는 config.get("enrichment", {}) 코드 기본값으로 동작.
    # yaml 값을 적용하려면 별도 트랙에서 import 추가 + 동작 검증이 필요하다.
    "enrichment.yaml": "보강 파이프라인은 코드 기본값으로 동작 — yaml 적용은 별도 트랙에서 결정",
}


def _base_import_names() -> list[str]:
    """base.yaml의 imports 목록을 파일명(파일 경로 제외)으로 반환한다."""
    with open(_BASE_YAML, encoding="utf-8") as f:
        base = yaml.safe_load(f) or {}
    return [Path(entry).name for entry in base.get("imports", [])]


def _base_import_paths() -> list[Path]:
    """base.yaml의 imports 목록을 base.yaml 기준 절대 경로로 반환한다."""
    with open(_BASE_YAML, encoding="utf-8") as f:
        base = yaml.safe_load(f) or {}
    return [_BASE_YAML.parent / entry for entry in base.get("imports", [])]


def _feature_yaml_files() -> list[Path]:
    """검증 대상 features/*.yaml 전수 (로컬 복제 아티팩트 제외)를 반환한다."""
    return sorted(p for p in _FEATURES_DIR.glob("*.yaml") if _VALID_STEM.match(p.stem))


@pytest.fixture(scope="module")
def loaded_config() -> dict[str, Any]:
    """실제 설정 파일을 로드한다 (검증은 끄고 원시 병합 결과 확인)."""
    return load_config(validate=False)


# ============================================================
# 1. imports 전수 검증
# ============================================================
@pytest.mark.parametrize(
    "feature_file",
    [p.name for p in _feature_yaml_files()],
)
def test_feature_yaml_imported_or_allowlisted(feature_file: str) -> None:
    """features/*.yaml 전수가 imports 또는 allowlist에 존재해야 한다.

    새 yaml을 추가하고 base.yaml imports를 잊으면 이 테스트가 실패한다.
    """
    imported = set(_base_import_names())
    if feature_file in imported:
        return
    assert feature_file in INTENTIONALLY_NOT_IMPORTED, (
        f"features/{feature_file}이(가) base.yaml imports에 없습니다. "
        f"의도된 동작이면 INTENTIONALLY_NOT_IMPORTED에 사유와 함께 추가하고, "
        f"아니면 app/config/base.yaml의 imports에 추가하십시오. "
        f"(미임포트 시 해당 섹션을 읽는 코드에 조용히 None/{{}}가 주입됩니다)"
    )


def test_allowlist_entries_are_consistent() -> None:
    """allowlist 항목은 실존 파일이어야 하고 imports와 중복되면 안 된다.

    - 파일이 삭제되면 allowlist에서 제거해 부패(stale)를 방지한다.
    - imports에 추가됐다면 allowlist에서 제거해 단일 정본을 유지한다.
    """
    imported = set(_base_import_names())
    for name, reason in INTENTIONALLY_NOT_IMPORTED.items():
        assert reason.strip(), f"allowlist 항목 '{name}'에 사유가 비어 있습니다"
        assert (_FEATURES_DIR / name).exists(), (
            f"allowlist 항목 '{name}'이(가) 실제 파일로 존재하지 않습니다. "
            f"파일이 삭제됐다면 allowlist에서도 제거하십시오."
        )
        assert name not in imported, (
            f"'{name}'이(가) imports와 allowlist에 동시에 존재합니다. "
            f"import됐다면 allowlist에서 제거하십시오."
        )


def test_all_import_paths_exist() -> None:
    """imports의 각 경로가 실제 파일이어야 한다 (오타 → 조용한 {} 반환 차단)."""
    for path in _base_import_paths():
        assert path.exists(), (
            f"base.yaml imports에 존재하지 않는 파일이 있습니다: {path}. "
            f"_load_yaml_file은 파일이 없으면 조용히 빈 dict를 반환하므로 "
            f"오타도 데드 컨피그가 됩니다."
        )


# ============================================================
# 2. 섹션 생존성 검증 (섹션명은 yaml 파싱으로 동적 파생)
# ============================================================
def _imported_top_level_sections() -> list[tuple[str, str]]:
    """import되는 각 yaml의 (파일명, 최상위 섹션명) 쌍을 동적으로 수집한다."""
    pairs: list[tuple[str, str]] = []
    for path in _base_import_paths():
        if not path.exists():
            # 실존 검증은 test_all_import_paths_exist가 담당
            continue
        with open(path, encoding="utf-8") as f:
            content = yaml.safe_load(f) or {}
        for section in content:
            pairs.append((path.name, str(section)))
    return pairs


@pytest.mark.parametrize(
    ("feature_file", "section"),
    _imported_top_level_sections(),
)
def test_imported_section_alive_in_loaded_config(
    loaded_config: dict[str, Any],
    feature_file: str,
    section: str,
) -> None:
    """import된 yaml의 최상위 섹션이 load_config() 결과에 살아 있어야 한다."""
    assert section in loaded_config, (
        f"'{feature_file}'의 섹션 '{section}'이(가) load_config() 결과에 없습니다. "
        f"병합 과정에서 섹션이 유실됐는지 확인하십시오."
    )
    assert loaded_config[section] is not None, (
        f"'{feature_file}'의 섹션 '{section}'이(가) None으로 로드됐습니다. "
        f"yaml 내용 또는 환경별 오버라이드를 확인하십시오."
    )


# ============================================================
# 3. 환경변수 치환 생존성 (구 grok 플레이스홀더 테스트의 일반화)
# ============================================================
# ${VAR:default} / ${VAR:-default} 구문은 환경변수 미설정 시에도 항상 기본값으로
# 치환되어야 한다. (콜론 없는 ${VAR}는 미설정 시 원문 유지가 의도된 동작이므로 제외)
_UNRESOLVED_DEFAULT_PLACEHOLDER = re.compile(r"\$\{[^}]*:[^}]*\}")


def _collect_unresolved_placeholders(value: Any, path: str = "") -> list[str]:
    """설정 트리를 재귀 탐색해 치환 실패 리터럴이 남은 경로를 수집한다."""
    found: list[str] = []
    if isinstance(value, str):
        if _UNRESOLVED_DEFAULT_PLACEHOLDER.search(value):
            found.append(f"{path} = {value!r}")
    elif isinstance(value, dict):
        for key, item in value.items():
            found.extend(
                _collect_unresolved_placeholders(item, f"{path}.{key}" if path else str(key))
            )
    elif isinstance(value, list):
        for idx, item in enumerate(value):
            found.extend(_collect_unresolved_placeholders(item, f"{path}[{idx}]"))
    return found


def test_env_default_placeholders_resolved(loaded_config: dict[str, Any]) -> None:
    """`${VAR:...}` 기본값 구문이 치환 실패 리터럴로 남지 않아야 한다."""
    unresolved = _collect_unresolved_placeholders(loaded_config)
    assert not unresolved, (
        "환경변수 치환 실패 리터럴이 남았습니다 (config_loader._substitute_env_vars "
        f"확인 필요): {unresolved}"
    )
