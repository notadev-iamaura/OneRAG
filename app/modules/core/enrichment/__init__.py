"""
LLM 문서 보강 (Enrichment) 모듈

문서 로드 시 LLM을 사용하여 메타데이터를 자동으로 생성하는 기능을 제공합니다.

주요 기능:
- 카테고리 자동 분류 (category, subcategory)
- 의도 파악 (intent)
- 콘텐츠 유형 분류 (content_type)
- 키워드 추출 (keywords)
- 요약문 생성 (summary)
- 도구 관련 여부 판단 (is_tool_related)
- DB 확인 필요 여부 (requires_db_check)

사용 예시:
    >>> from app.modules.core.enrichment import EnrichmentService
    >>> from app.lib.config_loader import load_config
    >>>
    >>> config = load_config()
    >>> enrichment_service = EnrichmentService(config)
    >>> await enrichment_service.initialize()
    >>>
    >>> # 단일 문서 보강
    >>> document = {"content": "Python 리스트 컴프리헨션 사용법에 대한 설명입니다."}
    >>> enriched = await enrichment_service.enrich(document)
    >>>
    >>> # 배치 처리
    >>> documents = [{"content": "..."}, {"content": "..."}]
    >>> enriched_docs = await enrichment_service.enrich_batch(documents)

작성일: 2025-11-07
목적: LLM 기반 문서 메타데이터 자동 생성
"""

from .interfaces.enricher_interface import EnricherInterface
from .schemas.enrichment_schema import EnrichmentConfig, EnrichmentResult
from .services.enrichment_service import EnrichmentService

__all__ = [
    "EnrichmentService",
    "EnrichmentResult",
    "EnrichmentConfig",
    "EnricherInterface",
]
