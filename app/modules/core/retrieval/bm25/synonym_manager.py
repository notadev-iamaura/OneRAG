"""
동의어 사전 관리자 (SynonymManager)

도메인 특화 동의어 처리:
- CSV 파일에서 동의어 그룹 로드
- 쿼리 확장: 동의어를 표준어로 정규화
- 역방향 조회: 표준어의 모든 변형 반환

CSV 형식: 같은 행의 모든 단어는 동의어
예: 표준어,동의어1,동의어2
"""

import csv
import re
from pathlib import Path

from app.lib.logger import get_logger

logger = get_logger(__name__)


class SynonymManager:
    """
    동의어 사전 관리자

    도메인별 줄임말, 은어, 동의어를 관리합니다.
    """

    def __init__(self, csv_path: str | None = None, enabled: bool = True):
        """
        Args:
            csv_path: 동의어 사전 CSV 파일 경로.
            enabled: 동의어 확장 기능 활성화 여부 (기본: True)
        """
        self.csv_path = csv_path
        self.enabled = enabled

        # 동의어 맵: {표준어: [표준어, 동의어1, 동의어2, ...]}
        self.synonym_groups: dict[str, list[str]] = {}

        # 역방향 맵: {동의어: 표준어}
        self.reverse_map: dict[str, str] = {}

        if self.enabled:
            self._load_synonyms()

    def _load_synonyms(self) -> None:
        """
        CSV 파일에서 동의어 사전 로드

        CSV 형식:
        - 같은 행의 모든 단어는 동의어
        - 첫 번째 단어가 표준어
        - 빈 셀, 주석(#, **) 무시
        """
        try:
            # csv_path가 None이면 스킵
            if self.csv_path is None:
                logger.debug("동의어 사전 경로 미설정")
                return

            path = Path(self.csv_path)
            if not path.exists():
                logger.warning(f"동의어 사전 파일 없음: {self.csv_path}")
                return

            with open(path, encoding="utf-8") as f:
                reader = csv.reader(f)

                for _row_num, row in enumerate(reader, 1):
                    # 빈 행 또는 주석 행 스킵
                    if not row or all(not cell.strip() for cell in row):
                        continue

                    # 첫 번째 셀이 주석(#, **)으로 시작하면 스킵
                    first_cell = row[0].strip()
                    if first_cell.startswith("#") or first_cell.startswith("**"):
                        continue

                    # 유효한 단어만 추출 (빈 셀, 특수문자 제외)
                    words = []
                    for cell in row:
                        word = self._normalize(cell)
                        if word and not word.startswith("**") and not word.startswith("-"):
                            words.append(word)

                    if len(words) >= 1:
                        # 첫 번째 단어가 표준어
                        standard = words[0]
                        self.synonym_groups[standard] = words

                        # 역방향 맵 구축
                        for word in words:
                            self.reverse_map[word] = standard

            logger.info(
                f"동의어 사전 로드 완료: {len(self.synonym_groups)}개 그룹, "
                f"{len(self.reverse_map)}개 단어"
            )

        except Exception as e:
            logger.error(f"동의어 사전 로드 실패: {e}")

    def _normalize(self, text: str) -> str:
        """
        텍스트 정규화

        - 앞뒤 공백 제거
        - 연속 공백을 단일 공백으로
        - 소문자 변환 (한글은 그대로)
        """
        if not text:
            return ""

        # 앞뒤 공백 제거
        text = text.strip()

        # 연속 공백 정리
        text = re.sub(r"\s+", " ", text)

        return text

    def expand_query(self, query: str) -> str:
        """
        쿼리에 포함된 동의어를 표준어로 변환

        동의어가 발견되면 표준어로 대체합니다.
        예: "단축어 표현" → "표준어 표현"

        Args:
            query: 원본 쿼리

        Returns:
            표준어로 변환된 쿼리
        """
        if not self.enabled or not query:
            return query

        words = query.split()
        expanded_words = []

        for word in words:
            normalized = self._normalize(word)

            # 역방향 맵에서 표준어 찾기
            if normalized in self.reverse_map:
                standard = self.reverse_map[normalized]
                if standard != normalized:
                    logger.debug(f"동의어 변환: {normalized} → {standard}")
                expanded_words.append(standard)
            else:
                expanded_words.append(word)

        return " ".join(expanded_words)

    def get_all_variants(self, term: str) -> list[str]:
        """
        특정 용어의 모든 동의어 반환

        Args:
            term: 검색할 용어 (표준어 또는 동의어)

        Returns:
            모든 동의어 리스트 (표준어 포함)
            용어가 사전에 없으면 [term] 반환
        """
        normalized = self._normalize(term)

        # 표준어인 경우
        if normalized in self.synonym_groups:
            return self.synonym_groups[normalized].copy()

        # 동의어인 경우 → 표준어 찾아서 그룹 반환
        if normalized in self.reverse_map:
            standard = self.reverse_map[normalized]
            return self.synonym_groups.get(standard, [normalized]).copy()

        # 사전에 없는 경우
        return [term]

    def get_standard_form(self, term: str) -> str:
        """
        용어의 표준어 형태 반환

        Args:
            term: 변환할 용어

        Returns:
            표준어 (사전에 없으면 원본 반환)
        """
        normalized = self._normalize(term)
        return self.reverse_map.get(normalized, term)

    def is_synonym(self, term1: str, term2: str) -> bool:
        """
        두 용어가 동의어인지 확인

        Args:
            term1: 첫 번째 용어
            term2: 두 번째 용어

        Returns:
            동의어 여부
        """
        standard1 = self.get_standard_form(term1)
        standard2 = self.get_standard_form(term2)
        return standard1 == standard2

    def reload(self) -> None:
        """동의어 사전 다시 로드"""
        self.synonym_groups.clear()
        self.reverse_map.clear()
        self._load_synonyms()

    @property
    def stats(self) -> dict:
        """동의어 사전 통계 반환"""
        return {
            "총_그룹_수": len(self.synonym_groups),
            "총_단어_수": len(self.reverse_map),
            "평균_그룹_크기": (
                sum(len(v) for v in self.synonym_groups.values()) / len(self.synonym_groups)
                if self.synonym_groups
                else 0
            ),
        }
