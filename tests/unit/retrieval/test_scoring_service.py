"""
ScoringService 단위 테스트

설정 기반 점수 가중치 적용 로직을 검증한다.

TDD Step 1: 이 테스트는 먼저 작성되어 FAIL해야 한다.
"""


class TestScoringServiceInit:
    """ScoringService 초기화 테스트"""

    def test_init_with_default_config(self):
        """기본 설정으로 초기화할 수 있어야 한다"""
        from app.modules.core.retrieval.scoring import ScoringService

        service = ScoringService({})
        assert service is not None

    def test_init_with_disabled_weights(self):
        """가중치 비활성화 상태로 초기화"""
        from app.modules.core.retrieval.scoring import ScoringService

        config = {
            "collection_weight_enabled": False,
            "file_type_weight_enabled": False,
        }
        service = ScoringService(config)
        assert service.collection_weight_enabled is False
        assert service.file_type_weight_enabled is False

    def test_init_with_enabled_weights(self):
        """가중치 활성화 상태로 초기화"""
        from app.modules.core.retrieval.scoring import ScoringService

        config = {
            "collection_weight_enabled": True,
            "file_type_weight_enabled": True,
            "collection_weights": {"StructuredMetadata": 1.5},
            "file_type_weights": {"PDF": 1.2},
        }
        service = ScoringService(config)
        assert service.collection_weight_enabled is True
        assert service.file_type_weight_enabled is True
        assert service.collection_weights["StructuredMetadata"] == 1.5
        assert service.file_type_weights["PDF"] == 1.2


class TestScoringServiceApplyWeight:
    """가중치 적용 로직 테스트"""

    def test_apply_weight_disabled_returns_original(self):
        """가중치 비활성화 시 원본 점수를 그대로 반환해야 한다"""
        from app.modules.core.retrieval.scoring import ScoringService

        config = {
            "collection_weight_enabled": False,
            "file_type_weight_enabled": False,
        }
        service = ScoringService(config)

        original_score = 0.75
        result = service.apply_weight(
            score=original_score,
            collection="StructuredMetadata",
            file_type="PDF"
        )

        assert result == original_score, "비활성화 시 원본 점수 그대로 반환"

    def test_apply_collection_weight_enabled(self):
        """컬렉션 가중치 활성화 시 배율이 적용되어야 한다"""
        from app.modules.core.retrieval.scoring import ScoringService

        config = {
            "collection_weight_enabled": True,
            "collection_weights": {"StructuredMetadata": 1.5, "Documents": 1.0},
            "file_type_weight_enabled": False,
        }
        service = ScoringService(config)

        original_score = 0.50
        result = service.apply_weight(
            score=original_score,
            collection="StructuredMetadata",
            file_type="PDF"
        )

        expected = original_score * 1.5  # 0.75
        assert result == expected, f"Expected {expected}, got {result}"

    def test_apply_file_type_weight_enabled(self):
        """파일 타입 가중치 활성화 시 배율이 적용되어야 한다"""
        from app.modules.core.retrieval.scoring import ScoringService

        config = {
            "collection_weight_enabled": False,
            "file_type_weight_enabled": True,
            "file_type_weights": {"PDF": 1.2, "TXT": 1.0},
        }
        service = ScoringService(config)

        original_score = 0.50
        result = service.apply_weight(
            score=original_score,
            collection="Documents",
            file_type="PDF"
        )

        expected = original_score * 1.2  # 0.60
        assert result == expected, f"Expected {expected}, got {result}"

    def test_apply_both_weights_enabled(self):
        """두 가중치 모두 활성화 시 순차 적용되어야 한다"""
        from app.modules.core.retrieval.scoring import ScoringService

        config = {
            "collection_weight_enabled": True,
            "collection_weights": {"StructuredMetadata": 1.5},
            "file_type_weight_enabled": True,
            "file_type_weights": {"PDF": 1.2},
        }
        service = ScoringService(config)

        original_score = 0.50
        result = service.apply_weight(
            score=original_score,
            collection="StructuredMetadata",
            file_type="PDF"
        )

        # 0.50 * 1.5 * 1.2 = 0.90
        expected = original_score * 1.5 * 1.2
        assert abs(result - expected) < 0.0001, f"Expected {expected}, got {result}"

    def test_unknown_collection_uses_default(self):
        """알 수 없는 컬렉션은 기본 가중치 1.0을 사용해야 한다"""
        from app.modules.core.retrieval.scoring import ScoringService

        config = {
            "collection_weight_enabled": True,
            "collection_weights": {"StructuredMetadata": 1.5},
        }
        service = ScoringService(config)

        original_score = 0.50
        result = service.apply_weight(
            score=original_score,
            collection="UnknownCollection",
            file_type="PDF"
        )

        assert result == original_score, "미지정 컬렉션은 가중치 1.0 적용"

    def test_unknown_file_type_uses_default(self):
        """알 수 없는 파일 타입은 기본 가중치 1.0을 사용해야 한다"""
        from app.modules.core.retrieval.scoring import ScoringService

        config = {
            "collection_weight_enabled": False,
            "file_type_weight_enabled": True,
            "file_type_weights": {"PDF": 1.2},
        }
        service = ScoringService(config)

        original_score = 0.50
        result = service.apply_weight(
            score=original_score,
            collection="Documents",
            file_type="UNKNOWN"
        )

        assert result == original_score, "미지정 파일 타입은 가중치 1.0 적용"

    def test_case_insensitive_file_type(self):
        """파일 타입은 대소문자를 구분하지 않아야 한다"""
        from app.modules.core.retrieval.scoring import ScoringService

        config = {
            "collection_weight_enabled": False,
            "file_type_weight_enabled": True,
            "file_type_weights": {"PDF": 1.2},
        }
        service = ScoringService(config)

        original_score = 0.50

        # 소문자 입력
        result = service.apply_weight(
            score=original_score,
            collection="Documents",
            file_type="pdf"  # 소문자
        )

        expected = original_score * 1.2
        assert abs(result - expected) < 0.0001, "파일 타입은 대소문자 무관하게 처리"

    def test_none_collection_and_file_type(self):
        """collection과 file_type이 None이어도 에러 없이 처리해야 한다"""
        from app.modules.core.retrieval.scoring import ScoringService

        config = {
            "collection_weight_enabled": True,
            "collection_weights": {"StructuredMetadata": 1.5},
            "file_type_weight_enabled": True,
            "file_type_weights": {"PDF": 1.2},
        }
        service = ScoringService(config)

        original_score = 0.50
        result = service.apply_weight(
            score=original_score,
            collection=None,
            file_type=None
        )

        # None이면 가중치 적용하지 않음
        assert result == original_score, "None 값은 가중치 미적용"


class TestScoringServiceFromConfig:
    """load_config 통합 테스트"""

    def test_create_from_loaded_config(self):
        """load_config로 로드한 설정으로 ScoringService 생성"""
        from app.lib.config_loader import load_config
        from app.modules.core.retrieval.scoring import ScoringService

        config = load_config(validate=False)
        scoring_config = config.get("scoring", {})

        service = ScoringService(scoring_config)

        # 기본값 검증
        assert service.collection_weight_enabled is False
        assert service.file_type_weight_enabled is False

