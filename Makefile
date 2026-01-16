.PHONY: help install install-dev sync update run dev test lint format clean docker-build docker-run neo4j-up neo4j-down neo4j-logs test-neo4j quickstart quickstart-down quickstart-logs quickstart-load frontend-install frontend-dev frontend-build frontend-lint frontend-test fullstack fullstack-down fullstack-logs fullstack-build

# 기본 타겟
.DEFAULT_GOAL := help

# 도움말
help:
	@echo "RAG_Standard - Makefile Commands"
	@echo "================================="
	@echo ""
	@echo "🚀 Quickstart (처음 시작하세요!):"
	@echo "  quickstart      - 원클릭 실행 (Weaviate + API + 샘플데이터)"
	@echo "  quickstart-down - Quickstart 서비스 종료"
	@echo "  quickstart-logs - Quickstart 로그 확인"
	@echo "  quickstart-load - 샘플 데이터만 로드"
	@echo ""
	@echo "📦 설치:"
	@echo "  install         - uv로 프로덕션 의존성 설치"
	@echo "  install-dev     - uv로 개발 의존성 포함 설치"
	@echo "  sync            - uv.lock 파일과 동기화"
	@echo "  update          - 의존성 업데이트"
	@echo ""
	@echo "🔧 개발:"
	@echo "  run             - 프로덕션 서버 실행"
	@echo "  dev             - 개발 서버 실행"
	@echo "  dev-reload      - 개발 서버 (자동 리로드)"
	@echo "  dev-fast        - 빠른 개발 서버 (로깅 최소화)"
	@echo ""
	@echo "🧪 테스트:"
	@echo "  test            - 테스트 실행"
	@echo "  test-cov        - 테스트 커버리지"
	@echo "  test-eval       - 평가 테스트 (CI/CD 품질 게이트)"
	@echo ""
	@echo "✨ 코드 품질:"
	@echo "  lint            - 코드 린팅 (ruff)"
	@echo "  lint-fix        - 린팅 자동 수정"
	@echo "  lint-imports    - 의존성 계층 검증"
	@echo "  format          - 코드 포맷팅"
	@echo "  type-check      - 타입 체크 (mypy)"
	@echo ""
	@echo "🐳 Docker:"
	@echo "  docker-build    - Docker 이미지 빌드"
	@echo "  docker-run      - Docker 컨테이너 실행"
	@echo ""
	@echo "📊 Neo4j (GraphRAG):"
	@echo "  neo4j-up        - Neo4j 컨테이너 시작"
	@echo "  neo4j-down      - Neo4j 컨테이너 종료"
	@echo "  neo4j-logs      - Neo4j 로그 확인"
	@echo "  test-neo4j      - Neo4j 통합 테스트"
	@echo ""
	@echo "🎨 Frontend (React):"
	@echo "  frontend-install - 프론트엔드 의존성 설치"
	@echo "  frontend-dev     - 프론트엔드 개발 서버 (localhost:5173)"
	@echo "  frontend-build   - 프론트엔드 프로덕션 빌드"
	@echo "  frontend-lint    - 프론트엔드 린트 검사"
	@echo "  frontend-test    - 프론트엔드 테스트"
	@echo ""
	@echo "🔗 Fullstack (Frontend + Backend + Weaviate):"
	@echo "  fullstack       - 전체 스택 Docker Compose 실행"
	@echo "  fullstack-down  - Fullstack 서비스 종료"
	@echo "  fullstack-logs  - Fullstack 로그 확인"
	@echo "  fullstack-build - Fullstack Docker 이미지 빌드"

# uv 설치 확인
check-uv:
	@command -v uv >/dev/null 2>&1 || { echo "uv가 설치되어 있지 않습니다. 'curl -LsSf https://astral.sh/uv/install.sh | sh'로 설치하세요."; exit 1; }

# 프로덕션 의존성 설치
install: check-uv
	uv sync --no-dev

# 개발 의존성 포함 설치
install-dev: check-uv
	uv sync

# lock 파일과 동기화
sync: check-uv
	uv sync

# 의존성 업데이트
update: check-uv
	uv lock --upgrade

# 프로덕션 서버 실행
run: install
	uv run python main.py

# 개발 서버 실행
dev: install-dev
	uv run python main.py

# 개발 서버 실행 (uvicorn 직접 실행)
dev-reload: install-dev
	uv run uvicorn main:app --reload --host 0.0.0.0 --port 8001 --reload-delay 0.25

# 빠른 개발 서버 (로깅 최소화)
dev-fast: install-dev
	uv run uvicorn main:app --reload --host 0.0.0.0 --port 8001 --log-level warning --reload-delay 0.25

# 테스트 실행 (UV 환경)
test: install-dev
	uv run pytest

# 테스트 실행 (시스템 Python 환경 - UV 문제 시 대안)
test-system:
	@echo "🐍 Using system Python environment..."
	@if [ ! -d ".venv_system" ]; then \
		echo "Creating system Python environment..."; \
		python3 -m venv .venv_system; \
		.venv_system/bin/pip install pytest pytest-asyncio fastapi pyyaml structlog psutil; \
	fi
	@source .venv_system/bin/activate && python -m pytest

