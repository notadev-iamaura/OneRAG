# 설치 및 환경 설정 (Setup)

이 문서는 OneRAG를 로컬 환경에 설치하고 실행하는 방법을 안내합니다.

---

## 1. 사전 요구 사항

- **Python**: 3.11 버전 이상
- **Docker & Docker Compose**: Weaviate, PostgreSQL 등 인프라 실행용
- **UV**: 최신 패키지 관리자 (속도 및 의존성 해결을 위해 강력 권장)

---

## 2. 설치 단계

### 2.1 저장소 복제 및 의존성 설치
```bash
git clone https://github.com/notadev-iamaura/OneRAG.git
cd OneRAG

uv sync
```

### 2.2 환경 변수 설정
Docker 기반 API 서버를 실행하려면 quickstart 템플릿을 복사해 `.env` 파일을 생성합니다.

```bash
cp quickstart/.env.quickstart .env
```

최소 입력 항목:
- `GOOGLE_API_KEY`: Gemini API 키. AI 답변 생성에 필요합니다.
- `FASTAPI_AUTH_KEY`: 관리자/업로드 API 보안 키. 로컬 기본값은 템플릿에 포함되어 있지만 외부 노출 전 반드시 변경하세요.

Docker 없이 CLI 체험만 할 경우에는 `.env`를 미리 만들 필요가 없습니다. `.env`가 없을 때 `make easy-start`가 `easy_start/.env.example`에서 자동 생성합니다.

---

## 3. 인프라 실행 (Docker)

Full API 서버는 Docker Compose로 Weaviate와 API 서버를 함께 실행합니다.

```bash
make start
```

---

## 4. 애플리케이션 실행

```bash
# Docker 없이 CLI 챗봇 실행
make easy-start

# 개발 서버 실행 (Auto-reload 활성화, 포트 8001)
make dev-reload

# 전체 테스트 실행
make test
```

`make start`로 서버를 실행하면 `http://localhost:8000/docs`에서 Swagger UI를 확인할 수 있습니다. `make dev-reload`는 `http://localhost:8001/docs`를 사용합니다. 관리자/업로드 API 호출 시 상단의 `Authorize` 버튼을 눌러 `FASTAPI_AUTH_KEY`를 입력하세요.

---

## 5. 모듈별 추가 설정

### 5.1 PII (개인정보 보호)
한국어 PII 기능에서 spaCy 한국어 모델이 필요하고 로컬 환경에 없다면 수동으로 설치할 수 있습니다:
```bash
uv pip install https://github.com/explosion/spacy-models/releases/download/ko_core_news_sm-3.7.0/ko_core_news_sm-3.7.0-py3-none-any.whl
```

### 5.2 GraphRAG (지식 그래프)
시스템은 기본적으로 `NetworkX` 기반의 벡터 통합 검색을 사용합니다. 대규모 데이터를 위해 `Neo4j`를 사용하려면 `docker-compose.neo4j.yml`을 실행하고 설정을 변경하세요.
