"""
PII 정책 엔진 (PIIPolicyEngine)

PII 탐지 결과를 평가하고 처리 방향을 결정:
- REVIEW_ONLY: 로그만 기록
- MASK_AND_PROCEED: 마스킹 후 진행
- BLOCK_ON_VIOLATION: 처리 중단 (민감 정보)
- QUARANTINE: 격리 (수동 검토 대기)

구현일: 2025-12-01
"""

from __future__ import annotations

from typing import Any

from app.lib.logger import get_logger

from .models import (
    PIIEntity,
    PIIPolicy,
    PIIType,
    PolicyAction,
    PolicyDecision,
)

logger = get_logger(__name__)


class PIIPolicyEngine:
    """
    PII 정책 엔진

    탐지된 PII 엔티티를 평가하고 처리 결정을 내립니다.
    정책은 엔티티 유형별로 다르게 적용 가능.

    사용 예시:
        engine = PIIPolicyEngine()
        decision = engine.evaluate(entities)
        if decision.action == PolicyAction.MASK_AND_PROCEED:
            # 마스킹 처리
            ...
    """

    def __init__(self, policy: PIIPolicy | None = None):
        """
        Args:
            policy: PII 정책 설정. None이면 기본 정책 사용.
        """
        self.policy = policy or PIIPolicy.default()
        logger.info(
            f"PIIPolicyEngine 초기화: policy={self.policy.name}, "
            f"quarantine_threshold={self.policy.quarantine_threshold}"
        )

    def evaluate(
        self,
        entities: list[PIIEntity],
        document_metadata: dict[str, Any] | None = None,
    ) -> PolicyDecision:
        """
        정책에 따른 처리 결정

        결정 우선순위:
        1. 격리 조건 (PII 개수 초과)
        2. 차단 조건 (민감 정보: SSN, CARD 등)
        3. 마스킹 조건 (일반 PII)
        4. 검토만 (PII 없거나 검토 대상만)

        Args:
            entities: 탐지된 PII 엔티티 목록
            document_metadata: 문서 메타데이터 (선택적, 정책 커스터마이징용)

        Returns:
            PolicyDecision: 처리 방향 및 마스킹 대상
        """
        if not entities:
            return PolicyDecision(
                action=PolicyAction.REVIEW_ONLY,
                entities_to_mask=(),
                reason="PII 미탐지",
                requires_human_review=False,
            )

        # 신뢰도 필터링
        valid_entities = self._filter_by_confidence(entities)

        if not valid_entities:
            return PolicyDecision(
                action=PolicyAction.REVIEW_ONLY,
                entities_to_mask=(),
                reason=f"신뢰도 임계값({self.policy.min_confidence}) 미달",
                requires_human_review=False,
            )

        # 1. 격리 조건 체크 (PII 개수 초과)
        if len(valid_entities) >= self.policy.quarantine_threshold:
            logger.warning(
                f"격리 조건 충족: {len(valid_entities)}개 PII >= "
                f"임계값 {self.policy.quarantine_threshold}"
            )
            return PolicyDecision(
                action=PolicyAction.QUARANTINE,
                entities_to_mask=(),
                reason=f"PII 개수 초과: {len(valid_entities)}개 탐지 "
                f"(임계값: {self.policy.quarantine_threshold})",
                requires_human_review=True,
            )

        # 2. 차단 조건 체크 (민감 정보)
        blocking_entities = self._get_blocking_entities(valid_entities)
        if blocking_entities:
            blocking_types = {e.entity_type.value for e in blocking_entities}
            logger.warning(f"차단 조건 충족: 민감 정보 탐지 - {blocking_types}")
            return PolicyDecision(
                action=PolicyAction.BLOCK_ON_VIOLATION,
                entities_to_mask=(),
                reason=f"민감 정보 탐지: {', '.join(blocking_types)}",
                requires_human_review=True,
            )

        # 3. 마스킹 대상 추출
        masking_entities = self._get_masking_entities(valid_entities)

        if masking_entities:
            entity_types = {e.entity_type.value for e in masking_entities}
            logger.info(f"마스킹 결정: {len(masking_entities)}개 엔티티 - {entity_types}")
            return PolicyDecision(
                action=PolicyAction.MASK_AND_PROCEED,
                entities_to_mask=tuple(masking_entities),
                reason=f"{len(masking_entities)}개 엔티티 마스킹 " f"({', '.join(entity_types)})",
                requires_human_review=False,
            )

        # 4. 검토만 필요한 경우 (REVIEW_ONLY 대상만 있음)
        review_only_types = {e.entity_type.value for e in valid_entities}
        return PolicyDecision(
            action=PolicyAction.REVIEW_ONLY,
            entities_to_mask=(),
            reason=f"검토 대상: {', '.join(review_only_types)}",
            requires_human_review=False,
        )

    def _filter_by_confidence(self, entities: list[PIIEntity]) -> list[PIIEntity]:
        """신뢰도 임계값 이상의 엔티티만 필터링"""
        return [e for e in entities if e.confidence >= self.policy.min_confidence]

    def _get_blocking_entities(self, entities: list[PIIEntity]) -> list[PIIEntity]:
        """차단 대상 엔티티 추출 (SSN, CARD 등)"""
        return [
            e
            for e in entities
            if self.policy.entity_actions.get(e.entity_type) == PolicyAction.BLOCK_ON_VIOLATION
        ]

    def _get_masking_entities(self, entities: list[PIIEntity]) -> list[PIIEntity]:
        """마스킹 대상 엔티티 추출"""
        return [
            e
            for e in entities
            if self.policy.entity_actions.get(e.entity_type) == PolicyAction.MASK_AND_PROCEED
        ]

    def update_policy(self, policy: PIIPolicy) -> None:
        """정책 업데이트"""
        self.policy = policy
        logger.info(f"정책 업데이트: {policy.name}")

    def set_entity_action(self, entity_type: PIIType, action: PolicyAction) -> None:
        """특정 엔티티 유형의 처리 방식 변경"""
        self.policy.entity_actions[entity_type] = action
        logger.info(f"엔티티 액션 변경: {entity_type.value} → {action.value}")
