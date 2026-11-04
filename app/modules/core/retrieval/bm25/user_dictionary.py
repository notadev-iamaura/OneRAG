"""
사용자 사전 (UserDictionary)

형태소 분석 예외 처리:
- 고유명사: 분리하면 안 되는 특정 항목명
- 합성어: 도메인 특화 복합어

형태소 분석기가 이 단어들을 분리하지 않도록 합니다.
예: "복합항목명" → ["복합", "항목명"] (X)
    "복합항목명" → ["복합항목명"] (O)
"""

import re

from app.lib.logger import get_logger

logger = get_logger(__name__)


class UserDictionary:
    """
    사용자 사전 (형태소 분석 예외)

    형태소 분석기에서 분리하면 안 되는 단어들을 관리합니다.
    """

    # 기본 사용자 사전
    DEFAULT_ENTRIES: set[str] = set()

    def __init__(
        self,
        custom_entries: set[str] | None = None,
        use_defaults: bool = True,
        enabled: bool = True,
    ):
        """
        Args:
            custom_entries: 추가 사용자 사전 엔트리 (None이면 기본만 사용)
            use_defaults: 기본 사용자 사전 사용 여부
            enabled: 사용자 사전 기능 활성화 여부 (기본: True)
        """
        self.enabled = enabled
        self.entries: set[str] = set()
        self.pattern: re.Pattern[str] | None = None

        if self.enabled:
            if use_defaults:
                self.entries.update(self.DEFAULT_ENTRIES)

            if custom_entries:
                self.entries.update(custom_entries)

            # 정규식 패턴 생성 (긴 단어부터 매칭하도록 정렬)
            self._build_pattern()

            logger.info(f"사용자 사전 초기화: {len(self.entries)}개 엔트리")
        else:
            logger.info("사용자 사전 비활성화됨")

    def _build_pattern(self) -> None:
        """정규식 패턴 빌드 (긴 단어 우선)"""
        if not self.entries:
            self.pattern = None
            return

        # 긴 단어부터 매칭하도록 정렬 (탐욕적 매칭 방지)
        sorted_entries = sorted(self.entries, key=len, reverse=True)

        # 특수문자 이스케이프
        escaped = [re.escape(e) for e in sorted_entries]

        # 패턴 생성: 단어 경계 없이 매칭 (한글은 \b 작동 안 함)
        self.pattern = re.compile("|".join(escaped))

    def protect_entries(self, text: str) -> tuple[str, dict[str, str]]:
        """
        텍스트에서 사용자 사전 엔트리를 보호

        형태소 분석 전에 호출하여 분리되면 안 되는 단어를
        임시 토큰으로 대체합니다.

        Args:
            text: 원본 텍스트

        Returns:
            (보호된 텍스트, 복원 맵)
        """
        if not self.enabled or not text or not self.pattern:
            return text, {}

        restore_map: dict[str, str] = {}
        counter = [0]  # 클로저용 mutable

        def replacer(match: re.Match) -> str:
            word = match.group(0)
            token = f"__USER_DICT_{counter[0]}__"
            restore_map[token] = word
            counter[0] += 1
            return token

        protected = self.pattern.sub(replacer, text)

        if restore_map:
            logger.debug(f"사용자 사전 보호: {len(restore_map)}개 단어")

        return protected, restore_map

    def restore_entries(self, text: str, restore_map: dict[str, str]) -> str:
        """
        보호된 텍스트 복원

        형태소 분석 후 호출하여 임시 토큰을 원래 단어로 복원합니다.

        Args:
            text: 보호된 텍스트
            restore_map: protect_entries에서 반환된 복원 맵

        Returns:
            복원된 텍스트
        """
        if not restore_map:
            return text

        result = text
        for token, original in restore_map.items():
            result = result.replace(token, original)

        return result

    def contains(self, word: str) -> bool:
        """
        단어가 사용자 사전에 있는지 확인

        Args:
            word: 확인할 단어

        Returns:
            사전 포함 여부
        """
        return word in self.entries

    def find_entries(self, text: str) -> list[str]:
        """
        텍스트에서 사용자 사전 엔트리 찾기

        Args:
            text: 검색할 텍스트

        Returns:
            발견된 사용자 사전 엔트리 리스트
        """
        if not text or not self.pattern:
            return []

        matches = self.pattern.findall(text)
        return list(set(matches))

    def add_entry(self, word: str) -> None:
        """사용자 사전 엔트리 추가"""
        self.entries.add(word)
        self._build_pattern()

    def remove_entry(self, word: str) -> bool:
        """
        사용자 사전 엔트리 제거

        Returns:
            제거 성공 여부
        """
        if word in self.entries:
            self.entries.discard(word)
            self._build_pattern()
            return True
        return False

    def get_entries(self) -> set[str]:
        """현재 사용자 사전 엔트리 세트 반환 (복사본)"""
        return self.entries.copy()

    @property
    def count(self) -> int:
        """엔트리 개수"""
        return len(self.entries)
