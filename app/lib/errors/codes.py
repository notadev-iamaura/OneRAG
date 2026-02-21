"""에러 코드 정의 모듈.

모든 RAG 시스템 에러 코드를 Enum으로 정의합니다.
도메인별로 그룹화되어 있어 에러 분류 및 추적이 용이합니다.
"""

from enum import Enum


class ErrorCode(str, Enum):
    """RAG 시스템 에러 코드 Enum.

    형식: {DOMAIN}-{NUMBER}
    - AUTH: 인증/인가 관련
    - SESSION: 세션 관리
    - SERVICE: 서비스 초기화
    - DOC: 문서 처리
    - UPLOAD: 파일 업로드
    - IMAGE: 이미지 처리
    - LLM: 언어 모델
    - VECTOR: 벡터 검색
    - SEARCH: 검색 관련
    - DB: 데이터베이스
    - CONFIG: 설정 관리
    - ROUTING: 라우팅/규칙
    - EMBEDDING: 임베딩
    - GENERAL: 일반 오류
    - API: API 응답
    """

    # AUTH (인증/인가) - 6개
    AUTH_001 = "AUTH-001"  # FASTAPI_AUTH_KEY 환경 변수 미설정
    AUTH_002 = "AUTH-002"  # 서버 인증 설정 오류
    AUTH_003 = "AUTH-003"  # X-API-Key 헤더 누락
    AUTH_004 = "AUTH-004"  # API Key 검증 실패
    AUTH_005 = "AUTH-005"  # get_api_key() 헤더 누락
    AUTH_006 = "AUTH-006"  # get_api_key() 검증 실패

    # SESSION (세션 관리) - 15개
    SESSION_001 = "SESSION-001"  # 세션 요청 처리 실패
    SESSION_002 = "SESSION-002"  # 세션 모듈 초기화 실패 (create_session)
    SESSION_003 = "SESSION-003"  # 새 세션 생성 중 예외
    SESSION_004 = "SESSION-004"  # 세션 모듈 초기화 실패 (get_chat_history)
    SESSION_005 = "SESSION-005"  # 히스토리 조회 시 세션 없음
    SESSION_006 = "SESSION-006"  # 채팅 히스토리 조회 중 예외
    SESSION_007 = "SESSION-007"  # 세션 모듈 초기화 실패 (delete_session)
    SESSION_008 = "SESSION-008"  # 삭제할 세션 없음
    SESSION_009 = "SESSION-009"  # 세션 삭제 중 예외
    SESSION_010 = "SESSION-010"  # 시스템 통계 조회 중 예외
    SESSION_011 = "SESSION-011"  # 세션 정보 조회 시 세션 없음
    SESSION_012 = "SESSION-012"  # 세션 정보 조회 중 예외
    SESSION_013 = "SESSION-013"  # 세션 생성 실패 (DB 오류 등)
    SESSION_CREATE_FAILED = "SESSION-013"  # 별칭: 세션 생성 실패
    SESSION_MODULE_NOT_AVAILABLE = "SESSION-002"  # 별칭: 세션 모듈 사용 불가

    # SERVICE (서비스 초기화) - 2개
    SERVICE_001 = "SERVICE-001"  # ChatService 초기화되지 않음
    SERVICE_002 = "SERVICE-002"  # quality score 범위 벗어남

    # DOC (문서 처리) - 16개
    DOC_001 = "DOC-001"  # retrieval_module 없음 (get_document_stats)
    DOC_002 = "DOC-002"  # 문서 통계 조회 중 예외
    DOC_003 = "DOC-003"  # 문서 삭제 확인 코드 오류
    DOC_004 = "DOC-004"  # retrieval_module 없음 (delete_all_documents)
    DOC_005 = "DOC-005"  # 일부 문서만 삭제됨
    DOC_006 = "DOC-006"  # 문서 삭제 후 상태 확인 실패
    DOC_007 = "DOC-007"  # 문서 삭제 중 예외
    DOC_008 = "DOC-008"  # 컬렉션 초기화 권한 없음
    DOC_009 = "DOC-009"  # retrieval_module 없음 (clear_collection_safe)
    DOC_010 = "DOC-010"  # 컬렉션 초기화 중 예외
    DOC_011 = "DOC-011"  # retrieval_module 없음 (backup_metadata)
    DOC_012 = "DOC-012"  # 메타데이터 백업 중 예외
    DOC_013 = "DOC-013"  # 파일 경로가 존재하지 않음
    DOC_014 = "DOC-014"  # 파일 타입 미지원
    DOC_015 = "DOC-015"  # 문서 로드 중 예외
    DOC_016 = "DOC-016"  # 문서 분할 중 예외

    # UPLOAD (파일 업로드) - 15개
    UPLOAD_001 = "UPLOAD-001"  # content_type 미지원
    UPLOAD_002 = "UPLOAD-002"  # 파일 크기가 max_size 초과
    UPLOAD_003 = "UPLOAD-003"  # document_processor 또는 retrieval_module 없음
    UPLOAD_004 = "UPLOAD-004"  # 파일 검증 실패
    UPLOAD_005 = "UPLOAD-005"  # 파일명 유효하지 않음
    UPLOAD_006 = "UPLOAD-006"  # Path Traversal 시도 차단
    UPLOAD_007 = "UPLOAD-007"  # 파일 경로 검증 중 오류
    UPLOAD_008 = "UPLOAD-008"  # 파일 업로드 중 예외
    UPLOAD_009 = "UPLOAD-009"  # job_id가 존재하지 않음
    UPLOAD_010 = "UPLOAD-010"  # retrieval_module 없음 (list_documents)
    UPLOAD_011 = "UPLOAD-011"  # 문서 목록 조회 중 예외
    UPLOAD_012 = "UPLOAD-012"  # retrieval_module 없음 (delete_document)
    UPLOAD_013 = "UPLOAD-013"  # 문서 삭제 중 예외
    UPLOAD_014 = "UPLOAD-014"  # retrieval_module 없음 (bulk_delete)
    UPLOAD_015 = "UPLOAD-015"  # 일괄 삭제 중 예외

    # IMAGE (이미지 처리) - 5개
    IMAGE_001 = "IMAGE-001"  # 이미지 개수 > 3600
    IMAGE_002 = "IMAGE-002"  # 파일 형식 또는 크기 검증 실패
    IMAGE_003 = "IMAGE-003"  # PIL 이미지 검증 실패
    IMAGE_004 = "IMAGE-004"  # generate_multimodal 메서드 없음
    IMAGE_005 = "IMAGE-005"  # 이미지 처리 중 예외

    # LLM (언어 모델) - 10개
    LLM_001 = "LLM-001"  # OPENROUTER_API_KEY 환경 변수 미설정
    LLM_002 = "LLM-002"  # 모든 fallback 모델 실패
    LLM_003 = "LLM-003"  # 클라이언트 미초기화 상태에서 생성 시도
    LLM_004 = "LLM-004"  # context_text가 비어있음
    LLM_005 = "LLM-005"  # 프롬프트 템플릿 파일 없음
    LLM_006 = "LLM-006"  # 프롬프트 템플릿 None 반환
    LLM_007 = "LLM-007"  # OpenRouter API 타임아웃
    LLM_008 = "LLM-008"  # LLM 생성 타임아웃 (일반)
    LLM_009 = "LLM-009"  # LLM 생성 요청 실패
    GENERATION_TIMEOUT = "LLM-008"  # 별칭: 생성 타임아웃
    GENERATION_REQUEST_FAILED = "LLM-009"  # 별칭: 생성 요청 실패

    # VECTOR (벡터 검색) - 12개
    VECTOR_001 = "VECTOR-001"  # Weaviate 연결 실패
    VECTOR_002 = "VECTOR-002"  # Documents 컬렉션 없음 (initialize)
    VECTOR_003 = "VECTOR-003"  # Documents 컬렉션 없음 (search)
    VECTOR_004 = "VECTOR-004"  # query_embedding 타입 오류
    VECTOR_005 = "VECTOR-005"  # WeaviateQueryError 발생
    VECTOR_006 = "VECTOR-006"  # Documents 컬렉션 없음 (add_documents)
    VECTOR_007 = "VECTOR-007"  # 문서 content 필드 누락
    VECTOR_008 = "VECTOR-008"  # 문서 embedding 필드 누락
    VECTOR_009 = "VECTOR-009"  # WEAVIATE_URL 미설정
    VECTOR_010 = "VECTOR-010"  # 배치 업로드 중 실패한 문서 존재
    VECTOR_011 = "VECTOR-011"  # add_documents 중 예외
    VECTOR_012 = "VECTOR-012"  # delete 중 예외

    # SEARCH (검색) - 4개
    SEARCH_001 = "SEARCH-001"  # 검색 쿼리 실행 실패
    SEARCH_002 = "SEARCH-002"  # 검색 결과 없음
    SEARCH_003 = "SEARCH-003"  # Retrieval 모듈 검색 실패
    RETRIEVAL_SEARCH_FAILED = "SEARCH-003"  # 별칭: Retrieval 검색 실패

    # DB (데이터베이스) - 6개
    DB_001 = "DB-001"  # DATABASE_URL 미설정
    DB_002 = "DB-002"  # 연결 테스트 실패
    DB_003 = "DB-003"  # 초기화 중 예외 (마이그레이션 관련)
    DB_004 = "DB-004"  # engine 없이 create_tables 호출
    DB_005 = "DB-005"  # engine 없이 drop_tables 호출
    DB_006 = "DB-006"  # async_session_maker 없이 get_session 호출

    # Configuration (설정) - 4개
    CONFIG_001 = "CONFIG-001"  # 설정 파일을 찾을 수 없음
    CONFIG_002 = "CONFIG-002"  # 중복된 설정 키
    CONFIG_003 = "CONFIG-003"  # 설정 검증 실패
    CONFIG_004 = "CONFIG-004"  # 잘못된 설정 형식

    # ROUTING (라우팅/규칙) - 4개
    ROUTING_001 = "ROUTING-001"  # 라우팅 규칙을 찾을 수 없음
    ROUTING_002 = "ROUTING-002"  # 잘못된 라우팅 규칙 형식
    ROUTING_003 = "ROUTING-003"  # YAML 파일 로드 실패
    ROUTING_004 = "ROUTING-004"  # 차단된 쿼리

    # EMBEDDING (임베딩) - 4개
    EMBEDDING_001 = "EMBEDDING-001"  # 임베딩 모델 초기화 실패
    EMBEDDING_002 = "EMBEDDING-002"  # 임베딩 요청 실패
    EMBEDDING_003 = "EMBEDDING-003"  # 잘못된 입력
    EMBEDDING_004 = "EMBEDDING-004"  # 할당량 초과

    # GENERAL (일반) - 4개
    GENERAL_001 = "GENERAL-001"  # 알 수 없는 오류
    GENERAL_002 = "GENERAL-002"  # 검증 오류
    GENERAL_003 = "GENERAL-003"  # 미구현 기능
    GENERAL_004 = "GENERAL-004"  # 내부 오류

    # STREAM (스트리밍) - 1개
    STREAM_001 = "STREAM-001"  # 스트리밍 중 오류 발생

    # API (API 응답) - 1개
    API_001 = "API-001"  # 내부 오류

    # === 레거시 호환 별칭 ===
    # Generation 별칭
    GENERATION_ALL_PROVIDERS_FAILED = "LLM-002"  # 모든 프로바이더 실패

    # Retrieval 별칭
    RETRIEVAL_NO_RESULTS = "SEARCH-002"  # 검색 결과 없음

    # Session 별칭
    SESSION_NOT_FOUND = "SESSION-005"  # 세션 없음
    SESSION_EXPIRED = "SESSION-005"  # 세션 만료 (세션 없음으로 처리)

    # Document 별칭
    DOCUMENT_LOAD_FAILED = "DOC-015"  # 문서 로드 실패
