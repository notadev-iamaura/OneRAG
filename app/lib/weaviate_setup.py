"""
Weaviate 스키마 초기화 모듈

주요 기능:
- Documents 스키마(Collection) 생성
- 기존 스키마 존재 확인
- Railway 배포 시 자동 초기화 지원
- 컬렉션 프로퍼티 정의의 단일 진실원천(single source of truth) 제공

설계 노트(도메인 범용화):
- 코어 스키마는 도메인 무관 필드(content/document_id/source_file/file_* 등)만
  정적으로 정의한다. category/quantity/score/location/entity_name 같은 특정 도메인
  (예: 도메인 특화 필드 field_a/field_b) 필드는 코어에서 분리한다.
- 임의 메타데이터는 이미 존재하는 `metadata_json` 단일 JSON 컬럼에 보존되므로
  타입 컬럼이 없어도 정보 손실이 없다(데이터 무손실).
- 운영자가 자기 도메인 필드를 인덱싱 가능한 컬럼으로 노출하려면 domain.yaml의
  `domain.metadata.schema_fields`에 정의한다. 정의 시 스키마 생성·검색 필터
  타입맵·관리자 응답에 코드 변경 없이 반영된다(설정 외부화).

의존성:
- app.lib.weaviate_client: Weaviate 연결
- app.lib.config_loader: domain.yaml(도메인 스키마 필드) 로드
- app.lib.logger: 로깅
"""

from typing import Any

from app.lib.logger import get_logger
from app.lib.weaviate_client import get_weaviate_client

logger = get_logger(__name__)

# ============================================================
# 컬렉션 프로퍼티 정의 — 단일 진실원천 (Single Source of Truth)
#
# (name, type, description) 튜플로 도메인 무관 코어 필드를 선언한다.
# type은 문자열 카테고리("text"|"int"|"number"|"text_array")로 표현하며,
# 실제 weaviate DataType 매핑은 _PROPERTY_TYPE_TO_DATATYPE에서 수행한다.
# 검색 리트리버(weaviate_retriever)는 이 정의에서 타입맵을 파생하므로
# 스키마와 필터 타입맵이 한 곳에서 동기화된다(중복 하드코딩 제거).
# ============================================================

# content는 BM25 토크나이즈 대상이라 별도 취급(tokenization=WORD)한다.
_CONTENT_PROPERTY_NAME = "content"

# 도메인 무관 코어 필드 정의: (name, type_category, description)
_CORE_PROPERTY_DEFS: list[tuple[str, str, str]] = [
    (_CONTENT_PROPERTY_NAME, "text", "문서 내용"),
    ("document_id", "text", "업로드/원문 문서 식별자"),
    ("source_file", "text", "출처 파일명"),
    ("filename", "text", "파일명 별칭"),
    ("file_name", "text", "파일명 별칭"),
    ("file_type", "text", "파일 타입"),
    ("file_path", "text", "원본 파일 경로"),
    ("file_hash", "text", "원본 파일 해시"),
    ("file_size", "int", "파일 크기(bytes)"),
    ("original_file_size", "int", "업로드 원본 파일 크기(bytes)"),
    ("chunk_index", "int", "청크 인덱스"),
    ("page", "int", "페이지 번호 별칭"),
    ("page_number", "int", "페이지 번호"),
    ("total_chunks", "int", "전체 청크 수"),
    ("char_count", "int", "청크 문자 수"),
    ("word_count", "int", "청크 단어 수"),
    ("load_timestamp", "number", "로드 시각 타임스탬프"),
    ("splitter_type", "text", "문서 분할 방식"),
    ("sheet_name", "text", "스프레드시트 시트명"),
    ("format", "text", "문서 포맷"),
    ("json_type", "text", "JSON 로딩 타입"),
    ("item_index", "int", "JSON 항목 인덱스"),
    ("total_items", "int", "JSON 전체 항목 수"),
    ("keys", "text_array", "JSON 키 목록"),
    ("json_loader", "text", "JSON 로더 종류"),
    ("jq_schema", "text", "JSONLoader jq schema"),
    ("content_key", "text", "JSONLoader content key"),
    ("source", "text", "데이터 출처"),
    ("created_at", "text", "생성 일시"),
    ("metadata_json", "text", "스키마에 없는 원본 메타데이터 JSON"),
]

# 도메인 스키마 필드가 type을 생략하면 적용할 기본 타입(텍스트).
_DEFAULT_DOMAIN_FIELD_TYPE = "text"
# 허용 타입 카테고리(미지원 값은 무시하고 기본 텍스트로 강등).
_SUPPORTED_PROPERTY_TYPES = {"text", "int", "number", "text_array"}


