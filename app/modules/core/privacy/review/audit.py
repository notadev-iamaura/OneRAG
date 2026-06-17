"""
PII 감사 로거 (PIIAuditLogger)

PII 탐지 및 처리 결과를 MongoDB에 기록하여 컴플라이언스 추적.
민감 정보는 해시 처리하여 원본 값 미저장.

구현일: 2025-12-01
"""

from __future__ import annotations

import hashlib
import logging
import re
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from .models import (
    AuditRecord,
    PIIEntity,
    PolicyAction,
    PolicyDecision,
)

if TYPE_CHECKING:
    from motor.motor_asyncio import AsyncIOMotorCollection

logger = logging.getLogger(__name__)


class PIIAuditLogger:
    """
    PII 감사 로거

    MongoDB에 PII 탐지 및 처리 결과를 기록합니다.
    민감 정보는 SHA-256 해시 처리하여 원본 값을 저장하지 않습니다.

    사용 예시:
        logger = PIIAuditLogger(collection)
        audit_id = await logger.log_detection(
            document_id="doc-123",
            entities=entities,
            decision=decision
        )
    """

    VERSION = "1.0.0"
    COLLECTION_NAME = "pii_audit_logs"

    # 감사 메타데이터 정제용 기본 전화번호 패턴(한국 형식). detector와 동일하게
    # 코드 인라인 하드코딩 대신 클래스 상수로 분리해 단일 진실원천화한다. 다른
    # 형식이 필요하면 생성자 phone_pattern으로 오버라이드한다(미설정 시 회귀 0).
    DEFAULT_AUDIT_PHONE_PATTERN = r"\d{2,3}-\d{3,4}-\d{4}"

    def __init__(
        self,
        collection: AsyncIOMotorCollection | None = None,
        enabled: bool = True,
        phone_pattern: str | None = None,
    ):
        """
        Args:
            collection: MongoDB 컬렉션. None이면 로그만 기록.
            enabled: 감사 로깅 활성화 여부
            phone_pattern: 메타데이터 정제용 전화번호 정규식. 미지정 시 한국
                기본 패턴(DEFAULT_AUDIT_PHONE_PATTERN)을 사용한다(회귀 0).
        """
        self._collection = collection
        self._enabled = enabled
        self._phone_pattern = re.compile(phone_pattern or self.DEFAULT_AUDIT_PHONE_PATTERN)

        if collection is None:
            logger.warning("PIIAuditLogger: MongoDB 컬렉션 미설정. 파일 로그만 기록됩니다.")

    async def log_detection(
        self,
        document_id: str,
        entities: list[PIIEntity],
        decision: PolicyDecision,
        source_file: str = "",
        processing_time_ms: float = 0.0,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """
        PII 탐지 결과 기록

        ✅ QA-002 대응: 원본 PII 값은 SHA-256 해시 처리하여 저장

        Args:
            document_id: 처리된 문서 ID
            entities: 탐지된 PII 엔티티 목록
            decision: 정책 결정
            source_file: 원본 파일명/소스
            processing_time_ms: 처리 소요 시간 (밀리초)
            metadata: 추가 메타데이터

        Returns:
            생성된 감사 레코드 ID
        """
        if not self._enabled:
            return ""

        # 고유 ID 생성
        audit_id = self._generate_audit_id()

        # ✅ PII 값 해시 처리
        hashed_entities = [
            {
                "entity_type": e.entity_type.value,
                "value_hash": self._hash_value(e.value),  # 원본 대신 해시
                "start_pos": e.start_pos,
                "end_pos": e.end_pos,
                "confidence": e.confidence,
            }
            for e in entities
        ]

        # ✅ 메타데이터에서도 PII 제거
        safe_metadata = self._sanitize_metadata(metadata or {})

        # 감사 레코드 생성
        record = AuditRecord(
            id=audit_id,
            timestamp=datetime.now(UTC),
            document_id=document_id,
            source_file=source_file,
            detected_entity_types=self._extract_entity_types(entities),
            total_pii_count=len(entities),
            policy_applied=decision.reason,
            action_taken=decision.action,
            entities_masked=len(decision.entities_to_mask),
            processor_version=self.VERSION,
            processing_time_ms=processing_time_ms,
            entities=hashed_entities,  # 해시 처리된 엔티티
            metadata=safe_metadata,  # 정제된 메타데이터
        )

        # MongoDB 저장 시도
        if self._collection is not None:
            try:
                await self._collection.insert_one(record.to_dict())
                logger.debug(f"✅ 감사 로그 저장 완료 (PII 해시 처리): {audit_id}")
            except Exception as e:
                logger.error(f"❌ 감사 로그 저장 실패: {e}")
                # 실패해도 ID 반환 (Graceful Degradation)

        # 파일 로그에도 기록
        self._log_to_file(record)

        return audit_id

    async def get_audit_trail(
        self,
        document_id: str,
        limit: int = 100,
    ) -> list[AuditRecord]:
        """
        문서별 감사 이력 조회

        Args:
            document_id: 조회할 문서 ID
            limit: 최대 반환 개수

        Returns:
            감사 레코드 목록 (최신순)
        """
        if self._collection is None:
            logger.warning("MongoDB 컬렉션 미설정. 감사 이력 조회 불가.")
            return []

        try:
            cursor = (
                self._collection.find({"document_id": document_id})
                .sort("timestamp", -1)
                .limit(limit)
            )
            records = []
            async for doc in cursor:
                records.append(AuditRecord.from_dict(doc))
            return records
        except Exception as e:
            logger.error(f"감사 이력 조회 실패: {e}")
            return []

    async def get_recent_audits(
        self,
        hours: int = 24,
        action_filter: PolicyAction | None = None,
        limit: int = 1000,
    ) -> list[AuditRecord]:
        """
        최근 감사 로그 조회

        Args:
            hours: 조회 기간 (시간)
            action_filter: 특정 액션만 필터링
            limit: 최대 반환 개수

        Returns:
            감사 레코드 목록
        """
        if self._collection is None:
            return []

        try:
            from datetime import timedelta

            cutoff = datetime.now(UTC) - timedelta(hours=hours)

            query: dict[str, Any] = {"timestamp": {"$gte": cutoff}}
            if action_filter:
                query["action_taken"] = action_filter.value

            cursor = self._collection.find(query).sort("timestamp", -1).limit(limit)

            records = []
            async for doc in cursor:
                records.append(AuditRecord.from_dict(doc))
            return records
        except Exception as e:
            logger.error(f"최근 감사 로그 조회 실패: {e}")
            return []

    async def get_statistics(
        self,
        hours: int = 24,
    ) -> dict[str, Any]:
        """
        감사 통계 조회

        Args:
            hours: 통계 기간 (시간)

        Returns:
            통계 딕셔너리
        """
        if self._collection is None:
            return {"error": "MongoDB 컬렉션 미설정"}

        try:
            from datetime import timedelta

            cutoff = datetime.now(UTC) - timedelta(hours=hours)

            # 집계 파이프라인
            pipeline: list[dict[str, Any]] = [
                {"$match": {"timestamp": {"$gte": cutoff}}},
                {
                    "$group": {
                        "_id": "$action_taken",
                        "count": {"$sum": 1},
                        "total_pii": {"$sum": "$total_pii_count"},
                        "avg_processing_time": {"$avg": "$processing_time_ms"},
                    }
                },
            ]

            cursor = self._collection.aggregate(pipeline)
            results = await cursor.to_list(length=100)

            stats: dict[str, Any] = {
                "period_hours": hours,
                "actions": {},
                "total_documents": 0,
                "total_pii_detected": 0,
            }

            for result in results:
                action = result["_id"]
                stats["actions"][action] = {
                    "count": result["count"],
                    "total_pii": result["total_pii"],
                    "avg_processing_time_ms": round(result["avg_processing_time"], 2),
                }
                stats["total_documents"] += result["count"]
                stats["total_pii_detected"] += result["total_pii"]

            return stats
        except Exception as e:
            logger.error(f"감사 통계 조회 실패: {e}")
            return {"error": str(e)}

    def _generate_audit_id(self) -> str:
        """고유 감사 ID 생성"""
        return f"audit-{uuid.uuid4().hex[:12]}"

    def _extract_entity_types(self, entities: list[PIIEntity]) -> list[str]:
        """엔티티 유형 목록 추출 (중복 제거)"""
        return list({e.entity_type.value for e in entities})

    def _hash_value(self, value: str) -> str:
        """
        PII 값 해시 처리 (SHA-256)

        Args:
            value: 원본 PII 값

        Returns:
            SHA-256 해시 (64자 hex)

        Examples:
            >>> _hash_value("010-1234-5678")
            'a3f8b...'  # 64자
        """
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def _sanitize_metadata(self, metadata: dict[str, Any]) -> dict[str, Any]:
        """
        메타데이터에서 PII 패턴 제거

        Args:
            metadata: 원본 메타데이터

        Returns:
            정제된 메타데이터 (PII 마스킹)
        """
        sanitized = {}
        for key, value in metadata.items():
            if isinstance(value, str):
                # 전화번호 마스킹 (패턴은 생성자/기본 상수 단일 소스)
                sanitized[key] = self._phone_pattern.sub("***-****-****", value)
            else:
                sanitized[key] = value

        return sanitized

    def _log_to_file(self, record: AuditRecord) -> None:
        """파일 로그에 감사 기록"""
        log_message = (
            f"[PII_AUDIT] id={record.id} "
            f"doc={record.document_id} "
            f"action={record.action_taken.value} "
            f"pii_count={record.total_pii_count} "
            f"masked={record.entities_masked} "
            f"time_ms={record.processing_time_ms:.2f}"
        )

        if record.action_taken == PolicyAction.BLOCK_ON_VIOLATION:
            logger.warning(log_message)
        elif record.action_taken == PolicyAction.QUARANTINE:
            logger.warning(log_message)
        else:
            logger.info(log_message)
