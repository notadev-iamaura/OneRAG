"""
Graceful Initializer - 모듈 초기화 시스템 (Graceful Degradation 지원)

TASK-H6: DI Container 통합 - Graceful Degradation 시스템
Wave 1: 핵심 데이터 구조 및 기본 클래스 구현

주요 기능:
- 3-Tier 우선순위 시스템 (CRITICAL, IMPORTANT, OPTIONAL)
- 모듈별 재시도 및 타임아웃 지원
- 실패한 모듈에 대한 Graceful Degradation
- 모듈 상태 추적 및 모니터링

설계 원칙:
- Backward Compatibility: 기존 코드와 병행 운영 가능
- Type Safety: dataclass + Enum으로 타입 안전성 확보
- Feature Flag: 점진적 배포를 위한 활성화/비활성화 지원
"""

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from app.lib.logger import get_logger

logger = get_logger(__name__)


class ModulePriority(Enum):
    """
    모듈 우선순위 등급

    CRITICAL: 시스템 동작에 필수적인 모듈 (실패 시 전체 시스템 중단)
    IMPORTANT: 핵심 기능이지만 제한된 기능으로 동작 가능 (실패 시 경고 + 제한 모드)
    OPTIONAL: 선택적 기능 모듈 (실패 시 무시 가능)
    """

    CRITICAL = 1
    IMPORTANT = 2
    OPTIONAL = 3


class ModuleInitStatus(Enum):
    """
    모듈 초기화 상태

    PENDING: 초기화 대기 중
    INITIALIZING: 초기화 진행 중
    SUCCESS: 초기화 성공
    FAILED: 초기화 실패
    DEGRADED: 제한된 기능으로 동작 중
    """

    PENDING = "pending"
    INITIALIZING = "initializing"
    SUCCESS = "success"
    FAILED = "failed"
    DEGRADED = "degraded"


@dataclass
class ModuleConfig:
    """
    모듈 초기화 설정

    Attributes:
        name: 모듈 이름 (로깅 및 추적용)
        priority: 모듈 우선순위 (CRITICAL, IMPORTANT, OPTIONAL)
        initializer: 초기화 함수 (async callable)
        dependencies: 의존하는 모듈 이름 목록
        retry_count: 재시도 횟수 (기본: 3)
        retry_delay: 첫 재시도 지연 시간(초) - Exponential Backoff 적용 (기본: 1.0)
        timeout: 초기화 타임아웃(초) (기본: 30.0)
    """

    name: str
    priority: ModulePriority
    initializer: Callable[[], Any]
    dependencies: list[str] = field(default_factory=list)
    retry_count: int = 3
    retry_delay: float = 1.0
    timeout: float = 30.0


@dataclass
class ModuleStatus:
    """
    모듈 초기화 상태 및 결과

    Attributes:
        name: 모듈 이름
        priority: 모듈 우선순위
        status: 현재 상태 (PENDING, INITIALIZING, SUCCESS, FAILED, DEGRADED)
        instance: 초기화된 모듈 인스턴스 (성공 시)
        error: 발생한 에러 (실패 시)
        retry_attempts: 시도한 재시도 횟수
        init_duration: 초기화 소요 시간(초)
        last_attempt: 마지막 시도 타임스탬프
    """

    name: str
    priority: ModulePriority
    status: ModuleInitStatus = ModuleInitStatus.PENDING
    instance: Any | None = None
    error: Exception | None = None
    retry_attempts: int = 0
    init_duration: float = 0.0
    last_attempt: float = field(default_factory=time.time)


