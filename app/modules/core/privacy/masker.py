"""
개인정보 마스킹 모듈 (PrivacyMasker)

답변에서 민감한 개인정보를 자동으로 마스킹:
- 개인 전화번호: 010-XXXX-XXXX → 010-****-5678 (뒤 4자리만 노출)
- 한글 이름: 홍길동 고객 → 홍** 고객 (성만 노출)

비마스킹 대상:
- 사업자 전화번호: 02-XXX-XXXX, 031-XXX-XXXX 등 (기관/사업자 문의처)
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


# ========================================
# 기본 PII 정규식 패턴 (대한민국 식별자 형식)
# ========================================
# 보안 정책: 이 값들은 config 미설정 시 사용되는 "국가 default"입니다.
# 운영자는 privacy.yaml의 patterns 섹션으로 타 국가 패턴을 추가/교체할 수 있으나,
# config가 없으면 아래 한국 기본 패턴이 byte-identical 하게 적용됩니다(회귀 0).
# 키를 추가/변경할 때는 보안 회귀가 없도록 반드시 기존 동작을 보존해야 합니다.
DEFAULT_PII_PATTERNS: dict[str, str] = {
    # 개인 전화번호 패턴 (010 시작): 010-1234-5678, 01012345678, 010 1234 5678
    "phone_personal": r"010[-\s]?\d{4}[-\s]?\d{4}",
    # 사업자 전화번호 패턴 (지역번호 시작 - 마스킹 제외용): 02-XXX-XXXX, 031-XXX-XXXX 등
    "phone_business": r"(02|0[3-6][1-5])[-\s]?\d{3,4}[-\s]?\d{4}",
    # 주민등록번호 패턴 (6자리 생년월일-성별코드+6자리)
    "ssn": r"\d{6}[-\s]?[1-4]\d{6}",
    # 여권번호 패턴 (대문자 1자리 + 숫자 8자리): M12345678, S87654321 등
    "passport": r"(?<![a-zA-Z])[A-Z]\d{8}(?!\d)",
    # 운전면허번호 패턴 (XX-XX-XXXXXX-XX): 지역코드(2)-년도(2)-일련번호(6)-검증(2)
    "driver_license": r"\d{2}-\d{2}-\d{6}-\d{2}",
    # 이메일 패턴 (선택적 마스킹)
    "email": r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
}

# 이름 글자 클래스 기본값 (한글 음절 범위)
# 타 언어 이름 마스킹이 필요하면 config(name_char_class)로 교체합니다.
DEFAULT_NAME_CHAR_CLASS: str = "[가-힣]"

# 파일명 마스킹 치환 라벨 기본값 (한국어 "고객")
# 운영자는 config(filename_mask_label)로 라벨을 교체할 수 있습니다.
DEFAULT_FILENAME_MASK_LABEL: str = "고객"

# 이름 마스킹용 호칭(suffix) 기본값 (mask_text/contains_pii 경로)
# di_container에서는 domain.yaml의 name_suffixes를 주입하지만,
# name_suffixes 미주입 시 아래 한국어 기본 호칭으로 패턴을 구성합니다(회귀 0).
DEFAULT_NAME_SUFFIXES: list[str] = ["고객님", "관리자님?", "담당자님?"]

# 파일명 마스킹용 호칭(suffix) 기본값 (mask_filename 경로)
# 기존 코드의 파일명 기본 패턴은 "고객님?"(님 선택적)만 매칭했다.
# 즉 "고객님"과 "고객" 모두 매칭하므로 회귀 0을 위해 그대로 보존한다.
# name_suffixes가 주입되면 그 목록을 파일명 패턴에도 동일 적용한다.
DEFAULT_FILENAME_NAME_SUFFIXES: list[str] = ["고객님?"]


@dataclass
class MaskingResult:
    """마스킹 결과"""

    original: str
    masked: str
    phone_count: int
    name_count: int
    ssn_count: int = 0
    passport_count: int = 0
    driver_license_count: int = 0

    @property
    def total_masked(self) -> int:
        return (
            self.phone_count
            + self.name_count
            + self.ssn_count
            + self.passport_count
            + self.driver_license_count
        )


class PrivacyMasker:
    """
    개인정보 마스킹 모듈

    RAG 답변에서 민감한 개인정보를 자동으로 탐지하고 마스킹합니다.

    정규식 패턴은 인스턴스 초기화 시 결정됩니다. config(``patterns`` 인자)를
    주입하지 않으면 ``DEFAULT_PII_PATTERNS`` 등 한국 기본 패턴이 그대로
    적용되어 기존 동작과 byte-identical 합니다(보안 회귀 0).
    """

    def __init__(
        self,
        mask_phone: bool = True,
        mask_name: bool = True,
        mask_email: bool = False,
        mask_ssn: bool = True,
        mask_passport: bool = True,
        mask_driver_license: bool = True,
        phone_mask_char: str = "*",
        name_mask_char: str = "*",
        whitelist: Sequence[str] | None = None,
        name_suffixes: list[str] | None = None,
        patterns: dict[str, str] | None = None,
        name_char_class: str | None = None,
        filename_mask_label: str | None = None,
    ):
        """
        Args:
            mask_phone: 개인 전화번호 마스킹 여부
            mask_name: 이름 마스킹 여부
            mask_email: 이메일 마스킹 여부 (기본 비활성화)
            mask_ssn: 주민등록번호 마스킹 여부 (기본 활성화)
            mask_passport: 여권번호 마스킹 여부 (기본 활성화)
            mask_driver_license: 운전면허번호 마스킹 여부 (기본 활성화)
            phone_mask_char: 전화번호 마스킹 문자
            name_mask_char: 이름 마스킹 문자
            whitelist: 마스킹 예외 단어 목록 (None이면 기본값 사용)
            name_suffixes: 이름 뒤에 붙는 호칭 패턴 목록 (예: ["고객님", "담당자님"])
                None이면 ``DEFAULT_NAME_SUFFIXES``(한국어 기본 호칭) 사용.
            patterns: PII 정규식 패턴 오버라이드. 키는 ``DEFAULT_PII_PATTERNS``와
                동일(phone_personal/phone_business/ssn/passport/driver_license/email).
                None이거나 일부 키만 주면 누락 키는 한국 기본 패턴으로 폴백합니다.
                보안 정책상 미설정 시 기본 마스킹 동작이 약화되지 않습니다.
            name_char_class: 이름 글자 클래스 정규식 (기본 ``[가-힣]``).
                타 언어 이름 마스킹이 필요할 때 config로 교체합니다.
            filename_mask_label: 파일명 마스킹 치환 라벨 (기본 "고객").
        """
        # None 방어: 설정 누락(yaml import 누락 등)으로 None이 주입돼도
        # 안전한 기본값으로 보정한다. 특히 phone_mask_char가 None이면
        # SSN 마스킹의 `char * 7` 연산에서 TypeError가 발생한다.
        self.mask_phone = True if mask_phone is None else mask_phone
        self.mask_name = True if mask_name is None else mask_name
        self.mask_email = False if mask_email is None else mask_email
        self.mask_ssn = True if mask_ssn is None else mask_ssn
        self.mask_passport = True if mask_passport is None else mask_passport
        self.mask_driver_license = (
            True if mask_driver_license is None else mask_driver_license
        )
        self.phone_mask_char = phone_mask_char if phone_mask_char else "*"
        self.name_mask_char = name_mask_char if name_mask_char else "*"

        # 화이트리스트 설정 (설정 파일 또는 기본값)
        if whitelist is not None:
            self._whitelist: frozenset[str] = frozenset(whitelist)
        else:
            self._whitelist = DEFAULT_WHITELIST

        # ----------------------------------------
        # PII 정규식 패턴 결정 (config 오버라이드 + 한국 기본 폴백)
        # ----------------------------------------
        # 누락 키는 DEFAULT_PII_PATTERNS로 폴백하여 보안 회귀를 차단한다.
        resolved_patterns = dict(DEFAULT_PII_PATTERNS)
        if patterns:
            for key, value in patterns.items():
                # 빈 문자열/None 값은 무시(기본 패턴 유지)하여 마스킹 약화 방지
                if value:
                    resolved_patterns[key] = value

        # 컴파일된 정규식 패턴 (인스턴스 속성)
        self.PERSONAL_PHONE_PATTERN = re.compile(resolved_patterns["phone_personal"])
        self.BUSINESS_PHONE_PATTERN = re.compile(resolved_patterns["phone_business"])
        self.SSN_PATTERN = re.compile(resolved_patterns["ssn"])
        self.PASSPORT_PATTERN = re.compile(resolved_patterns["passport"])
        self.DRIVER_LICENSE_PATTERN = re.compile(resolved_patterns["driver_license"])
        self.EMAIL_PATTERN = re.compile(resolved_patterns["email"])

        # ----------------------------------------
        # 이름/파일명 패턴 결정 (글자 클래스 + 호칭 config 외부화)
        # ----------------------------------------
        # 이름 글자 클래스 (기본 한글 음절 [가-힣], config로 교체 가능)
        char_class = name_char_class if name_char_class else DEFAULT_NAME_CHAR_CLASS

        # 파일명 마스킹 치환 라벨 (기본 "고객", config로 교체 가능)
        self._filename_mask_label = (
            filename_mask_label if filename_mask_label else DEFAULT_FILENAME_MASK_LABEL
        )

        # 이름 뒤 호칭(suffix) 결정 (config 미주입 시 한국어 기본 호칭)
        # 회귀 0: name_suffixes 미주입 시 기존처럼
        #   - mask_text 경로는 3종 호칭(고객님/관리자님?/담당자님?)
        #   - mask_filename 경로는 "고객님" 단일 호칭
        # 의 비대칭 기본값을 그대로 유지한다.
        # name_suffixes 주입 시에는 두 경로 모두 동일 목록을 적용한다.
        if name_suffixes:
            name_suffixes_list = name_suffixes
            filename_suffixes_list = name_suffixes
        else:
            name_suffixes_list = DEFAULT_NAME_SUFFIXES
            filename_suffixes_list = DEFAULT_FILENAME_NAME_SUFFIXES

        name_suffixes_pattern = "|".join(name_suffixes_list)
        filename_suffixes_pattern = "|".join(filename_suffixes_list)

        # 이름/파일명 정규식 동적 생성
        # 주의: f-string 안에서 정규식 수량자 {2,4}를 그대로 쓰면 format 치환으로
        # 해석되어 패턴이 깨진다(기존 버그). 문자열 연결로 안전하게 구성한다.
        self.KOREAN_NAME_PATTERN = re.compile(
            "(" + char_class + r"{2,4})(?=\s*(" + name_suffixes_pattern + "))"
        )
        self.FILENAME_PII_PATTERN = re.compile(
            "(" + char_class + r"{2,4})\s*(" + filename_suffixes_pattern + ")"
        )

        logger.info(
            f"PrivacyMasker 초기화: phone={mask_phone}, name={mask_name}, "
            f"email={mask_email}, ssn={mask_ssn}, passport={mask_passport}, "
            f"driver_license={mask_driver_license}, "
            f"whitelist_size={len(self._whitelist)}, suffixes={name_suffixes_list}, "
            f"patterns_overridden={bool(patterns)}, "
            f"name_char_class={'custom' if name_char_class else 'default'}"
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

        # 2. 여권번호 마스킹
        if self.mask_passport:
            result = self._mask_passport(result)

        # 3. 운전면허번호 마스킹
        if self.mask_driver_license:
            result = self._mask_driver_license(result)

        # 4. 개인 전화번호 마스킹 (사업자 전화번호 제외)
        if self.mask_phone:
            result = self._mask_personal_phone(result)

        # 5. 이름 마스킹 (설정된 호칭 기반)
        if self.mask_name:
            result = self._mask_names(result)

        # 6. 이메일 마스킹 (선택적)
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
            return MaskingResult(
                original=text, masked=text, phone_count=0, name_count=0,
                ssn_count=0, passport_count=0, driver_license_count=0,
            )

        phone_count = 0
        name_count = 0
        ssn_count = 0
        passport_count = 0
        driver_license_count = 0
        result = text

        # 1. 주민등록번호 마스킹 (최우선)
        if self.mask_ssn:
            ssn_count = len(self.SSN_PATTERN.findall(result))
            result = self._mask_ssn(result)

        # 2. 여권번호 마스킹
        if self.mask_passport:
            passport_count = len(self.PASSPORT_PATTERN.findall(result))
            result = self._mask_passport(result)

        # 3. 운전면허번호 마스킹
        if self.mask_driver_license:
            driver_license_count = len(self.DRIVER_LICENSE_PATTERN.findall(result))
            result = self._mask_driver_license(result)

        # 4. 개인 전화번호 마스킹
        if self.mask_phone:
            matches = self.PERSONAL_PHONE_PATTERN.findall(result)
            # 사업자 전화번호 제외
            personal_phones = [m for m in matches if not self._is_business_phone(m)]
            phone_count = len(personal_phones)
            result = self._mask_personal_phone(result)

        # 5. 이름 마스킹
        if self.mask_name:
            matches = self.KOREAN_NAME_PATTERN.findall(result)
            name_count = len(matches)
            result = self._mask_names(result)

        total = phone_count + name_count + ssn_count + passport_count + driver_license_count
        if total > 0:
            logger.info(
                f"개인정보 마스킹 완료: 주민등록번호 {ssn_count}개, 여권 {passport_count}개, "
                f"면허 {driver_license_count}개, 전화번호 {phone_count}개, 이름 {name_count}개"
            )

        return MaskingResult(
            original=text, masked=result, phone_count=phone_count,
            name_count=name_count, ssn_count=ssn_count,
            passport_count=passport_count, driver_license_count=driver_license_count,
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

    def _mask_passport(self, text: str) -> str:
        """
        여권번호 마스킹

        M12345678 → M********
        영문자 유지, 숫자 8자리 마스킹
        """

        def replace(match: re.Match[str]) -> str:
            passport: str = match.group()
            # 앞 영문자 유지, 숫자 부분 마스킹
            return passport[0] + self.phone_mask_char * 8

        return self.PASSPORT_PATTERN.sub(replace, text)

    def _mask_driver_license(self, text: str) -> str:
        """
        운전면허번호 마스킹

        13-05-123456-78 → 13-**-******-**
        지역코드(앞 2자리) 유지, 나머지 마스킹
        """

        def replace(match: re.Match[str]) -> str:
            dl: str = match.group()
            parts = dl.split("-")
            # 지역코드 유지, 나머지 마스킹
            return (
                f"{parts[0]}-{self.phone_mask_char * 2}"
                f"-{self.phone_mask_char * 6}-{self.phone_mask_char * 2}"
            )

        return self.DRIVER_LICENSE_PATTERN.sub(replace, text)

    def _mask_personal_phone(self, text: str) -> str:
        """
        개인 전화번호 마스킹

        010-1234-5678 → 010-****-5678
        01012345678 → 010****5678
        """

        def replace(match: re.Match[str]) -> str:
            phone: str = match.group()

            # 사업자 전화번호는 마스킹 안 함
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
        사업자 전화번호인지 확인

        사업자 전화번호는 지역번호로 시작:
        - 02: 서울
        - 031~039: 경기 등
        - 041~049: 충청 등
        """
        # 숫자만 추출
        digits = re.sub(r"[-\s]", "", phone)

        # 010으로 시작하면 개인 전화번호
        if digits.startswith("010"):
            return False

        # 02 또는 0XX로 시작하면 사업자 전화번호
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

        # 여권번호 확인
        if self.mask_passport and self.PASSPORT_PATTERN.search(text):
            return True

        # 운전면허번호 확인
        if self.mask_driver_license and self.DRIVER_LICENSE_PATTERN.search(text):
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
    # 주: FILENAME_PII_PATTERN과 치환 라벨(_filename_mask_label)은
    # __init__에서 config 기반으로 인스턴스 속성으로 설정된다.

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
            # 라벨은 config(filename_mask_label)로 외부화, 기본값 "고객"
            return f"{self._filename_mask_label}_{suffix}"

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