# 테스트 환경 자동 설정 및 실행
test-auto:
	@echo "🚀 Auto-configuring test environment..."
	@./scripts/test-env-setup.sh --minimal
	@if [ -d ".venv" ] && [ -f ".venv/bin/activate" ]; then \
		echo "Using UV environment..."; \
		source .venv/bin/activate && python -m pytest; \
	elif [ -d ".venv_system" ]; then \
		echo "Using system Python environment..."; \
		source .venv_system/bin/activate && python -m pytest; \
	else \
		echo "❌ No suitable environment found"; \
		exit 1; \
	fi

# 기본 테스트 (타임아웃 방지)
test-basic:
	@echo "🧪 Running basic tests only..."
	@if [ -d ".venv_system" ]; then \
		source .venv_system/bin/activate && python -m pytest tests/test_basic.py tests/test_config_simple.py -v --tb=short; \
	else \
		./scripts/test-env-setup.sh --system --minimal && \
		source .venv_system/bin/activate && python -m pytest tests/test_basic.py tests/test_config_simple.py -v --tb=short; \
	fi

# 테스트 커버리지
test-cov: install-dev
	uv run pytest --cov=app --cov-report=html --cov-report=term

# 평가 테스트 (CI/CD 품질 게이트)
test-eval: install-dev
	uv run pytest -m eval -v

# 배치 평가 실행 (Golden Dataset)
eval: install-dev
	uv run python scripts/run_eval.py

# 배치 평가 (Ragas 사용)
eval-ragas: install-dev
	uv run python scripts/run_eval.py --provider ragas

# 테스트 환경 진단
test-env-check:
	@echo "🔍 Testing environment diagnosis..."
	@./scripts/test-env-setup.sh --verbose

# 린팅
lint: install-dev
	uv run ruff check .

# 린팅 수정
lint-fix: install-dev
	uv run ruff check --fix .

# 코드 포맷팅
format: install-dev
	uv run black .
	uv run ruff check --fix .

# 타입 체크
type-check: install-dev
	uv run mypy .

# Import 의존성 검증 (v3.1.0+)
lint-imports: install-dev
	@echo "🔍 Checking import dependencies..."
	uv run lint-imports

# 의존성 그래프 생성 (v3.1.0+)
deps-graph: install-dev
	@echo "📊 Generating dependency graph..."
	@mkdir -p docs/diagrams
	uv run pydeps app --max-bacon=2 --cluster --rankdir=TB -o docs/diagrams/dependencies.svg
	@echo "✅ Dependency graph saved to docs/diagrams/dependencies.svg"