class GracefulInitializer:
    """
    Graceful Degradation을 지원하는 모듈 초기화 시스템

    주요 기능:
    1. 우선순위 기반 초기화 (CRITICAL → IMPORTANT → OPTIONAL)
    2. 모듈별 재시도 및 타임아웃 지원
    3. 의존성 그래프 기반 순서 보장
    4. 실패한 모듈에 대한 Graceful Degradation
    5. 상태 추적 및 모니터링

    사용 예시:
        initializer = GracefulInitializer()

        # 모듈 등록
        initializer.register_module(ModuleConfig(
            name="Session",
            priority=ModulePriority.CRITICAL,
            initializer=session.initialize,
            timeout=10.0
        ))

        # 모든 모듈 초기화
        results = await initializer.initialize_all()
    """

    def __init__(self) -> None:
        """GracefulInitializer 초기화"""
        self.modules: dict[str, ModuleConfig] = {}
        self.statuses: dict[str, ModuleStatus] = {}
        logger.info("GracefulInitializer 생성 완료")

    def register_module(self, config: ModuleConfig) -> None:
        """
        모듈 등록

        Args:
            config: 모듈 초기화 설정

        Raises:
            ValueError: 이미 등록된 모듈인 경우
        """
        if config.name in self.modules:
            raise ValueError(f"Module '{config.name}' already registered")
        self.modules[config.name] = config
        self.statuses[config.name] = ModuleStatus(name=config.name, priority=config.priority)
        logger.debug(
            "Module registered",
            extra={
                "module_name": config.name,
                "priority": config.priority.name
            }
        )

    async def _initialize_module_with_retry(self, config: ModuleConfig) -> ModuleStatus:
        """
        재시도 로직을 포함한 모듈 초기화

        Exponential Backoff 전략:
        - 1차 시도: 즉시
        - 2차 시도: 1초 지연
        - 3차 시도: 2초 지연
        - 4차 시도: 4초 지연

        Args:
            config: 모듈 초기화 설정

        Returns:
            ModuleStatus (초기화 결과)
        """
        status = self.statuses[config.name]
        status.status = ModuleInitStatus.INITIALIZING
        status.last_attempt = time.time()
        start_time = time.time()
        for attempt in range(config.retry_count + 1):
            try:
                logger.debug(
                    "초기화 시도",
                    extra={
                        "module_name": config.name,
                        "attempt": attempt + 1,
                        "max_attempts": config.retry_count + 1
                    }
                )
                instance = await asyncio.wait_for(config.initializer(), timeout=config.timeout)
                status.status = ModuleInitStatus.SUCCESS
                status.instance = instance
                status.retry_attempts = attempt
                status.init_duration = time.time() - start_time
                logger.info(
                    "모듈 초기화 성공",
                    extra={
                        "module_name": config.name,
                        "attempts": attempt + 1,
                        "duration_seconds": round(status.init_duration, 2)
                    }
                )
                return status
            except TimeoutError:
                error_msg = f"Timeout after {config.timeout}s"
                logger.warning(
                    "모듈 초기화 타임아웃",
                    extra={
                        "module_name": config.name,
                        "timeout_seconds": config.timeout,
                        "attempt": attempt + 1
                    }
                )
                status.error = Exception(error_msg)
            except Exception as e:
                logger.warning(
                    "모듈 초기화 실패",
                    extra={
                        "module_name": config.name,
                        "error": str(e),
                        "error_type": type(e).__name__,
                        "attempt": attempt + 1
                    }
                )
                status.error = e
            if attempt < config.retry_count:
                delay = config.retry_delay * 2**attempt
                logger.debug(
                    "재시도 대기 중",
                    extra={
                        "module_name": config.name,
                        "delay_seconds": round(delay, 1)
                    }
                )
                await asyncio.sleep(delay)
        status.status = ModuleInitStatus.FAILED
        status.retry_attempts = config.retry_count
        status.init_duration = time.time() - start_time
        logger.error(
            "모듈 초기화 최종 실패",
            extra={
                "module_name": config.name,
                "total_attempts": config.retry_count + 1,
                "duration_seconds": round(status.init_duration, 2),
                "error": str(status.error),
                "error_type": type(status.error).__name__
            },
            exc_info=True
        )
        return status

    def _resolve_initialization_order(self, module_names: list[str]) -> list[str]:
        """
        의존성 그래프 기반 초기화 순서 해결 (Topological Sort)

        Kahn's Algorithm을 사용하여 의존성 순서를 해결합니다.
        In-degree = 해당 모듈이 의존하는 다른 모듈의 개수

        Args:
            module_names: 초기화할 모듈 이름 목록

        Returns:
            의존성 순서로 정렬된 모듈 이름 목록

        Raises:
            ValueError: 순환 의존성 발견 시
        """
        graph: dict[str, set[str]] = {}
        in_degree: dict[str, int] = {}
        for name in module_names:
            config = self.modules[name]
            graph[name] = {dep for dep in config.dependencies if dep in module_names}
            in_degree[name] = len(graph[name])
        queue = [name for name in module_names if in_degree[name] == 0]
        sorted_order = []
        while queue:
            queue.sort()
            current = queue.pop(0)
            sorted_order.append(current)
            for name in module_names:
                if current in graph[name]:
                    in_degree[name] -= 1
                    if in_degree[name] == 0:
                        queue.append(name)
        if len(sorted_order) != len(module_names):
            remaining = set(module_names) - set(sorted_order)
            raise ValueError(f"Circular dependency detected in modules: {remaining}")
        logger.debug(
            "초기화 순서 해결 완료",
            extra={"initialization_order": sorted_order}
        )
        return sorted_order

    async def initialize_all(
        self, enable_graceful_degradation: bool = True
    ) -> dict[str, ModuleStatus]:
        """
        등록된 모든 모듈 초기화 (우선순위 기반)

        초기화 순서:
        1. CRITICAL 모듈들 (병렬 초기화, 의존성 순서 보장)
        2. IMPORTANT 모듈들 (병렬 초기화)
        3. OPTIONAL 모듈들 (병렬 초기화)

        Args:
            enable_graceful_degradation: Graceful Degradation 활성화 여부
                True: IMPORTANT/OPTIONAL 실패 시 계속 진행
                False: 모든 실패를 즉시 에러로 처리

        Returns:
            모듈 이름 → ModuleStatus 딕셔너리

        Raises:
            RuntimeError: CRITICAL 모듈 초기화 실패 시
        """
        logger.info("Graceful 모듈 초기화 시작")
        overall_start_time = time.time()
        priority_groups: dict[ModulePriority, list[str]] = {
            ModulePriority.CRITICAL: [],
            ModulePriority.IMPORTANT: [],
            ModulePriority.OPTIONAL: [],
        }
        for name, config in self.modules.items():
            priority_groups[config.priority].append(name)
        logger.info(
            "모듈 그룹 구성",
            extra={
                "critical_count": len(priority_groups[ModulePriority.CRITICAL]),
                "important_count": len(priority_groups[ModulePriority.IMPORTANT]),
                "optional_count": len(priority_groups[ModulePriority.OPTIONAL])
            }
        )
        for priority in [
            ModulePriority.CRITICAL,
            ModulePriority.IMPORTANT,
            ModulePriority.OPTIONAL,
        ]:
            module_names = priority_groups[priority]
            if not module_names:
                continue
            logger.info(f"\n{'=' * 60}")
            logger.info(
                "우선순위 모듈 초기화 중",
                extra={"priority": priority.name}
            )
            logger.info(f"{'=' * 60}")
            try:
                sorted_names = self._resolve_initialization_order(module_names)
            except ValueError as e:
                logger.error(
                    "의존성 해결 실패",
                    extra={
                        "error": str(e),
                        "error_type": type(e).__name__
                    },
                    exc_info=True
                )
                if priority == ModulePriority.CRITICAL:
                    raise RuntimeError(f"Critical module dependency error: {e}") from e
                continue
            init_tasks = [
                self._initialize_module_with_retry(self.modules[name]) for name in sorted_names
            ]
            results = await asyncio.gather(*init_tasks, return_exceptions=False)
            failed_modules = [
                status for status in results if status.status == ModuleInitStatus.FAILED
            ]
            if failed_modules:
                failed_names = [s.name for s in failed_modules]
                logger.warning(
                    "모듈 초기화 실패 발생",
                    extra={
                        "priority": priority.name,
                        "failed_count": len(failed_modules),
                        "failed_modules": failed_names
                    }
                )
                if priority == ModulePriority.CRITICAL:
                    error_details = "\n".join([f"  • {s.name}: {s.error}" for s in failed_modules])
                    raise RuntimeError(f"Critical module initialization failed:\n{error_details}")
                if not enable_graceful_degradation:
                    error_details = "\n".join([f"  • {s.name}: {s.error}" for s in failed_modules])
                    raise RuntimeError(
                        f"{priority.name} module initialization failed (graceful degradation disabled):\n{error_details}"
                    )
                for status in failed_modules:
                    logger.warning(
                        "모듈 DEGRADED 모드로 실행",
                        extra={
                            "module_name": status.name,
                            "priority": status.priority.name
                        }
                    )
                    status.status = ModuleInitStatus.DEGRADED
        total_duration = time.time() - overall_start_time
        success_count = sum(
            1 for s in self.statuses.values() if s.status == ModuleInitStatus.SUCCESS
        )
        degraded_count = sum(
            1 for s in self.statuses.values() if s.status == ModuleInitStatus.DEGRADED
        )
        failed_count = sum(1 for s in self.statuses.values() if s.status == ModuleInitStatus.FAILED)
        logger.info(f"\n{'=' * 60}")
        logger.info(
            "모듈 초기화 완료",
            extra={
                "total_duration_seconds": round(total_duration, 2),
                "success_count": success_count,
                "degraded_count": degraded_count,
                "failed_count": failed_count
            }
        )
        logger.info(f"{'=' * 60}\n")
        return self.statuses

    def get_module_status(self, name: str) -> ModuleStatus | None:
        """
        모듈 상태 조회

        Args:
            name: 모듈 이름

        Returns:
            ModuleStatus 또는 None (미등록 모듈)
        """
        return self.statuses.get(name)

    def get_all_statuses(self) -> dict[str, ModuleStatus]:
        """
        모든 모듈 상태 조회

        Returns:
            모듈 이름 → ModuleStatus 딕셔너리
        """
        return self.statuses.copy()

    def log_summary(self) -> None:
        """
        초기화 결과 요약 로그 출력

        성공/실패/제한 모드 모듈 수와 세부 정보를 출력합니다.
        """
        if not self.statuses:
            logger.warning("등록된 모듈 없음")
            return
        priority_stats: dict[ModulePriority, dict[str, int]] = {
            ModulePriority.CRITICAL: {"success": 0, "degraded": 0, "failed": 0},
            ModulePriority.IMPORTANT: {"success": 0, "degraded": 0, "failed": 0},
            ModulePriority.OPTIONAL: {"success": 0, "degraded": 0, "failed": 0},
        }
        for status in self.statuses.values():
            if status.status == ModuleInitStatus.SUCCESS:
                priority_stats[status.priority]["success"] += 1
            elif status.status == ModuleInitStatus.DEGRADED:
                priority_stats[status.priority]["degraded"] += 1
            elif status.status == ModuleInitStatus.FAILED:
                priority_stats[status.priority]["failed"] += 1
        total_success = sum(s["success"] for s in priority_stats.values())
        total_degraded = sum(s["degraded"] for s in priority_stats.values())
        total_failed = sum(s["failed"] for s in priority_stats.values())
        total_modules = len(self.statuses)
        logger.info("\n" + "=" * 70)
        logger.info("Module Initialization Summary")
        logger.info("=" * 70)
        for priority in [
            ModulePriority.CRITICAL,
            ModulePriority.IMPORTANT,
            ModulePriority.OPTIONAL,
        ]:
            stats = priority_stats[priority]
            if stats["success"] + stats["degraded"] + stats["failed"] > 0:
                logger.info(
                    f"  {priority.name:12s}: SUCCESS {stats['success']:2d}  DEGRADED {stats['degraded']:2d}  FAILED {stats['failed']:2d}"
                )
        logger.info("-" * 70)
        logger.info(
            f"  {'TOTAL':12s}: SUCCESS {total_success:2d}  DEGRADED {total_degraded:2d}  FAILED {total_failed:2d}  (Total: {total_modules})"
        )
        if total_degraded > 0 or total_failed > 0:
            logger.info("-" * 70)
            if total_degraded > 0:
                degraded_modules = [
                    f"{s.name} ({s.priority.name})"
                    for s in self.statuses.values()
                    if s.status == ModuleInitStatus.DEGRADED
                ]
                logger.warning(f"  DEGRADED: {', '.join(degraded_modules)}")
            if total_failed > 0:
                failed_modules = [
                    f"{s.name} ({s.priority.name}): {s.error}"
                    for s in self.statuses.values()
                    if s.status == ModuleInitStatus.FAILED
                ]
                logger.error("  FAILED:")
                for module_info in failed_modules:
                    logger.error(f"     - {module_info}")
        logger.info("=" * 70 + "\n")