def _load_domain_schema_fields() -> list[tuple[str, str, str]]:
    """domain.yaml에서 운영자 정의 도메인 스키마 필드를 로드한다.

    범용 RAG OSS 기본은 도메인 중립이므로 schema_fields 미정의 시 빈 목록을
    반환한다(코어 스키마만 생성). 운영자는 domain.yaml의
    `domain.metadata.schema_fields`로 자기 도메인 필드를 옵트인 정의한다.

    지원 형식(둘 다 허용):
        schema_fields:
          - name: field_a
            type: text          # text|int|number|text_array (생략 시 text)
            description: 도메인 특화 필드 설명
        # 또는 간단 매핑 형식
        schema_fields:
          field_a: text
          field_b: text

    Returns:
        (name, type_category, description) 튜플 목록. 코어 필드와 이름이
        겹치거나 잘못된 정의는 안전하게 건너뛴다(graceful degradation).
    """
    try:
        # 지연 임포트: 모듈 임포트 시 config 로딩 부작용을 피한다.
        from app.lib.config_loader import load_config

        config = load_config()
    except Exception as e:  # 설정 로드 실패는 치명적이지 않다 — 코어만 사용
        logger.warning(f"도메인 스키마 필드 로드 실패(코어 스키마만 사용): {e}")
        return []

    raw = (
        config.get("domain", {})
        .get("metadata", {})
        .get("schema_fields", None)
    )
    if not raw:
        return []

    core_names = {name for name, _, _ in _CORE_PROPERTY_DEFS}
    parsed: list[tuple[str, str, str]] = []
    seen: set[str] = set()

    def _add(name: Any, type_category: Any, description: Any) -> None:
        if not isinstance(name, str) or not name.strip():
            return
        field_name = name.strip()
        # 코어 필드와 중복되면 코어 정의를 우선(스키마 일관성 보호).
        if field_name in core_names or field_name in seen:
            logger.warning(
                f"도메인 스키마 필드 무시(코어/중복): {field_name}"
            )
            return
        category = str(type_category or _DEFAULT_DOMAIN_FIELD_TYPE).strip().lower()
        if category not in _SUPPORTED_PROPERTY_TYPES:
            logger.warning(
                f"도메인 스키마 필드 '{field_name}' 미지원 타입 '{category}' "
                f"→ '{_DEFAULT_DOMAIN_FIELD_TYPE}'로 강등"
            )
            category = _DEFAULT_DOMAIN_FIELD_TYPE
        desc = str(description) if description else f"도메인 필드: {field_name}"
        parsed.append((field_name, category, desc))
        seen.add(field_name)

    if isinstance(raw, dict):
        # 간단 매핑 형식: {name: type}
        for name, type_category in raw.items():
            _add(name, type_category, None)
    elif isinstance(raw, list):
        # 상세 형식: [{name, type, description}, ...]
        for item in raw:
            if isinstance(item, dict):
                _add(item.get("name"), item.get("type"), item.get("description"))
            elif isinstance(item, str):
                _add(item, None, None)
    else:
        logger.warning(
            "domain.metadata.schema_fields는 dict 또는 list여야 합니다 — 무시"
        )

    if parsed:
        logger.info(
            f"도메인 스키마 필드 {len(parsed)}개 적용: "
            f"{[name for name, _, _ in parsed]}"
        )
    return parsed


def _document_property_defs() -> list[tuple[str, str, str]]:
    """코어 + 도메인 필드를 합친 전체 프로퍼티 정의(단일 진실원천).

    리트리버 타입맵·관리자 응답·스키마 생성이 모두 이 정의를 파생 기반으로
    삼아 중복 하드코딩을 제거한다.
    """
    return [*_CORE_PROPERTY_DEFS, *_load_domain_schema_fields()]


def document_property_types() -> dict[str, str]:
    """프로퍼티명 → 타입 카테고리("text"|"int"|"number"|"text_array") 매핑.

    weaviate_retriever가 필터 타입맵(_TEXT_PROPERTIES 등)을 파생할 때 사용하는
    단일 진실원천 진입점이다(스키마와 검색 타입맵 동기화).
    """
    return {name: type_category for name, type_category, _ in _document_property_defs()}


def _resolve_bm25_tokenization() -> Any:
    """content(BM25 대상) 필드의 토크나이저를 config에서 해석한다(기본 WORD).

    `weaviate.schema.bm25_tokenization`(문자열: word|whitespace|lowercase|field|
    trigram|gse|gse_ch|kagome_kr|kagome_ja)를 weaviate Tokenization enum으로
    매핑한다. 한국어 코퍼스는 kagome_kr, 일본어는 kagome_ja 등으로 BM25 품질을
    바꿀 수 있다. 미설정/미지원 값/로드 실패 시 WORD로 폴백한다(회귀 0).
    설치된 weaviate-client에 없는 enum 멤버는 매핑에서 자동 제외해 버전 안전하다.
    """
    from weaviate.classes.config import Tokenization

    name_map: dict[str, Any] = {}
    for key, attr in (
        ("word", "WORD"),
        ("whitespace", "WHITESPACE"),
        ("lowercase", "LOWERCASE"),
        ("field", "FIELD"),
        ("trigram", "TRIGRAM"),
        ("gse", "GSE"),
        ("gse_ch", "GSE_CH"),
        ("kagome_kr", "KAGOME_KR"),
        ("kagome_ja", "KAGOME_JA"),
    ):
        member = getattr(Tokenization, attr, None)
        if member is not None:
            name_map[key] = member

    try:
        # 지연 임포트: 모듈 임포트 시 config 로딩 부작용을 피한다.
        from app.lib.config_loader import load_config

        config = load_config()
        raw = config.get("weaviate", {}).get("schema", {}).get("bm25_tokenization")
    except Exception as e:  # 설정 로드 실패는 치명적이지 않다 — 기본 WORD 사용
        logger.warning(f"BM25 토크나이저 config 로드 실패(WORD 사용): {e}")
        return Tokenization.WORD

    if isinstance(raw, str):
        return name_map.get(raw.strip().lower(), Tokenization.WORD)
    return Tokenization.WORD


