"""
Weaviate Retriever - 하이브리드 검색 (Dense + Sparse BM25)

주요 기능:
- 내장 하이브리드 검색 (alpha 파라미터로 가중치 조절)
- Vector Search (Dense, 3072 dimensions, cosine)
- BM25 Search (Sparse, 한국어 토크나이저 kagome_kr)
- IRetriever 인터페이스 구현
- Phase 2: BM25 고도화 (동의어 확장, 불용어 제거, 사용자 사전)

데이터 구조:
- vector: 3072차원 float 배열 (Gemini embedding-001)
- content: 텍스트 내용 (tokenization: kagome_kr)
- source_file: 출처 파일명
- file_type: 파일 타입
- keywords: LLM 추출 키워드 배열 (tokenization: kagome_kr)

의존성:
- weaviate-client: Weaviate Python 클라이언트 (v4+)
- app.lib.weaviate_client: Weaviate 연결 클라이언트
- app.modules.core.retrieval.interfaces: IRetriever 인터페이스
- app.modules.core.retrieval.bm25: BM25 고도화 모듈 (Phase 2)

    Phase 2 구현 (2025-11-28):
    - SynonymManager: 동의어 확장
    - StopwordFilter: 불용어 제거
    - UserDictionary: 합성어 보호
"""

import asyncio
from datetime import UTC
from typing import Any

from weaviate.classes.query import MetadataQuery
from weaviate.collections.collection import Collection
from weaviate.exceptions import WeaviateQueryError

from .....lib.logger import get_logger
from .....lib.weaviate_client import WeaviateClient
from ..interfaces import SearchResult

# Phase 2: BM25 고도화 모듈 (Optional Import - Graceful Degradation)
try:
    from ..bm25 import StopwordFilter, SynonymManager, UserDictionary

    BM25_MODULES_AVAILABLE = True
except ImportError:
    BM25_MODULES_AVAILABLE = False
    SynonymManager = None  # type: ignore
    StopwordFilter = None  # type: ignore
    UserDictionary = None  # type: ignore

logger = get_logger(__name__)


