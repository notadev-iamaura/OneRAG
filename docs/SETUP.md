# 설치 및 환경 설정 (Setup) - v1.0.0

이 문서는 Blank RAG 시스템을 로컬 환경에 설치하고 실행하는 방법을 안내합니다.

---

## 1. 사전 요구 사항

- **Python**: 3.11 버전 이상
- **Docker & Docker Compose**: Weaviate, PostgreSQL 등 인프라 실행용
- **UV**: 최신 패키지 관리자 (속도 및 의존성 해결을 위해 강력 권장)

---

## 2. 설치 단계

### 2.1 저장소 복제 및 의존성 설치
```bash
git clone <repository-url>
cd RAG_Standard

# uv를 사용하여 가상환경 생성 및 모든 의존성 설치
# v1.0.0부터 spaCy 한국어 모델(ko_core_news_sm)도 자동으로 설치됩니다.
uv sync
```

### 2.2 환경 변수 설정
`.env.example` 파일을 복사하여 `.env` 파일을 생성하고 필수 값을 입력합니다.

```bash
cp .env.example .env
```

**필수 입력 항목:**
- `FASTAPI_AUTH_KEY`: 관리자 API 보안 키 (X-API-Key 헤더에 사용)
- `GOOGLE_API_KEY`: Gemini API 키
- `WEAVIATE_URL`: Weaviate 서버 주소
- `DATABASE_URL`: PostgreSQL 연결 주소 (프롬프트 관리 및 감사 로그용)

---

## 3. 인프라 실행 (Docker)

로컬 개발을 위한 필수 컨테이너들을 실행합니다.

```bash
# Weaviate 및 DB 실행
docker compose -f docker-compose.weaviate.yml up -d
```

---

## 4. 애플리케이션 실행

```bash
# 개발 서버 실행 (Auto-reload 활성화)
make dev-reload

# 전체 테스트 실행 (1080+ 테스트)
# 테스트 환경에서는 Langfuse 로그 노이즈가 자동으로 차단됩니다.
make test
```

서버가 실행되면 `http://localhost:8000/docs`에서 Swagger UI를 확인할 수 있습니다. 관리자 API 호출 시 상단의 `Authorize` 버튼을 눌러 `FASTAPI_AUTH_KEY`를 입력하세요.

---

## 5. 모듈별 추가 설정

### 5.1 PII (개인정보 보호)
`ko_core_news_sm` 모델이 `uv sync` 시 설치되지 않았다면 수동으로 설치할 수 있습니다:
```bash
uv pip install https://github.com/explosion/spacy-models/releases/download/ko_core_news_sm-3.7.0/ko_core_news_sm-3.7.0-py3-none-any.whl
```

### 5.2 GraphRAG (지식 그래프)
시스템은 기본적으로 `NetworkX` 기반의 벡터 통합 검색을 사용합니다. 대규모 데이터를 위해 `Neo4j`를 사용하려면 `docker-compose.neo4j.yml`을 실행하고 설정을 변경하세요.
