"""에러 메시지 및 해결 방법 저장소.

모든 에러 메시지를 한국어와 영어로 저장하며,
각 에러에 대한 해결 방법도 제공합니다.
"""


# 에러 메시지 저장소: {error_code: {"ko": "한국어 메시지", "en": "English message"}}
ERROR_MESSAGES: dict[str, dict[str, str]] = {
    # AUTH (인증/인가) - 6개
    "AUTH-001": {
        "ko": "FASTAPI_AUTH_KEY 환경 변수가 설정되지 않았습니다",
        "en": "FASTAPI_AUTH_KEY environment variable is not set",
    },
    "AUTH-002": {
        "ko": "서버 인증 설정 오류",
        "en": "Server authentication configuration error",
    },
    "AUTH-003": {
        "ko": "API Key가 필요합니다",
        "en": "API Key is required",
    },
    "AUTH-004": {
        "ko": "제공된 API Key가 유효하지 않습니다",
        "en": "The provided API Key is invalid",
    },
    "AUTH-005": {
        "ko": "API Key가 필요합니다",
        "en": "API Key is required",
    },
    "AUTH-006": {
        "ko": "제공된 API Key가 유효하지 않습니다",
        "en": "The provided API Key is invalid",
    },
    # SESSION (세션 관리) - 12개
    "SESSION-001": {
        "ko": "세션 처리 실패",
        "en": "Session processing failed",
    },
    "SESSION-002": {
        "ko": "세션 모듈 오류",
        "en": "Session module error",
    },
    "SESSION-003": {
        "ko": "세션 생성 실패",
        "en": "Failed to create session",
    },
    "SESSION-004": {
        "ko": "세션 모듈 오류",
        "en": "Session module error",
    },
    "SESSION-005": {
        "ko": "세션을 찾을 수 없습니다",
        "en": "Session not found",
    },
    "SESSION-006": {
        "ko": "히스토리 조회 실패",
        "en": "Failed to retrieve history",
    },
    "SESSION-007": {
        "ko": "세션 모듈 오류",
        "en": "Session module error",
    },
    "SESSION-008": {
        "ko": "세션을 찾을 수 없습니다",
        "en": "Session not found",
    },
    "SESSION-009": {
        "ko": "세션 삭제 실패",
        "en": "Failed to delete session",
    },
    "SESSION-010": {
        "ko": "통계 조회 실패",
        "en": "Failed to retrieve statistics",
    },
    "SESSION-011": {
        "ko": "세션을 찾을 수 없습니다",
        "en": "Session not found",
    },
    "SESSION-012": {
        "ko": "세션 정보 조회 실패",
        "en": "Failed to retrieve session information",
    },
    "SESSION-013": {
        "ko": "세션 생성 실패",
        "en": "Failed to create session",
    },
    # SERVICE (서비스 초기화) - 2개
    "SERVICE-001": {
        "ko": "서비스 초기화 중",
        "en": "Service is initializing",
    },
    "SERVICE-002": {
        "ko": "유효하지 않은 품질 점수: {score}",
        "en": "Invalid quality score: {score}",
    },
    # DOC (문서 처리) - 16개
    "DOC-001": {
        "ko": "검색 모듈 초기화 실패",
        "en": "Failed to initialize retrieval module",
    },
    "DOC-002": {
        "ko": "문서 통계 조회 실패: {reason}",
        "en": "Failed to retrieve document statistics: {reason}",
    },
    "DOC-003": {
        "ko": "확인 코드 불일치",
        "en": "Confirmation code mismatch",
    },
    "DOC-004": {
        "ko": "검색 모듈 초기화 실패",
        "en": "Failed to initialize retrieval module",
    },
    "DOC-005": {
        "ko": "부분 삭제 완료: {deleted_count}/{total_count}개 문서 삭제됨",
        "en": "Partial deletion completed: {deleted_count}/{total_count} documents deleted",
    },
    "DOC-006": {
        "ko": "삭제 상태 확인 실패: {reason}",
        "en": "Failed to verify deletion status: {reason}",
    },
    "DOC-007": {
        "ko": "문서 삭제 실패: {reason}",
        "en": "Failed to delete documents: {reason}",
    },
    "DOC-008": {
        "ko": "권한 없음: 디버그 모드에서만 사용 가능합니다",
        "en": "Permission denied: Only available in debug mode",
    },
    "DOC-009": {
        "ko": "검색 모듈 초기화 실패",
        "en": "Failed to initialize retrieval module",
    },
    "DOC-010": {
        "ko": "컬렉션 초기화 실패: {reason}",
        "en": "Failed to initialize collection: {reason}",
    },
    "DOC-011": {
        "ko": "검색 모듈 초기화 실패",
        "en": "Failed to initialize retrieval module",
    },
    "DOC-012": {
        "ko": "메타데이터 백업 실패: {reason}",
        "en": "Failed to backup metadata: {reason}",
    },
    "DOC-013": {
        "ko": "파일을 찾을 수 없습니다: {path}",
        "en": "File not found: {path}",
    },
    "DOC-014": {
        "ko": "지원하지 않는 파일 형식입니다: {file_type}",
        "en": "Unsupported file format: {file_type}",
    },
    "DOC-015": {
        "ko": "파일을 읽을 수 없습니다: {reason}",
        "en": "Cannot read file: {reason}",
    },
    "DOC-016": {
        "ko": "문서 청킹 중 오류가 발생했습니다: {reason}",
        "en": "Error occurred during document chunking: {reason}",
    },
    # UPLOAD (파일 업로드) - 15개
    "UPLOAD-001": {
        "ko": "지원하지 않는 파일 형식: {content_type}",
        "en": "Unsupported file format: {content_type}",
    },
    "UPLOAD-002": {
        "ko": "파일 크기 초과: {size}MB (최대 {max_size}MB)",
        "en": "File size exceeds limit: {size}MB (maximum {max_size}MB)",
    },
    "UPLOAD-003": {
        "ko": "필수 모듈을 사용할 수 없습니다",
        "en": "Required modules not available",
    },
    "UPLOAD-004": {
        "ko": "파일 검증 실패: {reason}",
        "en": "File validation failed: {reason}",
    },
    "UPLOAD-005": {
        "ko": "잘못된 파일명: {filename}",
        "en": "Invalid filename: {filename}",
    },
    "UPLOAD-006": {
        "ko": "보안 검증 실패: Path Traversal 시도 차단됨",
        "en": "Security validation failed: Path Traversal attempt blocked",
    },
    "UPLOAD-007": {
        "ko": "파일 경로 검증 실패: {reason}",
        "en": "File path validation failed: {reason}",
    },
    "UPLOAD-008": {
        "ko": "업로드 실패: {reason}",
        "en": "Upload failed: {reason}",
    },
    "UPLOAD-009": {
        "ko": "작업을 찾을 수 없음: {job_id}",
        "en": "Job not found: {job_id}",
    },
    "UPLOAD-010": {
        "ko": "시스템 모듈 사용 불가",
        "en": "System module unavailable",
    },
    "UPLOAD-011": {
        "ko": "문서 목록 조회 실패: {reason}",
        "en": "Failed to list documents: {reason}",
    },
    "UPLOAD-012": {
        "ko": "시스템 모듈 사용 불가",
        "en": "System module unavailable",
    },
    "UPLOAD-013": {
        "ko": "문서 삭제 실패: {reason}",
        "en": "Failed to delete document: {reason}",
    },
    "UPLOAD-014": {
        "ko": "시스템 모듈 사용 불가",
        "en": "System module unavailable",
    },
    "UPLOAD-015": {
        "ko": "일괄 삭제 실패: {reason}",
        "en": "Bulk deletion failed: {reason}",
    },
    # IMAGE (이미지 처리) - 5개
    "IMAGE-001": {
        "ko": "이미지 개수 제한 초과: {count}개 (최대 {max_count}개)",
        "en": "Image count limit exceeded: {count} images (maximum {max_count})",
    },
    "IMAGE-002": {
        "ko": "이미지 검증 실패: {reason}",
        "en": "Image validation failed: {reason}",
    },
    "IMAGE-003": {
        "ko": "이미지 내용 검증 실패: {reason}",
        "en": "Image content validation failed: {reason}",
    },
    "IMAGE-004": {
        "ko": "이미지 분석 서비스 사용 불가",
        "en": "Image analysis service unavailable",
    },
    "IMAGE-005": {
        "ko": "이미지 처리 오류: {reason}",
        "en": "Image processing error: {reason}",
    },
    # LLM (언어 모델) - 7개
    "LLM-001": {
        "ko": "OpenRouter API 키가 설정되지 않았습니다",
        "en": "OpenRouter API key is not set",
    },
    "LLM-002": {
        "ko": "답변 생성 실패: 모든 모델 시도 실패",
        "en": "Answer generation failed: All model attempts failed",
    },
    "LLM-003": {
        "ko": "OpenRouter 클라이언트가 초기화되지 않았습니다",
        "en": "OpenRouter client is not initialized",
    },
    "LLM-004": {
        "ko": "검색된 문서가 없습니다",
        "en": "No documents retrieved",
    },
    "LLM-005": {
        "ko": "프롬프트 템플릿을 찾을 수 없습니다: {template_name}",
        "en": "Prompt template not found: {template_name}",
    },
    "LLM-006": {
        "ko": "프롬프트 템플릿을 찾을 수 없습니다",
        "en": "Prompt template not found",
    },
    "LLM-007": {
        "ko": "AI 응답 시간이 초과되었습니다",
        "en": "AI response timeout",
    },
    "LLM-009": {
        "ko": "LLM 생성 요청이 실패했습니다",
        "en": "LLM generation request failed",
    },
    # VECTOR (벡터 검색) - 12개
    "VECTOR-001": {
        "ko": "Weaviate 벡터 데이터베이스에 연결할 수 없습니다: {reason}",
        "en": "Cannot connect to Weaviate vector database: {reason}",
    },
    "VECTOR-002": {
        "ko": "Weaviate 'Documents' 컬렉션이 존재하지 않습니다",
        "en": "Weaviate 'Documents' collection does not exist",
    },
    "VECTOR-003": {
        "ko": "Weaviate 'Documents' 컬렉션이 존재하지 않습니다",
        "en": "Weaviate 'Documents' collection does not exist",
    },
    "VECTOR-004": {
        "ko": "Embedding은 list 타입이어야 합니다",
        "en": "Embedding must be of type list",
    },
    "VECTOR-005": {
        "ko": "Weaviate 검색 중 오류가 발생했습니다: {reason}",
        "en": "Error occurred during Weaviate search: {reason}",
    },
    "VECTOR-006": {
        "ko": "Weaviate 'Documents' 컬렉션이 존재하지 않습니다",
        "en": "Weaviate 'Documents' collection does not exist",
    },
    "VECTOR-007": {
        "ko": "문서에 'content' 필드가 없습니다",
        "en": "Document is missing 'content' field",
    },
    "VECTOR-008": {
        "ko": "문서에 'embedding' 필드가 없습니다",
        "en": "Document is missing 'embedding' field",
    },
    "VECTOR-009": {
        "ko": "WEAVIATE_URL 환경 변수가 필요합니다",
        "en": "WEAVIATE_URL environment variable is required",
    },
    "VECTOR-010": {
        "ko": "문서 인덱싱 중 오류가 발생했습니다: {failed_count}개 문서 실패",
        "en": "Error occurred during document indexing: {failed_count} documents failed",
    },
    "VECTOR-011": {
        "ko": "문서 인덱싱 중 오류가 발생했습니다: {reason}",
        "en": "Error occurred during document indexing: {reason}",
    },
    "VECTOR-012": {
        "ko": "문서 삭제 실패: {reason}",
        "en": "Document deletion failed: {reason}",
    },
    # SEARCH (검색) - 3개
    "SEARCH-001": {
        "ko": "검색 쿼리 실행 실패: {reason}",
        "en": "Search query execution failed: {reason}",
    },
    "SEARCH-002": {
        "ko": "검색 결과가 없습니다",
        "en": "No search results found",
    },
    "SEARCH-003": {
        "ko": "Retrieval 모듈에서 검색 실패",
        "en": "Retrieval module search failed",
    },
    # DB (데이터베이스) - 6개
    "DB-001": {
        "ko": "PostgreSQL 데이터베이스에 연결할 수 없습니다: DATABASE_URL이 설정되지 않았습니다",
        "en": "Cannot connect to PostgreSQL database: DATABASE_URL is not set",
    },
    "DB-002": {
        "ko": "PostgreSQL 데이터베이스에 연결할 수 없습니다: {reason}",
        "en": "Cannot connect to PostgreSQL database: {reason}",
    },
    "DB-003": {
        "ko": "데이터베이스 마이그레이션 실패: {reason}",
        "en": "Database migration failed: {reason}",
    },
    "DB-004": {
        "ko": "데이터베이스가 초기화되지 않았습니다",
        "en": "Database is not initialized",
    },
    "DB-005": {
        "ko": "데이터베이스가 초기화되지 않았습니다",
        "en": "Database is not initialized",
    },
    "DB-006": {
        "ko": "데이터베이스가 초기화되지 않았습니다",
        "en": "Database is not initialized",
    },
    # CONFIG (설정) - 4개
    "CONFIG-001": {
        "ko": "설정 파일을 찾을 수 없습니다",
        "en": "Configuration file not found",
    },
    "CONFIG-002": {
        "ko": "설정 파일에서 중복된 키가 발견되었습니다",
        "en": "Duplicate keys found in configuration file",
    },
    "CONFIG-003": {
        "ko": "설정 검증 실패",
        "en": "Configuration validation failed",
    },
    "CONFIG-004": {
        "ko": "잘못된 설정 형식",
        "en": "Invalid configuration format",
    },
    # LLM-008 (생성 타임아웃)
    "LLM-008": {
        "ko": "LLM 생성 시간이 초과되었습니다",
        "en": "LLM generation timeout",
    },
    # ROUTING (라우팅/규칙) - 4개
    "ROUTING-001": {
        "ko": "라우팅 규칙을 찾을 수 없습니다",
        "en": "Routing rule not found",
    },
    "ROUTING-002": {
        "ko": "잘못된 라우팅 규칙 형식입니다",
        "en": "Invalid routing rule format",
    },
    "ROUTING-003": {
        "ko": "라우팅 YAML 파일 로드에 실패했습니다: {reason}",
        "en": "Failed to load routing YAML file: {reason}",
    },
    "ROUTING-004": {
        "ko": "차단된 쿼리입니다: {reason}",
        "en": "Query blocked: {reason}",
    },
    # EMBEDDING (임베딩) - 4개
    "EMBEDDING-001": {
        "ko": "임베딩 모델이 초기화되지 않았습니다",
        "en": "Embedding model is not initialized",
    },
    "EMBEDDING-002": {
        "ko": "임베딩 요청에 실패했습니다: {reason}",
        "en": "Embedding request failed: {reason}",
    },
    "EMBEDDING-003": {
        "ko": "임베딩 입력이 유효하지 않습니다: {reason}",
        "en": "Invalid embedding input: {reason}",
    },
    "EMBEDDING-004": {
        "ko": "임베딩 API 할당량을 초과했습니다",
        "en": "Embedding API quota exceeded",
    },
    # GENERAL (일반) - 4개
    "GENERAL-001": {
        "ko": "알 수 없는 오류가 발생했습니다",
        "en": "An unknown error occurred",
    },
    "GENERAL-002": {
        "ko": "입력 데이터 검증에 실패했습니다: {reason}",
        "en": "Input validation failed: {reason}",
    },
    "GENERAL-003": {
        "ko": "이 기능은 아직 구현되지 않았습니다",
        "en": "This feature is not implemented yet",
    },
    "GENERAL-004": {
        "ko": "내부 오류가 발생했습니다: {reason}",
        "en": "Internal error occurred: {reason}",
    },
    # API (API 응답) - 1개
    "API-001": {
        "ko": "내부 서버 오류",
        "en": "Internal server error",
    },
    # GROK (Grok Collections API) - 3개
    "GROK-001": {
        "ko": "xAI API 인증 실패: API 키가 유효하지 않거나 설정되지 않았습니다",
        "en": "xAI API authentication failed: API key is invalid or not configured",
    },
    "GROK-002": {
        "ko": "xAI API 속도 제한 초과: 잠시 후 다시 시도해주세요",
        "en": "xAI API rate limit exceeded: please try again later",
    },
    "GROK-003": {
        "ko": "Grok Collections 검색 실패: {reason}",
        "en": "Grok Collections search failed: {reason}",
    },
}

