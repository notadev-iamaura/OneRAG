"""
공용 DI 컨테이너 레지스트리 (API 라우터 모듈용)

목적:
    monitoring.py / prompts.py 등 라우터 모듈마다 복붙되던
    "_shared_container 전역 + set_container + _get_container(경고 폴백)" 블록을
    한 곳으로 모은다. 새 라우터는 ContainerRegistry 인스턴스 하나만 만들면 되고,
    폴백 동작을 바꿀 때도 이 파일 한 곳만 수정하면 된다.

주요 구성:
    - ContainerRegistry: 라우터 모듈별 공유 컨테이너 보관 + 미주입 시 경고 폴백

의존성:
    - app.lib.logger (경고 로그)
    - app.core.di_container (폴백 생성 시 지연 임포트 — 순환 임포트 방지)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..lib.logger import get_logger

# 순환 임포트 방지: 타입 힌트용으로만 임포트
if TYPE_CHECKING:
    from ..core.di_container import AppContainer

logger = get_logger(__name__)


class ContainerRegistry:
    """API 라우터 모듈별 공유 DI 컨테이너 보관소.

    main.py lifespan에서 set()으로 실행 중 파이프라인의 컨테이너를 주입하고,
    라우터 핸들러는 get()으로 동일 싱글톤(cost_tracker, prompt_manager 등)을
    참조한다. 미주입 시(주로 단위 테스트) 경고를 남기고 새 AppContainer를
    생성해 폴백한다 — 기존 모듈별 복붙 블록과 동일한 동작을 보존한다.
    """

    def __init__(self, owner: str, fallback_hint: str) -> None:
        """레지스트리 초기화.

        Args:
            owner: 경고 로그에 표시할 소유 라우터 이름 (예: "monitoring")
            fallback_hint: 폴백 시 발생 가능한 부작용 안내 문구
                (예: "메트릭이 비어 있을 수 있음")
        """
        self._owner = owner
        self._fallback_hint = fallback_hint
        self._container: AppContainer | None = None

    def set(self, container: AppContainer) -> None:
        """공유 DI 컨테이너 주입 (main.py lifespan에서 호출).

        Args:
            container: 실행 중 파이프라인과 동일한 AppContainer 싱글톤
        """
        self._container = container

    def get(self) -> AppContainer:
        """공유 컨테이너를 반환한다 (미주입 시 경고 후 새 인스턴스 — 테스트 폴백).

        Returns:
            주입된 공유 컨테이너, 또는 폴백으로 생성한 새 AppContainer
        """
        if self._container is not None:
            return self._container
        # 폴백 경로에서만 지연 임포트 (모듈 로드 시 순환 임포트 방지)
        from ..core.di_container import AppContainer

        logger.warning(
            f"[{self._owner}] 공유 컨테이너 미주입 — 새 AppContainer 생성 "
            f"({self._fallback_hint})"
        )
        return AppContainer()
