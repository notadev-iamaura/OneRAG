"""
개인정보 마스킹 모듈 (PrivacyMasker)

답변에서 민감한 개인정보를 자동으로 마스킹:
- 개인 전화번호: 010-XXXX-XXXX → 010-****-5678 (뒤 4자리만 노출)
- 한글 이름: 홍길동 고객 → 홍** 고객 (성만 노출)

비마스킹 대상:
- 업체 전화번호: 02-XXX-XXXX, 031-XXX-XXXX 등 (업체 문의처)
- 화이트리스트 단어: 담당, 고객 등 (privacy.yaml에서 관리)

Phase 2 구현 (2025-11-28)
모듈 통합 (2025-12-08): 화이트리스트 지원 추가
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

logger = logging.getLogger(__name__)


# ========================================
# 기본 화이트리스트 (설정 파일에서 오버라이드 가능)
# ========================================
DEFAULT_WHITELIST: frozenset[str] = frozenset([])


@dataclass
class MaskingResult:
    """마스킹 결과"""

    original: str
    masked: str
    phone_count: int
    name_count: int
    ssn_count: int = 0

    @property
    def total_masked(self) -> int:
        return self.phone_count + self.name_count + self.ssn_count


class PrivacyMasker:
    """
    개인정보 마스킹 모듈

    RAG 답변에서 민감한 개인정보를 자동으로 탐지하고 마스킹합니다.
    """

    # ========================================
    # 정규식 패턴
    # ========================================

    # 개인 전화번호 패턴 (010 시작)
    # 형식: 010-1234-5678, 01012345678, 010 1234 5678
    PERSONAL_PHONE_PATTERN = re.compile(r"010[-\s]?\d{4}[-\s]?\d{4}")

    # 업체 전화번호 패턴 (지역번호 시작 - 마스킹 제외용)
    # 형식: 02-XXX-XXXX, 031-XXX-XXXX 등
    BUSINESS_PHONE_PATTERN = re.compile(r"(02|0[3-6][1-5])[-\s]?\d{3,4}[-\s]?\d{4}")

    # 한글 이름 패턴 (2~4글자 + 호칭)
    # 초기화 시 name_suffixes를 기반으로 동적 생성됨
    KOREAN_NAME_PATTERN = re.compile(r"([가-힣]{2,4})(?=\s*(고객님|관리자님?|담당자님?))")

    # 주민등록번호 패턴 (6자리 생년월일-성별코드+6자리)
    SSN_PATTERN = re.compile(r"\d{6}[-\s]?[1-4]\d{6}")

    # 이메일 패턴 (선택적 마스킹)
    EMAIL_PATTERN = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")

    # 파일명에서 개인정보 패턴 (고객명 등)
    # 초기화 시 name_suffixes를 기반으로 동적 생성됨
    FILENAME_PII_PATTERN = re.compile(r"([가-힣]{2,4})\s*(고객님?|관리자님?|담당자님?)")

    def __init__(
        self,
        mask_phone: bool = True,
        mask_name: bool = True,
        mask_email: bool = False,
        mask_ssn: bool = True,
        phone_mask_char: str = "*",
        name_mask_char: str = "*",
        whitelist: Sequence[str] | None = None,
        name_suffixes: list[str] | None = None,
    ):
        """
        Args:
            mask_phone: 개인 전화번호 마스킹 여부
            mask_name: 이름 마스킹 여부
            mask_email: 이메일 마스킹 여부 (기본 비활성화)
            mask_ssn: 주민등록번호 마스킹 여부 (기본 활성화)
            phone_mask_char: 전화번호 마스킹 문자
            name_mask_char: 이름 마스킹 문자
            whitelist: 마스킹 예외 단어 목록 (None이면 기본값 사용)
            name_suffixes: 이름 뒤에 붙는 호칭 패턴 목록 (예: ["고객님", "담당자님"])
        """
        self.mask_phone = mask_phone
        self.mask_name = mask_name
        self.mask_email = mask_email
        self.mask_ssn = mask_ssn
        self.phone_mask_char = phone_mask_char
        self.name_mask_char = name_mask_char

        # 화이트리스트 설정 (설정 파일 또는 기본값)
        if whitelist is not None:
            self._whitelist: frozenset[str] = frozenset(whitelist)
        else:
            self._whitelist = DEFAULT_WHITELIST

        # 이름 패턴 동적 생성
        if name_suffixes:
            suffixes_pattern = "|".join(name_suffixes)
            self.KOREAN_NAME_PATTERN = re.compile(
                rf"([가-힣]{2,4})(?=\s*({suffixes_pattern}))"
            )
            self.FILENAME_PII_PATTERN = re.compile(
                rf"([가-힣]{2,4})\s*({suffixes_pattern})"
            )

        logger.info(
            f"PrivacyMasker 초기화: phone={mask_phone}, name={mask_name}, "
            f"email={mask_email}, ssn={mask_ssn}, whitelist_size={len(self._whitelist)}, "
            f"suffixes={name_suffixes}"
        )

    @property
    def whitelist(self) -> frozenset[str]:
        """화이트리스트 반환 (읽기 전용)"""
        return self._whitelist

    def update_whitelist(self, words: Sequence[str]) -> None:
        """
        화이트리스트에 단어 추가

        Args:
            words: 추가할 단어 목록
        """
        self._whitelist = self._whitelist | frozenset(words)
        logger.info(f"화이트리스트 업데이트: {len(words)}개 추가, 총 {len(self._whitelist)}개")

    def mask_text(self, text: str) -> str:
        """
        텍스트에서 개인정보 마스킹

        Args:
            text: 원본 텍스트

        Returns:
            마스킹된 텍스트
        """
        if not text:
            return text

        result = text

        # 1. 주민등록번호 마스킹 (최우선 - 가장 민감)
        if self.mask_ssn:
            result = self._mask_ssn(result)

        # 2. 개인 전화번호 마스킹 (업체 전화번호 제외)
        if self.mask_phone:
            result = self._mask_personal_phone(result)

        # 3. 이름 마스킹 (설정된 호칭 기반)
        if self.mask_name:
            result = self._mask_names(result)

        # 4. 이메일 마스킹 (선택적)
        if self.mask_email:
            result = self._mask_email(result)

        return result

    def mask_text_detailed(self, text: str) -> MaskingResult:
        """
        텍스트에서 개인정보 마스킹 (상세 결과 반환)

        Args:
            text: 원본 텍스트

        Returns:
            MaskingResult with counts
        """
        if not text:
            return MaskingResult(original=text, masked=text, phone_count=0, name_count=0, ssn_count=0)

        phone_count = 0
        name_count = 0
        ssn_count = 0
        result = text

        # 1. 주민등록번호 마스킹 (최우선)
        if self.mask_ssn:
            ssn_count = len(self.SSN_PATTERN.findall(result))
            result = self._mask_ssn(result)

        # 2. 개인 전화번호 마스킹
        if self.mask_phone:
            matches = self.PERSONAL_PHONE_PATTERN.findall(result)
            # 업체 전화번호 제외
            personal_phones = [m for m in matches if not self._is_business_phone(m)]
            phone_count = len(personal_phones)
            result = self._mask_personal_phone(result)

        # 3. 이름 마스킹
        if self.mask_name:
            matches = self.KOREAN_NAME_PATTERN.findall(result)
            name_count = len(matches)
            result = self._mask_names(result)

        if phone_count > 0 or name_count > 0 or ssn_count > 0:
            logger.info(
                f"개인정보 마스킹 완료: 주민등록번호 {ssn_count}개, "
                f"전화번호 {phone_count}개, 이름 {name_count}개"
            )

        return MaskingResult(
            original=text, masked=result, phone_count=phone_count,
            name_count=name_count, ssn_count=ssn_count,
        )

    def _mask_ssn(self, text: str) -> str:
        """
        주민등록번호 마스킹

        990101-1234567 → 990101-*******
        9901011234567 → 990101*******
        """

        def replace(match: re.Match[str]) -> str:
            ssn: str = match.group()
            # 하이픈/공백 유무에 따라 앞 6자리 유지, 뒤 7자리 마스킹
            if "-" in ssn:
                return ssn[:7] + self.phone_mask_char * 7
            elif " " in ssn:
                return ssn[:7] + self.phone_mask_char * 7
            else:
                return ssn[:6] + self.phone_mask_char * 7

        return self.SSN_PATTERN.sub(replace, text)

    def _mask_personal_phone(self, text: str) -> str:
        """
        개인 전화번호 마스킹

        010-1234-5678 → 010-****-5678
        01012345678 → 010****5678
        """

        def replace(match: re.Match[str]) -> str:
            phone: str = match.group()

            # 업체 전화번호는 마스킹 안 함
            if self._is_business_phone(phone):
                return phone

            # 하이픈 유무에 따라 처리
            if "-" in phone:
                parts = phone.split("-")
                if len(parts) == 3:
                    # 010-1234-5678 → 010-****-5678
                    return f"{parts[0]}-{self.phone_mask_char * 4}-{parts[2]}"
            elif " " in phone:
                parts = phone.split(" ")
                if len(parts) == 3:
                    return f"{parts[0]} {self.phone_mask_char * 4} {parts[2]}"
            else:
                # 01012345678 → 010****5678
                return phone[:3] + self.phone_mask_char * 4 + phone[-4:]

            return phone

        return self.PERSONAL_PHONE_PATTERN.sub(replace, text)

    def _mask_names(self, text: str) -> str:
        """
        이름 마스킹 (성만 노출, 화이트리스트 예외 적용)

        홍길동 고객 → 홍** 고객
        이영희 담당 → 이** 담당
        담당자 → 담당자 (화이트리스트 예외)
        관리자 → 관리자 (화이트리스트 예외)
        """

        def replace(match: re.Match[str]) -> str:
            name: str = match.group(1)  # 캡처 그룹 (이름 부분만)

            if len(name) < 2:
                return name

            # 화이트리스트 예외 처리 (오탐 방지)
            if name in self._whitelist:
                return name

            # 성(첫 글자)만 노출, 나머지 마스킹
            masked: str = name[0] + self.name_mask_char * (len(name) - 1)
            return masked

        return self.KOREAN_NAME_PATTERN.sub(replace, text)

    def _mask_email(self, text: str) -> str:
        """
        이메일 마스킹

        example@email.com → e*****e@email.com
        """

        def replace(match: re.Match) -> str:
            email = match.group()
            local, domain = email.split("@")

            if len(local) <= 2:
                masked_local = local[0] + self.phone_mask_char
            else:
                masked_local = local[0] + self.phone_mask_char * (len(local) - 2) + local[-1]

            return f"{masked_local}@{domain}"

        return self.EMAIL_PATTERN.sub(replace, text)

    def _is_business_phone(self, phone: str) -> bool:
        """
        업체 전화번호인지 확인

        업체 전화번호는 지역번호로 시작:
        - 02: 서울
        - 031~039: 경기 등
        - 041~049: 충청 등
        """
        # 숫자만 추출
        digits = re.sub(r"[-\s]", "", phone)

        # 010으로 시작하면 개인 전화번호
        if digits.startswith("010"):
            return False

        # 02 또는 0XX로 시작하면 업체 전화번호
        if digits.startswith("02") or (digits.startswith("0") and len(digits) >= 10):
            return True

        return False

    def contains_pii(self, text: str) -> bool:
        """
        텍스트에 개인정보가 포함되어 있는지 확인
        """
        if not text:
            return False

        # 주민등록번호 확인 (최우선)
        if self.SSN_PATTERN.search(text):
            return True

        # 개인 전화번호 확인
        if self.PERSONAL_PHONE_PATTERN.search(text):
            phones = self.PERSONAL_PHONE_PATTERN.findall(text)
            personal_phones = [p for p in phones if not self._is_business_phone(p)]
            if personal_phones:
                return True

        # 이름 확인
        if self.KOREAN_NAME_PATTERN.search(text):
            return True

        return False

    # ========================================
    # 파일명 마스킹 (API 응답용)
    # ========================================

    # 파일명에서 개인정보 패턴 (고객명 등)
    # 초기화 시 name_suffixes를 기반으로 동적 생성됨
    FILENAME_PII_PATTERN = re.compile(r"([가-힣]{2,4})\s*(고객님?)")

    def mask_filename(self, filename: str) -> str:
        """
        파일명에서 개인정보 마스킹

        API 응답의 sources.document 필드에서 고객명 보호를 위해 사용.

        변환 예시:
        - "홍길동 고객님.txt" → "고객_고객님.txt"
        - "이영희 담당자님.txt" → "고객_담당자님.txt"
        - "김철수 관리자님.txt" → "고객_관리자님.txt"
        - "파일제목.txt" → "파일제목.txt" (매칭 안 되면 유지)

        Args:
            filename: 원본 파일명

        Returns:
            마스킹된 파일명
        """
        if not filename:
            return filename

        # 파일명에서 이름 패턴 검색 및 마스킹
        def replace(match: re.Match[str]) -> str:
            # name = match.group(1)  # 이름 부분 (사용 안 함)
            suffix = match.group(2)  # 고객님, 담당자님 등

            # "고객_고객님", "고객_담당자님" 형태로 변환
            return f"고객_{suffix}"

        masked = self.FILENAME_PII_PATTERN.sub(replace, filename)

        # 마스킹이 적용되었는지 로그
        if masked != filename:
            logger.debug(f"파일명 마스킹: {filename} → {masked}")

        return masked

    def mask_sources_filenames(self, sources: list[dict]) -> list[dict]:
        """
        sources 배열의 모든 파일명 마스킹

        Args:
            sources: RAG 파이프라인 sources 배열

        Returns:
            파일명이 마스킹된 sources 배열
        """
        masked_sources = []
        masked_count = 0

        for source in sources:
            masked_source = source.copy()

            # document 필드 마스킹
            if "document" in masked_source and masked_source["document"]:
                original = masked_source["document"]
                masked_source["document"] = self.mask_filename(original)
                if masked_source["document"] != original:
                    masked_count += 1

            # file_path 필드 마스킹 (메타데이터)
            if "file_path" in masked_source and masked_source["file_path"]:
                # 파일 경로는 전체를 마스킹하지 않고 파일명 부분만 마스킹
                import os

                dir_path = os.path.dirname(masked_source["file_path"])
                file_name = os.path.basename(masked_source["file_path"])
                masked_name = self.mask_filename(file_name)
                masked_source["file_path"] = (
                    os.path.join(dir_path, masked_name) if dir_path else masked_name
                )

            masked_sources.append(masked_source)

        if masked_count > 0:
            logger.info(f"파일명 마스킹 완료: {masked_count}개 소스")

        return masked_sources