# 에러 해결 방법 저장소: {error_code: {"ko": [...], "en": [...]}}
ERROR_SOLUTIONS: dict[str, dict[str, list[str]]] = {
    # AUTH (인증/인가)
    "AUTH-001": {
        "ko": [
            "프로덕션 환경에서 FASTAPI_AUTH_KEY 환경 변수를 설정하세요",
            ".env 파일에 FASTAPI_AUTH_KEY 값을 추가하세요",
            "환경 변수 설정 후 애플리케이션을 재시작하세요",
        ],
        "en": [
            "Set FASTAPI_AUTH_KEY environment variable in production",
            "Add FASTAPI_AUTH_KEY value to .env file",
            "Restart the application after setting environment variable",
        ],
    },
    "AUTH-002": {
        "ko": [
            "프로덕션 환경에서 API 인증을 구성하세요",
            "FASTAPI_AUTH_KEY 환경 변수를 확인하세요",
            "서버 설정을 검토하세요",
        ],
        "en": [
            "Configure API authentication in production environment",
            "Verify FASTAPI_AUTH_KEY environment variable",
            "Review server configuration",
        ],
    },
    "AUTH-003": {
        "ko": [
            "요청 헤더에 X-API-Key를 포함하세요",
            "올바른 API 키를 입력했는지 확인하세요",
            ".env 파일의 ADMIN_API_KEY 설정을 확인하세요",
        ],
        "en": [
            "Include X-API-Key in request headers",
            "Verify that you entered the correct API key",
            "Check ADMIN_API_KEY configuration in .env file",
        ],
    },
    "AUTH-004": {
        "ko": [
            "올바른 API 키를 입력했는지 확인하세요",
            ".env 파일의 ADMIN_API_KEY와 일치하는지 확인하세요",
            "API 키가 만료되었다면 새로 발급받으세요",
        ],
        "en": [
            "Verify that you entered the correct API key",
            "Ensure it matches ADMIN_API_KEY in .env file",
            "Obtain a new API key if expired",
        ],
    },
    "AUTH-005": {
        "ko": [
            "요청 헤더에 X-API-Key를 포함하세요",
            "올바른 API 키를 입력했는지 확인하세요",
        ],
        "en": [
            "Include X-API-Key in request headers",
            "Verify that you entered the correct API key",
        ],
    },
    "AUTH-006": {
        "ko": [
            "올바른 API 키를 입력했는지 확인하세요",
            "API 키가 만료되었다면 새로 발급받으세요",
        ],
        "en": [
            "Verify that you entered the correct API key",
            "Obtain a new API key if expired",
        ],
    },
    # SESSION (세션 관리)
    "SESSION-001": {
        "ko": [
            "세션 ID가 유효한지 확인하세요",
            "요청 데이터 형식을 검토하세요",
            "서버 로그를 확인하여 자세한 오류를 파악하세요",
        ],
        "en": [
            "Verify that session ID is valid",
            "Review request data format",
            "Check server logs for detailed error information",
        ],
    },
    "SESSION-002": {
        "ko": [
            "세션 저장소 연결을 확인하세요",
            "데이터베이스 설정을 검토하세요",
            "애플리케이션을 재시작해보세요",
        ],
        "en": [
            "Verify session storage connection",
            "Review database configuration",
            "Try restarting the application",
        ],
    },
    "SESSION-003": {
        "ko": [
            "데이터베이스 연결을 확인하세요",
            "세션 저장소 용량을 확인하세요",
            "서버 로그를 확인하여 자세한 오류를 파악하세요",
        ],
        "en": [
            "Verify database connection",
            "Check session storage capacity",
            "Check server logs for detailed error information",
        ],
    },
    "SESSION-004": {
        "ko": [
            "세션 저장소 연결을 확인하세요",
            "데이터베이스 설정을 검토하세요",
        ],
        "en": [
            "Verify session storage connection",
            "Review database configuration",
        ],
    },
    "SESSION-005": {
        "ko": [
            "세션 ID를 확인하세요",
            "세션이 만료되지 않았는지 확인하세요",
            "새 세션을 생성하세요",
        ],
        "en": [
            "Verify session ID",
            "Check if session has not expired",
            "Create a new session",
        ],
    },
    "SESSION-006": {
        "ko": [
            "데이터베이스 연결을 확인하세요",
            "세션 ID가 유효한지 확인하세요",
            "서버 로그를 확인하여 자세한 오류를 파악하세요",
        ],
        "en": [
            "Verify database connection",
            "Verify that session ID is valid",
            "Check server logs for detailed error information",
        ],
    },
    "SESSION-007": {
        "ko": [
            "세션 저장소 연결을 확인하세요",
            "데이터베이스 설정을 검토하세요",
        ],
        "en": [
            "Verify session storage connection",
            "Review database configuration",
        ],
    },
    "SESSION-008": {
        "ko": [
            "세션 ID를 확인하세요",
            "세션이 이미 삭제되지 않았는지 확인하세요",
        ],
        "en": [
            "Verify session ID",
            "Check if session has not already been deleted",
        ],
    },
    "SESSION-009": {
        "ko": [
            "데이터베이스 연결을 확인하세요",
            "서버 로그를 확인하여 자세한 오류를 파악하세요",
        ],
        "en": [
            "Verify database connection",
            "Check server logs for detailed error information",
        ],
    },
    "SESSION-010": {
        "ko": [
            "데이터베이스 연결을 확인하세요",
            "서버 로그를 확인하여 자세한 오류를 파악하세요",
        ],
        "en": [
            "Verify database connection",
            "Check server logs for detailed error information",
        ],
    },
    "SESSION-011": {
        "ko": [
            "세션 ID를 확인하세요",
            "세션이 만료되지 않았는지 확인하세요",
        ],
        "en": [
            "Verify session ID",
            "Check if session has not expired",
        ],
    },
    "SESSION-012": {
        "ko": [
            "데이터베이스 연결을 확인하세요",
            "서버 로그를 확인하여 자세한 오류를 파악하세요",
        ],
        "en": [
            "Verify database connection",
            "Check server logs for detailed error information",
        ],
    },
    "SESSION-013": {
        "ko": [
            "데이터베이스 연결을 확인하세요",
            "세션 저장소 용량을 확인하세요",
            "서버 로그를 확인하여 자세한 오류를 파악하세요",
        ],
        "en": [
            "Verify database connection",
            "Check session storage capacity",
            "Check server logs for detailed error information",
        ],
    },
    # SERVICE (서비스 초기화)
    "SERVICE-001": {
        "ko": [
            "서비스 초기화가 완료될 때까지 기다리세요",
            "필요한 모든 환경 변수가 설정되었는지 확인하세요",
            "데이터베이스 연결을 확인하세요",
        ],
        "en": [
            "Wait for service initialization to complete",
            "Verify all required environment variables are set",
            "Verify database connection",
        ],
    },
    "SERVICE-002": {
        "ko": [
            "품질 점수는 0.0에서 1.0 사이의 값이어야 합니다",
            "요청 데이터를 확인하세요",
        ],
        "en": [
            "Quality score must be between 0.0 and 1.0",
            "Verify request data",
        ],
    },
    # DOC (문서 처리)
    "DOC-001": {
        "ko": [
            "검색 모듈이 초기화되었는지 확인하세요",
            "애플리케이션을 재시작해보세요",
            "Weaviate 연결을 확인하세요",
        ],
        "en": [
            "Verify retrieval module is initialized",
            "Try restarting the application",
            "Verify Weaviate connection",
        ],
    },
    "DOC-002": {
        "ko": [
            "Weaviate 연결을 확인하세요",
            "데이터베이스 연결을 확인하세요",
            "서버 로그를 확인하여 자세한 오류를 파악하세요",
        ],
        "en": [
            "Verify Weaviate connection",
            "Verify database connection",
            "Check server logs for detailed error information",
        ],
    },
    "DOC-003": {
        "ko": [
            "올바른 확인 코드를 입력하세요",
            "확인 코드는 대소문자를 구분합니다",
        ],
        "en": [
            "Enter the correct confirmation code",
            "Confirmation code is case-sensitive",
        ],
    },
    "DOC-004": {
        "ko": [
            "검색 모듈이 초기화되었는지 확인하세요",
            "애플리케이션을 재시작해보세요",
        ],
        "en": [
            "Verify retrieval module is initialized",
            "Try restarting the application",
        ],
    },
    "DOC-005": {
        "ko": [
            "삭제 실패한 문서 목록을 확인하세요",
            "나머지 문서를 다시 삭제 시도하세요",
            "Weaviate 로그를 확인하세요",
        ],
        "en": [
            "Check list of failed deletions",
            "Retry deleting remaining documents",
            "Check Weaviate logs",
        ],
    },
    "DOC-006": {
        "ko": [
            "Weaviate 연결을 확인하세요",
            "서버 로그를 확인하여 자세한 오류를 파악하세요",
        ],
        "en": [
            "Verify Weaviate connection",
            "Check server logs for detailed error information",
        ],
    },
    "DOC-007": {
        "ko": [
            "Weaviate 연결을 확인하세요",
            "문서 ID가 유효한지 확인하세요",
            "서버 로그를 확인하여 자세한 오류를 파악하세요",
        ],
        "en": [
            "Verify Weaviate connection",
            "Verify document ID is valid",
            "Check server logs for detailed error information",
        ],
    },
    "DOC-008": {
        "ko": [
            "DEBUG_MODE 환경 변수를 true로 설정하세요",
            "프로덕션 환경에서는 이 작업을 실행할 수 없습니다",
        ],
        "en": [
            "Set DEBUG_MODE environment variable to true",
            "This operation cannot be performed in production environment",
        ],
    },
    "DOC-009": {
        "ko": [
            "검색 모듈이 초기화되었는지 확인하세요",
            "애플리케이션을 재시작해보세요",
        ],
        "en": [
            "Verify retrieval module is initialized",
            "Try restarting the application",
        ],
    },
    "DOC-010": {
        "ko": [
            "Weaviate 연결을 확인하세요",
            "서버 로그를 확인하여 자세한 오류를 파악하세요",
        ],
        "en": [
            "Verify Weaviate connection",
            "Check server logs for detailed error information",
        ],
    },
    "DOC-011": {
        "ko": [
            "검색 모듈이 초기화되었는지 확인하세요",
            "애플리케이션을 재시작해보세요",
        ],
        "en": [
            "Verify retrieval module is initialized",
            "Try restarting the application",
        ],
    },
    "DOC-012": {
        "ko": [
            "백업 디렉토리 권한을 확인하세요",
            "디스크 공간을 확인하세요",
            "서버 로그를 확인하여 자세한 오류를 파악하세요",
        ],
        "en": [
            "Verify backup directory permissions",
            "Check disk space",
            "Check server logs for detailed error information",
        ],
    },
    "DOC-013": {
        "ko": [
            "파일 경로가 올바른지 확인하세요",
            "파일이 존재하는지 확인하세요",
            "파일 권한을 확인하세요",
        ],
        "en": [
            "Verify file path is correct",
            "Verify file exists",
            "Check file permissions",
        ],
    },
    "DOC-014": {
        "ko": [
            "지원되는 파일 형식으로 변환하세요 (PDF, DOCX, TXT 등)",
            "파일 확장자를 확인하세요",
        ],
        "en": [
            "Convert to supported file format (PDF, DOCX, TXT, etc.)",
            "Verify file extension",
        ],
    },
    "DOC-015": {
        "ko": [
            "파일이 손상되지 않았는지 확인하세요",
            "파일 권한을 확인하세요",
            "다른 파일로 다시 시도하세요",
        ],
        "en": [
            "Verify file is not corrupted",
            "Check file permissions",
            "Try again with a different file",
        ],
    },
    "DOC-016": {
        "ko": [
            "문서 내용이 올바른지 확인하세요",
            "문서 크기를 줄여보세요",
            "서버 로그를 확인하여 자세한 오류를 파악하세요",
        ],
        "en": [
            "Verify document content is valid",
            "Try reducing document size",
            "Check server logs for detailed error information",
        ],
    },
    # UPLOAD (파일 업로드)
    "UPLOAD-001": {
        "ko": [
            "지원되는 파일 형식으로 변환하세요",
            "파일 형식을 확인하세요",
        ],
        "en": [
            "Convert to supported file format",
            "Verify file format",
        ],
    },
    "UPLOAD-002": {
        "ko": [
            "파일 크기를 줄이세요",
            "파일을 여러 개로 분할하세요",
        ],
        "en": [
            "Reduce file size",
            "Split file into multiple parts",
        ],
    },
    "UPLOAD-003": {
        "ko": [
            "필수 모듈이 초기화되었는지 확인하세요",
            "애플리케이션을 재시작해보세요",
        ],
        "en": [
            "Verify required modules are initialized",
            "Try restarting the application",
        ],
    },
    "UPLOAD-004": {
        "ko": [
            "파일이 손상되지 않았는지 확인하세요",
            "파일 형식과 크기를 확인하세요",
        ],
        "en": [
            "Verify file is not corrupted",
            "Verify file format and size",
        ],
    },
    "UPLOAD-005": {
        "ko": [
            "유효한 파일명을 사용하세요",
            "특수 문자를 제거하세요",
        ],
        "en": [
            "Use valid filename",
            "Remove special characters",
        ],
    },
    "UPLOAD-006": {
        "ko": [
            "안전한 파일 경로를 사용하세요",
            "상대 경로나 '..' 사용을 피하세요",
        ],
        "en": [
            "Use safe file path",
            "Avoid using relative paths or '..'",
        ],
    },
    "UPLOAD-007": {
        "ko": [
            "파일 경로를 확인하세요",
            "서버 로그를 확인하여 자세한 오류를 파악하세요",
        ],
        "en": [
            "Verify file path",
            "Check server logs for detailed error information",
        ],
    },
    "UPLOAD-008": {
        "ko": [
            "네트워크 연결을 확인하세요",
            "파일을 다시 업로드해보세요",
            "서버 로그를 확인하여 자세한 오류를 파악하세요",
        ],
        "en": [
            "Verify network connection",
            "Try uploading file again",
            "Check server logs for detailed error information",
        ],
    },
    "UPLOAD-009": {
        "ko": [
            "작업 ID를 확인하세요",
            "작업이 만료되지 않았는지 확인하세요",
        ],
        "en": [
            "Verify job ID",
            "Check if job has not expired",
        ],
    },
    "UPLOAD-010": {
        "ko": [
            "검색 모듈이 초기화되었는지 확인하세요",
            "애플리케이션을 재시작해보세요",
        ],
        "en": [
            "Verify retrieval module is initialized",
            "Try restarting the application",
        ],
    },
    "UPLOAD-011": {
        "ko": [
            "Weaviate 연결을 확인하세요",
            "서버 로그를 확인하여 자세한 오류를 파악하세요",
        ],
        "en": [
            "Verify Weaviate connection",
            "Check server logs for detailed error information",
        ],
    },
    "UPLOAD-012": {
        "ko": [
            "검색 모듈이 초기화되었는지 확인하세요",
            "애플리케이션을 재시작해보세요",
        ],
        "en": [
            "Verify retrieval module is initialized",
            "Try restarting the application",
        ],
    },
    "UPLOAD-013": {
        "ko": [
            "문서 ID를 확인하세요",
            "Weaviate 연결을 확인하세요",
            "서버 로그를 확인하여 자세한 오류를 파악하세요",
        ],
        "en": [
            "Verify document ID",
            "Verify Weaviate connection",
            "Check server logs for detailed error information",
        ],
    },
    "UPLOAD-014": {
        "ko": [
            "검색 모듈이 초기화되었는지 확인하세요",
            "애플리케이션을 재시작해보세요",
        ],
        "en": [
            "Verify retrieval module is initialized",
            "Try restarting the application",
        ],
    },
    "UPLOAD-015": {
        "ko": [
            "문서 ID 목록을 확인하세요",
            "Weaviate 연결을 확인하세요",
            "서버 로그를 확인하여 자세한 오류를 파악하세요",
        ],
        "en": [
            "Verify document ID list",
            "Verify Weaviate connection",
            "Check server logs for detailed error information",
        ],
    },
    # IMAGE (이미지 처리)
    "IMAGE-001": {
        "ko": [
            "이미지 개수를 줄이세요",
            "최대 허용 개수를 확인하세요",
        ],
        "en": [
            "Reduce number of images",
            "Check maximum allowed count",
        ],
    },
    "IMAGE-002": {
        "ko": [
            "이미지 형식을 확인하세요 (JPEG, PNG 등)",
            "이미지 크기를 줄이세요",
        ],
        "en": [
            "Verify image format (JPEG, PNG, etc.)",
            "Reduce image size",
        ],
    },
    "IMAGE-003": {
        "ko": [
            "이미지가 손상되지 않았는지 확인하세요",
            "다른 이미지로 다시 시도하세요",
        ],
        "en": [
            "Verify image is not corrupted",
            "Try again with a different image",
        ],
    },
    "IMAGE-004": {
        "ko": [
            "이미지 분석 기능을 사용할 수 없습니다",
            "서비스 관리자에게 문의하세요",
        ],
        "en": [
            "Image analysis feature is unavailable",
            "Contact service administrator",
        ],
    },
    "IMAGE-005": {
        "ko": [
            "이미지 형식을 확인하세요",
            "이미지를 다시 업로드해보세요",
            "서버 로그를 확인하여 자세한 오류를 파악하세요",
        ],
        "en": [
            "Verify image format",
            "Try uploading image again",
            "Check server logs for detailed error information",
        ],
    },
    # LLM (언어 모델)
    "LLM-001": {
        "ko": [
            "OPENROUTER_API_KEY 환경 변수를 설정하세요",
            ".env 파일에 API 키를 추가하세요",
            "OpenRouter에서 API 키를 발급받으세요",
        ],
        "en": [
            "Set OPENROUTER_API_KEY environment variable",
            "Add API key to .env file",
            "Obtain API key from OpenRouter",
        ],
    },
    "LLM-002": {
        "ko": [
            "API 키가 유효한지 확인하세요",
            "네트워크 연결을 확인하세요",
            "OpenRouter 서비스 상태를 확인하세요",
        ],
        "en": [
            "Verify API key is valid",
            "Verify network connection",
            "Check OpenRouter service status",
        ],
    },
    "LLM-003": {
        "ko": [
            "OPENROUTER_API_KEY 환경 변수를 확인하세요",
            "애플리케이션을 재시작해보세요",
        ],
        "en": [
            "Verify OPENROUTER_API_KEY environment variable",
            "Try restarting the application",
        ],
    },
    "LLM-004": {
        "ko": [
            "검색 쿼리를 확인하세요",
            "문서가 업로드되었는지 확인하세요",
            "Weaviate 연결을 확인하세요",
        ],
        "en": [
            "Verify search query",
            "Verify documents are uploaded",
            "Verify Weaviate connection",
        ],
    },
    "LLM-005": {
        "ko": [
            "프롬프트 템플릿 파일을 확인하세요",
            "템플릿 경로를 확인하세요",
        ],
        "en": [
            "Verify prompt template file",
            "Check template path",
        ],
    },
    "LLM-006": {
        "ko": [
            "프롬프트 템플릿 설정을 확인하세요",
            "템플릿 파일이 존재하는지 확인하세요",
        ],
        "en": [
            "Verify prompt template configuration",
            "Verify template file exists",
        ],
    },
    "LLM-007": {
        "ko": [
            "네트워크 연결을 확인하세요",
            "OpenRouter 서비스 상태를 확인하세요",
            "요청을 다시 시도하세요",
        ],
        "en": [
            "Verify network connection",
            "Check OpenRouter service status",
            "Retry request",
        ],
    },
    "LLM-009": {
        "ko": [
            "API 키가 유효한지 확인하세요",
            "네트워크 연결을 확인하세요",
            "OpenRouter 서비스 상태를 확인하세요",
            "다른 모델을 시도하세요",
        ],
        "en": [
            "Verify API key is valid",
            "Verify network connection",
            "Check OpenRouter service status",
            "Try a different model",
        ],
    },
    # VECTOR (벡터 검색)
    "VECTOR-001": {
        "ko": [
            "WEAVIATE_URL 환경 변수를 확인하세요",
            "Weaviate 서버가 실행 중인지 확인하세요",
            "네트워크 연결을 확인하세요",
        ],
        "en": [
            "Verify WEAVIATE_URL environment variable",
            "Verify Weaviate server is running",
            "Verify network connection",
        ],
    },
    "VECTOR-002": {
        "ko": [
            "Weaviate 컬렉션을 초기화하세요",
            "애플리케이션을 재시작해보세요",
        ],
        "en": [
            "Initialize Weaviate collection",
            "Try restarting the application",
        ],
    },
    "VECTOR-003": {
        "ko": [
            "Weaviate 컬렉션을 초기화하세요",
            "문서를 먼저 업로드하세요",
        ],
        "en": [
            "Initialize Weaviate collection",
            "Upload documents first",
        ],
    },
    "VECTOR-004": {
        "ko": [
            "Embedding 데이터 형식을 확인하세요",
            "Embedding이 리스트 형태인지 확인하세요",
        ],
        "en": [
            "Verify embedding data format",
            "Verify embedding is in list format",
        ],
    },
    "VECTOR-005": {
        "ko": [
            "Weaviate 연결을 확인하세요",
            "검색 쿼리를 확인하세요",
            "서버 로그를 확인하여 자세한 오류를 파악하세요",
        ],
        "en": [
            "Verify Weaviate connection",
            "Verify search query",
            "Check server logs for detailed error information",
        ],
    },
    "VECTOR-006": {
        "ko": [
            "Weaviate 컬렉션을 초기화하세요",
            "애플리케이션을 재시작해보세요",
        ],
        "en": [
            "Initialize Weaviate collection",
            "Try restarting the application",
        ],
    },
    "VECTOR-007": {
        "ko": [
            "문서에 'content' 필드를 추가하세요",
            "문서 데이터 형식을 확인하세요",
        ],
        "en": [
            "Add 'content' field to document",
            "Verify document data format",
        ],
    },
    "VECTOR-008": {
        "ko": [
            "문서에 'embedding' 필드를 추가하세요",
            "문서 데이터 형식을 확인하세요",
        ],
        "en": [
            "Add 'embedding' field to document",
            "Verify document data format",
        ],
    },
    "VECTOR-009": {
        "ko": [
            "WEAVIATE_URL 환경 변수를 설정하세요",
            ".env 파일에 Weaviate URL을 추가하세요",
        ],
        "en": [
            "Set WEAVIATE_URL environment variable",
            "Add Weaviate URL to .env file",
        ],
    },
    "VECTOR-010": {
        "ko": [
            "실패한 문서 목록을 확인하세요",
            "Weaviate 로그를 확인하세요",
            "문서 데이터를 다시 확인하세요",
        ],
        "en": [
            "Check list of failed documents",
            "Check Weaviate logs",
            "Recheck document data",
        ],
    },
    "VECTOR-011": {
        "ko": [
            "Weaviate 연결을 확인하세요",
            "문서 데이터 형식을 확인하세요",
            "서버 로그를 확인하여 자세한 오류를 파악하세요",
        ],
        "en": [
            "Verify Weaviate connection",
            "Verify document data format",
            "Check server logs for detailed error information",
        ],
    },
    "VECTOR-012": {
        "ko": [
            "Weaviate 연결을 확인하세요",
            "문서 ID가 유효한지 확인하세요",
            "서버 로그를 확인하여 자세한 오류를 파악하세요",
        ],
        "en": [
            "Verify Weaviate connection",
            "Verify document ID is valid",
            "Check server logs for detailed error information",
        ],
    },
    # SEARCH (검색)
    "SEARCH-001": {
        "ko": [
            "검색 쿼리를 확인하세요",
            "Weaviate 연결을 확인하세요",
            "서버 로그를 확인하여 자세한 오류를 파악하세요",
        ],
        "en": [
            "Verify search query",
            "Verify Weaviate connection",
            "Check server logs for detailed error information",
        ],
    },
    "SEARCH-002": {
        "ko": [
            "검색 키워드를 변경해보세요",
            "문서가 업로드되었는지 확인하세요",
            "검색 필터를 조정해보세요",
        ],
        "en": [
            "Try different search keywords",
            "Verify documents are uploaded",
            "Adjust search filters",
        ],
    },
    "SEARCH-003": {
        "ko": [
            "Retrieval 모듈이 초기화되었는지 확인하세요",
            "Weaviate 연결을 확인하세요",
            "서버 로그를 확인하여 자세한 오류를 파악하세요",
        ],
        "en": [
            "Verify retrieval module is initialized",
            "Verify Weaviate connection",
            "Check server logs for detailed error information",
        ],
    },
    # DB (데이터베이스)
    "DB-001": {
        "ko": [
            "DATABASE_URL 환경 변수를 설정하세요",
            ".env 파일에 데이터베이스 URL을 추가하세요",
            "PostgreSQL 서버가 실행 중인지 확인하세요 (pg_isready)",
        ],
        "en": [
            "Set DATABASE_URL environment variable",
            "Add database URL to .env file",
            "Verify PostgreSQL server is running (pg_isready)",
        ],
    },
    "DB-002": {
        "ko": [
            "PostgreSQL 서버가 실행 중인지 확인하세요",
            "데이터베이스 연결 정보를 확인하세요",
            "네트워크 연결을 확인하세요",
        ],
        "en": [
            "Verify PostgreSQL server is running",
            "Verify database connection information",
            "Verify network connection",
        ],
    },
    "DB-003": {
        "ko": [
            "데이터베이스 마이그레이션 스크립트를 확인하세요",
            "데이터베이스 권한을 확인하세요",
            "서버 로그를 확인하여 자세한 오류를 파악하세요",
        ],
        "en": [
            "Verify database migration scripts",
            "Check database permissions",
            "Check server logs for detailed error information",
        ],
    },
    "DB-004": {
        "ko": [
            "데이터베이스 연결을 초기화하세요",
            "애플리케이션을 재시작해보세요",
        ],
        "en": [
            "Initialize database connection",
            "Try restarting the application",
        ],
    },
    "DB-005": {
        "ko": [
            "데이터베이스 연결을 초기화하세요",
            "애플리케이션을 재시작해보세요",
        ],
        "en": [
            "Initialize database connection",
            "Try restarting the application",
        ],
    },
    "DB-006": {
        "ko": [
            "데이터베이스 연결을 초기화하세요",
            "애플리케이션을 재시작해보세요",
        ],
        "en": [
            "Initialize database connection",
            "Try restarting the application",
        ],
    },
    # CONFIG (설정)
    "CONFIG-001": {
        "ko": [
            "app/config/base.yaml 파일이 존재하는지 확인하세요",
            "Git에서 최신 버전을 pull 하세요 (git pull origin main)",
            "레거시 config.yaml 파일 사용 시 app/config/config.yaml 확인",
            "파일 권한을 확인하세요 (읽기 권한 필요)",
        ],
        "en": [
            "Verify app/config/base.yaml file exists",
            "Pull latest version from Git (git pull origin main)",
            "For legacy config.yaml, check app/config/config.yaml",
            "Verify file permissions (read permission required)",
        ],
    },
    "CONFIG-002": {
        "ko": [
            "설정 파일에서 중복된 키를 검색하세요",
            "YAML 린터를 사용하여 문법을 검증하세요 (yamllint)",
            "들여쓰기가 올바른지 확인하세요 (공백 2칸 사용)",
            "주석으로 처리하거나 하나만 남기세요",
        ],
        "en": [
            "Search for duplicate keys in configuration file",
            "Validate syntax using YAML linter (yamllint)",
            "Verify indentation is correct (use 2 spaces)",
            "Comment out or keep only one key",
        ],
    },
    "CONFIG-003": {
        "ko": [
            "app/config/base.yaml의 필수 필드를 확인하세요",
            "Pydantic 스키마 정의를 참고하세요 (app/config/schemas/)",
            "타입이 올바른지 확인하세요 (문자열, 숫자, 불린 등)",
            "환경 변수가 올바르게 치환되는지 확인하세요",
            "로그에서 구체적인 검증 오류를 확인하세요",
        ],
        "en": [
            "Verify required fields in app/config/base.yaml",
            "Refer to Pydantic schema definitions (app/config/schemas/)",
            "Verify types are correct (string, number, boolean, etc.)",
            "Verify environment variables are substituted correctly",
            "Check logs for specific validation errors",
        ],
    },
    "CONFIG-004": {
        "ko": [
            "YAML 파일 형식이 올바른지 확인하세요",
            "파일 인코딩이 UTF-8인지 확인하세요",
            "파일 읽기 권한이 있는지 확인하세요",
            "imports 경로가 올바른지 확인하세요",
            "환경 변수 치환 형식이 올바른지 확인하세요 (${VAR_NAME})",
        ],
        "en": [
            "Verify YAML file format is correct",
            "Verify file encoding is UTF-8",
            "Verify file has read permissions",
            "Verify imports paths are correct",
            "Verify environment variable substitution format (${VAR_NAME})",
        ],
    },
    # LLM-008 (생성 타임아웃)
    "LLM-008": {
        "ko": [
            "네트워크 연결을 확인하세요",
            "OpenRouter 서비스 상태를 확인하세요",
            "타임아웃 설정을 늘려보세요 (config.yaml의 timeout 값)",
            "모델을 더 빠른 모델로 변경해보세요",
            "요청을 다시 시도하세요",
        ],
        "en": [
            "Verify network connection",
            "Check OpenRouter service status",
            "Increase timeout setting (timeout value in config.yaml)",
            "Try switching to a faster model",
            "Retry request",
        ],
    },
    # ROUTING (라우팅/규칙)
    "ROUTING-001": {
        "ko": [
            "라우팅 규칙 YAML 파일이 존재하는지 확인하세요",
            "요청한 규칙 이름이 올바른지 확인하세요",
        ],
        "en": [
            "Verify routing rules YAML file exists",
            "Check if the requested rule name is correct",
        ],
    },
    "ROUTING-002": {
        "ko": [
            "YAML 파일 형식이 올바른지 확인하세요",
            "규칙 스키마를 검토하세요",
        ],
        "en": [
            "Verify YAML file format is correct",
            "Review rule schema",
        ],
    },
    "ROUTING-003": {
        "ko": [
            "YAML 파일 경로가 올바른지 확인하세요",
            "파일 읽기 권한을 확인하세요",
            "YAML 문법 오류가 있는지 검토하세요",
        ],
        "en": [
            "Verify YAML file path is correct",
            "Check file read permissions",
            "Review YAML syntax for errors",
        ],
    },
    "ROUTING-004": {
        "ko": [
            "쿼리 내용을 검토하세요",
            "라우팅 규칙의 차단 조건을 확인하세요",
        ],
        "en": [
            "Review query content",
            "Check routing rule blocking conditions",
        ],
    },
    # EMBEDDING (임베딩)
    "EMBEDDING-001": {
        "ko": [
            "임베딩 모델 설정을 확인하세요",
            "애플리케이션을 재시작해보세요",
        ],
        "en": [
            "Verify embedding model configuration",
            "Try restarting the application",
        ],
    },
    "EMBEDDING-002": {
        "ko": [
            "네트워크 연결을 확인하세요",
            "임베딩 API 키가 유효한지 확인하세요",
            "요청을 다시 시도하세요",
        ],
        "en": [
            "Verify network connection",
            "Verify embedding API key is valid",
            "Retry request",
        ],
    },
    "EMBEDDING-003": {
        "ko": [
            "입력 텍스트가 비어있지 않은지 확인하세요",
            "입력 텍스트 길이가 제한을 초과하지 않는지 확인하세요",
        ],
        "en": [
            "Verify input text is not empty",
            "Check if input text length exceeds limit",
        ],
    },
    "EMBEDDING-004": {
        "ko": [
            "API 사용량을 확인하세요",
            "할당량 증가를 요청하세요",
            "잠시 후 다시 시도하세요",
        ],
        "en": [
            "Check API usage",
            "Request quota increase",
            "Try again later",
        ],
    },
    # GENERAL (일반)
    "GENERAL-001": {
        "ko": [
            "서버 로그를 확인하여 자세한 오류를 파악하세요",
            "시스템 관리자에게 문의하세요",
        ],
        "en": [
            "Check server logs for detailed error information",
            "Contact system administrator",
        ],
    },
    "GENERAL-002": {
        "ko": [
            "입력 데이터 형식을 확인하세요",
            "필수 필드가 모두 포함되었는지 확인하세요",
        ],
        "en": [
            "Verify input data format",
            "Check if all required fields are included",
        ],
    },
    "GENERAL-003": {
        "ko": [
            "다른 기능을 사용하세요",
            "기능 구현 예정을 확인하세요",
        ],
        "en": [
            "Use alternative feature",
            "Check feature implementation schedule",
        ],
    },
    "GENERAL-004": {
        "ko": [
            "서버 로그를 확인하여 자세한 오류를 파악하세요",
            "애플리케이션을 재시작해보세요",
            "시스템 관리자에게 문의하세요",
        ],
        "en": [
            "Check server logs for detailed error information",
            "Try restarting the application",
            "Contact system administrator",
        ],
    },
    # API (API 응답)
    "API-001": {
        "ko": [
            "서버 로그를 확인하여 자세한 오류를 파악하세요",
            "애플리케이션을 재시작해보세요",
            "데이터베이스 및 외부 서비스 연결을 확인하세요",
            "시스템 관리자에게 문의하세요",
        ],
        "en": [
            "Check server logs for detailed error information",
            "Try restarting the application",
            "Verify database and external service connections",
            "Contact system administrator",
        ],
    },
    # GROK (Grok Collections API)
    "GROK-001": {
        "ko": [
            "XAI_API_KEY 환경변수가 올바르게 설정되었는지 확인하세요",
            "xAI 콘솔(https://console.x.ai)에서 API 키를 발급받으세요",
            "API 키가 만료되지 않았는지 확인하세요",
        ],
        "en": [
            "Verify XAI_API_KEY environment variable is set correctly",
            "Get an API key from xAI console (https://console.x.ai)",
            "Check if your API key has expired",
        ],
    },
    "GROK-002": {
        "ko": [
            "잠시 후 다시 시도해주세요 (보통 1분 이내)",
            "API 호출 빈도를 줄여주세요",
            "xAI 콘솔에서 요금 플랜을 확인하세요",
        ],
        "en": [
            "Wait a moment and try again (usually within 1 minute)",
            "Reduce API call frequency",
            "Check your rate plan on xAI console",
        ],
    },
    "GROK-003": {
        "ko": [
            "xAI 콘솔에서 Collection ID가 올바른지 확인하세요",
            "네트워크 연결을 확인하세요",
            "xAI API 서비스 상태(https://status.x.ai)를 확인하세요",
        ],
        "en": [
            "Verify Collection ID is correct on xAI console",
            "Check your network connection",
            "Check xAI API service status (https://status.x.ai)",
        ],
    },
}


