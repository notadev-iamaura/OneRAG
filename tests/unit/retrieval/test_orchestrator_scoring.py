"""
Orchestrator 스코어링 통합 테스트

Orchestrator가 ScoringService를 올바르게 사용하는지 검증한다.

TDD Step 1: 이 테스트는 먼저 작성되어 FAIL해야 한다.
"""
import inspect
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.modules.core.retrieval.scoring import ScoringService


class TestOrchestratorScoringIntegration:
    """Orchestrator-ScoringService 통합 테스트"""

    @pytest.fixture
    def mock_retriever(self):
        """Mock Retriever 생성"""
        retriever = MagicMock()
        retriever.search = AsyncMock(return_value=[])
        return retriever

    @pytest.fixture
    def scoring_config(self):
        """스코어링 설정"""
        return {
            "scoring": {
                "collection_weight_enabled": False,
                "file_type_weight_enabled": False,
                "collection_weights": {},
                "file_type_weights": {},
            }
        }

    def test_orchestrator_has_scoring_service(self, mock_retriever, scoring_config):
        """Orchestrator가 ScoringService 인스턴스를 가져야 한다"""
        from app.modules.core.retrieval.orchestrator import RetrievalOrchestrator

        orchestrator = RetrievalOrchestrator(
            retriever=mock_retriever,
            config=scoring_config,
        )

        assert hasattr(orchestrator, "scoring_service"), "scoring_service 속성이 없습니다"
        assert isinstance(orchestrator.scoring_service, ScoringService)

    def test_scoring_service_initialized_with_config(self, mock_retriever):
        """ScoringService가 설정값으로 초기화되어야 한다"""
        from app.modules.core.retrieval.orchestrator import RetrievalOrchestrator

        config = {
            "scoring": {
                "collection_weight_enabled": True,
                "collection_weights": {"StructuredMetadata": 1.5},
                "file_type_weight_enabled": True,
                "file_type_weights": {"PDF": 1.2},
            }
        }

        orchestrator = RetrievalOrchestrator(
            retriever=mock_retriever,
            config=config,
        )

        assert orchestrator.scoring_service.collection_weight_enabled is True
        assert orchestrator.scoring_service.collection_weights["StructuredMetadata"] == 1.5
        assert orchestrator.scoring_service.file_type_weight_enabled is True
        assert orchestrator.scoring_service.file_type_weights["PDF"] == 1.2

    def test_rrf_merge_no_score_multipliers_param(self, mock_retriever, scoring_config):
        """_rrf_merge에서 score_multipliers 파라미터가 제거되어야 한다"""
        from app.modules.core.retrieval.orchestrator import RetrievalOrchestrator

        orchestrator = RetrievalOrchestrator(
            retriever=mock_retriever,
            config=scoring_config,
        )

        # _rrf_merge 시그니처 검사
        sig = inspect.signature(orchestrator._rrf_merge)
        param_names = list(sig.parameters.keys())

        assert "score_multipliers" not in param_names, \
            "_rrf_merge에서 score_multipliers 파라미터가 제거되어야 합니다"

    def test_search_and_merge_no_score_multipliers_param(self, mock_retriever, scoring_config):
        """_search_and_merge에서 score_multipliers 파라미터가 제거되어야 한다"""
        from app.modules.core.retrieval.orchestrator import RetrievalOrchestrator

        orchestrator = RetrievalOrchestrator(
            retriever=mock_retriever,
            config=scoring_config,
        )

        # _search_and_merge 시그니처 검사
        sig = inspect.signature(orchestrator._search_and_merge)
        param_names = list(sig.parameters.keys())

        assert "score_multipliers" not in param_names, \
            "_search_and_merge에서 score_multipliers 파라미터가 제거되어야 합니다"


class TestOrchestratorDefaultScoringBehavior:
    """기본 스코어링 동작 테스트"""

    @pytest.fixture
    def mock_retriever(self):
        """Mock Retriever 생성"""
        retriever = MagicMock()
        retriever.search = AsyncMock(return_value=[])
        return retriever

    def test_default_config_disables_weights(self, mock_retriever):
        """설정이 없으면 가중치가 비활성화되어야 한다"""
        from app.modules.core.retrieval.orchestrator import RetrievalOrchestrator

        # scoring 설정 없이 생성
        orchestrator = RetrievalOrchestrator(
            retriever=mock_retriever,
            config={},
        )

        # ScoringService의 기본값이 False인지 확인
        assert orchestrator.scoring_service.collection_weight_enabled is False
        assert orchestrator.scoring_service.file_type_weight_enabled is False

    def test_scoring_disabled_returns_plain_score(self, mock_retriever):
        """가중치 비활성화 시 원본 점수를 반환해야 한다"""
        from app.modules.core.retrieval.orchestrator import RetrievalOrchestrator

        orchestrator = RetrievalOrchestrator(
            retriever=mock_retriever,
            config={
                "scoring": {
                    "collection_weight_enabled": False,
                    "file_type_weight_enabled": False,
                }
            },
        )

        # ScoringService.apply_weight 테스트
        original_score = 0.75
        result = orchestrator.scoring_service.apply_weight(
            score=original_score,
            collection="StructuredMetadata",
            file_type="PDF"
        )

        assert result == original_score, "비활성화 시 원본 점수 그대로 반환"