# 정리
clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	find . -type f -name "*.pyo" -delete
	find . -type f -name "*.log" -delete
	find . -type d -name ".pytest_cache" -exec rm -rf {} +
	find . -type d -name ".mypy_cache" -exec rm -rf {} +
	find . -type d -name ".ruff_cache" -exec rm -rf {} +
	find . -type f -name ".coverage" -delete
	find . -type d -name "htmlcov" -exec rm -rf {} +
	rm -rf uploads/temp/*

# Docker 빌드
docker-build:
	docker build -t rag-chatbot:latest .

# Docker 실행
docker-run:
	docker run -p 8000:8000 --env-file ../.env rag-chatbot:latest

# 환경 정보 출력
info: check-uv
	@echo "Python version:"
	@uv run python --version
	@echo "\nInstalled packages:"
	@uv pip list

# 개발 환경 초기 설정
setup: check-uv
	uv venv
	uv sync
	@echo "\n✅ 개발 환경 설정 완료!"
	@echo "다음 명령어로 개발 서버를 실행하세요: make dev"

# =============================================================================
# Neo4j 관련 명령 (GraphRAG 로컬 개발용)
# =============================================================================

# Neo4j 로컬 시작
neo4j-up:
	docker-compose -f docker-compose.neo4j.yml up -d
	@echo "✅ Neo4j 시작됨"
	@echo "Neo4j UI: http://localhost:7474"
	@echo "Bolt: bolt://localhost:7687"
	@echo "초기 인증: neo4j / testpassword123"

# Neo4j 로컬 중지
neo4j-down:
	docker-compose -f docker-compose.neo4j.yml down
	@echo "✅ Neo4j 중지됨"

# Neo4j 로그 확인
neo4j-logs:
	docker-compose -f docker-compose.neo4j.yml logs -f

# Neo4j 통합 테스트 (로컬 Neo4j 필요)
test-neo4j:
	@echo "🧪 Neo4j 통합 테스트 실행..."
	@echo "⚠️  먼저 'make neo4j-up'으로 Neo4j를 시작하세요"
	NEO4J_URI=bolt://localhost:7687 \
	NEO4J_USER=neo4j \
	NEO4J_PASSWORD=testpassword123 \
	uv run pytest tests/integration/test_neo4j_integration.py -v -m integration

# =============================================================================
# Quickstart 명령 (원클릭 실행)
# =============================================================================

# .env 파일 확인
check-env:
	@if [ ! -f .env ]; then \
		echo "❌ .env 파일이 없습니다."; \
		echo ""; \
		echo "다음 명령어로 .env 파일을 생성하세요:"; \
		echo "  cp quickstart/.env.quickstart .env"; \
		echo ""; \
		echo "그 후 .env 파일을 열어 API 키를 설정하세요:"; \
		echo "  - Google AI Studio (무료): https://aistudio.google.com/apikey"; \
		echo "  - OpenAI: https://platform.openai.com/api-keys"; \
		exit 1; \
	fi

# Quickstart 원클릭 실행
quickstart: check-env
	@echo "🚀 RAG_Standard Quickstart 시작..."
	@echo ""
	@echo "1️⃣  Docker 서비스 시작 중..."
	docker compose up -d
	@echo ""
	@echo "2️⃣  서비스 준비 대기 중..."
	@sleep 5
	@echo ""
	@echo "3️⃣  샘플 데이터 로드 중..."
	uv run python quickstart/load_sample_data.py
	@echo ""
	@echo "=============================================="
	@echo "🎉 Quickstart 완료!"
	@echo ""
	@echo "📖 API 문서: http://localhost:8000/docs"
	@echo "❤️  Health:   http://localhost:8000/health"
	@echo ""
	@echo "종료: make quickstart-down"
	@echo "=============================================="

# Quickstart 서비스 종료
quickstart-down:
	@echo "🛑 Quickstart 서비스 종료 중..."
	docker compose down
	@echo "✅ 종료 완료"

# Quickstart 로그 확인
quickstart-logs:
	docker compose logs -f

# 샘플 데이터만 로드
quickstart-load:
	@echo "📥 샘플 데이터 로드 중..."
	uv run python quickstart/load_sample_data.py

# =============================================================================
# Frontend 명령 (React 프론트엔드)
# =============================================================================

# 프론트엔드 의존성 설치
frontend-install:
	@echo "📦 프론트엔드 의존성 설치 중..."
	cd frontend && npm install
	@echo "✅ 프론트엔드 의존성 설치 완료"

# 프론트엔드 개발 서버
frontend-dev: frontend-install
	@echo "🎨 프론트엔드 개발 서버 시작..."
	@echo "URL: http://localhost:5173"
	cd frontend && npm run dev

# 프론트엔드 프로덕션 빌드
frontend-build: frontend-install
	@echo "🔨 프론트엔드 프로덕션 빌드 중..."
	cd frontend && npm run build
	@echo "✅ 프론트엔드 빌드 완료 (frontend/dist/)"

# 프론트엔드 린트
frontend-lint: frontend-install
	@echo "🔍 프론트엔드 린트 검사 중..."
	cd frontend && npm run lint

# 프론트엔드 테스트
frontend-test: frontend-install
	@echo "🧪 프론트엔드 테스트 실행..."
	cd frontend && npm run test:run

# =============================================================================
# Fullstack 명령 (Frontend + Backend + Weaviate)
# =============================================================================

# Fullstack Docker Compose 실행 (Frontend + Backend + DB + 가이드 챗봇 데이터)
fullstack: check-env
	@echo "🚀 Fullstack 서비스 시작 중..."
	@echo ""
	@echo "서비스 목록:"
	@echo "  - Weaviate (벡터 DB): http://localhost:8080"
	@echo "  - Backend (API):      http://localhost:8000"
	@echo "  - Frontend (React):   http://localhost:5173"
	@echo ""
	@echo "1️⃣  Docker 서비스 시작 중..."
	docker compose --profile fullstack up -d
	@echo ""
	@echo "2️⃣  서비스 준비 대기 중..."
	@sleep 10
	@echo ""
	@echo "3️⃣  가이드 챗봇 데이터 로드 중..."
	uv run python quickstart/load_sample_data.py
	@echo ""
	@echo "=============================================="
	@echo "🎉 Fullstack 서비스 준비 완료!"
	@echo ""
	@echo "🎨 Frontend: http://localhost:5173"
	@echo "📖 API Docs: http://localhost:8000/docs"
	@echo "❤️  Health:   http://localhost:8000/health"
	@echo ""
	@echo "💬 가이드 챗봇 테스트 질문:"
	@echo "   - RAG_Standard 어떻게 설치해?"
	@echo "   - 채팅 API 사용법 알려줘"
	@echo "   - 환경변수 뭐 설정해야 돼?"
	@echo ""
	@echo "종료: make fullstack-down"
	@echo "=============================================="

# Fullstack 서비스 종료
fullstack-down:
	@echo "🛑 Fullstack 서비스 종료 중..."
	docker compose --profile fullstack down
	@echo "✅ 종료 완료"

# Fullstack 로그 확인
fullstack-logs:
	docker compose --profile fullstack logs -f

# Fullstack Docker 이미지 빌드
fullstack-build:
	@echo "🔨 Fullstack Docker 이미지 빌드 중..."
	docker compose --profile fullstack build
	@echo "✅ 이미지 빌드 완료"