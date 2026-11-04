"""
화이트리스트 관리자 (WhitelistManager)

PII 마스킹 예외 단어를 중앙에서 관리하는 모듈.
privacy.yaml 설정과 동기화하여 모든 PII 처리 모드에서 공유.

주요 기능:
- YAML 설정 파일에서 화이트리스트 로드
- 런타임 화이트리스트 추가/제거
- 단어 존재 여부 확인

생성일: 2025-12-08 (PII 모듈 통합)
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from app.lib.logger import get_logger

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

logger = get_logger(__name__)


# ========================================
# 기본 화이트리스트 (설정 파일 로드 실패 시 폴백)
# ========================================
DEFAULT_WHITELIST: frozenset[str] = frozenset(
    [
        # 일반 호칭 및 명사 (오탐 방지)
        "담당",
        "관리자",
        "직원",
        "고객",
        "가족",
        "친구",
        "동생",
        "이모",
        "가이드",
        "지원",
        "문의",
        "안내",
        "확인",
        "추천",
        "팀장",
        "매니저",
        "대표",
        "이사",
        "부장",
        "과장",
        "대리",
        "사원",
        "주임",
        "연구원",
        "교수",
        "박사",
    ]
)


class WhitelistManager:
    """
    PII 마스킹 예외 화이트리스트 관리자

    YAML 설정 파일과 연동하여 화이트리스트를 중앙 관리합니다.
    모든 PII 처리 모드 (answer, document, filename)에서 공유됩니다.

    사용 예시:
        >>> manager = WhitelistManager()
        >>> manager.contains("이모")  # True
        >>> manager.contains("김철수")  # False
    """

    # 설정 파일 기본 경로
    DEFAULT_CONFIG_PATH = Path("app/config/features/privacy.yaml")

    def __init__(
        self,
        config_path: str | Path | None = None,
        initial_words: Sequence[str] | None = None,
    ):
        """
        Args:
            config_path: privacy.yaml 설정 파일 경로 (None이면 기본 경로)
            initial_words: 초기 화이트리스트 단어 목록 (설정 파일 대신 직접 지정)
        """
        self._config_path = Path(config_path) if config_path else self.DEFAULT_CONFIG_PATH
        self._words: frozenset[str] = frozenset()
        self._loaded_from_config: bool = False

        # 초기화 순서: initial_words > config file > defaults
        if initial_words is not None:
            self._words = frozenset(initial_words)
            logger.info(f"화이트리스트 초기화 (직접 지정): {len(self._words)}개 단어")
        else:
            self._load_from_config()

    def _load_from_config(self) -> None:
        """
        YAML 설정 파일에서 화이트리스트 로드

        실패 시 기본 화이트리스트 사용
        """
        try:
            if not self._config_path.exists():
                logger.warning(f"설정 파일 없음: {self._config_path}, 기본값 사용")
                self._words = DEFAULT_WHITELIST
                return

            with open(self._config_path, encoding="utf-8") as f:
                config = yaml.safe_load(f)

            # privacy.whitelist 경로에서 로드
            whitelist = config.get("privacy", {}).get("whitelist", [])

            if whitelist:
                self._words = frozenset(whitelist)
                self._loaded_from_config = True
                logger.info(
                    f"화이트리스트 로드 성공: {self._config_path} ({len(self._words)}개 단어)"
                )
            else:
                logger.warning("설정 파일에 whitelist 없음, 기본값 사용")
                self._words = DEFAULT_WHITELIST

        except yaml.YAMLError as e:
            logger.error(f"YAML 파싱 오류: {e}, 기본값 사용")
            self._words = DEFAULT_WHITELIST
        except Exception as e:
            logger.error(f"화이트리스트 로드 실패: {e}, 기본값 사용")
            self._words = DEFAULT_WHITELIST

    @property
    def words(self) -> frozenset[str]:
        """화이트리스트 단어 집합 (읽기 전용)"""
        return self._words

    @property
    def loaded_from_config(self) -> bool:
        """설정 파일에서 로드되었는지 여부"""
        return self._loaded_from_config

    def contains(self, word: str) -> bool:
        """
        단어가 화이트리스트에 포함되어 있는지 확인

        Args:
            word: 확인할 단어

        Returns:
            포함 여부
        """
        return word in self._words

    def add_words(self, words: Iterable[str]) -> int:
        """
        화이트리스트에 단어 추가 (런타임)

        Args:
            words: 추가할 단어 목록

        Returns:
            추가된 단어 수
        """
        new_words = frozenset(words)
        before_count = len(self._words)
        self._words = self._words | new_words
        added_count = len(self._words) - before_count

        if added_count > 0:
            logger.info(f"화이트리스트 단어 추가: {added_count}개 (총 {len(self._words)}개)")

        return added_count

    def remove_words(self, words: Iterable[str]) -> int:
        """
        화이트리스트에서 단어 제거 (런타임)

        Args:
            words: 제거할 단어 목록

        Returns:
            제거된 단어 수
        """
        remove_set = frozenset(words)
        before_count = len(self._words)
        self._words = self._words - remove_set
        removed_count = before_count - len(self._words)

        if removed_count > 0:
            logger.info(f"화이트리스트 단어 제거: {removed_count}개 (총 {len(self._words)}개)")

        return removed_count

    def reload(self) -> bool:
        """
        설정 파일에서 화이트리스트 다시 로드

        Returns:
            로드 성공 여부
        """
        before_count = len(self._words)
        self._load_from_config()
        after_count = len(self._words)

        if before_count != after_count:
            logger.info(f"화이트리스트 리로드: {before_count} → {after_count}개")

        return self._loaded_from_config

    def __len__(self) -> int:
        """화이트리스트 단어 수"""
        return len(self._words)

    def __contains__(self, word: str) -> bool:
        """in 연산자 지원"""
        return self.contains(word)

    def __iter__(self) -> Iterator[str]:
        """반복자 지원"""
        return iter(self._words)

    def to_list(self) -> list[str]:
        """화이트리스트를 정렬된 리스트로 반환"""
        return sorted(self._words)


# ========================================
# 싱글톤 인스턴스 (선택적 사용)
# ========================================
_default_manager: WhitelistManager | None = None


def get_whitelist_manager() -> WhitelistManager:
    """
    기본 WhitelistManager 싱글톤 인스턴스 반환

    DI Container를 사용하지 않는 경우 편의 함수로 사용.

    Returns:
        WhitelistManager 싱글톤 인스턴스
    """
    global _default_manager
    if _default_manager is None:
        _default_manager = WhitelistManager()
    return _default_manager


def reset_whitelist_manager() -> None:
    """
    싱글톤 인스턴스 리셋 (테스트용)
    """
    global _default_manager
    _default_manager = None
