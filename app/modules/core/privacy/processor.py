"""
PII 처리 Facade (PIIProcessor)

모든 PII 처리 시나리오를 하나의 인터페이스로 통합하는 Facade 패턴 구현.

처리 모드:
- "answer": RAG 답변 마스킹 (실시간, 경량)
- "document": 배치 문서 전처리 (전체 파이프라인)
- "filename": 파일명 마스킹 (API 응답용)

사용 예시:
    >>> processor = PIIProcessor()
    >>> result = processor.process("이름: 김철수 고객님", mode="answer")
    >>> print(result.masked_text)  # "이름: 김** 고객님"

생성일: 2025-12-08 (PII 모듈 통합)
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any

from .masker import MaskingResult, PrivacyMasker
from .whitelist import WhitelistManager, get_whitelist_manager

if TYPE_CHECKING:
    from collections.abc import Sequence

    from .review.processor import PIIReviewProcessor, ProcessResult

logger = logging.getLogger(__name__)


class ProcessMode(Enum):
    """PII 처리 모드"""

    ANSWER = "answer"  # RAG 답변 마스킹 (실시간, 경량)
    DOCUMENT = "document"  # 배치 문서 전처리 (전체 파이프라인)
    FILENAME = "filename"  # 파일명 마스킹 (API 응답용)


@dataclass
class PIIProcessResult:
    """
    PII 처리 결과 (통합)

    모든 처리 모드에서 일관된 결과 형식을 제공합니다.

    Attributes:
        original_text: 원본 텍스트
        masked_text: 마스킹된 텍스트
        mode: 처리 모드
        phone_masked_count: 마스킹된 전화번호 수
        name_masked_count: 마스킹된 이름 수
        total_masked_count: 총 마스킹 수
        contains_pii: PII 포함 여부
        processing_time_ms: 처리 시간 (밀리초)
        metadata: 추가 메타데이터
    """

    original_text: str
    masked_text: str
    mode: ProcessMode
    phone_masked_count: int = 0
    name_masked_count: int = 0
    total_masked_count: int = 0
    contains_pii: bool = False
    processing_time_ms: float = 0.0
    metadata: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        """딕셔너리 변환"""
        return {
            "mode": self.mode.value,
            "phone_masked_count": self.phone_masked_count,
            "name_masked_count": self.name_masked_count,
            "total_masked_count": self.total_masked_count,
            "contains_pii": self.contains_pii,
            "processing_time_ms": self.processing_time_ms,
            "metadata": self.metadata or {},
        }


class PIIProcessor:
    """
    PII 처리 Facade

    모든 PII 처리 시나리오를 하나의 간단한 인터페이스로 제공합니다.
    v3.3.0: review/ 패키지와 통합되어 고도화된 문서 검토 기능 제공.

    호텔 컨시어지 비유:
    - 고객(호출 코드)은 컨시어지(PIIProcessor)에게 요청만 하면 됨
    - 내부에서 적절한 부서(masker, review_processor)를 알아서 조율
    - 고객은 복잡한 내부 구조를 알 필요 없음
    """

    def __init__(
        self,
        whitelist_manager: WhitelistManager | None = None,
        review_processor: PIIReviewProcessor | None = None,
        mask_phone: bool = True,
        mask_name: bool = True,
        mask_email: bool = False,
        phone_mask_char: str = "*",
        name_mask_char: str = "*",
    ):
        """
        Args:
            whitelist_manager: 화이트리스트 관리자 (None이면 기본 인스턴스 사용)
            review_processor: 고도화된 PII 검토 프로세서 (Phase 7+)
            mask_phone: 전화번호 마스킹 여부
            mask_name: 이름 마스킹 여부
            mask_email: 이메일 마스킹 여부
            phone_mask_char: 전화번호 마스킹 문자
            name_mask_char: 이름 마스킹 문자
        """
        # 화이트리스트 관리자 (DI 또는 싱글톤)
        self._whitelist_manager = whitelist_manager or get_whitelist_manager()

        # 고도화된 검토 프로세서 (선택적)
        self._review_processor = review_processor

        # 설정 저장
        self._mask_phone = mask_phone
        self._mask_name = mask_name
        self._mask_email = mask_email
        self._phone_mask_char = phone_mask_char
        self._name_mask_char = name_mask_char

        # 내부 컴포넌트 (지연 초기화)
        self._masker: PrivacyMasker | None = None

        logger.info(
            f"PIIProcessor 초기화: phone={mask_phone}, name={mask_name}, "
            f"email={mask_email}, review_enabled={review_processor is not None}, "
            f"whitelist_size={len(self._whitelist_manager)}"
        )

    @property
    def masker(self) -> PrivacyMasker:
        """
        PrivacyMasker 인스턴스 (지연 초기화)

        화이트리스트가 변경되어도 항상 최신 상태 반영
        """
        if self._masker is None:
            self._masker = PrivacyMasker(
                mask_phone=self._mask_phone,
                mask_name=self._mask_name,
                mask_email=self._mask_email,
                phone_mask_char=self._phone_mask_char,
                name_mask_char=self._name_mask_char,
                whitelist=list(self._whitelist_manager.words),
            )
        return self._masker

    @property
    def whitelist_manager(self) -> WhitelistManager:
        """화이트리스트 관리자 접근"""
        return self._whitelist_manager

    async def process_async(
        self,
        text: str,
        mode: str | ProcessMode = ProcessMode.ANSWER,
        document_id: str = "",
        source_file: str = "",
    ) -> PIIProcessResult:
        """
        비동기 PII 처리 (비동기 리소스가 필요한 모드 지원)

        Args:
            text: 처리할 텍스트
            mode: 처리 모드
            document_id: 문서 ID (DOCUMENT 모드용)
            source_file: 소스 파일명 (감사용)

        Returns:
            PIIProcessResult: 처리 결과
        """
        start_time = time.perf_counter()

        # 문자열 → Enum 변환
        if isinstance(mode, str):
            try:
                mode = ProcessMode(mode)
            except ValueError:
                mode = ProcessMode.ANSWER

        # DOCUMENT 모드이고 review_processor가 있으면 고도화된 로직 실행
        if mode == ProcessMode.DOCUMENT and self._review_processor:
            result = await self._process_document_advanced(text, document_id, source_file)
        else:
            # 나머지는 동기 로직 래핑
            result = self.process(text, mode)

        elapsed_ms = (time.perf_counter() - start_time) * 1000
        result.processing_time_ms = elapsed_ms
        return result

    def process(
        self,
        text: str,
        mode: str | ProcessMode = ProcessMode.ANSWER,
    ) -> PIIProcessResult:
        """
        동기 PII 처리 (실시간 답변용)

        주의: DOCUMENT 모드에서 고도화된 기능을 사용하려면 process_async를 권장합니다.
        """
        start_time = time.perf_counter()

        # 문자열 → Enum 변환
        if isinstance(mode, str):
            try:
                mode = ProcessMode(mode)
            except ValueError:
                mode = ProcessMode.ANSWER

        # 모드별 처리
        if mode == ProcessMode.ANSWER:
            result = self._process_answer(text)
        elif mode == ProcessMode.DOCUMENT:
            # review_processor가 있어도 동기 호출에서는 기본 마스킹만 수행
            result = self._process_answer(text)
            result.mode = ProcessMode.DOCUMENT
        elif mode == ProcessMode.FILENAME:
            result = self._process_filename(text)
        else:
            result = self._process_answer(text)

        # 처리 시간 기록
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        result.processing_time_ms = elapsed_ms

        return result

    def _process_answer(self, text: str) -> PIIProcessResult:
        """
        RAG 답변 마스킹 처리 (경량, 빠름)
        """
        if not text:
            return PIIProcessResult(
                original_text=text,
                masked_text=text,
                mode=ProcessMode.ANSWER,
            )

        # 상세 마스킹 결과 획득
        masking_result: MaskingResult = self.masker.mask_text_detailed(text)

        return PIIProcessResult(
            original_text=masking_result.original,
            masked_text=masking_result.masked,
            mode=ProcessMode.ANSWER,
            phone_masked_count=masking_result.phone_count,
            name_masked_count=masking_result.name_count,
            total_masked_count=masking_result.total_masked,
            contains_pii=masking_result.total_masked > 0,
        )

    async def _process_document_advanced(
        self, text: str, document_id: str, source_file: str
    ) -> PIIProcessResult:
        """
        고도화된 문서 검토 (review/ 패키지 연동)
        """
        if not self._review_processor:
            return self._process_answer(text)

        # review_processor 실행
        review_result: ProcessResult = await self._review_processor.process_text(
            text=text,
            document_id=document_id,
            source_file=source_file
        )

        masked_text = review_result.processed_content or "[정책에 의해 차단됨]"

        return PIIProcessResult(
            original_text=text,
            masked_text=masked_text,
            mode=ProcessMode.DOCUMENT,
            total_masked_count=review_result.entities_masked,
            contains_pii=review_result.entities_detected > 0,
            metadata={
                "audit_id": review_result.audit_id,
                "action": review_result.action_taken.value,
                "requires_review": review_result.requires_review,
                "entities_detected": review_result.entities_detected
            }
        )

    def _process_filename(self, text: str) -> PIIProcessResult:
        """
        파일명 마스킹 처리 (API 응답용)

        - "홍길동 고객님.txt" → "고객_고객님.txt"
        - "이영희 담당자님.txt" → "고객_담당자님.txt"
        """
        if not text:
            return PIIProcessResult(
                original_text=text,
                masked_text=text,
                mode=ProcessMode.FILENAME,
            )

        masked = self.masker.mask_filename(text)
        was_masked = masked != text

        return PIIProcessResult(
            original_text=text,
            masked_text=masked,
            mode=ProcessMode.FILENAME,
            name_masked_count=1 if was_masked else 0,
            total_masked_count=1 if was_masked else 0,
            contains_pii=was_masked,
        )

    def process_batch(
        self,
        texts: Sequence[str],
        mode: str | ProcessMode = ProcessMode.ANSWER,
    ) -> list[PIIProcessResult]:
        """
        여러 텍스트 일괄 처리

        Args:
            texts: 처리할 텍스트 목록
            mode: 처리 모드

        Returns:
            처리 결과 목록
        """
        return [self.process(text, mode) for text in texts]

    def mask_sources_filenames(self, sources: list[dict]) -> list[dict]:
        """
        RAG sources 배열의 파일명 마스킹

        기존 PrivacyMasker.mask_sources_filenames()와 동일한 인터페이스 제공.

        Args:
            sources: RAG 파이프라인 sources 배열

        Returns:
            파일명이 마스킹된 sources 배열
        """
        return self.masker.mask_sources_filenames(sources)

    def contains_pii(self, text: str) -> bool:
        """
        텍스트에 PII 포함 여부 확인 (마스킹 없이)

        Args:
            text: 확인할 텍스트

        Returns:
            PII 포함 여부
        """
        return self.masker.contains_pii(text)

    def update_whitelist(self, words: Sequence[str]) -> None:
        """
        화이트리스트에 단어 추가

        Args:
            words: 추가할 단어 목록
        """
        self._whitelist_manager.add_words(words)
        # masker 인스턴스 갱신 필요
        self._masker = None

    def reload_whitelist(self) -> bool:
        """
        설정 파일에서 화이트리스트 다시 로드

        Returns:
            로드 성공 여부
        """
        result = self._whitelist_manager.reload()
        # masker 인스턴스 갱신 필요
        self._masker = None
        return result


# ========================================
# 편의 함수 (싱글톤 사용)
# ========================================
_default_processor: PIIProcessor | None = None


def get_pii_processor() -> PIIProcessor:
    """
    기본 PIIProcessor 싱글톤 인스턴스 반환

    DI Container를 사용하지 않는 경우 편의 함수로 사용.

    Returns:
        PIIProcessor 싱글톤 인스턴스
    """
    global _default_processor
    if _default_processor is None:
        _default_processor = PIIProcessor()
    return _default_processor


def reset_pii_processor() -> None:
    """
    싱글톤 인스턴스 리셋 (테스트용)
    """
    global _default_processor
    _default_processor = None


def process_pii(text: str, mode: str = "answer") -> PIIProcessResult:
    """
    PII 처리 편의 함수

    Args:
        text: 처리할 텍스트
        mode: 처리 모드 ("answer", "document", "filename")

    Returns:
        처리 결과
    """
    return get_pii_processor().process(text, mode)
