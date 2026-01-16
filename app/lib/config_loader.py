"""
Configuration loader for RAG Chatbot
YAML 기반 계층적 설정 로더 + Pydantic 검증

v3.1.0 개선사항:
- 모듈화된 Pydantic 스키마 지원 (app/config/schemas/)
- Feature Flag로 레거시/신규 검증 선택 가능
- Graceful Degradation 지원 (검증 실패 시에도 시스템 동작)

v3.3.1 개선사항:
- 환경별 설정 분리 (development, test, production)
- environment.py 기반 다층 환경 감지 통합
- config_validator.py Pydantic 검증 강화 통합
"""

import os
import re
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import ValidationError

# 레거시 스키마 (하위 호환성)
from ..config.schemas import detect_duplicate_keys_in_yaml
from ..config.schemas import validate_config_dict as validate_config_dict_legacy

# 신규 모듈화된 스키마
from ..config.schemas.root import validate_config_safe
from .config_validator import validate_full_config
from .environment import is_production_environment
from .errors import ConfigError, ErrorCode


class ConfigLoader:
    """설정 로더 클래스"""

    def __init__(self) -> None:
        env_file = Path(__file__).parent.parent.parent / ".env"
        if env_file.exists():
            load_dotenv(env_file)
        self.base_path = Path(__file__).parent.parent / "config"

        # 다층 환경 감지 로직 사용 (environment.py)
        if is_production_environment():
            self.environment = "production"
        else:
            # 개발/테스트 환경 구분
            env_value = os.getenv("ENVIRONMENT") or os.getenv("NODE_ENV") or "development"
            self.environment = env_value.lower()

            # test 환경 감지
            if self.environment not in ["development", "test", "production"]:
                self.environment = "development"

        print(f"🔧 환경 감지: {self.environment}")

    def load_config(
        self,
        validate: bool = True,
        use_modular_schema: bool = False,
        raise_on_validation_error: bool = False,
        enable_enhanced_validation: bool = True,
    ) -> dict[str, Any]:
        """
        설정 로드 및 병합 (모듈화된 base.yaml + imports + 환경별 설정)

        Args:
            validate: Pydantic 검증 활성화 여부 (기본 True)
            use_modular_schema: 신규 모듈화된 스키마 사용 여부 (기본 False)
                - False: 레거시 schemas.py 사용 (기본값, 하위 호환성)
                - True: 신규 schemas/ 디렉토리 사용 (점진적 마이그레이션)
            raise_on_validation_error: 검증 실패 시 예외 발생 여부 (기본 False)
                - False: Graceful Degradation (검증 실패해도 시스템 동작)
                - True: 검증 실패 시 ConfigError 발생 (개발 환경 권장)
            enable_enhanced_validation: 강화된 Pydantic 검증 활성화 (기본 True)
                - True: config_validator.py의 검증 로직 적용
                - False: 레거시 검증만 사용

        Returns:
            검증된 설정 딕셔너리 (또는 검증되지 않은 원본 dict)
        """
        try:
            base_config_path = self.base_path / "base.yaml"
            legacy_config_path = self.base_path / "config.yaml"
            if base_config_path.exists():
                config_file_path = base_config_path
                print("📦 Using modular config: base.yaml (+ imports)")
            elif legacy_config_path.exists():
                config_file_path = legacy_config_path
                print("⚠️  Using legacy config: config.yaml (consider migrating to base.yaml)")
            else:
                raise ConfigError(
                    ErrorCode.CONFIG_001,
                    searched_paths=[str(base_config_path), str(legacy_config_path)],
                    config_directory=str(self.base_path),
                    environment=self.environment,
                )
            duplicates = detect_duplicate_keys_in_yaml(str(config_file_path))
            if duplicates:
                raise ConfigError(
                    ErrorCode.CONFIG_002,
                    config_file=str(config_file_path),
                    duplicate_keys=duplicates,
                    duplicate_count=len(duplicates),
                )
            base_config = self._load_yaml_file(config_file_path)
            env_config_path = self.base_path / "environments" / f"{self.environment}.yaml"
            if env_config_path.exists():
                env_config = self._load_yaml_file(env_config_path)
                base_config = self._merge_configs(base_config, env_config)
            base_config = self._substitute_env_vars(base_config)
            base_config = self._apply_env_overrides(base_config)

            # 강화된 Pydantic 검증 (v3.3.1)
            if validate and enable_enhanced_validation:
                print("🔧 강화된 Pydantic 검증 적용 중...")
                try:
                    base_config = validate_full_config(
                        base_config,
                        strict=raise_on_validation_error,
                    )
                    print("✅ 강화된 설정 검증 완료")
                except Exception as e:
                    if raise_on_validation_error:
                        raise ConfigError(
                            ErrorCode.CONFIG_003,
                            validation_errors=str(e),
                            environment=self.environment,
                        ) from e
                    print(f"⚠️ 강화된 검증 경고: {e}")
                    print("⚠️ 기본 검증으로 전환합니다.")

            # Pydantic 검증 (Feature Flag로 레거시/신규 선택)
            if validate:
                if use_modular_schema:
                    # 신규 모듈화된 스키마 사용 (Graceful Degradation 지원)
                    print("🔧 Using modular Pydantic schemas (app/config/schemas/)")
                    result = validate_config_safe(
                        base_config,
                        raise_on_error=raise_on_validation_error,
                        log_errors=True,
                    )

                    # RootConfig 객체면 dict로 변환
                    if hasattr(result, "model_dump"):
                        return dict(result.model_dump(exclude_none=False, exclude_unset=False))
                    else:
                        # 검증 실패로 dict 반환된 경우 (Graceful Degradation)
                        return dict(result)  # type: ignore[arg-type]

                else:
                    # 레거시 스키마 사용 (기존 동작 유지)
                    print("🔧 Using legacy Pydantic schema (app/config/schemas.py)")
                    try:
                        validated_config = validate_config_dict_legacy(base_config)
                        print("✅ 설정 검증 완료")
                        validated_dict: dict[str, Any] = validated_config.model_dump(
                            exclude_none=False, exclude_unset=False
                        )
                        return validated_dict
                    except ValidationError as e:
                        if raise_on_validation_error:
                            raise ConfigError(
                                ErrorCode.CONFIG_003,
                                validation_errors=str(e),
                                environment=self.environment,
                            ) from e

                        print(f"⚠️  설정 검증 경고:\n{e}")
                        print("⚠️  검증 없이 설정을 로드합니다 (위험)")
                        return base_config

            return base_config
        except ConfigError:
            raise
        except ValidationError as e:
            raise ConfigError(
                ErrorCode.CONFIG_003,
                validation_errors=str(e),
                environment=self.environment,
            ) from e
        except Exception as e:
            raise ConfigError(
                ErrorCode.CONFIG_004,
                config_path=str(self.base_path),
                environment=self.environment,
                original_error=str(e),
            ) from e

    def _load_yaml_file(self, file_path: Path) -> dict[str, Any]:
        """
        YAML 파일 로드 (imports 지원)

        imports 키가 있으면 해당 파일들을 재귀적으로 로드하여 병합.
        상대 경로는 현재 파일 기준으로 해석.

        Example:
            imports:
              - features/embeddings.yaml
              - features/generation.yaml
        """
        if not file_path.exists():
            return {}
        with open(file_path, encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}
        if "imports" in config:
            imports = config.pop("imports")
            for import_path in imports:
                if not Path(import_path).is_absolute():
                    import_file = file_path.parent / import_path
                else:
                    import_file = Path(import_path)
                imported_config = self._load_yaml_file(import_file)
                config = self._merge_configs(config, imported_config)
                print(f"  ✓ Imported: {import_path}")
        return config

    def _merge_configs(self, base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
        """설정 깊은 병합"""
        merged = base.copy()
        for key, value in override.items():
            if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
                merged[key] = self._merge_configs(merged[key], value)
            else:
                merged[key] = value
        return merged

    def _apply_env_overrides(self, config: dict[str, Any]) -> dict[str, Any]:
        """환경 변수 오버라이드 적용"""
        env_mappings = {
            "PORT": ("server", "port"),
            "HOST": ("server", "host"),
            "GOOGLE_API_KEY": ("llm", "google", "api_key"),
            "OPENAI_API_KEY": ("llm", "openai", "api_key"),
            "ANTHROPIC_API_KEY": ("llm", "anthropic", "api_key"),
            "COHERE_API_KEY": ("reranking", "providers", "cohere", "api_key"),
            "REDIS_URL": ("session", "redis_url"),
            "LOG_LEVEL": ("logging", "level"),
            # MongoDB 환경 변수 매핑 (통합 테스트 지원)
            "MONGODB_URI": ("mongodb", "uri"),
            "MONGODB_DATABASE": ("mongodb", "database"),
            "MONGODB_DB_NAME": ("mongodb", "database"),  # 별칭 지원
            "MONGODB_TIMEOUT_MS": ("mongodb", "timeout_ms"),
            # Quickstart 지원: 임베딩/LLM 환경 변수 오버라이드
            # YAML 설정보다 환경 변수가 우선 적용됨
            "EMBEDDINGS_PROVIDER": ("embeddings", "provider"),
            "LLM_PROVIDER": ("llm", "provider"),
            "LLM_MODEL": ("llm", "model"),
        }
        for env_var, config_path in env_mappings.items():
            value = os.getenv(env_var)
            if value is not None:
                self._set_nested_value(config, config_path, value)
        return config

    def _set_nested_value(self, config: dict[str, Any], path: tuple[str, ...], value: str) -> None:
        """중첩된 딕셔너리에 값 설정"""
        current = config
        for key in path[:-1]:
            if key not in current:
                current[key] = {}
            elif not isinstance(current[key], dict):
                current[key] = {}
            current = current[key]
        converted_value = self._convert_value(value)
        current[path[-1]] = converted_value

    def _convert_value(self, value: str) -> Any:
        """환경 변수 값 타입 변환"""
        if value.lower() in ("true", "false"):
            return value.lower() == "true"
        try:
            if "." in value:
                return float(value)
            else:
                return int(value)
        except ValueError:
            pass
        return value

    def _substitute_env_vars(self, config: dict[str, Any]) -> dict[str, Any]:
        """환경 변수 치환 적용"""

        def substitute_value(value: Any) -> Any:
            if isinstance(value, str):
                pattern = "\\$\\{([^}]+)\\}"

                def replace_env_var(match: re.Match[str]) -> str:
                    var_expr = match.group(1)
                    if ":-" in var_expr:
                        var_name, default_value = var_expr.split(":-", 1)
                        return os.getenv(var_name, default_value)
                    else:
                        return os.getenv(var_expr, match.group(0))

                return re.sub(pattern, replace_env_var, value)
            elif isinstance(value, dict):
                return {k: substitute_value(v) for k, v in value.items()}
            elif isinstance(value, list):
                return [substitute_value(item) for item in value]
            else:
                return value

        substituted = substitute_value(config)
        if not isinstance(substituted, dict):
            return config
        return substituted


def load_config(
    validate: bool = True,
    use_modular_schema: bool = False,
    raise_on_validation_error: bool = False,
    enable_enhanced_validation: bool = True,
) -> dict[str, Any]:
    """
    전역 설정 로드 함수

    Args:
        validate: Pydantic 검증 활성화 여부 (기본 True)
        use_modular_schema: 신규 모듈화된 스키마 사용 여부 (기본 False)
        raise_on_validation_error: 검증 실패 시 예외 발생 여부 (기본 False)
        enable_enhanced_validation: 강화된 Pydantic 검증 활성화 (기본 True)

    Returns:
        검증된 설정 딕셔너리

    Examples:
        >>> # 기본 사용 (강화된 검증 포함)
        >>> config = load_config()
        >>>
        >>> # 레거시 검증만 사용
        >>> config = load_config(enable_enhanced_validation=False)
        >>>
        >>> # 신규 모듈화된 스키마 + 강화된 검증
        >>> config = load_config(use_modular_schema=True, enable_enhanced_validation=True)
        >>>
        >>> # 개발 환경: 엄격한 검증
        >>> config = load_config(raise_on_validation_error=True)
    """
    loader = ConfigLoader()
    return loader.load_config(
        validate=validate,
        use_modular_schema=use_modular_schema,
        raise_on_validation_error=raise_on_validation_error,
        enable_enhanced_validation=enable_enhanced_validation,
    )
