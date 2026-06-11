"""
enrichment.yaml 생존성 + 동작 무변화(behavior-neutral) 가드 테스트

차단하는 결함:
    EnrichmentService가 config["enrichment"]를 실제로 읽는데 enrichment.yaml이
    base.yaml imports에 없어 운영자의 yaml/환경변수 수정이 조용히 무시되던
    "살아있는 데드 컨피그" 결함. import 추가가 기존 동작(코드 기본값)을
    바꾸지 않아야 한다는 조건도 함께 고정한다.

검증 항목:
    1. 기본 load_config()(Pydantic 검증 경로)에서 enrichment 섹션 생존
       (validate=False 경로는 test_required_sections.py의 파생 가드가 담당).
    2. 환경변수 미설정 시 yaml 치환 결과가 EnrichmentConfig 코드 기본값과
       정확히 동등 — import만으로 동작 변화 없음을 보장.
    3. OPENAI_API_KEY 미설정 시 미치환 리터럴("${OPENAI_API_KEY}")이
       가짜 API 키로 오인되지 않음 (yaml의 `:-` 빈 기본값 회귀 차단).
"""

from __future__ import annotations

from pathlib import Path

import yaml

from app.lib.config_loader import ConfigLoader, load_config
from app.modules.core.enrichment.schemas.enrichment_schema import EnrichmentConfig
from app.modules.core.enrichment.services.enrichment_service import EnrichmentService

# enrichment.yaml이 참조하는 환경변수 전수 — 기본값 경로 검증 시 부재를 강제한다
_ENRICHMENT_ENV_VARS = (
    "ENRICHMENT_ENABLED",
    "ENRICHMENT_LLM_MODEL",
    "ENRICHMENT_LLM_TEMPERATURE",
    "ENRICHMENT_LLM_MAX_TOKENS",
    "ENRICHMENT_BATCH_SIZE",
    "ENRICHMENT_CONCURRENCY",
    "ENRICHMENT_TIMEOUT_SINGLE",
    "ENRICHMENT_TIMEOUT_BATCH",
    "ENRICHMENT_MAX_RETRIES",
    "ENRICHMENT_CACHE_ENABLED",
    "ENRICHMENT_CACHE_TTL",
    "ENRICHMENT_MIN_CONFIDENCE",
    "OPENAI_API_KEY",
)

_ENRICHMENT_YAML = (
    Path(__file__).resolve().parents[3] / "app" / "config" / "features" / "enrichment.yaml"
)


def _substituted_enrichment_config(monkeypatch) -> dict:
    """환경변수 부재 상태에서 enrichment.yaml을 치환한 설정 dict를 반환한다.

    ConfigLoader() 초기화가 .env를 os.environ에 적재하므로, 초기화 이후에
    관련 환경변수를 제거해 yaml 기본값 경로만 결정적으로 검증한다.
    """
    loader = ConfigLoader()
    for var in _ENRICHMENT_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    with open(_ENRICHMENT_YAML, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    substituted = loader._substitute_env_vars(raw)
    assert isinstance(substituted, dict)
    return substituted


def test_enrichment_section_survives_default_validation_path() -> None:
    """기본 load_config()(Pydantic 검증 경로)에서 enrichment 섹션이 보존돼야 한다."""
    config = load_config()
    enrichment = config.get("enrichment")
    assert enrichment is not None, (
        "load_config() 결과에 'enrichment' 섹션이 없습니다. "
        "app/config/features/enrichment.yaml이 base.yaml imports에 포함됐는지, "
        "루트 스키마가 extra 섹션을 보존하는지 확인하십시오."
    )
    assert isinstance(enrichment, dict) and "enabled" in enrichment, (
        "enrichment 섹션에 enabled 키가 없습니다 — 운영자가 설정만으로 켤 수 없습니다"
    )


def test_enrichment_yaml_defaults_match_code_defaults(monkeypatch) -> None:
    """환경변수 미설정 시 yaml 값이 코드 기본값과 정확히 동등해야 한다.

    enrichment.yaml import는 동작 무변화(behavior-neutral)가 전제다.
    yaml 기본값이 코드 기본값과 갈라지면 import 자체가 동작 변화를
    일으키므로 이 테스트가 실패한다.
    """
    config = _substituted_enrichment_config(monkeypatch)
    service = EnrichmentService(config)

    assert service.enrichment_config == EnrichmentConfig(), (
        "enrichment.yaml 기본값이 EnrichmentConfig 코드 기본값과 다릅니다: "
        f"{service.enrichment_config.model_dump()} != {EnrichmentConfig().model_dump()}"
    )
    assert service.is_enabled() is False, "보강 기능은 기본 비활성이어야 합니다"


def test_enrichment_api_key_absent_does_not_leak_placeholder(monkeypatch) -> None:
    """OPENAI_API_KEY 미설정 시 가짜 키(미치환 리터럴)가 반환되면 안 된다.

    `api_key: ${OPENAI_API_KEY}` 형태(콜론 없음)는 미설정 시 리터럴
    "${OPENAI_API_KEY}"로 남아 truthy가 되고, _get_openai_api_key가 이를
    실제 키로 오인해 폴백 체인이 끊긴다. yaml은 `${OPENAI_API_KEY:-}`
    (빈 문자열 기본값)을 유지해야 한다.
    """
    config = _substituted_enrichment_config(monkeypatch)
    service = EnrichmentService(config)

    api_key = service._get_openai_api_key()
    assert api_key is None, (
        f"OPENAI_API_KEY 미설정인데 api_key가 반환됐습니다: {api_key!r} — "
        "enrichment.yaml의 api_key에 `:-` 빈 기본값이 빠졌는지 확인하십시오."
    )