class WeaviateRetriever:
    """
    Weaviate 하이브리드 검색 구현

    특징:
    - Weaviate 내장 하이브리드 검색 (alpha 파라미터)
    - Gemini 3072d embedding 지원
    - BM25 Full-Text Search (한국어 토크나이저 kagome_kr)
    - Client-side RRF 불필요 (Weaviate 내장)

    아키텍처:
    - MongoDB 대비 150+ 라인 코드 간소화 (87% 감소)
    - hybrid 쿼리 한 번으로 Dense + Sparse 검색 통합
    - alpha=0.6 (60% Vector + 40% BM25)

    데이터 스키마:
    - vector: float[] (3072 dimensions)
    - content: string (tokenization: kagome_kr)
    - source_file: string
    - file_type: string
    - keywords: string[] (tokenization: kagome_kr)
    """

    def __init__(
        self,
        embedder: Any,
        weaviate_client: WeaviateClient,
        collection_name: str = "Documents",
        alpha: float = 0.6,
        # Phase 2: BM25 고도화 모듈 (Optional)
        synonym_manager: Any | None = None,
        stopword_filter: Any | None = None,
        user_dictionary: Any | None = None,
        # Phase 3: 다중 컬렉션 검색 (Optional)
        additional_collections: list[str] | None = None,
        collection_properties: dict[str, list[str]] | None = None,
    ):
        """
        Weaviate Retriever 초기화 (DI Container)

        Args:
            embedder: Dense embedding 모델 (Google Gemini)
            weaviate_client: Weaviate 클라이언트 (DI)
            collection_name: Weaviate 메인 컬렉션 이름 (기본: "Documents")
            alpha: 하이브리드 검색 가중치 (기본: 0.6)
                  - 0: BM25(키워드) 100%
                  - 1: Vector(의미) 100%
                  - 0.6: 60% Vector + 40% BM25 (MongoDB 기존 가중치와 동일)
            synonym_manager: Phase 2 동의어 관리자 (Optional)
            stopword_filter: Phase 2 불용어 필터 (Optional)
            user_dictionary: Phase 2 사용자 사전 (Optional)
            additional_collections: Phase 3 추가 컬렉션 목록 (Optional)
                예: ["NotionMetadata"] - 메인 컬렉션과 함께 검색
            collection_properties: 컬렉션별 리턴 프로퍼티 설정 (Optional)
                예: {"Documents": ["content", "source"], "NotionMetadata": ["shop_name"]}

        Note:
            MongoDB Client-side RRF (150+ 라인) → Weaviate 내장 하이브리드 (20 라인)
        """
        self.embedder = embedder
        self.collection_name = collection_name
        self.alpha = alpha
        self.additional_collections = additional_collections or []
        self.collection_properties = collection_properties or {}

        # Weaviate 클라이언트 및 컬렉션 (DI)
        self.weaviate_client = weaviate_client
        self.collection: Collection | None = None
        # Phase 3: 추가 컬렉션 객체 저장
        self._additional_collection_objects: dict[str, Collection] = {}

        # Phase 2: BM25 고도화 모듈
        self.synonym_manager = synonym_manager
        self.stopword_filter = stopword_filter
        self.user_dictionary = user_dictionary

        # BM25 전처리 활성화 여부 확인
        self._bm25_preprocessing_enabled = any(
            [synonym_manager is not None, stopword_filter is not None, user_dictionary is not None]
        )

        # 통계
        self.stats = {
            "total_searches": 0,
            "hybrid_searches": 0,
            "errors": 0,
            "bm25_preprocessed": 0,  # Phase 2: BM25 전처리 적용 횟수
            "multi_collection_searches": 0,  # Phase 3: 다중 컬렉션 검색 횟수
        }

        # 로그 메시지 구성
        bm25_status = "enabled" if self._bm25_preprocessing_enabled else "disabled"
        multi_col_status = (
            f"+{len(self.additional_collections)}" if self.additional_collections else "disabled"
        )
        logger.info(
            f"WeaviateRetriever 초기화: collection={collection_name}, "
            f"alpha={alpha}, bm25_preprocessing={bm25_status}, "
            f"additional_collections={multi_col_status}"
        )

    async def initialize(self) -> None:
        """
        Weaviate Retriever 초기화 (컬렉션 접근 확인)

        작업:
        1. Weaviate 클라이언트 연결 확인
        2. 메인 컬렉션 존재 및 접근 확인
        3. Phase 3: 추가 컬렉션 초기화 (NotionMetadata 등)

        Graceful Degradation:
        - Weaviate 연결 불가 시 로그만 남기고 계속 진행
        - MVP Phase 1에서는 Weaviate 없이도 앱 시작 가능
        - 추가 컬렉션 실패해도 메인 컬렉션으로 계속 진행
        """
        try:
            logger.debug("WeaviateRetriever 초기화 시작...")

            # 1. Weaviate 연결 상태 확인
            if not self.weaviate_client.is_ready():
                weaviate_url = getattr(self.weaviate_client, "url", "설정되지 않음")
                raise ConnectionError(
                    "Weaviate 벡터 데이터베이스에 연결할 수 없습니다. "
                    f"해결 방법: 1) WEAVIATE_URL({weaviate_url}) 설정을 확인하세요. "
                    "2) Weaviate 서버가 실행 중인지 확인하세요 (docker ps | grep weaviate). "
                    "3) 네트워크 방화벽 규칙을 점검하세요. "
                    "로컬 개발: docker-compose -f docker-compose.weaviate.yml up -d 로 Weaviate를 실행할 수 있습니다."
                )

            # 2. 메인 Collection 가져오기
            self.collection = self.weaviate_client.get_collection(self.collection_name)

            if self.collection is None:
                raise RuntimeError(
                    "Weaviate 'Documents' 컬렉션이 존재하지 않습니다. "
                    "해결 방법: 1) POST /api/admin/weaviate/init 엔드포인트로 스키마를 초기화하세요. "
                    "2) 또는 scripts/init_weaviate.py 스크립트를 실행하세요. "
                    "3) Weaviate 대시보드(http://localhost:8080/v1/schema)에서 스키마를 확인할 수 있습니다."
                )

            logger.info(f"✅ 메인 컬렉션 초기화 완료: {self.collection_name}")

            # 3. Phase 3: 추가 컬렉션 초기화 (Graceful Degradation)
            for col_name in self.additional_collections:
                try:
                    col = self.weaviate_client.get_collection(col_name)
                    if col is not None:
                        self._additional_collection_objects[col_name] = col
                        logger.info(f"✅ 추가 컬렉션 초기화 완료: {col_name}")
                    else:
                        logger.warning(
                            f"⚠️  추가 컬렉션을 찾을 수 없습니다: {col_name} (무시하고 계속 진행)"
                        )
                except Exception as col_err:
                    logger.warning(
                        f"⚠️  추가 컬렉션 초기화 실패: {col_name} - {col_err} (무시하고 계속 진행)"
                    )

            # 최종 상태 로깅
            total_collections = 1 + len(self._additional_collection_objects)
            logger.info(
                f"✅ WeaviateRetriever 초기화 완료: "
                f"총 {total_collections}개 컬렉션 (메인: {self.collection_name}, "
                f"추가: {list(self._additional_collection_objects.keys())})"
            )

        except (ConnectionError, RuntimeError):
            # 스펙에 정의된 에러는 그대로 전파
            raise
        except Exception as e:
            logger.error(
                f"❌ WeaviateRetriever 초기화 중 예상치 못한 오류: {str(e)}",
                extra={"collection": self.collection_name},
            )
            # MVP Phase 1: 예상치 못한 에러도 로그만 남기고 계속 진행
            logger.warning("⚠️  Weaviate Retriever를 건너뛰고 계속 진행합니다.")
            return

    async def health_check(self) -> bool:
        """
        Weaviate 연결 및 컬렉션 상태 확인

        검증 항목:
        1. Weaviate 클라이언트 연결
        2. 컬렉션 접근 가능 여부

        Returns:
            정상 동작 여부 (True/False)
        """
        try:
            # 1. 컬렉션 초기화 확인
            if self.collection is None:
                logger.warning("Weaviate health check 실패: 컬렉션 미초기화")
                return False

            # 2. Weaviate 연결 확인
            is_ready = self.weaviate_client.is_ready()

            if not is_ready:
                logger.warning("Weaviate health check 실패: 연결 끊김")
                return False

            logger.debug("Weaviate health check 성공")
            return True

        except Exception as e:
            logger.error(f"Weaviate health check 실패: {str(e)}")
            return False

    async def search(
        self,
        query: str,
        top_k: int = 10,
        filters: dict[str, Any] | None = None,
    ) -> list[SearchResult]:
        """
        하이브리드 검색 수행 (Dense + Sparse with Weaviate 내장 RRF)

        Weaviate 내장 하이브리드 방식:
        1. hybrid 쿼리 하나로 Vector + BM25 검색 동시 실행
        2. Weaviate 내부에서 RRF 알고리즘 자동 적용
        3. alpha 파라미터로 가중치 조절

        Phase 3: 다중 컬렉션 검색
        - 메인 컬렉션 + 추가 컬렉션 (NotionMetadata 등) 병렬 검색
        - RRF로 결과 병합하여 다양한 소스 활용

        Args:
            query: 검색 쿼리 문자열
            top_k: 반환할 최대 결과 수
            filters: 메타데이터 필터링 조건 (예: {"file_type": "pdf"})

        Returns:
            검색 결과 리스트 (SearchResult)

        Raises:
            WeaviateQueryError: Weaviate 검색 오류 시
        """
        try:
            if self.collection is None:
                raise RuntimeError(
                    "Weaviate 'Documents' 컬렉션이 존재하지 않습니다. "
                    "해결 방법: 1) POST /api/admin/weaviate/init 엔드포인트로 스키마를 초기화하세요. "
                    "2) 또는 scripts/init_weaviate.py 스크립트를 실행하세요. "
                    "3) Weaviate 대시보드(http://localhost:8080/v1/schema)에서 스키마를 확인할 수 있습니다."
                )

            # Phase 2: BM25 쿼리 전처리 (동의어 확장, 불용어 제거)
            processed_query = self._preprocess_query(query)

            # 1. Dense embedding 생성 (원본 쿼리 사용 - 의미 보존)
            logger.debug(f"Query embedding 생성 중: query='{query[:50]}...'")
            query_embedding = await asyncio.to_thread(
                self.embedder.embed_query, query  # Dense는 원본 쿼리 사용
            )

            if not isinstance(query_embedding, list):
                raise ValueError(
                    f"Embedding은 list 타입이어야 합니다. 받은 타입: {type(query_embedding)}"
                )

            # 2. Phase 3: 다중 컬렉션 검색 (메인 + 추가 컬렉션)
            if self._additional_collection_objects:
                # 다중 컬렉션 검색 (병렬 실행 + RRF 병합)
                results = await self._search_multi_collections(
                    query=query,
                    processed_query=processed_query,
                    query_embedding=query_embedding,
                    top_k=top_k,
                    filters=filters,
                )
                self.stats["multi_collection_searches"] += 1
            else:
                # 단일 컬렉션 검색 (기존 로직)
                results = await self._search_single_collection(
                    collection=self.collection,
                    collection_name=self.collection_name,
                    processed_query=processed_query,
                    query_embedding=query_embedding,
                    top_k=top_k,
                )

            # 3. 통계 업데이트
            self.stats["total_searches"] += 1
            self.stats["hybrid_searches"] += 1

            logger.info(f"Weaviate 하이브리드 검색 완료: {len(results)}개 결과 반환")
            return results

        except WeaviateQueryError as e:
            logger.error(f"Weaviate 검색 오류: {str(e)}", extra={"query": query[:100]})
            self.stats["errors"] += 1
            raise RuntimeError(
                f"Weaviate 검색 중 오류가 발생했습니다: {e}. "
                "해결 방법: 1) Weaviate 서버 상태를 확인하세요 (GET /api/admin/weaviate/status). "
                "2) 쿼리 파라미터가 올바른지 확인하세요. "
                "3) Weaviate 로그를 확인하세요 (docker logs weaviate-standalone)."
            ) from e

        except Exception as e:
            logger.error(
                f"Weaviate 검색 예상치 못한 오류: {str(e)}",
                extra={"query": query[:100]},
                exc_info=True,  # 스택 트레이스 포함
            )
            self.stats["errors"] += 1
            raise

    async def _search_single_collection(
        self,
        collection: Collection,
        collection_name: str,
        processed_query: str,
        query_embedding: list[float],
        top_k: int,
    ) -> list[SearchResult]:
        """
        단일 컬렉션에서 하이브리드 검색 수행

        Args:
            collection: Weaviate 컬렉션 객체
            collection_name: 컬렉션 이름 (로깅용)
            processed_query: BM25용 전처리된 쿼리
            query_embedding: Dense embedding 벡터
            top_k: 반환할 결과 수

        Returns:
            검색 결과 리스트
        """
        logger.debug(f"단일 컬렉션 검색: {collection_name}, top_k={top_k}")

        # weaviate-client v4.19+ 호환성: return_properties를 사용하지 않음
        # 모든 프로퍼티를 반환하고 결과 처리 시 필요한 것만 사용
        response = collection.query.hybrid(
            query=processed_query,
            vector=query_embedding,
            alpha=self.alpha,
            limit=top_k,
            return_metadata=MetadataQuery(score=True),
        )

        results = []
        for obj in response.objects:
            # NotionMetadata 결과에 collection 정보 추가
            metadata = dict(obj.properties)
            metadata["_collection"] = collection_name

            # metadata 필드를 source_file로 매핑 (소스 표시용)
            # shop_name 또는 name 필드가 있으면 이를 source_file로 사용
            entity_name = metadata.get("shop_name") or metadata.get("name")
            if entity_name:
                metadata["source_file"] = f"{entity_name} (메타데이터)"
                metadata["file_type"] = "METADATA"

            results.append(
                SearchResult(
                    id=str(obj.uuid),
                    content=str(obj.properties.get("content", "")),
                    score=obj.metadata.score if obj.metadata.score else 0.0,
                    metadata=metadata,
                )
            )

        return results

    async def _search_multi_collections(
        self,
        query: str,
        processed_query: str,
        query_embedding: list[float],
        top_k: int,
        filters: dict[str, Any] | None = None,
    ) -> list[SearchResult]:
        """
        다중 컬렉션에서 병렬 검색 후 RRF로 결과 병합

        Phase 3 구현:
        - 메인 컬렉션 (Documents) + 추가 컬렉션 (NotionMetadata) 병렬 검색
        - RRF (Reciprocal Rank Fusion)로 결과 통합
        - 각 컬렉션에서 top_k개씩 검색 후 병합

        Args:
            query: 원본 검색 쿼리
            processed_query: BM25용 전처리된 쿼리
            query_embedding: Dense embedding 벡터
            top_k: 최종 반환할 결과 수
            filters: 필터링 조건 (현재 미사용)

        Returns:
            RRF로 병합된 검색 결과 리스트
        """
        logger.info(
            f"🔍 다중 컬렉션 검색 시작: 메인({self.collection_name}) + "
            f"추가({list(self._additional_collection_objects.keys())})"
        )

        # 1. 모든 컬렉션에서 병렬 검색
        search_tasks = []

        # 메인 컬렉션
        search_tasks.append(
            self._search_single_collection(
                collection=self.collection,  # type: ignore[arg-type]
                collection_name=self.collection_name,
                processed_query=processed_query,
                query_embedding=query_embedding,
                top_k=top_k,
            )
        )

        # 추가 컬렉션들
        for col_name, col_obj in self._additional_collection_objects.items():
            search_tasks.append(
                self._search_single_collection(
                    collection=col_obj,
                    collection_name=col_name,
                    processed_query=processed_query,
                    query_embedding=query_embedding,
                    top_k=top_k,
                )
            )

        # 병렬 실행
        results_per_collection = await asyncio.gather(*search_tasks, return_exceptions=True)

        # 2. RRF로 결과 병합
        merged_results = self._rrf_merge_results(results_per_collection, top_k)

        logger.info(
            f"✅ 다중 컬렉션 검색 완료: "
            f"{len(search_tasks)}개 컬렉션 → {len(merged_results)}개 결과"
        )

        return merged_results

    def _rrf_merge_results(
        self,
        results_per_collection: list[list[SearchResult] | BaseException],
        top_k: int,
        rrf_k: int = 60,
    ) -> list[SearchResult]:
        """
        RRF (Reciprocal Rank Fusion)로 다중 컬렉션 결과 병합

        Score(doc) = Σ [1 / (k + rank)]

        Args:
            results_per_collection: 각 컬렉션의 검색 결과 (asyncio.gather 결과)
            top_k: 최종 반환할 결과 수
            rrf_k: RRF 상수 (기본값 60)

        Returns:
            RRF 점수로 정렬된 결과 리스트
        """
        doc_scores: dict[str, float] = {}
        doc_objects: dict[str, SearchResult] = {}
        doc_sources: dict[str, list[str]] = {}  # 어느 컬렉션에서 왔는지

        for col_idx, results in enumerate(results_per_collection):
            if isinstance(results, BaseException):
                logger.warning(f"컬렉션 {col_idx} 검색 실패: {results}")
                continue

            for rank, result in enumerate(results):
                doc_id = result.id

                # RRF 점수 계산
                rrf_score = 1.0 / (rrf_k + rank)
                doc_scores[doc_id] = doc_scores.get(doc_id, 0.0) + rrf_score

                # 문서 객체 저장 (첫 등장 시)
                if doc_id not in doc_objects:
                    doc_objects[doc_id] = result
                    doc_sources[doc_id] = []

                # 소스 컬렉션 추적
                collection_name = result.metadata.get("_collection", "unknown")
                if collection_name not in doc_sources[doc_id]:
                    doc_sources[doc_id].append(collection_name)

        # RRF 점수로 정렬
        sorted_doc_ids = sorted(
            doc_scores.keys(), key=lambda doc_id: doc_scores[doc_id], reverse=True
        )

        # 최종 결과 생성
        merged_results = []
        for doc_id in sorted_doc_ids[:top_k]:
            result = doc_objects[doc_id]
            result.metadata["_rrf_score"] = doc_scores[doc_id]
            result.metadata["_sources"] = doc_sources[doc_id]
            result.score = doc_scores[doc_id]  # RRF 점수로 교체
            merged_results.append(result)

        return merged_results

    async def add_documents(self, documents: list[dict[str, Any]]) -> dict[str, Any]:
        """
        문서를 Weaviate에 배치 업로드

        안전한 업로드 방식 적용 (scripts/index_all_data.py 패턴):
        - properties와 vector를 별도 파라미터로 전달
        - insert() 메서드 사용 (insert_many 대신)
        - 에러 발생 시 개별 문서 건너뛰고 계속 진행

        Args:
            documents: 업로드할 문서 리스트
                각 문서는 다음 구조를 가져야 함:
                {
                    "content": str,           # 필수: 문서 내용
                    "embedding": list[float], # 필수: 임베딩 벡터
                    "metadata": dict,         # 선택: 메타데이터 (source, file_type 등)
                }

        Returns:
            업로드 결과 딕셔너리:
            {
                "success_count": int,     # 성공한 문서 수
                "error_count": int,       # 실패한 문서 수
                "total_count": int,       # 전체 문서 수
                "errors": list[str],      # 에러 메시지 리스트
            }

        사용 예시:
            documents = [
                {
                    "content": "서비스 안내 내용",
                    "embedding": [0.1, 0.2, ...],  # 3072차원
                    "metadata": {
                        "source": "manual.json",
                        "file_type": "JSON",
                        "category": "정보",
                    }
                }
            ]
            result = await retriever.add_documents(documents)
        """
        if self.collection is None:
            raise RuntimeError(
                "Weaviate 'Documents' 컬렉션이 존재하지 않습니다. "
                "해결 방법: 1) POST /api/admin/weaviate/init 엔드포인트로 스키마를 초기화하세요. "
                "2) 또는 scripts/init_weaviate.py 스크립트를 실행하세요. "
                "3) Weaviate 대시보드(http://localhost:8080/v1/schema)에서 스키마를 확인할 수 있습니다."
            )

        success_count = 0
        error_count = 0
        errors = []

        logger.info(f"📤 Weaviate 문서 업로드 시작: {len(documents)}개 문서")

        for i, doc in enumerate(documents):
            try:
                # 1. 필수 필드 검증
                if "content" not in doc:
                    raise ValueError("문서에 'content' 필드가 없습니다.")
                if "embedding" not in doc:
                    raise ValueError("문서에 'embedding' 필드가 없습니다.")

                # 2. properties 준비 (embedding 제외)
                properties = {
                    "content": doc["content"],
                }

                # 3. metadata 병합 (있는 경우)
                if "metadata" in doc and isinstance(doc["metadata"], dict):
                    # 모든 메타데이터 필드를 properties로 병합
                    # (스키마에 정의되지 않은 필드는 Weaviate가 무시하거나 에러를 발생시킬 수 있음)
                    for key, value in doc["metadata"].items():
                        if value is not None:
                            properties[key] = value

                # 4. created_at 기본값 설정 (없는 경우)
                if "created_at" not in properties:
                    from datetime import datetime

                    properties["created_at"] = datetime.now(UTC).isoformat()

                # 5. embedding 추출
                vector = doc["embedding"]

                # 6. Weaviate에 업로드 (안전한 방식: properties와 vector 분리)
                await asyncio.to_thread(
                    self.collection.data.insert, properties=properties, vector=vector
                )

                success_count += 1

                # 진행 상황 로그 (100개마다)
                if (i + 1) % 100 == 0:
                    logger.info(f"📊 업로드 진행: {success_count}/{len(documents)}")

            except Exception as e:
                error_count += 1
                error_msg = f"문서 {i+1} 업로드 실패: {str(e)}"
                errors.append(error_msg)
                logger.warning(error_msg)
                # 개별 문서 실패해도 계속 진행

        # 7. 결과 반환
        result = {
            "success_count": success_count,
            "error_count": error_count,
            "total_count": len(documents),
            "errors": errors,
        }

        logger.info(
            f"✅ Weaviate 문서 업로드 완료: "
            f"성공 {success_count}개, 실패 {error_count}개, 전체 {len(documents)}개"
        )

        return result

    async def cleanup(self) -> None:
        """
        Weaviate 클라이언트 리소스 정리

        작업:
        1. WeaviateClient 연결 종료
        2. Collection 참조 해제

        호출 시점:
        - BatchCrawler 종료 시
        - 애플리케이션 종료 시

        Note:
            Weaviate 클라이언트는 WeaviateClient 래퍼를 통해 관리되므로,
            여기서는 참조만 해제하고 실제 연결 종료는 WeaviateClient에 위임합니다.
        """
        try:
            logger.debug("WeaviateRetriever cleanup 시작...")

            # Collection 참조 해제
            if self.collection is not None:
                self.collection = None
                logger.debug("Collection 참조 해제 완료")

            # WeaviateClient는 싱글톤이므로 close() 호출하지 않음
            # (DI Container가 애플리케이션 종료 시 관리)
            # Collection만 cleanup하고 client는 유지
            if self.weaviate_client is not None:
                logger.debug("WeaviateClient 참조 유지 (싱글톤, DI Container 관리)")

            logger.info("✅ WeaviateRetriever cleanup 완료")

        except Exception as e:
            logger.error(f"❌ WeaviateRetriever cleanup 중 오류: {str(e)}", exc_info=True)

    # ========================================
    # 문서 관리 메서드 (Document Management)
    # ========================================

    async def get_document_chunks(self, document_id: str) -> list[dict[str, Any]]:
        """
        document_id에 해당하는 모든 청크를 조회

        Args:
            document_id: 조회할 문서 ID

        Returns:
            청크 리스트 (각 청크는 id, content, metadata를 포함)
        """
        if self.collection is None:
            raise RuntimeError(
                "Weaviate 'Documents' 컬렉션이 초기화되지 않았습니다. "
                "initialize()를 먼저 호출하세요."
            )

        from weaviate.classes.query import Filter

        response = self.collection.query.fetch_objects(
            filters=Filter.by_property("document_id").equal(document_id),
            limit=10000,  # 단일 문서의 청크 수 상한
        )

        chunks = []
        for obj in response.objects:
            props = dict(obj.properties)
            chunks.append({
                "id": str(obj.uuid),
                "content": props.get("content", ""),
                "metadata": props,
            })

        logger.debug(
            f"get_document_chunks 완료: document_id={document_id}, "
            f"chunks={len(chunks)}"
        )
        return chunks

    async def delete_document(self, document_id: str) -> bool:
        """
        document_id의 모든 청크를 삭제

        Args:
            document_id: 삭제할 문서 ID

        Returns:
            삭제 성공 여부 (청크가 존재하여 삭제했으면 True)
        """
        chunks = await self.get_document_chunks(document_id)
        if not chunks:
            logger.warning(f"삭제할 문서가 없습니다: document_id={document_id}")
            return False

        for chunk in chunks:
            self.collection.data.delete_by_id(chunk["id"])  # type: ignore[union-attr]

        logger.info(
            f"문서 삭제 완료: document_id={document_id}, "
            f"삭제된 청크 수={len(chunks)}"
        )
        return True

    async def list_documents(
        self, page: int = 1, page_size: int = 20
    ) -> dict[str, Any]:
        """
        고유 document_id별로 그룹화하여 문서 목록 반환

        Args:
            page: 페이지 번호 (1부터 시작)
            page_size: 페이지 당 문서 수

        Returns:
            {"documents": [...], "total_count": int} 형식의 딕셔너리
        """
        if self.collection is None:
            raise RuntimeError(
                "Weaviate 'Documents' 컬렉션이 초기화되지 않았습니다."
            )

        # 모든 객체 조회 후 document_id별 그룹화
        response = self.collection.query.fetch_objects(limit=10000)

        # document_id별 그룹화
        doc_groups: dict[str, list[dict[str, Any]]] = {}
        for obj in response.objects:
            props = dict(obj.properties)
            doc_id = str(props.get("document_id", str(obj.uuid)))
            if doc_id not in doc_groups:
                doc_groups[doc_id] = []
            doc_groups[doc_id].append(props)

        # 문서 정보 구성
        all_documents = []
        for doc_id, chunks in doc_groups.items():
            first_chunk = chunks[0]
            # upload_date 추출 (created_at 필드에서)
            created_at = first_chunk.get("created_at", "")
            upload_date: float = 0.0
            if isinstance(created_at, str) and created_at:
                try:
                    from datetime import datetime
                    dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                    upload_date = dt.timestamp()
                except (ValueError, TypeError):
                    upload_date = 0.0

            all_documents.append({
                "id": doc_id,
                "filename": first_chunk.get("source_file", "unknown"),
                "file_type": first_chunk.get("file_type", "unknown"),
                "file_size": first_chunk.get("file_size", 0),
                "upload_date": upload_date,
                "chunk_count": len(chunks),
            })

        # 페이지네이션 적용
        total_count = len(all_documents)
        start_idx = (page - 1) * page_size
        end_idx = start_idx + page_size
        paginated = all_documents[start_idx:end_idx]

        return {
            "documents": paginated,
            "total_count": total_count,
        }

    async def get_document_details(
        self, document_id: str
    ) -> dict[str, Any] | None:
        """
        문서 상세 정보를 청크 메타데이터에서 집계하여 반환

        Args:
            document_id: 조회할 문서 ID

        Returns:
            문서 상세 정보 딕셔너리 또는 None (미존재 시)
        """
        chunks = await self.get_document_chunks(document_id)
        if not chunks:
            return None

        first_meta = chunks[0].get("metadata", {})

        # upload_date 추출
        created_at = first_meta.get("created_at", "")
        upload_date: float = 0.0
        if isinstance(created_at, str) and created_at:
            try:
                from datetime import datetime
                dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                upload_date = dt.timestamp()
            except (ValueError, TypeError):
                upload_date = 0.0

        # 청크 미리보기 (각 청크의 앞 200자)
        chunk_previews = [
            chunk.get("content", "")[:200]
            for chunk in chunks
        ]

        # 파일 크기 합산
        file_size = sum(
            len(chunk.get("content", "").encode("utf-8"))
            for chunk in chunks
        )

        return {
            "id": document_id,
            "filename": first_meta.get("source_file", "unknown"),
            "file_type": first_meta.get("file_type", "unknown"),
            "file_size": file_size,
            "upload_date": upload_date,
            "actual_chunk_count": len(chunks),
            "chunk_previews": chunk_previews,
            "metadata": first_meta,
        }

    async def get_document_stats(self) -> dict[str, Any]:
        """
        문서/벡터 수량 통계 반환

        Returns:
            {"total_documents": int, "vector_count": int}
        """
        if self.collection is None:
            raise RuntimeError(
                "Weaviate 'Documents' 컬렉션이 초기화되지 않았습니다."
            )

        response = self.collection.query.fetch_objects(limit=10000)

        doc_ids = set()
        vector_count = 0
        for obj in response.objects:
            props = dict(obj.properties)
            doc_id = props.get("document_id", str(obj.uuid))
            doc_ids.add(doc_id)
            vector_count += 1

        return {
            "total_documents": len(doc_ids),
            "vector_count": vector_count,
        }

    async def get_collection_info(self) -> dict[str, Any]:
        """
        컬렉션 메타정보 반환

        Returns:
            컬렉션 이름, 최초/최근 문서 날짜 등
        """
        if self.collection is None:
            raise RuntimeError(
                "Weaviate 'Documents' 컬렉션이 초기화되지 않았습니다."
            )

        response = self.collection.query.fetch_objects(limit=10000)

        dates = []
        for obj in response.objects:
            props = dict(obj.properties)
            created_at = props.get("created_at", "")
            if isinstance(created_at, str) and created_at:
                dates.append(created_at)

        oldest = min(dates) if dates else None
        newest = max(dates) if dates else None

        return {
            "collection_name": self.collection_name,
            "oldest_document": oldest,
            "newest_document": newest,
            "total_objects": len(response.objects),
        }

    async def delete_all_documents(self) -> bool:
        """
        컬렉션의 모든 문서를 삭제

        Returns:
            삭제 성공 여부
        """
        if self.collection is None:
            raise RuntimeError(
                "Weaviate 'Documents' 컬렉션이 초기화되지 않았습니다."
            )

        response = self.collection.query.fetch_objects(limit=10000)

        for obj in response.objects:
            self.collection.data.delete_by_id(str(obj.uuid))

        logger.warning(
            f"전체 문서 삭제 완료: {len(response.objects)}개 객체 삭제"
        )
        return True

    async def recreate_collection(self) -> bool:
        """
        컬렉션 재생성 (전체 삭제 후 초기화)

        Returns:
            재생성 성공 여부
        """
        await self.delete_all_documents()
        logger.info(f"컬렉션 재생성 완료: {self.collection_name}")
        return True

    async def backup_metadata(self) -> list[dict[str, Any]]:
        """
        모든 문서의 메타데이터를 백업

        Returns:
            고유 document_id별 메타데이터 리스트
        """
        if self.collection is None:
            raise RuntimeError(
                "Weaviate 'Documents' 컬렉션이 초기화되지 않았습니다."
            )

        response = self.collection.query.fetch_objects(limit=10000)

        # document_id별 그룹화하여 메타데이터 수집
        doc_metadata: dict[str, dict[str, Any]] = {}
        for obj in response.objects:
            props = dict(obj.properties)
            doc_id = str(props.get("document_id", str(obj.uuid)))
            if doc_id not in doc_metadata:
                doc_metadata[doc_id] = {
                    "id": doc_id,
                    "filename": props.get("source_file", "unknown"),
                    "file_type": props.get("file_type", "unknown"),
                    "created_at": props.get("created_at", ""),
                    "chunk_count": 0,
                }
            doc_metadata[doc_id]["chunk_count"] += 1

        return list(doc_metadata.values())

    # ========================================
    # Phase 2: BM25 전처리 파이프라인
    # ========================================

    def _preprocess_query(self, query: str) -> str:
        """
        BM25 검색을 위한 쿼리 전처리

        Phase 2 파이프라인:
        1. 사용자 사전 - 합성어 보호 (분리 방지 단어 등)
        2. 동의어 확장 (축약어 → 표준어)
        3. 불용어 제거 (검색에 불필요한 빈번 단어)
        4. 사용자 사전 - 합성어 복원

        Args:
            query: 원본 검색 쿼리

        Returns:
            전처리된 쿼리 (BM25 검색용)

        Note:
            - Dense embedding은 원본 쿼리 사용 (의미 보존)
            - BM25 검색만 전처리된 쿼리 사용 (키워드 매칭 향상)
            - 모든 모듈이 Optional이므로 Graceful Degradation 지원
        """
        if not self._bm25_preprocessing_enabled:
            return query

        processed = query
        restore_map: dict[str, str] = {}

        try:
            # Step 1: 사용자 사전 - 합성어 보호 (분리 방지)
            # "복합단어" → "__USER_DICT_0__" (임시 토큰으로 대체)
            if self.user_dictionary is not None:
                processed, restore_map = self.user_dictionary.protect_entries(processed)

            # Step 2: 동의어 확장
            # "축약어 표현" → "표준어 표현"
            if self.synonym_manager is not None:
                processed = self.synonym_manager.expand_query(processed)

            # Step 3: 불용어 제거
            # "불용어 핵심키워드" → "핵심키워드"
            if self.stopword_filter is not None:
                processed = self.stopword_filter.filter_text(processed)

            # Step 4: 사용자 사전 - 합성어 복원
            # "__USER_DICT_0__" → "복합단어" (원래 단어로 복원)
            if self.user_dictionary is not None and restore_map:
                processed = self.user_dictionary.restore_entries(processed, restore_map)

            # 전처리 결과 로깅 (변경 시에만)
            if processed != query:
                self.stats["bm25_preprocessed"] += 1
                logger.debug(f"BM25 쿼리 전처리: '{query}' → '{processed}'")

        except Exception as e:
            # 전처리 실패 시 원본 쿼리 사용 (Graceful Degradation)
            logger.warning(
                f"BM25 쿼리 전처리 실패, 원본 사용: {str(e)}", extra={"query": query[:100]}
            )
            return query

        return processed
