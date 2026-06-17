"""
PII 검토 프로세서 (PIIReviewProcessor)

문서 전처리 파이프라인에 통합되어 PII를 탐지, 평가, 처리, 기록하는 핵심 컴포넌트.
Decorator 패턴으로 기존 파이프라인에 비침투적 통합 가능.

구현일: 2025-12-01
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Protocol

from .audit import PIIAuditLogger
from .detector import HybridPIIDetector
from .models import (
    PIIEntity,
    PIIType,
    PolicyAction,
    ProcessResult,
)
from .policy import PIIPolicyEngine

logger = logging.getLogger(__name__)


class PIIReviewError(Exception):
    """PII 검토 중 발생한 오류"""

    pass


class PIIViolationError(PIIReviewError):
    """PII 정책 위반 오류 (처리 차단)"""

    pass


@dataclass
class Document:
    """처리 대상 문서 (간소화된 모델)"""

    id: str
    content: str
    metadata: dict[str, Any]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Document:
        """딕셔너리에서 생성"""
        return cls(
            id=data.get("id", ""),
            content=data.get("content", ""),
            metadata=data.get("metadata", {}),
        )


class DocumentProcessorProtocol(Protocol):
    """문서 프로세서 프로토콜 (기존 프로세서 인터페이스)"""

    async def process(self, document: Document) -> Document:
        """문서 처리"""
        ...


class PIIReviewProcessor:
    """
    PII 검토 프로세서

    문서 전처리 파이프라인에 통합되어:
    1. PII 탐지 (HybridPIIDetector)
    2. 정책 평가 (PIIPolicyEngine)
    3. 마스킹 처리
    4. 감사 로그 기록 (PIIAuditLogger)

    사용 예시:
        processor = PIIReviewProcessor(detector, policy_engine, audit_logger)
        result = await processor.process(document)
        if result.is_blocked:
            # 처리 차단됨
            ...
    """

    # ========================================
    # 기본 마스크 템플릿 (코드 기본값 = 한국어 라벨)
    # ========================================
    # 범용화 정책: 아래 상수는 "기본값"이며, __init__의 mask_templates 인자로
    # 키별 오버라이드만 가능하다. 미설정 키는 이 기본값으로 폴백하므로
    # 설정을 비우거나 일부만 채워도 마스킹 라벨이 누락되지 않는다(회귀 0).
    # 치환 라벨은 처리된 문서 본문에 남아 출력에 노출되므로, 비한국어 운영자는
    # privacy.yaml review.mask_templates로 자국어 라벨([Phone]/[SSN] 등)을 코드
    # 포크 없이 주입한다. UNKNOWN 키 값은 미정의 PIIType의 폴백 라벨로도 쓰인다.
    DEFAULT_MASK_TEMPLATES: dict[PIIType, str] = {
        PIIType.PHONE: "[전화번호]",
        PIIType.EMAIL: "[이메일]",
        PIIType.SSN: "[주민등록번호]",
        PIIType.ACCOUNT: "[계좌번호]",
        PIIType.CARD: "[카드번호]",
        PIIType.PERSON_NAME: "[이름]",
        PIIType.ADDRESS: "[주소]",
        PIIType.ORGANIZATION: "[기관명]",
        PIIType.UNKNOWN: "[개인정보]",
    }

    def __init__(
        self,
        detector: HybridPIIDetector,
        policy_engine: PIIPolicyEngine,
        audit_logger: PIIAuditLogger,
        enabled: bool = True,
        mask_templates: dict[str, str] | dict[PIIType, str] | None = None,
    ):
        """
        Args:
            detector: PII 탐지기
            policy_engine: 정책 엔진
            audit_logger: 감사 로거
            enabled: PII 검토 활성화 여부
            mask_templates: PII 유형별 마스킹 라벨 오버라이드(선택). 키별로
                자국어/도메인 라벨을 주입한다. 키는 PIIType 또는 그 문자열값
                ("phone"/"email"/"ssn"/"account"/"card"/"person_name"/"address"
                /"organization"/"unknown")을 허용한다(yaml은 문자열).
                미설정/빈 dict면 클래스 DEFAULT_MASK_TEMPLATES(한국어)로 폴백하고,
                일부 키만 주면 나머지 키는 기본값으로 폴백한다(회귀 0).
        """
        self.detector = detector
        self.policy_engine = policy_engine
        self.audit_logger = audit_logger
        self._enabled = enabled

        # 마스크 템플릿: 한국어 기본값 위에 config 오버라이드를 병합한다.
        # yaml은 PIIType 값을 문자열로 전달하므로 PIIType 인스턴스로 정규화하고,
        # 미설정 키는 DEFAULT_MASK_TEMPLATES로 폴백한다(회귀 0).
        self.MASK_TEMPLATES: dict[PIIType, str] = dict(self.DEFAULT_MASK_TEMPLATES)
        if mask_templates:
            for key, label in mask_templates.items():
                pii_type = key if isinstance(key, PIIType) else PIIType(key)
                self.MASK_TEMPLATES[pii_type] = label

        logger.info(f"PIIReviewProcessor 초기화: enabled={enabled}")

    @property
    def enabled(self) -> bool:
        """활성화 상태"""
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        """활성화 상태 변경"""
        self._enabled = value
        logger.info(f"PIIReviewProcessor 상태 변경: enabled={value}")

    async def process(
        self,
        document: Document,
        source_file: str = "",
    ) -> ProcessResult:
        """
        문서 PII 검토 및 처리

        Args:
            document: 처리할 문서
            source_file: 원본 파일명/소스 (감사용)

        Returns:
            ProcessResult: 처리 결과

        Raises:
            PIIViolationError: 정책 위반으로 처리 차단 시
        """
        start_time = time.perf_counter()

        # 비활성화 상태면 원본 그대로 반환
        if not self._enabled:
            return ProcessResult(
                document_id=document.id,
                original_content=document.content,
                processed_content=document.content,
                action_taken=PolicyAction.REVIEW_ONLY,
                entities_detected=0,
                entities_masked=0,
                audit_id="",
                requires_review=False,
            )

        try:
            # 1. PII 탐지
            entities = self.detector.detect(document.content)

            # 2. 정책 평가
            decision = self.policy_engine.evaluate(
                entities=entities,
                document_metadata=document.metadata,
            )

            # 3. 정책에 따른 처리
            processed_content: str | None = document.content

            if decision.action == PolicyAction.MASK_AND_PROCEED:
                processed_content = self._mask_entities(
                    document.content,
                    list(decision.entities_to_mask),
                )

            elif decision.action == PolicyAction.BLOCK_ON_VIOLATION:
                processed_content = None

            elif decision.action == PolicyAction.QUARANTINE:
                # 메타데이터에 격리 정보 추가
                document.metadata["quarantined"] = True
                document.metadata["quarantine_reason"] = decision.reason

            # 4. 처리 시간 계산
            processing_time_ms = (time.perf_counter() - start_time) * 1000

            # 5. 감사 로그 기록
            audit_id = await self.audit_logger.log_detection(
                document_id=document.id,
                entities=entities,
                decision=decision,
                source_file=source_file or document.metadata.get("source_file", ""),
                processing_time_ms=processing_time_ms,
            )

            # 6. 결과 반환
            result = ProcessResult(
                document_id=document.id,
                original_content=document.content,
                processed_content=processed_content,
                action_taken=decision.action,
                entities_detected=len(entities),
                entities_masked=len(decision.entities_to_mask),
                audit_id=audit_id,
                requires_review=decision.requires_human_review,
                processing_time_ms=processing_time_ms,
            )

            # 로깅
            if result.entities_detected > 0:
                logger.info(
                    f"PII 검토 완료: doc={document.id}, "
                    f"detected={result.entities_detected}, "
                    f"masked={result.entities_masked}, "
                    f"action={result.action_taken.value}, "
                    f"time={result.processing_time_ms:.2f}ms"
                )

            return result

        except Exception as e:
            logger.error(f"PII 검토 실패: {e}", exc_info=True)
            # Graceful Degradation: 실패 시 원본 그대로 반환
            return ProcessResult(
                document_id=document.id,
                original_content=document.content,
                processed_content=document.content,
                action_taken=PolicyAction.REVIEW_ONLY,
                entities_detected=0,
                entities_masked=0,
                audit_id="",
                requires_review=False,
                processing_time_ms=(time.perf_counter() - start_time) * 1000,
            )

    async def process_text(
        self,
        text: str,
        document_id: str = "",
        source_file: str = "",
    ) -> ProcessResult:
        """
        텍스트 직접 처리 (편의 메서드)

        Args:
            text: 처리할 텍스트
            document_id: 문서 ID (선택)
            source_file: 소스 파일명 (선택)

        Returns:
            ProcessResult: 처리 결과
        """
        document = Document(
            id=document_id or f"text-{hash(text[:100])}",
            content=text,
            metadata={"source_file": source_file},
        )
        return await self.process(document, source_file)

    async def process_batch(
        self,
        documents: list[Document],
        source_file: str = "",
    ) -> list[ProcessResult]:
        """
        배치 처리

        Args:
            documents: 처리할 문서 목록
            source_file: 공통 소스 파일명

        Returns:
            ProcessResult 목록
        """
        results = []
        for doc in documents:
            result = await self.process(doc, source_file)
            results.append(result)
        return results

    def _mask_entities(
        self,
        text: str,
        entities: list[PIIEntity],
    ) -> str:
        """
        엔티티 마스킹

        역순으로 처리하여 위치 변경 방지.

        Args:
            text: 원본 텍스트
            entities: 마스킹할 엔티티 목록

        Returns:
            마스킹된 텍스트
        """
        if not entities:
            return text

        result = text

        # 끝에서부터 처리 (위치 유지)
        sorted_entities = sorted(entities, key=lambda e: e.start_pos, reverse=True)

        for entity in sorted_entities:
            mask = self._get_mask(entity)
            result = result[: entity.start_pos] + mask + result[entity.end_pos :]

        return result

    def _get_mask(self, entity: PIIEntity) -> str:
        """엔티티 유형별 마스크 문자열 반환

        미정의 PIIType은 UNKNOWN 라벨로 폴백한다. UNKNOWN 라벨 자체도
        config 오버라이드 대상이므로(기본 "[개인정보]"), 비한국어 운영자는
        폴백 라벨까지 자국어로 교체할 수 있다(회귀 0: 미설정 시 한국어 유지).
        """
        return self.MASK_TEMPLATES.get(
            entity.entity_type,
            self.MASK_TEMPLATES.get(PIIType.UNKNOWN, "[개인정보]"),
        )


class PIIReviewDecorator:
    """
    PII 검토 데코레이터

    기존 DocumentProcessor에 PII 검토 기능을 비침투적으로 추가.
    Decorator 패턴으로 기존 코드 수정 없이 통합 가능.

    사용 예시:
        original_processor = DocumentProcessor()
        decorated = PIIReviewDecorator(original_processor, pii_processor)
        result = await decorated.process(document)
    """

    def __init__(
        self,
        processor: DocumentProcessorProtocol,
        pii_processor: PIIReviewProcessor,
        enabled: bool = True,
        block_on_violation: bool = True,
    ):
        """
        Args:
            processor: 기존 문서 프로세서
            pii_processor: PII 검토 프로세서
            enabled: PII 검토 활성화 여부
            block_on_violation: 정책 위반 시 처리 차단 여부
        """
        self._processor = processor
        self._pii_processor = pii_processor
        self._enabled = enabled
        self._block_on_violation = block_on_violation

    async def process(self, document: Document) -> Document:
        """
        PII 검토 후 기존 프로세서 실행

        Args:
            document: 처리할 문서

        Returns:
            처리된 문서

        Raises:
            PIIViolationError: 정책 위반으로 차단 시
        """
        if not self._enabled:
            return await self._processor.process(document)

        # PII 검토
        review_result = await self._pii_processor.process(document)

        # 차단 조건 체크
        if review_result.is_blocked and self._block_on_violation:
            raise PIIViolationError(f"PII 정책 위반으로 처리 차단: {document.id}")

        # 마스킹된 콘텐츠로 교체
        if review_result.processed_content is not None:
            document.content = review_result.processed_content

        # 메타데이터에 검토 정보 추가
        document.metadata["pii_review"] = {
            "audit_id": review_result.audit_id,
            "entities_detected": review_result.entities_detected,
            "entities_masked": review_result.entities_masked,
            "action": review_result.action_taken.value,
            "requires_review": review_result.requires_review,
        }

        # 기존 프로세서 실행
        return await self._processor.process(document)
