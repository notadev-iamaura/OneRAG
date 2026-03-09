"""
SQL Search 모듈

LLM 기반 SQL 생성 및 실행을 통한 메타데이터 검색 시스템입니다.
RAG 파이프라인과 병렬로 실행되어 정확한 수치 정보를 제공합니다.

주요 컴포넌트:
- SQLGenerator: LLM을 사용하여 SQL 쿼리 생성
- QueryExecutor: PostgreSQL에서 SQL 실행
- ResultFormatter: 결과를 사람이 읽기 쉬운 형식으로 변환
- SQLSearchService: 전체 파이프라인 통합

사용 예:
    from app.modules.core.sql_search import SQLSearchService

    service = SQLSearchService(config, db_manager)
    result = await service.search("가격이 저렴한 서비스 추천해줘")

    if result.used:
        print(result.formatted_context)
        # [SQL 검색 결과]
        # 1. 항목A: 55,000원
        # 2. 항목B: 66,000원
"""

from .query_executor import QueryExecutor, QueryResult
from .result_formatter import ResultFormatter
from .service import SingleQueryResult, SQLSearchResult, SQLSearchService
from .sql_generator import SingleSQLQuery, SQLGenerationResult, SQLGenerator

__all__ = [
    # Service (통합)
    "SQLSearchService",
    "SQLSearchResult",
    "SingleQueryResult",  # 멀티 쿼리 개별 결과
    # Generator
    "SQLGenerator",
    "SQLGenerationResult",
    "SingleSQLQuery",  # 멀티 쿼리 단일 쿼리 정보
    # Executor
    "QueryExecutor",
    "QueryResult",
    # Formatter
    "ResultFormatter",
]