def _document_schema_properties() -> list[Any]:
    """Return the canonical Documents collection properties.

    코어 도메인 무관 필드 + domain.yaml로 정의된 도메인 필드를 합쳐
    weaviate Property 객체 목록으로 변환한다.
    """
    from weaviate.classes.config import DataType, Property

    content_tokenization = _resolve_bm25_tokenization()

    type_to_datatype = {
        "text": DataType.TEXT,
        "int": DataType.INT,
        "number": DataType.NUMBER,
        "text_array": DataType.TEXT_ARRAY,
    }

    properties: list[Any] = []
    for name, type_category, description in _document_property_defs():
        if name == _CONTENT_PROPERTY_NAME:
            # content는 BM25 토크나이즈 대상이라 별도 취급한다.
            properties.append(
                Property(
                    name=name,
                    data_type=DataType.TEXT,
                    description=description,
                    skip_vectorization=False,
                    tokenization=content_tokenization,
                )
            )
            continue
        properties.append(
            Property(
                name=name,
                data_type=type_to_datatype[type_category],
                description=description,
            )
        )
    return properties


def _collection_property_names(collection: Any) -> set[str]:
    """Read property names from a Weaviate v4 collection config."""
    config = collection.config.get(simple=True)
    properties = getattr(config, "properties", {})
    if isinstance(properties, dict):
        return set(properties)
    return {prop.name for prop in properties if getattr(prop, "name", None)}


def _ensure_document_schema_properties(client: Any, collection_name: str) -> int:
    """Add missing Documents properties to an existing collection."""
    collection = client.collections.get(collection_name)
    existing_names = _collection_property_names(collection)
    added_count = 0

    for prop in _document_schema_properties():
        if prop.name in existing_names:
            continue
        collection.config.add_property(prop)
        existing_names.add(prop.name)
        added_count += 1
        logger.info(f"✅ {collection_name} 누락 프로퍼티 추가: {prop.name}")

    return added_count


async def create_schema() -> bool:
    """
    Weaviate에 Documents 스키마(Collection) 생성

    이미 스키마가 존재하면 스킵합니다.

    Returns:
        bool: 생성 성공 시 True, 실패 시 False

    사용 예시:
        >>> from app.infrastructure.persistence.weaviate_setup import create_schema
        >>> await create_schema()
        ✅ Documents 스키마 생성 완료!
    """
    try:
        # Weaviate 클라이언트 가져오기
        weaviate_client = get_weaviate_client()

        if weaviate_client.client is None:
            logger.error("❌ Weaviate 클라이언트 연결 실패 - 스키마 생성 불가")
            return False

        client = weaviate_client.client

        # 기존 스키마(Collection) 확인
        collection_name = "Documents"

        # Collection이 이미 존재하는지 확인
        if client.collections.exists(collection_name):
            added_count = _ensure_document_schema_properties(client, collection_name)
            if added_count:
                logger.info(
                    f"✅ {collection_name} 스키마 보강 완료: {added_count}개 프로퍼티 추가"
                )
            else:
                logger.info(f"✅ {collection_name} 스키마 이미 최신 상태")
            return True

        logger.info(f"🔧 {collection_name} 스키마 생성 중...")

        # Documents Collection 생성
        # Weaviate v4 방식 사용
        from weaviate.classes.config import Configure

        client.collections.create(
            name=collection_name,
            description="RAG 챗봇을 위한 문서 저장소",
            # 벡터화 설정 (외부 임베딩 직접 입력)
            vector_config=Configure.Vectors.self_provided(),
            # 속성 정의 (Flat structure - nested object 제거)
            properties=_document_schema_properties(),
            # 인덱싱 설정
            inverted_index_config=Configure.inverted_index(
                bm25_b=0.75,
                bm25_k1=1.2,
            ),
        )

        logger.info(f"✅ {collection_name} 스키마 생성 완료!")
        return True

    except Exception as e:
        logger.error(f"❌ Weaviate 스키마 생성 실패: {e}", exc_info=True)
        return False


def get_schema_info() -> dict | None:
    """
    현재 Weaviate 스키마 정보 조회

    Returns:
        dict: 스키마 정보 또는 None (연결 실패 시)
    """
    try:
        weaviate_client = get_weaviate_client()

        if weaviate_client.client is None:
            return None

        # Collection 목록 가져오기
        collections = weaviate_client.client.collections.list_all()

        return {
            "collections": [c.name for c in collections.values()],
            "total_count": len(collections),
        }

    except Exception as e:
        logger.error(f"스키마 정보 조회 실패: {e}")
        return None
