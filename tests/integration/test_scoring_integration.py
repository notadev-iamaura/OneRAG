"""
스코어링 시스템 통합 테스트

End-to-End로 설정 변경이 검색 결과에 반영되는지 검증한다.

테스트 범위:
1. 기본 설정으로 순수 RRF 점수 반환
2. 컬렉션 가중치 활성화 시 점수 변화
3. 파일 타입 가중치 활성화 시 점수 변화
4. ScoringService가 Orchestrator에 올바르게 주입되는지
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.lib.config_loader import load_config
from app.modules.core.retrieval.interfaces import SearchResult
from app.modules.core.retrieval.scoring import ScoringService


class TestScoringIntegrationWithConfig:
    """설정 파일 기반 통합 테스트"""

    @pytest.mark.integration
    def test_load_config_and_create_scoring_service(self):
        """load_config로 설정을 로드하고 ScoringService를 생성할 수 있어야 한다"""
        config = load_config(validate=False)

        # scoring 섹션 존재 확인
        assert "scoring" in config, "scoring 섹션이 설정에 존재해야 합니다"

        # ScoringService 생성
        scoring_config = config.get("scoring", {})
        service = ScoringService(scoring_config)

        # 기본값 검증
        assert service.collection_weight_enabled is False
        assert service.file_type_weight_enabled is False

    @pytest.mark.integration
    def test_default_config_returns_plain_score(self):
        """기본 설정에서는 가중치 없이 순수 점수를 반환해야 한다"""
        config = load_config(validate=False)
        scoring_config = config.get("scoring", {})
        service = ScoringService(scoring_config)

        original_score = 0.75

        result = service.apply_weight(
            score=original_score,
            collection="StructuredMetadata",
            file_type="PDF"
        )

        assert result == original_score, "기본 설정에서는 원본 점수 그대로 반환"

    @pytest.mark.integration
    def test_collection_weights_from_config(self):
        """설정 파일의 컬렉션 가중치가 올바르게 로드되어야 한다"""
        config = load_config(validate=False)
        scoring_config = config.get("scoring", {})
        service = ScoringService(scoring_config)

        # 설정 파일에서 로드된 컬렉션 가중치 확인
        assert "Documents" in service.collection_weights

        # 기본값 1.0 확인
        assert service.collection_weights["Documents"] == 1.0


class TestScoringIntegrationWithOrchestrator:
    """Orchestrator 통합 테스트"""

    @pytest.fixture
    def mock_retriever(self):
        """Mock Retriever 생성"""
        retriever = MagicMock()
        retriever.search = AsyncMock(return_value=[])
        retriever.initialize = AsyncMock()
        return retriever

    @pytest.mark.integration
    def test_orchestrator_uses_scoring_service(self, mock_retriever):
        """Orchestrator가 ScoringService를 사용하는지 확인"""
        from app.modules.core.retrieval.orchestrator import RetrievalOrchestrator

        config = load_config(validate=False)

        orchestrator = RetrievalOrchestrator(
            retriever=mock_retriever,
            config=config,
        )

        # ScoringService가 주입되었는지 확인
        assert hasattr(orchestrator, "scoring_service")
        assert isinstance(orchestrator.scoring_service, ScoringService)

        # 설정이 올바르게 전달되었는지 확인
        assert orchestrator.scoring_service.collection_weight_enabled is False
        assert orchestrator.scoring_service.file_type_weight_enabled is False

    @pytest.mark.integration
    def test_orchestrator_with_custom_scoring_config(self, mock_retriever):
        """커스텀 스코어링 설정으로 Orchestrator 생성"""
        from app.modules.core.retrieval.orchestrator import RetrievalOrchestrator

        custom_config = {
            "scoring": {
                "collection_weight_enabled": True,
                "collection_weights": {"StructuredMetadata": 1.5, "Documents": 0.8},
                "file_type_weight_enabled": True,
                "file_type_weights": {"PDF": 1.2, "TXT": 1.1},
            }
        }

        orchestrator = RetrievalOrchestrator(
            retriever=mock_retriever,
            config=custom_config,
        )

        # 커스텀 설정이 적용되었는지 확인
        assert orchestrator.scoring_service.collection_weight_enabled is True
        assert orchestrator.scoring_service.collection_weights["StructuredMetadata"] == 1.5
        assert orchestrator.scoring_service.file_type_weight_enabled is True
        assert orchestrator.scoring_service.file_type_weights["PDF"] == 1.2


class TestScoringIntegrationWithSearchResult:
    """SearchResult와 스코어링 통합 테스트"""

    @pytest.mark.integration
    def test_scoring_service_with_search_result_metadata(self):
        """SearchResult의 메타데이터를 사용하여 가중치를 적용할 수 있어야 한다"""
        service = ScoringService({
            "collection_weight_enabled": True,
            "collection_weights": {"StructuredMetadata": 1.5},
            "file_type_weight_enabled": True,
            "file_type_weights": {"PDF": 1.2},
        })

        # Mock SearchResult
        result = SearchResult(
            id="test-doc-1",
            content="테스트 내용",
            score=0.50,
            metadata={
                "_collection": "StructuredMetadata",
                "file_type": "PDF",
            }
        )

        # 메타데이터에서 값 추출
        collection = result.metadata.get("_collection")
        file_type = result.metadata.get("file_type")

        # 가중치 적용
        adjusted_score = service.apply_weight(
            score=result.score,
            collection=collection,
            file_type=file_type,
        )

        # 예상 점수: 0.50 * 1.5 * 1.2 = 0.90
        expected = 0.50 * 1.5 * 1.2
        assert abs(adjusted_score - expected) < 0.0001


class TestScoringConfigurationScenarios:
    """다양한 설정 시나리오 테스트"""

    @pytest.mark.integration
    def test_scenario_plain_system(self):
        """시나리오 1: Plain System (모든 가중치 비활성화)"""
        service = ScoringService({
            "collection_weight_enabled": False,
            "file_type_weight_enabled": False,
        })

        # 모든 입력에 대해 원본 점수 반환
        test_cases = [
            (0.75, "StructuredMetadata", "PDF"),
            (0.50, "Documents", "TXT"),
            (0.25, "Unknown", "XLSX"),
        ]

        for score, collection, file_type in test_cases:
            result = service.apply_weight(score, collection, file_type)
            assert result == score, f"Plain System에서는 항상 원본 점수 {score} 반환"

    @pytest.mark.integration
    def test_scenario_metadata_priority(self):
        """시나리오 2: 메타데이터 우선 (StructuredMetadata 부스트)"""
        service = ScoringService({
            "collection_weight_enabled": True,
            "collection_weights": {
                "StructuredMetadata": 1.5,  # 50% 부스트
                "Documents": 0.8,       # 20% 감쇄
            },
            "file_type_weight_enabled": False,
        })

        base_score = 0.50

        # StructuredMetadata: 50% 부스트
        metadata_score = service.apply_weight(base_score, collection="StructuredMetadata")
        assert metadata_score == 0.75

        # Documents: 20% 감쇄
        document_score = service.apply_weight(base_score, collection="Documents")
        assert document_score == 0.40

    @pytest.mark.integration
    def test_scenario_file_type_priority(self):
        """시나리오 3: 파일 타입 우선 (PDF, TXT 부스트)"""
        service = ScoringService({
            "collection_weight_enabled": False,
            "file_type_weight_enabled": True,
            "file_type_weights": {
                "PDF": 1.2,   # 가이드북 20% 부스트
                "TXT": 1.1,   # 대화 기록 10% 부스트
                "XLSX": 1.0,  # FAQ 기본
            },
        })

        base_score = 0.50

        # PDF: 20% 부스트
        pdf_score = service.apply_weight(base_score, file_type="PDF")
        assert abs(pdf_score - 0.60) < 0.0001

        # TXT: 10% 부스트
        txt_score = service.apply_weight(base_score, file_type="TXT")
        assert abs(txt_score - 0.55) < 0.0001

    @pytest.mark.integration
    def test_scenario_combined_weights(self):
        """시나리오 4: 복합 가중치 (컬렉션 + 파일타입)"""
        service = ScoringService({
            "collection_weight_enabled": True,
            "collection_weights": {"StructuredMetadata": 1.5},
            "file_type_weight_enabled": True,
            "file_type_weights": {"PDF": 1.2},
        })

        base_score = 0.50

        # StructuredMetadata + PDF: 1.5 * 1.2 = 1.8배
        combined_score = service.apply_weight(
            base_score,
            collection="StructuredMetadata",
            file_type="PDF"
        )
        expected = base_score * 1.5 * 1.2  # 0.90
        assert abs(combined_score - expected) < 0.0001

