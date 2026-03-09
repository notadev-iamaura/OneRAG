"""
EnrichmentService 단위 테스트

목적: EnrichmentService의 분기 로직, 폴백 체인, 배치 처리 엣지 케이스를 검증합니다.
대상: app/modules/core/enrichment/services/enrichment_service.py
의존성: pytest, pytest-asyncio, unittest.mock
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.core.enrichment.enrichers.null_enricher import NullEnricher
from app.modules.core.enrichment.schemas.enrichment_schema import (
    EnrichmentResult,
)
from app.modules.core.enrichment.services.enrichment_service import EnrichmentService

# ---------------------------------------------------------------------------
# 헬퍼: 테스트용 설정 딕셔너리 생성
# ---------------------------------------------------------------------------

def _make_config(
    enabled: bool = False,
    api_key: str | None = None,
    batch_size: int = 10,
    batch_concurrency: int = 3,
) -> dict:
    """테스트용 설정 딕셔너리 생성"""
    cfg: dict = {
        "enrichment": {
            "enabled": enabled,
            "llm": {"model": "gpt-4o-mini", "temperature": 0.1},
            "batch": {"size": batch_size, "concurrency": batch_concurrency},
            "timeout": {"single": 30, "batch": 90},
            "retry": {"max_attempts": 3},
            "cache": {"enabled": False},
            "quality": {"min_confidence": 0.0, "fallback_to_original": True},
        }
    }
    if api_key is not None:
        cfg["enrichment"]["llm"]["api_key"] = api_key
    return cfg


def _make_enrichment_result(**overrides) -> EnrichmentResult:
    """테스트용 EnrichmentResult 생성"""
    defaults = {
        "category": "테스트",
        "subcategory": "단위",
        "intent": "테스트 요청",
        "content_type": "테스트문의",
        "keywords": ["테스트"],
        "summary": "테스트 요약",
    }
    defaults.update(overrides)
    return EnrichmentResult(**defaults)


# ===========================================================================
# 1. _parse_enrichment_config() — 설정 파싱 정확성
# ===========================================================================

class TestParseEnrichmentConfig:
    """설정 파싱 로직 검증: 중첩 dict에서 올바르게 값을 추출하는지 확인"""

    def test_전체_설정_파싱(self) -> None:
        """모든 섹션이 있는 전체 설정 → 올바른 EnrichmentConfig 생성"""
        config = {
            "enrichment": {
                "enabled": True,
                "llm": {"model": "gpt-4o", "temperature": 0.5, "max_tokens": 2000},
                "batch": {"size": 20, "concurrency": 5},
                "timeout": {"single": 60, "batch": 120},
                "retry": {"max_attempts": 5},
                "cache": {"enabled": True},
                "quality": {"min_confidence": 0.8, "fallback_to_original": False},
            }
        }
        service = EnrichmentService(config)
        ec = service.enrichment_config

        # 각 중첩 섹션의 값이 정확히 추출되었는지 검증
        assert ec.enabled is True
        assert ec.llm_model == "gpt-4o"
        assert ec.llm_temperature == 0.5
        assert ec.llm_max_tokens == 2000
        assert ec.batch_size == 20
        assert ec.batch_concurrency == 5
        assert ec.timeout_single == 60
        assert ec.timeout_batch == 120
        assert ec.max_retries == 5
        assert ec.cache_enabled is True
        assert ec.min_confidence == 0.8
        assert ec.fallback_to_original is False

    def test_빈_설정_기본값(self) -> None:
        """빈 dict → Pydantic 기본값으로 정상 생성"""
        service = EnrichmentService({})
        ec = service.enrichment_config

        assert ec.enabled is False
        assert ec.llm_model == "gpt-4o-mini"
        assert ec.batch_size == 10
        assert ec.batch_concurrency == 3


# ===========================================================================
# 2~5. initialize() 4가지 경로
# ===========================================================================

class TestInitialize:
    """initialize() 메서드의 4가지 분기 경로 검증"""

    @pytest.mark.asyncio
    async def test_경로1_비활성화시_NullEnricher(self) -> None:
        """enabled=false → NullEnricher 사용"""
        service = EnrichmentService(_make_config(enabled=False))
        await service.initialize()

        assert isinstance(service.enricher, NullEnricher)

    @pytest.mark.asyncio
    async def test_경로2_활성화_API키_없음_NullEnricher_폴백(self) -> None:
        """enabled=true + API 키 전부 없음 → NullEnricher 폴백

        폴백이 없으면 enricher=None으로 남아 모든 enrich() 호출이 실패합니다.
        """
        # API 키 관련 설정이 전혀 없는 config
        service = EnrichmentService(_make_config(enabled=True))
        await service.initialize()

        assert isinstance(service.enricher, NullEnricher)

    @pytest.mark.asyncio
    async def test_경로3_활성화_API키_있음_LLMEnricher_생성(self) -> None:
        """enabled=true + API 키 존재 → LLMEnricher 생성 및 initialize() 호출"""
        config = _make_config(enabled=True, api_key="sk-test-key")

        # LLMEnricher를 Mock하여 외부 의존성 차단
        mock_llm_enricher = AsyncMock()
        mock_llm_enricher.initialize = AsyncMock()

        with patch(
            "app.modules.core.enrichment.services.enrichment_service.LLMEnricher",
            return_value=mock_llm_enricher,
        ) as mock_cls:
            service = EnrichmentService(config)
            await service.initialize()

            # LLMEnricher 생성자 호출 확인
            mock_cls.assert_called_once()
            # initialize() 호출 확인
            mock_llm_enricher.initialize.assert_awaited_once()
            # enricher가 Mock LLMEnricher인지 확인
            assert service.enricher is mock_llm_enricher

    @pytest.mark.asyncio
    async def test_경로4_LLMEnricher_초기화_예외시_NullEnricher_폴백(self) -> None:
        """LLMEnricher 생성/초기화 예외 → NullEnricher 폴백

        폴백이 없으면 서비스 전체가 중단됩니다.
        """
        config = _make_config(enabled=True, api_key="sk-test-key")

        with patch(
            "app.modules.core.enrichment.services.enrichment_service.LLMEnricher",
            side_effect=RuntimeError("OpenAI 연결 실패"),
        ):
            service = EnrichmentService(config)
            await service.initialize()

            # 예외 발생 후 NullEnricher로 폴백되었는지 확인
            assert isinstance(service.enricher, NullEnricher)


# ===========================================================================
# 6. _get_openai_api_key() 3단계 우선순위
# ===========================================================================

class TestGetOpenaiApiKey:
    """API 키 탐색 우선순위 검증: 순서가 뒤바뀌면 의도치 않은 키 사용"""

    def test_1순위_enrichment_llm_api_key(self) -> None:
        """enrichment.llm.api_key가 있으면 최우선 반환"""
        config = {
            "enrichment": {"llm": {"api_key": "first-priority"}},
            "generation": {"openai": {"api_key": "second-priority"}},
            "llm": {"openai": {"api_key": "third-priority"}},
        }
        service = EnrichmentService(config)
        assert service._get_openai_api_key() == "first-priority"

    def test_2순위_generation_openai_api_key(self) -> None:
        """1순위 없고 generation.openai.api_key만 있으면 2순위 반환"""
        config = {
            "enrichment": {"llm": {}},
            "generation": {"openai": {"api_key": "second-priority"}},
            "llm": {"openai": {"api_key": "third-priority"}},
        }
        service = EnrichmentService(config)
        assert service._get_openai_api_key() == "second-priority"

    def test_3순위_llm_openai_api_key(self) -> None:
        """1,2순위 없고 llm.openai.api_key만 있으면 3순위 반환"""
        config = {
            "enrichment": {"llm": {}},
            "generation": {"openai": {}},
            "llm": {"openai": {"api_key": "third-priority"}},
        }
        service = EnrichmentService(config)
        assert service._get_openai_api_key() == "third-priority"

    def test_전부_없으면_None(self) -> None:
        """모든 경로에 API 키 없음 → None 반환"""
        config = {"enrichment": {"llm": {}}}
        service = EnrichmentService(config)
        assert service._get_openai_api_key() is None


# ===========================================================================
# 7~8. enrich() 단일 문서 보강
# ===========================================================================

class TestEnrich:
    """enrich() 메서드의 에러 핸들링 검증"""

    @pytest.mark.asyncio
    async def test_미초기화_상태_None_반환(self) -> None:
        """enricher=None (초기화 안 됨) → None 반환"""
        service = EnrichmentService(_make_config())
        # initialize() 호출하지 않음 → enricher는 None
        result = await service.enrich({"content": "테스트"})
        assert result is None

    @pytest.mark.asyncio
    async def test_enricher_예외시_None_반환(self) -> None:
        """enricher.enrich()가 예외 발생 → None 반환 (에러 삼킴)"""
        service = EnrichmentService(_make_config())
        # enricher를 예외 발생하는 Mock으로 설정
        mock_enricher = AsyncMock()
        mock_enricher.enrich = AsyncMock(
            side_effect=RuntimeError("LLM 호출 실패")
        )
        service.enricher = mock_enricher

        result = await service.enrich({"content": "테스트"})
        assert result is None


# ===========================================================================
# 9~11. enrich_batch() 배치 처리
# ===========================================================================

class TestEnrichBatch:
    """enrich_batch() 배치 처리 및 엣지 케이스 검증"""

    @pytest.mark.asyncio
    async def test_빈_문서_빈_리스트(self) -> None:
        """documents=[] → [] 반환"""
        service = EnrichmentService(_make_config())
        service.enricher = NullEnricher()

        result = await service.enrich_batch([])
        assert result == []

    @pytest.mark.asyncio
    async def test_미초기화_None_리스트(self) -> None:
        """enricher=None → 문서 수만큼 None 리스트"""
        service = EnrichmentService(_make_config())
        docs = [{"content": "a"}, {"content": "b"}, {"content": "c"}]

        result = await service.enrich_batch(docs)
        assert result == [None, None, None]

    @pytest.mark.xfail(
        reason="알려진 버그: 실패 배치의 None 개수가 batch_size 고정값 사용 (line 214)"
    )
    @pytest.mark.asyncio
    async def test_실패_배치_None_개수_버그(self) -> None:
        """batch_size=3, 문서 7개 → 배치 [3,3,1], 마지막 배치 실패 시

        현재 코드는 line 214에서 `[None] * batch_size` (=3)를 사용하지만,
        마지막 배치의 실제 크기는 1이므로 결과가 7이 아닌 9가 됩니다.
        올바른 동작은 결과 길이가 입력 문서 수(7)와 같아야 합니다.
        """
        config = _make_config(enabled=True, batch_size=3, batch_concurrency=3)
        service = EnrichmentService(config)

        # Mock enricher: enrich_batch를 직접 제어
        mock_enricher = AsyncMock()
        call_count = 0

        async def mock_enrich_batch(batch):
            nonlocal call_count
            call_count += 1
            if call_count == 3:
                # 3번째 배치 (1개짜리)에서 예외 발생
                raise RuntimeError("배치 처리 실패")
            # 정상 배치: 결과 반환
            return [_make_enrichment_result() for _ in batch]

        mock_enricher.enrich_batch = AsyncMock(side_effect=mock_enrich_batch)
        service.enricher = mock_enricher

        docs = [{"content": f"doc-{i}"} for i in range(7)]
        results = await service.enrich_batch(docs)

        # 결과 길이는 입력 문서 수와 동일해야 함
        # 현재 버그: batch_size(3) 고정으로 9개가 나옴
        assert len(results) == 7


# ===========================================================================
# 12. get_stats() — enricher 타입별 분기
# ===========================================================================

class TestGetStats:
    """get_stats() 메서드의 enricher 타입별 분기 검증"""

    def test_NullEnricher_사용시_비활성_통계(self) -> None:
        """NullEnricher → {"enabled": False, "enricher_type": "NullEnricher"}"""
        service = EnrichmentService(_make_config())
        service.enricher = NullEnricher()

        stats = service.get_stats()
        assert stats == {"enabled": False, "enricher_type": "NullEnricher"}

    def test_LLMEnricher_사용시_get_stats_호출(self) -> None:
        """LLMEnricher → enricher.get_stats() 위임 확인"""
        service = EnrichmentService(_make_config())

        # LLMEnricher를 isinstance 체크를 통과하는 Mock으로 설정
        mock_stats = {"total_enrichments": 10, "success_rate": 90.0}

        with patch(
            "app.modules.core.enrichment.services.enrichment_service.LLMEnricher",
        ) as mock_cls:
            mock_instance = MagicMock(spec_set=["get_stats"])
            mock_instance.get_stats.return_value = mock_stats
            # isinstance(service.enricher, LLMEnricher)가 True가 되도록 설정
            mock_cls.return_value = mock_instance
            service.enricher = mock_instance

            # isinstance 체크를 위해 LLMEnricher 클래스 패치
            # MagicMock은 isinstance 체크를 통과하지 못하므로
            # 실제 분기에서 else로 갈 수 있음 → 직접 타입 검증
            # 대신 LLMEnricher 인스턴스를 실제로 만들어서 테스트
            pass

        # 실제 LLMEnricher isinstance 체크를 통과하는 방법:
        # LLMEnricher를 직접 import하고 __class__를 패치
        from app.modules.core.enrichment.enrichers.llm_enricher import LLMEnricher

        mock_enricher = MagicMock(spec=LLMEnricher)
        mock_enricher.get_stats.return_value = mock_stats
        service.enricher = mock_enricher

        stats = service.get_stats()
        assert stats == mock_stats
        mock_enricher.get_stats.assert_called_once()

    def test_enricher_None_비활성_통계(self) -> None:
        """enricher=None → NullEnricher 분기 통계 (else 경로)"""
        service = EnrichmentService(_make_config())
        # enricher가 None이면 isinstance(None, LLMEnricher) = False → else
        stats = service.get_stats()
        assert stats == {"enabled": False, "enricher_type": "NullEnricher"}
