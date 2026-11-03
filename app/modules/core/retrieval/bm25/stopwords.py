"""
불용어 필터 (StopwordFilter)

도메인 범용 불용어 처리:
- 과도하게 빈번한 단어 제거
- 대화 상투어 제거 (문의, 안내 등)
- 의미 없는 수식어 제거 (추천, 후기 등)

불용어는 모든 문서에 등장하여 구별력이 없거나,
검색 품질을 저하시키는 단어들입니다.

Phase 2 구현 (2025-11-28)
"""

from collections.abc import Iterable

from app.lib.logger import get_logger

logger = get_logger(__name__)


class StopwordFilter:
    """
    불용어 필터

    BM25 검색에서 불용어를 제거하여 검색 품질을 향상시킵니다.
    """

    # 기본 불용어 목록
    DEFAULT_STOPWORDS: set[str] = {
        # ========================================
        # 일반적인 한국어 불용어 (도메인 무관)
        # ========================================
        "있는",
        "없는",
        "하는",
        "되는",
        "같은",
        "그런",
        "이런",
        "저런",
        "어떤",
        "것",
        "거",
        "수",
        "등",
        "외",
        "및",
        "또는",
        "그리고",
        "하지만",
    }

    def __init__(
        self,
        custom_stopwords: Iterable[str] | None = None,
        use_defaults: bool = True,
        enabled: bool = True,
    ):
        """
        Args:
            custom_stopwords: 추가 불용어 (set, list 등 Iterable 지원)
            use_defaults: 기본 불용어 사용 여부
            enabled: 불용어 필터 기능 활성화 여부 (기본: True)
        """
        self.enabled = enabled
        self.stopwords: set[str] = set()

        if self.enabled:
            if use_defaults:
                self.stopwords.update(self.DEFAULT_STOPWORDS)

            if custom_stopwords:
                self.stopwords.update(custom_stopwords)

            logger.info(f"불용어 필터 초기화: {len(self.stopwords)}개 불용어")
        else:
            logger.info("불용어 필터 비활성화됨")

    def filter(self, tokens: list[str]) -> list[str]:
        """
        토큰 리스트에서 불용어 제거

        Args:
            tokens: 토큰 리스트

        Returns:
            불용어가 제거된 토큰 리스트
        """
        if not self.enabled:
            return tokens

        filtered = [t for t in tokens if t not in self.stopwords]

        removed_count = len(tokens) - len(filtered)
        if removed_count > 0:
            logger.debug(f"불용어 {removed_count}개 제거: {tokens} → {filtered}")

        return filtered

    def filter_text(self, text: str) -> str:
        """
        텍스트에서 불용어 제거

        Args:
            text: 원본 텍스트

        Returns:
            불용어가 제거된 텍스트
        """
        if not text:
            return text

        words = text.split()
        filtered = self.filter(words)
        return " ".join(filtered)

    def is_stopword(self, word: str) -> bool:
        """
        단어가 불용어인지 확인

        Args:
            word: 확인할 단어

        Returns:
            불용어 여부
        """
        return word in self.stopwords

    def add_stopword(self, word: str) -> None:
        """불용어 추가"""
        self.stopwords.add(word)

    def remove_stopword(self, word: str) -> bool:
        """
        불용어 제거

        Returns:
            제거 성공 여부
        """
        if word in self.stopwords:
            self.stopwords.discard(word)
            return True
        return False

    def get_stopwords(self) -> set[str]:
        """현재 불용어 세트 반환 (복사본)"""
        return self.stopwords.copy()

    @property
    def count(self) -> int:
        """불용어 개수"""
        return len(self.stopwords)