def get_message_template(error_code: str, lang: str = "ko") -> str:
    """에러 메시지 템플릿 가져오기.

    Args:
        error_code: 에러 코드 (예: "AUTH-001")
        lang: 언어 코드 ("ko" 또는 "en")

    Returns:
        에러 메시지 템플릿 문자열

    Raises:
        KeyError: 에러 코드가 존재하지 않는 경우
        ValueError: 지원하지 않는 언어 코드인 경우
    """
    if error_code not in ERROR_MESSAGES:
        raise KeyError(f"Unknown error code: {error_code}")

    if lang not in ("ko", "en"):
        raise ValueError(f"Unsupported language: {lang}")

    return ERROR_MESSAGES[error_code][lang]


def get_solutions_list(error_code: str, lang: str = "ko") -> list[str]:
    """에러 해결 방법 목록 가져오기.

    Args:
        error_code: 에러 코드 (예: "AUTH-001")
        lang: 언어 코드 ("ko" 또는 "en")

    Returns:
        에러 해결 방법 리스트

    Raises:
        KeyError: 에러 코드가 존재하지 않는 경우
        ValueError: 지원하지 않는 언어 코드인 경우
    """
    if error_code not in ERROR_SOLUTIONS:
        raise KeyError(f"Unknown error code: {error_code}")

    if lang not in ("ko", "en"):
        raise ValueError(f"Unsupported language: {lang}")

    return ERROR_SOLUTIONS[error_code][lang]
