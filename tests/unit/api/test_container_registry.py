"""
공용 DI 컨테이너 레지스트리(ContainerRegistry) 단위 테스트

목적:
    monitoring/prompts에서 추출한 공용 헬퍼가 기존 모듈별 복붙 블록과 동일하게
    1) 주입된 컨테이너를 그대로 반환하고
    2) 미주입 시 경고 로그 + 새 AppContainer 폴백을 수행하며
    3) monitoring/prompts가 자체 블록 대신 공용 레지스트리에 위임하는지 검증한다.
"""

from __future__ import annotations

from unittest.mock import patch

from app.api import container_registry
from app.api.container_registry import ContainerRegistry


def test_get_returns_injected_container() -> None:
    """set()으로 주입한 컨테이너 객체를 get()이 그대로 반환한다."""
    registry = ContainerRegistry(owner="test", fallback_hint="힌트")
    sentinel = object()
    registry.set(sentinel)  # type: ignore[arg-type]
    assert registry.get() is sentinel


def test_get_without_injection_falls_back_with_warning() -> None:
    """미주입 시 경고를 남기고 새 AppContainer를 생성해 반환한다 (기존 동작 보존)."""
    registry = ContainerRegistry(owner="test-owner", fallback_hint="값이 비어 있을 수 있음")

    # 경고 로그가 소유자(owner)와 힌트를 포함해 출력되는지 확인
    with patch.object(container_registry.logger, "warning") as mock_warning:
        container = registry.get()

    # dependency-injector의 DeclarativeContainer는 인스턴스화 시 DynamicContainer를
    # 반환하므로 isinstance 대신 대표 provider 보유 여부로 폴백 생성을 검증한다
    assert container is not None
    assert hasattr(container, "prompt_manager")
    assert hasattr(container, "cost_tracker")
    mock_warning.assert_called_once()
    warning_message = mock_warning.call_args.args[0]
    assert "test-owner" in warning_message
    assert "미주입" in warning_message
    assert "값이 비어 있을 수 있음" in warning_message


def test_monitoring_and_prompts_delegate_to_shared_registry() -> None:
    """monitoring/prompts의 set_container/_get_container가 공용 레지스트리에 위임한다.

    main.py는 monitoring.set_container(...)/prompts.set_container(...)를 그대로
    호출하므로(수정 금지), 모듈 함수 이름은 유지된 채 내부만 위임돼야 한다.
    """
    from app.api import monitoring, prompts

    # 바운드 메서드 동등성: 같은 레지스트리 인스턴스의 같은 메서드인지 확인
    assert monitoring.set_container == monitoring._container_registry.set
    assert monitoring._get_container == monitoring._container_registry.get
    assert prompts.set_container == prompts._container_registry.set
    assert prompts._get_container == prompts._container_registry.get

    # 두 라우터가 서로 다른 레지스트리 인스턴스를 사용해야 한다 (독립 주입)
    assert monitoring._container_registry is not prompts._container_registry
