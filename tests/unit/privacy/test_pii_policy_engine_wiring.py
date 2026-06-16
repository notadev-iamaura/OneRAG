"""
PIIPolicyEngine DI 배선 교정 테스트

기존 di_container 배선은 PIIPolicyEngine에 policy_name/entity_actions 등을
직접 넘겨 인스턴스화 시 TypeError였다(PII 리뷰 활성화 시 크래시). 팩토리
_create_pii_policy_engine이 config를 PIIPolicy로 구성해 교정함을 검증한다.
"""

from app.core.di_container import _create_pii_policy_engine
from app.modules.core.privacy.review.models import PIIType, PolicyAction
from app.modules.core.privacy.review.policy import PIIPolicyEngine


class TestPiiPolicyEngineFactory:
    def test_builds_engine_without_typeerror(self):
        """기본 config(None)로도 엔진이 정상 생성된다(이전엔 TypeError)."""
        engine = _create_pii_policy_engine(None)
        assert isinstance(engine, PIIPolicyEngine)

    def test_maps_config_entity_actions_to_enums(self):
        """config 문자열 entity_actions가 PIIType/PolicyAction enum으로 매핑된다."""
        cfg = {
            "name": "custom",
            "quarantine_threshold": 5,
            "min_confidence": 0.9,
            "entity_actions": {
                "phone": "mask",
                "ssn": "block",
                "person_name": "review",  # 단축 별칭 → REVIEW_ONLY
            },
        }
        engine = _create_pii_policy_engine(cfg)
        policy = engine.policy
        assert policy.name == "custom"
        assert policy.quarantine_threshold == 5
        assert policy.min_confidence == 0.9
        assert policy.entity_actions[PIIType.PHONE] == PolicyAction.MASK_AND_PROCEED
        assert policy.entity_actions[PIIType.SSN] == PolicyAction.BLOCK_ON_VIOLATION
        assert policy.entity_actions[PIIType.PERSON_NAME] == PolicyAction.REVIEW_ONLY

    def test_missing_keys_keep_default_actions(self):
        """config에 없는 엔티티 타입은 기본 정책 액션을 유지한다(회귀 0)."""
        cfg = {"entity_actions": {"phone": "block"}}
        engine = _create_pii_policy_engine(cfg)
        # 오버라이드된 phone
        assert engine.policy.entity_actions[PIIType.PHONE] == PolicyAction.BLOCK_ON_VIOLATION
        # 미지정 unknown은 기본값(REVIEW_ONLY) 유지
        assert PIIType.UNKNOWN in engine.policy.entity_actions

    def test_unknown_entity_type_skipped_gracefully(self):
        cfg = {"entity_actions": {"not_a_type": "mask", "phone": "mask"}}
        engine = _create_pii_policy_engine(cfg)
        assert engine.policy.entity_actions[PIIType.PHONE] == PolicyAction.MASK_AND_PROCEED

    def test_non_dict_config_falls_back_to_default(self):
        engine = _create_pii_policy_engine("not-a-dict")
        assert isinstance(engine, PIIPolicyEngine)
        assert engine.policy.name == "default"
