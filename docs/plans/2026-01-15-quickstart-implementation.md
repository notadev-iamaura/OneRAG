# Quickstart 원클릭 실행 환경 구현 계획

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** `git clone` → `cp .env.example .env` → `make quickstart` 3단계로 RAG 시스템 실행 가능하게 만들기

**Architecture:** WeKnora 스타일 채택. 루트에 통합 docker-compose.yml 생성, Makefile에 quickstart 명령어 추가. 앱 서버와 Weaviate를 동시에 실행하고 헬스체크 후 샘플 데이터 자동 로드.

**Tech Stack:** Docker Compose, Make, Shell Script, Python (샘플 데이터 로드)

**참고 프로젝트:**
- [Dify](https://github.com/langgenius/dify) - docker-compose 구조
- [WeKnora](https://github.com/Tencent/WeKnora) - make 명령어 구조

---

## Task 1: 통합 docker-compose.yml 생성

**Files:**
- Create: `docker-compose.yml`
- Reference: `docker-compose.weaviate.yml`
- Reference: `Dockerfile`

**Step 1: docker-compose.yml 작성**

```yaml
# docker-compose.yml
# RAG_Standard 통합 실행 환경
# 사용법: docker compose up -d

version: '3.8'

services:
  # Weaviate 벡터 데이터베이스
  weaviate:
    image: cr.weaviate.io/semitechnologies/weaviate:1.27.8
    container_name: rag-weaviate
    restart: unless-stopped
    ports:
      - "8080:8080"
      - "50051:50051"
    environment:
      ENABLE_TOKENIZER_KAGOME_KR: 'true'
      PERSISTENCE_DATA_PATH: '/var/lib/weaviate'
      AUTHENTICATION_ANONYMOUS_ACCESS_ENABLED: 'true'
      QUERY_DEFAULTS_LIMIT: 25
      LOG_LEVEL: 'info'
    volumes:
      - weaviate_data:/var/lib/weaviate
    healthcheck:
      test: ["CMD", "wget", "--quiet", "--tries=1", "--spider", "http://localhost:8080/v1/.well-known/ready"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 30s

  # RAG API 서버
  api:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: rag-api
    restart: unless-stopped
    ports:
      - "8000:8000"
    environment:
      - WEAVIATE_URL=http://weaviate:8080
      - WEAVIATE_GRPC_PORT=50051
      - HOST=0.0.0.0
      - PORT=8000
      - ENVIRONMENT=development
      - LOG_LEVEL=INFO
    env_file:
      - .env
    depends_on:
      weaviate:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 60s

volumes:
  weaviate_data:
    name: rag_weaviate_data
```

**Step 2: docker-compose.yml 문법 검증**

Run: `docker compose config`
Expected: YAML 파싱 성공, 에러 없음

**Step 3: Commit**

```bash
git add docker-compose.yml
git commit -m "기능: 통합 docker-compose.yml 추가 (앱 서버 + Weaviate)"
```

---

## Task 2: .env.example 간소화 버전 생성

**Files:**
- Create: `.env.quickstart`

**Step 1: 최소 설정만 포함한 .env.quickstart 작성**

```bash
# .env.quickstart
# RAG_Standard Quickstart 환경변수
# 복사 후 API 키만 입력하면 바로 실행 가능
#
# 사용법:
#   cp .env.quickstart .env
#   # .env 파일에서 GOOGLE_API_KEY 입력
#   make quickstart

# =============================================================================
# 필수 설정 (2개만!)
# =============================================================================

# 1. API 인증 키 (아무 문자열, 32자 이상)
FASTAPI_AUTH_KEY=quickstart_dev_key_change_in_production_1234567890

# 2. LLM API 키 (아래 중 1개 선택하여 입력)
# Google AI Studio에서 무료 발급: https://makersuite.google.com/app/apikey
GOOGLE_API_KEY=your_google_api_key_here

# 또는 OpenAI
# OPENAI_API_KEY=sk-your_openai_key_here

# 또는 Anthropic
# ANTHROPIC_API_KEY=sk-ant-your_anthropic_key_here

# =============================================================================
# 자동 설정 (수정 불필요)
# =============================================================================
WEAVIATE_URL=http://weaviate:8080
WEAVIATE_GRPC_PORT=50051
ENVIRONMENT=development
LOG_LEVEL=INFO
HOST=0.0.0.0
PORT=8000
```

**Step 2: Commit**

```bash
git add .env.quickstart
git commit -m "문서: .env.quickstart 간소화 템플릿 추가"
```

---

## Task 3: 샘플 데이터 스크립트 생성

**Files:**
- Create: `scripts/load_sample_data.py`
- Create: `data/sample/faq.json`

**Step 1: 샘플 FAQ 데이터 생성**

```json
{
  "name": "RAG_Standard 샘플 FAQ",
  "description": "Quickstart 테스트용 샘플 데이터",
  "documents": [
    {
      "id": "faq-001",
      "title": "RAG란 무엇인가요?",
      "content": "RAG(Retrieval-Augmented Generation)는 검색 증강 생성 기술입니다. 대규모 언어 모델(LLM)이 답변을 생성하기 전에 관련 문서를 검색하여 더 정확하고 최신의 정보를 제공합니다. 기존 LLM의 환각(hallucination) 문제를 줄이고, 특정 도메인 지식을 활용할 수 있게 해줍니다.",
      "metadata": {"category": "개념", "difficulty": "초급"}
    },
    {
      "id": "faq-002",
      "title": "Weaviate는 무엇인가요?",
      "content": "Weaviate는 오픈소스 벡터 데이터베이스입니다. 텍스트, 이미지 등의 데이터를 벡터로 변환하여 저장하고, 의미 기반 검색(semantic search)을 지원합니다. BM25와 벡터 검색을 결합한 하이브리드 검색이 가능하며, 한국어 토크나이저도 지원합니다.",
      "metadata": {"category": "기술", "difficulty": "초급"}
    },
    {
      "id": "faq-003",
      "title": "GraphRAG의 장점은 무엇인가요?",
      "content": "GraphRAG는 지식 그래프와 RAG를 결합한 기술입니다. 단순 문서 검색을 넘어 엔티티 간의 관계를 추론할 수 있습니다. 예를 들어 '삼성전자의 경쟁사는?'이라는 질문에 직접적인 답이 없어도, 그래프 관계를 통해 관련 기업들을 찾아낼 수 있습니다.",
      "metadata": {"category": "기술", "difficulty": "중급"}
    },
    {
      "id": "faq-004",
      "title": "이 시스템의 API 키는 어떻게 발급받나요?",
      "content": "Google AI Studio(https://makersuite.google.com/app/apikey)에서 무료로 발급받을 수 있습니다. 계정당 분당 60회 요청이 무료입니다. OpenAI나 Anthropic API 키도 사용 가능하며, .env 파일에 설정하면 됩니다.",
      "metadata": {"category": "설정", "difficulty": "초급"}
    },
    {
      "id": "faq-005",
      "title": "Docker 없이 실행할 수 있나요?",
      "content": "가능합니다. Python 3.11 이상과 uv 패키지 매니저가 필요합니다. 'uv sync'로 의존성을 설치하고, Weaviate는 별도로 실행해야 합니다. 하지만 Docker Compose를 사용하면 'make quickstart' 한 줄로 모든 것이 자동 설정됩니다.",
      "metadata": {"category": "설정", "difficulty": "초급"}
    }
  ]
}
```

**Step 2: 샘플 데이터 로드 스크립트 생성**

```python
#!/usr/bin/env python3
"""
샘플 데이터 로드 스크립트
RAG_Standard quickstart용 FAQ 데이터를 Weaviate에 자동 인덱싱합니다.

사용법:
    python scripts/load_sample_data.py

    또는 make quickstart 실행 시 자동 호출됩니다.
"""

import json
import os
import sys
import time
from pathlib import Path

# 프로젝트 루트를 Python 경로에 추가
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


def wait_for_weaviate(url: str, max_retries: int = 30, delay: int = 2) -> bool:
    """Weaviate 서버가 준비될 때까지 대기합니다."""
    import httpx

    print(f"⏳ Weaviate 서버 대기 중... ({url})")

    for i in range(max_retries):
        try:
            response = httpx.get(f"{url}/v1/.well-known/ready", timeout=5)
            if response.status_code == 200:
                print("✅ Weaviate 서버 준비 완료!")
                return True
        except Exception:
            pass

        print(f"   재시도 {i + 1}/{max_retries}...")
        time.sleep(delay)

    print("❌ Weaviate 서버 연결 실패")
    return False


def wait_for_api(url: str, max_retries: int = 30, delay: int = 2) -> bool:
    """API 서버가 준비될 때까지 대기합니다."""
    import httpx

    print(f"⏳ API 서버 대기 중... ({url})")

    for i in range(max_retries):
        try:
            response = httpx.get(f"{url}/health", timeout=5)
            if response.status_code == 200:
                print("✅ API 서버 준비 완료!")
                return True
        except Exception:
            pass

        print(f"   재시도 {i + 1}/{max_retries}...")
        time.sleep(delay)

    print("❌ API 서버 연결 실패")
    return False


def load_sample_data(api_url: str, api_key: str, data_path: str) -> bool:
    """샘플 데이터를 API를 통해 인덱싱합니다."""
    import httpx

    print(f"📂 샘플 데이터 로드 중... ({data_path})")

    # JSON 파일 로드
    with open(data_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    documents = data.get("documents", [])
    print(f"   {len(documents)}개 문서 발견")

    # 각 문서를 인덱싱
    headers = {"X-API-Key": api_key, "Content-Type": "application/json"}
    success_count = 0

    for doc in documents:
        try:
            # 인덱싱 API 호출 (실제 엔드포인트에 맞게 조정 필요)
            payload = {
                "content": doc["content"],
                "metadata": {
                    "title": doc["title"],
                    "doc_id": doc["id"],
                    **doc.get("metadata", {})
                }
            }

            response = httpx.post(
                f"{api_url}/api/admin/documents",
                json=payload,
                headers=headers,
                timeout=30
            )

            if response.status_code in (200, 201):
                success_count += 1
                print(f"   ✅ {doc['id']}: {doc['title']}")
            else:
                print(f"   ⚠️ {doc['id']}: HTTP {response.status_code}")

        except Exception as e:
            print(f"   ❌ {doc['id']}: {str(e)}")

    print(f"\n📊 결과: {success_count}/{len(documents)} 문서 인덱싱 완료")
    return success_count > 0


def main():
    """메인 실행 함수"""
    # 환경변수에서 설정 로드
    weaviate_url = os.getenv("WEAVIATE_URL", "http://localhost:8080")
    api_url = os.getenv("API_URL", "http://localhost:8000")
    api_key = os.getenv("FASTAPI_AUTH_KEY", "")

    # Docker 내부에서 실행 시 호스트명 조정
    if os.getenv("DOCKER_INTERNAL"):
        weaviate_url = "http://weaviate:8080"
        api_url = "http://api:8000"

    data_path = project_root / "data" / "sample" / "faq.json"

    print("=" * 50)
    print("🚀 RAG_Standard 샘플 데이터 로더")
    print("=" * 50)

    # 1. Weaviate 대기
    if not wait_for_weaviate(weaviate_url):
        sys.exit(1)

    # 2. API 서버 대기
    if not wait_for_api(api_url):
        sys.exit(1)

    # 3. 샘플 데이터 로드
    if not data_path.exists():
        print(f"❌ 샘플 데이터 파일 없음: {data_path}")
        sys.exit(1)

    if not api_key:
        print("⚠️ FASTAPI_AUTH_KEY 미설정 - 샘플 데이터 로드 건너뜀")
        print("   .env 파일에 API 키를 설정한 후 다시 실행하세요.")
        sys.exit(0)

    if load_sample_data(api_url, api_key, str(data_path)):
        print("\n" + "=" * 50)
        print("✅ Quickstart 준비 완료!")
        print("=" * 50)
        print(f"\n👉 API 문서: {api_url}/docs")
        print(f"👉 헬스체크: {api_url}/health")
        print("\n테스트 질문 예시:")
        print('   curl -X POST "{api_url}/api/chat" \\')
        print('        -H "X-API-Key: {your_key}" \\')
        print('        -H "Content-Type: application/json" \\')
        print('        -d \'{"message": "RAG란 무엇인가요?"}\'')
    else:
        print("\n⚠️ 샘플 데이터 로드 실패 - 수동으로 데이터를 추가하세요.")
        sys.exit(1)


if __name__ == "__main__":
    main()
```

**Step 3: 디렉토리 생성 및 파일 저장**

Run: `mkdir -p data/sample`

**Step 4: Commit**

```bash
git add data/sample/faq.json scripts/load_sample_data.py
git commit -m "기능: 샘플 FAQ 데이터 및 로드 스크립트 추가"
```

---

## Task 4: Makefile에 quickstart 명령어 추가

**Files:**
- Modify: `Makefile`

**Step 1: Makefile에 quickstart 관련 명령어 추가**

Makefile 상단 `.PHONY` 라인에 추가:
```makefile
.PHONY: help install install-dev sync update run dev test lint format clean docker-build docker-run neo4j-up neo4j-down neo4j-logs test-neo4j quickstart quickstart-down quickstart-logs quickstart-load-data
```

help 섹션에 추가:
```makefile
	@echo ""
	@echo "Quickstart (원클릭 실행):"
	@echo "quickstart        - Docker로 전체 시스템 실행 (Weaviate + API)"
	@echo "quickstart-down   - Quickstart 시스템 종료"
	@echo "quickstart-logs   - Quickstart 로그 확인"
	@echo "quickstart-load-data - 샘플 데이터 로드"
```

Makefile 하단에 quickstart 섹션 추가:
```makefile
# =============================================================================
# Quickstart (원클릭 실행)
# =============================================================================

# Docker 및 Docker Compose 설치 확인
check-docker:
	@command -v docker >/dev/null 2>&1 || { echo "❌ Docker가 설치되어 있지 않습니다. https://docs.docker.com/get-docker/ 에서 설치하세요."; exit 1; }
	@docker compose version >/dev/null 2>&1 || { echo "❌ Docker Compose가 설치되어 있지 않습니다."; exit 1; }
	@echo "✅ Docker 환경 확인 완료"

# .env 파일 확인
check-env:
	@if [ ! -f .env ]; then \
		echo "⚠️  .env 파일이 없습니다. .env.quickstart에서 복사합니다..."; \
		cp .env.quickstart .env; \
		echo "📝 .env 파일이 생성되었습니다."; \
		echo "   GOOGLE_API_KEY를 설정한 후 다시 실행하세요."; \
		echo "   발급: https://makersuite.google.com/app/apikey"; \
		exit 1; \
	fi
	@grep -q "your_google_api_key_here\|your_openai_key_here\|your_anthropic_key_here" .env && { \
		echo "❌ .env 파일에 API 키가 설정되지 않았습니다."; \
		echo "   GOOGLE_API_KEY, OPENAI_API_KEY, 또는 ANTHROPIC_API_KEY 중 하나를 설정하세요."; \
		exit 1; \
	} || true
	@echo "✅ 환경변수 확인 완료"

# Quickstart 전체 실행
quickstart: check-docker check-env
	@echo "🚀 RAG_Standard Quickstart 시작..."
	@echo ""
	docker compose up -d --build
	@echo ""
	@echo "⏳ 서비스 시작 대기 중... (약 1-2분 소요)"
	@sleep 10
	@$(MAKE) quickstart-load-data || true
	@echo ""
	@echo "=============================================="
	@echo "✅ RAG_Standard가 실행 중입니다!"
	@echo "=============================================="
	@echo ""
	@echo "👉 API 문서: http://localhost:8000/docs"
	@echo "👉 헬스체크: http://localhost:8000/health"
	@echo "👉 Weaviate: http://localhost:8080"
	@echo ""
	@echo "종료하려면: make quickstart-down"

# Quickstart 종료
quickstart-down:
	@echo "🛑 RAG_Standard 종료 중..."
	docker compose down
	@echo "✅ 종료 완료"

# Quickstart 로그 확인
quickstart-logs:
	docker compose logs -f

# API 서버 로그만 확인
quickstart-logs-api:
	docker compose logs -f api

# Weaviate 로그만 확인
quickstart-logs-weaviate:
	docker compose logs -f weaviate

# 샘플 데이터 로드
quickstart-load-data:
	@echo "📂 샘플 데이터 로드 중..."
	@if [ -f .env ]; then \
		export $$(grep -v '^#' .env | xargs) && \
		python scripts/load_sample_data.py; \
	else \
		echo "⚠️ .env 파일이 없어 샘플 데이터를 로드할 수 없습니다."; \
	fi

# 데이터 볼륨 포함 완전 삭제
quickstart-clean:
	@echo "🧹 RAG_Standard 데이터 정리 중..."
	docker compose down -v
	@echo "✅ 모든 데이터가 삭제되었습니다."
```

**Step 2: Makefile 문법 검증**

Run: `make help`
Expected: quickstart 관련 명령어가 도움말에 표시됨

**Step 3: Commit**

```bash
git add Makefile
git commit -m "기능: Makefile에 quickstart 명령어 추가"
```

---

## Task 5: README.md 업데이트

**Files:**
- Modify: `README.md`
- Modify: `README_EN.md`

**Step 1: README.md의 Quick Start 섹션 수정**

기존 "🏃 빠른 시작 (5분)" 섹션을 다음으로 교체:

```markdown
## 🏃 빠른 시작 (3분)

### 사전 요구사항

- Docker & Docker Compose ([설치 가이드](https://docs.docker.com/get-docker/))
- LLM API 키 (아래 중 1개)
  - [Google AI Studio](https://makersuite.google.com/app/apikey) - **무료 티어 제공 (권장)**
  - [OpenAI](https://platform.openai.com/api-keys)
  - [Anthropic](https://console.anthropic.com/)

### 3단계 실행

```bash
# 1. 클론
git clone https://github.com/youngouk/RAG_Standard.git
cd RAG_Standard

# 2. 환경변수 설정
cp .env.quickstart .env
# .env 파일을 열어 GOOGLE_API_KEY 입력

# 3. 실행
make quickstart
```

**끝!** 브라우저에서 http://localhost:8000/docs 접속

### 종료

```bash
make quickstart-down
```

> 📖 **상세 설정 가이드**: Docker 없이 실행하거나 프로덕션 환경 설정은 [docs/SETUP.md](docs/SETUP.md) 참조
```

**Step 2: README_EN.md 동일하게 수정**

```markdown
## 🏃 Quick Start (3 minutes)

### Prerequisites

- Docker & Docker Compose ([Install Guide](https://docs.docker.com/get-docker/))
- LLM API Key (one of the following)
  - [Google AI Studio](https://makersuite.google.com/app/apikey) - **Free tier available (Recommended)**
  - [OpenAI](https://platform.openai.com/api-keys)
  - [Anthropic](https://console.anthropic.com/)

### 3-Step Setup

```bash
# 1. Clone
git clone https://github.com/youngouk/RAG_Standard.git
cd RAG_Standard

# 2. Configure
cp .env.quickstart .env
# Edit .env and set GOOGLE_API_KEY

# 3. Run
make quickstart
```

**Done!** Open http://localhost:8000/docs in your browser

### Stop

```bash
make quickstart-down
```

> 📖 **Detailed Setup Guide**: For running without Docker or production setup, see [docs/SETUP.md](docs/SETUP.md)
```

**Step 3: Commit**

```bash
git add README.md README_EN.md
git commit -m "문서: Quick Start를 3단계로 간소화"
```

---

## Task 6: 통합 테스트

**Step 1: docker-compose 빌드 테스트**

Run: `docker compose build`
Expected: 빌드 성공

**Step 2: docker-compose 실행 테스트**

Run: `docker compose up -d`
Expected: 컨테이너 2개 실행 (weaviate, api)

**Step 3: 헬스체크**

Run: `curl http://localhost:8000/health`
Expected: HTTP 200, JSON 응답

**Step 4: Weaviate 연결 확인**

Run: `curl http://localhost:8080/v1/.well-known/ready`
Expected: HTTP 200

**Step 5: 종료**

Run: `docker compose down`

**Step 6: make quickstart 전체 테스트**

Run: `make quickstart`
Expected:
- Docker 환경 확인 완료
- 환경변수 확인 완료
- 서비스 시작
- 샘플 데이터 로드 (API 키 있을 경우)
- 완료 메시지 출력

**Step 7: 최종 Commit**

```bash
git add -A
git commit -m "기능: Quickstart 원클릭 실행 환경 완성

- 통합 docker-compose.yml (앱 서버 + Weaviate)
- .env.quickstart 간소화 템플릿
- 샘플 FAQ 데이터 및 로드 스크립트
- Makefile quickstart 명령어
- README 3단계 Quick Start로 업데이트

사용법:
  git clone → cp .env.quickstart .env → make quickstart"
```

---

## 체크리스트

- [ ] Task 1: docker-compose.yml 생성
- [ ] Task 2: .env.quickstart 생성
- [ ] Task 3: 샘플 데이터 및 로드 스크립트
- [ ] Task 4: Makefile quickstart 명령어
- [ ] Task 5: README 업데이트
- [ ] Task 6: 통합 테스트

---

## 예상 결과

```bash
$ git clone https://github.com/youngouk/RAG_Standard.git
$ cd RAG_Standard
$ cp .env.quickstart .env
$ # GOOGLE_API_KEY 입력
$ make quickstart

🚀 RAG_Standard Quickstart 시작...
✅ Docker 환경 확인 완료
✅ 환경변수 확인 완료

[+] Building...
[+] Running 2/2
 ✔ Container rag-weaviate  Started
 ✔ Container rag-api       Started

⏳ 서비스 시작 대기 중...
✅ Weaviate 서버 준비 완료!
✅ API 서버 준비 완료!
📂 샘플 데이터 로드 중...
   ✅ faq-001: RAG란 무엇인가요?
   ✅ faq-002: Weaviate는 무엇인가요?
   ...

==============================================
✅ RAG_Standard가 실행 중입니다!
==============================================

👉 API 문서: http://localhost:8000/docs
👉 헬스체크: http://localhost:8000/health
👉 Weaviate: http://localhost:8080

종료하려면: make quickstart-down
```
