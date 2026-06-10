"""
한국어 형태소 토크나이저

Kiwi 한국어 형태소 분석기를 래핑하여 BM25 검색에 필요한
토큰화 기능을 제공합니다.

의존성:
- kiwipiepy: pip install kiwipiepy (선택적)

기존 BM25 전처리 모듈(StopwordFilter, SynonymManager, UserDictionary)과
선택적으로 연동하여 검색 품질을 높입니다.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from app.modules.core.retrieval.bm25.stopwords import StopwordFilter
    from app.modules.core.retrieval.bm25.synonym_manager import SynonymManager
    from app.modules.core.retrieval.bm25.user_dictionary import UserDictionary

logger = logging.getLogger(__name__)


@runtime_checkable
class Tokenizer(Protocol):
    """BM25 토크나이저 인터페이스 (언어별 구현 교체용).

    범용성: bm25.yaml의 tokenizer 설정으로 언어에 맞는 구현을 선택한다.
    """

    def tokenize(self, text: str) -> list[str]: ...

    def tokenize_batch(self, texts: list[str]) -> list[list[str]]: ...


class WhitespaceTokenizer:
    """언어 중립 공백 기반 토크나이저 (비한국어 코퍼스용).

    형태소 분석 없이 소문자화 + 공백 분리만 수행한다. 영어·다국어 BM25에
    적합하며, 한국어 형태소 분석기(Kiwi)가 부적합한 코퍼스에서 사용한다.
    """

    def tokenize(self, text: str) -> list[str]:
        return text.lower().split()

    def tokenize_batch(self, texts: list[str]) -> list[list[str]]:
        return [self.tokenize(t) for t in texts]

# Kiwi에서 추출할 의미 있는 품사 태그
# NNG: 일반 명사, NNP: 고유 명사, NNB: 의존 명사
# VV: 동사, VA: 형용사, MAG: 일반 부사
# SL: 외국어, SN: 숫자, SH: 한자
_MEANINGFUL_POS_TAGS = frozenset(
    {"NNG", "NNP", "VV", "VA", "MAG", "SL", "SN", "SH"}
)


class KoreanTokenizer:
    """
    Kiwi 기반 한국어 형태소 토크나이저

    BM25 검색을 위해 텍스트를 의미 있는 형태소 토큰으로 분리합니다.
    조사, 어미 등 검색에 불필요한 품사는 제거합니다.

    Args:
        stopword_filter: 불용어 필터 (선택적, DI 주입)
        synonym_manager: 동의어 관리자 (선택적, DI 주입)
        user_dictionary: 사용자 사전 (선택적, DI 주입)

    사용 예시:
        tokenizer = KoreanTokenizer()
        tokens = tokenizer.tokenize("삼성전자의 주가가 올랐습니다")
        # → ["삼성전자", "주가", "오르"]
    """

    def __init__(
        self,
        stopword_filter: StopwordFilter | None = None,
        synonym_manager: SynonymManager | None = None,
        user_dictionary: UserDictionary | None = None,
    ) -> None:
        self._stopword_filter = stopword_filter
        self._synonym_manager = synonym_manager
        self._user_dictionary = user_dictionary

        # Kiwi 인스턴스 (지연 초기화)
        self._kiwi = self._initialize_kiwi()

        logger.info(
            "KoreanTokenizer 초기화 완료 "
            f"(stopword_filter={'있음' if stopword_filter else '없음'}, "
            f"synonym_manager={'있음' if synonym_manager else '없음'}, "
            f"user_dictionary={'있음' if user_dictionary else '없음'})"
        )

    def _initialize_kiwi(self) -> Kiwi:  # type: ignore[name-defined]  # noqa: F821
        """Kiwi 형태소 분석기 초기화"""
        try:
            from kiwipiepy import Kiwi

            kiwi = Kiwi()
            logger.debug("Kiwi 형태소 분석기 로드 완료")
            return kiwi
        except ImportError as e:
            raise ImportError(
                "KoreanTokenizer를 사용하려면 kiwipiepy가 필요합니다. "
                "설치: uv add kiwipiepy 또는 pip install kiwipiepy"
            ) from e

    def tokenize(self, text: str) -> list[str]:
        """
        텍스트를 의미 있는 형태소 토큰으로 분리

        전처리 파이프라인:
        1. UserDictionary 보호 (합성어 보호)
        2. SynonymManager 확장 (동의어 정규화)
        3. Kiwi 형태소 분석 (의미 있는 품사만 추출)
        4. StopwordFilter 적용 (불용어 제거)
        5. UserDictionary 복원

        Args:
            text: 토큰화할 텍스트

        Returns:
            의미 있는 형태소 토큰 리스트
        """
        if not text or not text.strip():
            return []

        processed_text = text
        restore_map: dict[str, str] = {}

        # 1. UserDictionary 보호 (합성어 → 임시 토큰)
        if self._user_dictionary:
            processed_text, restore_map = self._user_dictionary.protect_entries(
                processed_text
            )

        # 2. SynonymManager 확장 (동의어 → 표준어)
        if self._synonym_manager:
            processed_text = self._synonym_manager.expand_query(processed_text)

        # 3. Kiwi 형태소 분석 — 의미 있는 품사만 추출
        tokens: list[str] = []
        for token in self._kiwi.tokenize(processed_text):
            if token.tag in _MEANINGFUL_POS_TAGS:
                form = token.form
                # UserDictionary 복원
                if restore_map:
                    form = self._user_dictionary.restore_entries(  # type: ignore[union-attr]
                        form, restore_map
                    )
                tokens.append(form)

        # 4. StopwordFilter 적용
        if self._stopword_filter:
            tokens = self._stopword_filter.filter(tokens)

        return tokens

    def tokenize_batch(self, texts: list[str]) -> list[list[str]]:
        """
        다수 텍스트 일괄 토큰화

        Args:
            texts: 토큰화할 텍스트 리스트

        Returns:
            각 텍스트별 토큰 리스트의 리스트
        """
        return [self.tokenize(text) for text in texts]
