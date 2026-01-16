# RAG_Standard 사용 가이드 챗봇 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Quickstart 샘플 데이터를 25개 문서로 확장하여 "RAG_Standard 오픈소스 사용 가이드 챗봇"을 제공한다.

**Architecture:** 기존 `quickstart/sample_data.json`을 확장하고, `make fullstack`에 데이터 로드를 추가한다. 문서는 6개 카테고리(시작하기, 핵심개념, API사용법, 설정가이드, 아키텍처, 개발자가이드)로 구조화하며, 각 문서는 실제 코드 예시와 명확한 설명을 포함한다.

**Tech Stack:** JSON (샘플 데이터), Makefile (빌드 자동화), Weaviate (벡터 DB), Python (로드 스크립트)

---

## Task 1: Makefile fullstack 명령어에 샘플 데이터 로드 추가

**Files:**
- Modify: `Makefile:346-364` (fullstack 타겟)

**Step 1: fullstack 타겟 수정 내용 확인**

현재 fullstack 타겟:
```makefile
fullstack: check-env
	@echo "🚀 Fullstack 서비스 시작 중..."
	# ... 서비스 시작만 있고 데이터 로드 없음
```

**Step 2: fullstack 타겟에 데이터 로드 추가**

```makefile
# Fullstack Docker Compose 실행 (프론트엔드 + 백엔드 + DB + 샘플데이터)
fullstack: check-env
	@echo "🚀 Fullstack 서비스 시작 중..."
	@echo ""
	@echo "서비스 목록:"
	@echo "  - Weaviate (벡터 DB): http://localhost:8080"
	@echo "  - Backend (API):      http://localhost:8000"
	@echo "  - Frontend (React):   http://localhost:5173"
	@echo ""
	docker compose --profile fullstack up -d
	@echo ""
	@echo "2️⃣  서비스 준비 대기 중..."
	@sleep 10
	@echo ""
	@echo "3️⃣  가이드 챗봇 데이터 로드 중..."
	uv run python quickstart/load_sample_data.py
	@echo ""
	@echo "=============================================="
	@echo "🎉 Fullstack 서비스 시작됨!"
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
```

**Step 3: 변경 사항 적용**

Run: `make fullstack-down && make fullstack` (테스트용, 실제 실행은 나중에)

**Step 4: Commit**

```bash
git add Makefile
git commit -m "기능: fullstack 명령어에 샘플 데이터 자동 로드 추가"
```

---

## Task 2: 샘플 데이터 확장 - 시작하기 카테고리 (4개)

**Files:**
- Modify: `quickstart/sample_data.json`

**Step 1: 기존 데이터 구조 확인**

현재 5개 FAQ 문서가 있음. 이를 유지하면서 새 문서 추가.

**Step 2: 시작하기 카테고리 문서 4개 추가**

```json
{
  "id": "guide-start-001",
  "title": "RAG_Standard 설치 방법",
  "content": "RAG_Standard를 설치하는 방법은 3단계입니다.\n\n**Step 1: 클론 및 의존성 설치**\n```bash\ngit clone https://github.com/youngouk/RAG_Standard.git\ncd RAG_Standard\nuv sync\n```\n\n**Step 2: 환경 설정**\n```bash\ncp quickstart/.env.quickstart .env\n# .env 파일에서 GOOGLE_API_KEY 설정\n```\nGoogle AI Studio에서 무료 API 키 발급: https://aistudio.google.com/apikey\n\n**Step 3: 실행**\n```bash\nmake quickstart\n```\n\n완료 후 http://localhost:8000/docs 에서 API 테스트 가능합니다.\n\n**필수 요구사항:**\n- Docker 20.10+\n- Docker Compose v2+\n- uv 패키지 매니저 (자동 설치됨)",
  "metadata": {
    "category": "시작하기",
    "tags": ["설치", "quickstart", "docker", "uv"]
  }
},
{
  "id": "guide-start-002",
  "title": "Quickstart vs Fullstack 차이점",
  "content": "RAG_Standard는 두 가지 실행 모드를 제공합니다.\n\n**Quickstart (백엔드 전용)**\n```bash\nmake quickstart\n```\n- Weaviate (벡터 DB) + API 서버만 실행\n- API 테스트, 백엔드 개발에 적합\n- http://localhost:8000/docs 에서 Swagger UI 제공\n\n**Fullstack (프론트엔드 포함)**\n```bash\nmake fullstack\n```\n- Weaviate + API 서버 + React 프론트엔드\n- 전체 사용자 경험 테스트에 적합\n- http://localhost:5173 에서 챗봇 UI 제공\n\n**명령어 비교:**\n| 명령어 | 서비스 | 포트 |\n|--------|--------|------|\n| quickstart | Weaviate, API | 8080, 8000 |\n| fullstack | Weaviate, API, Frontend | 8080, 8000, 5173 |",
  "metadata": {
    "category": "시작하기",
    "tags": ["quickstart", "fullstack", "비교"]
  }
},
{
  "id": "guide-start-003",
  "title": "필수 환경변수 설정",
  "content": "RAG_Standard 실행에 필요한 환경변수입니다.\n\n**최소 필수 (Quickstart)**\n```bash\n# LLM API 키 (하나만 필수)\nGOOGLE_API_KEY=AIza...  # 권장 (무료 티어)\n```\n\n**프로덕션 필수**\n```bash\n# 보안\nFASTAPI_AUTH_KEY=your-secret-key-32chars  # 관리자 API 인증\nENVIRONMENT=production\n\n# LLM (최소 1개)\nGOOGLE_API_KEY=AIza...\nOPENAI_API_KEY=sk-...      # 선택\nANTHROPIC_API_KEY=sk-ant-...  # 선택\n```\n\n**벡터 DB (기본값 자동 설정)**\n```bash\nWEAVIATE_URL=http://localhost:8080\nVECTOR_DB_PROVIDER=weaviate\n```\n\n**LLM 선택**\n```bash\nLLM_PROVIDER=google          # google, openai, anthropic, openrouter\nLLM_MODEL=gemini-2.0-flash   # 모델명\n```",
  "metadata": {
    "category": "시작하기",
    "tags": ["환경변수", "설정", "API키"]
  }
},
{
  "id": "guide-start-004",
  "title": "첫 번째 채팅 테스트하기",
  "content": "설치 후 첫 번째 채팅을 테스트하는 방법입니다.\n\n**방법 1: Swagger UI (가장 쉬움)**\n1. http://localhost:8000/docs 접속\n2. POST /chat 엔드포인트 클릭\n3. Try it out 버튼 클릭\n4. Request body에 입력:\n```json\n{\n  \"message\": \"RAG 시스템이 뭐야?\",\n  \"stream\": false\n}\n```\n5. Execute 버튼 클릭\n\n**방법 2: curl 명령어**\n```bash\ncurl -X POST http://localhost:8000/chat \\\n  -H \"Content-Type: application/json\" \\\n  -d '{\"message\": \"RAG 시스템이 뭐야?\"}'\n```\n\n**방법 3: Python 코드**\n```python\nimport httpx\n\nresponse = httpx.post(\n    \"http://localhost:8000/chat\",\n    json={\"message\": \"RAG 시스템이 뭐야?\"}\n)\nprint(response.json()[\"answer\"])\n```\n\n**예상 응답:**\nRAG(Retrieval-Augmented Generation)는 검색 증강 생성 기술입니다...",
  "metadata": {
    "category": "시작하기",
    "tags": ["테스트", "채팅", "API"]
  }
}
```

**Step 3: Commit**

```bash
git add quickstart/sample_data.json
git commit -m "문서: 시작하기 가이드 4개 추가"
```

---

## Task 3: 샘플 데이터 확장 - API 사용법 카테고리 (5개)

**Files:**
- Modify: `quickstart/sample_data.json`

**Step 1: API 사용법 문서 5개 추가**

```json
{
  "id": "guide-api-001",
  "title": "채팅 API 사용법 (POST /chat)",
  "content": "RAG 기반 채팅 API 사용법입니다.\n\n**엔드포인트:** POST /chat\n\n**요청 본문:**\n```json\n{\n  \"message\": \"질문 내용\",\n  \"session_id\": \"optional-session-id\",\n  \"stream\": false,\n  \"use_agent\": false\n}\n```\n\n**파라미터 설명:**\n- `message` (필수): 사용자 질문\n- `session_id` (선택): 대화 이력 유지용 세션 ID\n- `stream` (선택): true면 SSE 스트리밍 응답\n- `use_agent` (선택): true면 Agentic RAG 모드\n\n**응답 예시:**\n```json\n{\n  \"answer\": \"RAG는 검색 증강 생성 기술입니다...\",\n  \"sources\": [{\"title\": \"문서1\", \"score\": 0.95}],\n  \"metadata\": {\"tokens\": 150, \"latency_ms\": 1200}\n}\n```\n\n**Rate Limit:** 100회/15분",
  "metadata": {
    "category": "API 사용법",
    "tags": ["채팅", "API", "POST"]
  }
},
{
  "id": "guide-api-002",
  "title": "스트리밍 응답 받기 (SSE)",
  "content": "실시간 스트리밍 응답을 받는 방법입니다.\n\n**방법 1: stream 파라미터 사용**\n```bash\ncurl -X POST http://localhost:8000/chat \\\n  -H \"Content-Type: application/json\" \\\n  -d '{\"message\": \"질문\", \"stream\": true}'\n```\n\n**방법 2: 전용 스트리밍 엔드포인트**\n```bash\ncurl -X POST http://localhost:8000/chat/stream \\\n  -H \"Content-Type: application/json\" \\\n  -d '{\"message\": \"질문\"}'\n```\n\n**SSE 이벤트 형식:**\n```\nevent: chunk\ndata: {\"token\": \"RAG\"}\n\nevent: chunk\ndata: {\"token\": \"는 \"}\n\nevent: sources\ndata: {\"sources\": [...]}\n\nevent: done\ndata: {\"total_tokens\": 150}\n```\n\n**JavaScript 예시:**\n```javascript\nconst eventSource = new EventSource('/chat/stream?message=질문');\neventSource.onmessage = (e) => {\n  const data = JSON.parse(e.data);\n  console.log(data.token);\n};\n```",
  "metadata": {
    "category": "API 사용법",
    "tags": ["스트리밍", "SSE", "실시간"]
  }
},
{
  "id": "guide-api-003",
  "title": "WebSocket 실시간 채팅",
  "content": "WebSocket을 이용한 양방향 실시간 채팅입니다.\n\n**엔드포인트:** ws://localhost:8000/chat-ws?session_id=xxx\n\n**연결 및 메시지 전송:**\n```javascript\nconst ws = new WebSocket('ws://localhost:8000/chat-ws?session_id=user-123');\n\nws.onopen = () => {\n  ws.send(JSON.stringify({\n    type: 'message',\n    message_id: 'msg_001',\n    content: '질문입니다',\n    session_id: 'user-123'\n  }));\n};\n\nws.onmessage = (event) => {\n  const data = JSON.parse(event.data);\n  switch(data.type) {\n    case 'stream_start':\n      console.log('응답 시작');\n      break;\n    case 'stream_token':\n      console.log(data.token);  // 토큰 단위 출력\n      break;\n    case 'stream_sources':\n      console.log('출처:', data.sources);\n      break;\n    case 'stream_end':\n      console.log('완료');\n      break;\n  }\n};\n```\n\n**메시지 타입:**\n- `stream_start`: 응답 시작\n- `stream_token`: 토큰 (index 포함)\n- `stream_sources`: 참조 문서\n- `stream_end`: 완료 (토큰수, 처리시간)\n- `stream_error`: 에러",
  "metadata": {
    "category": "API 사용법",
    "tags": ["WebSocket", "실시간", "양방향"]
  }
},
{
  "id": "guide-api-004",
  "title": "세션 관리 API",
  "content": "대화 세션을 관리하는 API입니다.\n\n**세션 생성:**\n```bash\ncurl -X POST http://localhost:8000/chat/session\n```\n응답: `{\"session_id\": \"sess_abc123\"}`\n\n**채팅 히스토리 조회:**\n```bash\ncurl http://localhost:8000/chat/history/sess_abc123\n```\n응답: 해당 세션의 모든 대화 내역\n\n**세션 정보 조회:**\n```bash\ncurl http://localhost:8000/chat/session/sess_abc123/info\n```\n응답: 세션 생성 시간, 메시지 수 등\n\n**세션 삭제:**\n```bash\ncurl -X DELETE http://localhost:8000/chat/session/sess_abc123\n```\n\n**Python 예시:**\n```python\nimport httpx\n\nclient = httpx.Client(base_url=\"http://localhost:8000\")\n\n# 세션 생성\nsession = client.post(\"/chat/session\").json()\nsession_id = session[\"session_id\"]\n\n# 세션으로 채팅\nresponse = client.post(\"/chat\", json={\n    \"message\": \"안녕\",\n    \"session_id\": session_id\n})\n```",
  "metadata": {
    "category": "API 사용법",
    "tags": ["세션", "히스토리", "관리"]
  }
},
{
  "id": "guide-api-005",
  "title": "문서 업로드 API",
  "content": "RAG 검색용 문서를 업로드하는 API입니다.\n\n**단일 문서 업로드:**\n```bash\ncurl -X POST http://localhost:8000/upload/documents \\\n  -H \"Content-Type: multipart/form-data\" \\\n  -F \"file=@document.pdf\"\n```\n\n**지원 파일 형식:**\n- PDF (.pdf)\n- Word (.docx)\n- 텍스트 (.txt)\n- 마크다운 (.md)\n- JSON (.json)\n\n**Python 예시:**\n```python\nimport httpx\n\nwith open(\"document.pdf\", \"rb\") as f:\n    response = httpx.post(\n        \"http://localhost:8000/upload/documents\",\n        files={\"file\": f}\n    )\nprint(response.json())  # {\"document_id\": \"doc_xxx\", \"chunks\": 15}\n```\n\n**Rate Limit:** 20회/시간\n\n**주의사항:**\n- 최대 파일 크기: 10MB\n- 업로드된 문서는 자동으로 청킹 및 벡터화됨\n- 처리 시간은 문서 크기에 따라 다름",
  "metadata": {
    "category": "API 사용법",
    "tags": ["업로드", "문서", "파일"]
  }
}
```

**Step 2: Commit**

```bash
git add quickstart/sample_data.json
git commit -m "문서: API 사용법 가이드 5개 추가"
```

---

## Task 4: 샘플 데이터 확장 - 설정 가이드 카테고리 (4개)

**Files:**
- Modify: `quickstart/sample_data.json`

**Step 1: 설정 가이드 문서 4개 추가**

```json
{
  "id": "guide-config-001",
  "title": "LLM Provider 선택 및 변경",
  "content": "RAG_Standard는 4가지 LLM Provider를 지원합니다.\n\n**지원 Provider:**\n| Provider | 환경변수 | 특징 |\n|----------|---------|------|\n| Google Gemini | GOOGLE_API_KEY | 권장, 무료 티어 |\n| OpenAI GPT | OPENAI_API_KEY | GPT-4, GPT-3.5 |\n| Anthropic Claude | ANTHROPIC_API_KEY | Claude 3 |\n| OpenRouter | OPENROUTER_API_KEY | 다양한 모델 |\n\n**Provider 변경:**\n```bash\n# .env 파일에서\nLLM_PROVIDER=google       # google, openai, anthropic, openrouter\nLLM_MODEL=gemini-2.0-flash\n```\n\n**자동 Fallback 설정:**\n```yaml\n# app/config/base.yaml\nllm:\n  fallback_order:\n    - google\n    - openai\n    - anthropic\n```\n주 LLM 실패 시 순서대로 자동 전환됩니다.\n\n**모델별 권장 용도:**\n- gemini-2.0-flash: 빠른 응답, 일반 질문\n- gpt-4: 복잡한 추론\n- claude-3-opus: 긴 문서 분석",
  "metadata": {
    "category": "설정 가이드",
    "tags": ["LLM", "설정", "Provider"]
  }
},
{
  "id": "guide-config-002",
  "title": "벡터 DB 선택 및 설정",
  "content": "RAG_Standard는 6가지 벡터 DB를 지원합니다.\n\n**지원 DB:**\n| DB | 하이브리드 검색 | 특징 |\n|----|---------------|------|\n| Weaviate (기본) | ✅ Dense+BM25 | 셀프호스팅, 권장 |\n| Chroma | ❌ Dense만 | 경량, 개발용 |\n| Pinecone | ✅ Dense+Sparse | 서버리스 |\n| Qdrant | ✅ Dense+Full-Text | 고성능 |\n| pgvector | ❌ Dense만 | PostgreSQL |\n| MongoDB | ❌ Dense만 | Atlas |\n\n**DB 변경:**\n```bash\n# .env\nVECTOR_DB_PROVIDER=weaviate  # weaviate, chroma, pinecone, qdrant, pgvector, mongodb\n```\n\n**Weaviate 설정 (권장):**\n```bash\nWEAVIATE_URL=http://localhost:8080\nWEAVIATE_GRPC_HOST=localhost\nWEAVIATE_GRPC_PORT=50051\n```\n\n**Pinecone 설정:**\n```bash\nVECTOR_DB_PROVIDER=pinecone\nPINECONE_API_KEY=xxx\nPINECONE_ENVIRONMENT=us-east-1\nPINECONE_INDEX_NAME=rag-index\n```",
  "metadata": {
    "category": "설정 가이드",
    "tags": ["벡터DB", "Weaviate", "설정"]
  }
},
{
  "id": "guide-config-003",
  "title": "보안 설정 (프로덕션)",
  "content": "프로덕션 배포를 위한 보안 설정입니다.\n\n**필수 보안 설정:**\n```bash\n# .env\nFASTAPI_AUTH_KEY=your-32-char-secret-key-here\nENVIRONMENT=production\n```\n\n**API Key 인증:**\n모든 관리자 API (/api/admin/*)는 X-API-Key 헤더 필수:\n```bash\ncurl -H \"X-API-Key: your-key\" http://localhost:8000/api/admin/status\n```\n\n**PII 마스킹:**\n자동으로 개인정보(전화번호, 이메일 등) 마스킹:\n- 입력: \"연락처는 010-1234-5678입니다\"\n- 출력: \"연락처는 010-****-5678입니다\"\n\n**CORS 설정:**\n```yaml\n# app/config/production.yaml\nsecurity:\n  cors_origins:\n    - https://yourdomain.com\n```\n\n**Rate Limiting:**\n- /chat: 100회/15분\n- /upload: 20회/시간\n- 관리자 API: 무제한 (인증된 요청만)",
  "metadata": {
    "category": "설정 가이드",
    "tags": ["보안", "인증", "프로덕션"]
  }
},
{
  "id": "guide-config-004",
  "title": "YAML 설정 파일 구조",
  "content": "RAG_Standard는 YAML 기반 설정을 사용합니다.\n\n**설정 파일 위치:**\n```\napp/config/\n├── base.yaml            # 공통 설정\n├── environments/\n│   ├── development.yaml # 개발 환경\n│   ├── test.yaml       # 테스트 환경\n│   └── production.yaml  # 프로덕션\n└── routing_rules_v2.yaml  # 동적 라우팅\n```\n\n**환경 자동 감지:**\n`ENVIRONMENT` 환경변수에 따라 해당 설정 파일 자동 로드:\n- development: debug=true, reload=true\n- test: 짧은 타임아웃\n- production: 워커 4개, 캐시 활성화\n\n**주요 설정 예시 (base.yaml):**\n```yaml\nllm:\n  default_provider: google\n  temperature: 0.7\n  max_tokens: 2048\n\nretrieval:\n  enable_hybrid_search: true\n  enable_reranking: true\n  top_k: 5\n\ngeneration:\n  enable_self_rag: true\n  quality_threshold: 0.7\n```\n\n**설정 우선순위:**\n환경변수 > environments/*.yaml > base.yaml",
  "metadata": {
    "category": "설정 가이드",
    "tags": ["YAML", "설정", "환경"]
  }
}
```

**Step 2: Commit**

```bash
git add quickstart/sample_data.json
git commit -m "문서: 설정 가이드 4개 추가"
```

---

## Task 5: 샘플 데이터 확장 - 아키텍처 카테고리 (4개)

**Files:**
- Modify: `quickstart/sample_data.json`

**Step 1: 아키텍처 문서 4개 추가**

```json
{
  "id": "guide-arch-001",
  "title": "프로젝트 디렉토리 구조",
  "content": "RAG_Standard의 코드 구조입니다.\n\n**주요 디렉토리:**\n```\napp/\n├── api/              # REST API 레이어\n│   ├── routers/      # 엔드포인트 (chat, admin, websocket)\n│   ├── services/     # 비즈니스 로직\n│   └── schemas/      # Pydantic 모델\n│\n├── modules/core/     # RAG 핵심 모듈\n│   ├── retrieval/    # 검색 (Weaviate, GraphRAG, 리랭킹)\n│   ├── generation/   # 답변 생성 (LLM, 프롬프트)\n│   ├── privacy/      # PII 마스킹\n│   └── session/      # 세션 관리\n│\n├── core/             # 중앙 의존성\n│   └── di_container.py  # DI Container\n│\n└── lib/              # 공통 유틸리티\n    ├── llm_client.py # Multi-LLM Factory\n    └── auth.py       # 인증\n```\n\n**모듈별 역할:**\n- `api/`: HTTP 요청/응답 처리\n- `modules/core/`: RAG 파이프라인 로직\n- `core/`: 의존성 주입 관리\n- `lib/`: 공통 유틸리티",
  "metadata": {
    "category": "아키텍처",
    "tags": ["구조", "디렉토리", "모듈"]
  }
},
{
  "id": "guide-arch-002",
  "title": "DI 컨테이너 패턴",
  "content": "RAG_Standard는 Dependency Injection 패턴을 사용합니다.\n\n**DI Container 위치:** `app/core/di_container.py`\n\n**주요 Provider (80+개):**\n- Singleton: 70개 (설정, DB 연결 등)\n- Factory: 10개 (동적 생성)\n\n**8개 주요 Factory:**\n| Factory | 역할 |\n|---------|------|\n| LLMClientFactory | Multi-LLM 관리 |\n| VectorStoreFactory | 벡터 DB 선택 |\n| RetrieverFactory | 검색 전략 |\n| AgentFactory | 에이전트 생성 |\n| EvaluatorFactory | 평가 시스템 |\n| GraphRAGFactory | 그래프 검색 |\n\n**사용 예시:**\n```python\nfrom app.core.di_container import get_container\n\ncontainer = get_container()\n\n# LLM 클라이언트 가져오기\nllm = container.llm_factory()\n\n# 벡터 스토어 가져오기\nvector_store = container.vector_store_factory()\n```\n\n**장점:**\n- 테스트 시 Mock으로 쉽게 교체\n- 런타임에 구현체 변경 가능\n- 순환 의존성 방지",
  "metadata": {
    "category": "아키텍처",
    "tags": ["DI", "의존성주입", "Container"]
  }
},
{
  "id": "guide-arch-003",
  "title": "RAG 파이프라인 흐름",
  "content": "RAG_Standard의 질문-응답 흐름입니다.\n\n**파이프라인 단계:**\n```\n1. 사용자 질문 입력\n       ↓\n2. RetrievalOrchestrator (검색)\n   ├─ Weaviate 벡터 검색\n   ├─ BM25 키워드 검색\n   ├─ GraphRAG 관계 검색\n   └─ RRF 점수 병합\n       ↓\n3. JinaColBERT 리랭킹\n       ↓\n4. GenerationModule (답변 생성)\n   └─ LLMFactory → Gemini/GPT/Claude\n       ↓\n5. SelfRAGOrchestrator (품질 평가)\n   └─ 품질 미달 시 재검색/재생성\n       ↓\n6. PIIProcessor (개인정보 마스킹)\n       ↓\n7. 응답 반환\n```\n\n**핵심 모듈:**\n- `RetrievalOrchestrator`: 여러 검색 방법 병합\n- `GenerationModule`: 프롬프트 관리 + LLM 호출\n- `SelfRAGOrchestrator`: 답변 품질 자동 평가\n- `PIIProcessor`: 개인정보 보호",
  "metadata": {
    "category": "아키텍처",
    "tags": ["파이프라인", "RAG", "흐름"]
  }
},
{
  "id": "guide-arch-004",
  "title": "새 기능 추가 방법",
  "content": "RAG_Standard에 새 기능을 추가하는 방법입니다.\n\n**새 API 엔드포인트 추가:**\n1. `app/api/schemas/`에 요청/응답 모델 정의\n2. `app/api/routers/`에 라우터 생성\n3. `main.py`에 라우터 등록\n\n**새 벡터 DB 추가:**\n1. `app/infrastructure/storage/vector/`에 클래스 생성:\n```python\nclass MyVectorStore(VectorStore):\n    async def search(self, query, limit):\n        # 구현\n        pass\n```\n2. `VectorStoreFactory`에 등록\n3. 환경변수 `VECTOR_DB_PROVIDER=mydb` 설정\n\n**새 LLM Provider 추가:**\n1. `app/lib/llm_client.py`의 Factory에 추가\n2. 환경변수 설정\n3. `llm.fallback_order`에 추가\n\n**테스트 작성:**\n```python\n# tests/unit/test_my_feature.py\ndef test_my_feature():\n    # Given\n    # When\n    # Then\n    assert result == expected\n```\n\n**규칙:**\n- 기존 인터페이스(Protocol) 준수\n- DI Container를 통한 의존성 주입\n- 단위 테스트 필수",
  "metadata": {
    "category": "아키텍처",
    "tags": ["확장", "개발", "추가"]
  }
}
```

**Step 2: Commit**

```bash
git add quickstart/sample_data.json
git commit -m "문서: 아키텍처 가이드 4개 추가"
```

---

## Task 6: 샘플 데이터 확장 - 개발자 가이드 카테고리 (3개)

**Files:**
- Modify: `quickstart/sample_data.json`

**Step 1: 개발자 가이드 문서 3개 추가**

```json
{
  "id": "guide-dev-001",
  "title": "테스트 실행 방법",
  "content": "RAG_Standard의 테스트 실행 방법입니다.\n\n**전체 테스트 (1,370+개):**\n```bash\nmake test\n```\n\n**커버리지 리포트:**\n```bash\nmake test-cov\n# htmlcov/index.html에서 결과 확인\n```\n\n**특정 테스트만 실행:**\n```bash\n# 파일 단위\nuv run pytest tests/unit/api/test_chat.py -v\n\n# 함수 단위\nuv run pytest tests/unit/api/test_chat.py::test_chat_endpoint -v\n\n# 마커 기준\nuv run pytest -m \"not slow\" -v  # slow 제외\n```\n\n**테스트 구조:**\n```\ntests/\n├── unit/           # 단위 테스트\n├── integration/    # 통합 테스트\n├── e2e/           # E2E 테스트\n└── fixtures/       # 테스트 데이터\n```\n\n**테스트 작성 규칙:**\n- Given-When-Then 패턴\n- Mock 사용 시 `unittest.mock` 또는 `pytest-mock`\n- 비동기 테스트: `@pytest.mark.asyncio`",
  "metadata": {
    "category": "개발자 가이드",
    "tags": ["테스트", "pytest", "커버리지"]
  }
},
{
  "id": "guide-dev-002",
  "title": "코드 품질 관리",
  "content": "RAG_Standard의 코드 품질 도구입니다.\n\n**린팅 (Ruff):**\n```bash\nmake lint         # 검사만\nmake lint-fix     # 자동 수정\n```\n\n**타입 체크 (Mypy):**\n```bash\nmake type-check   # 엄격 모드\n```\n\n**코드 포맷팅 (Black):**\n```bash\nmake format\n```\n\n**의존성 계층 검증:**\n```bash\nmake lint-imports  # Import Linter\n```\n\n**CI/CD 체크리스트:**\n모든 PR은 다음을 통과해야 함:\n1. `make lint` - 린팅 오류 없음\n2. `make type-check` - 타입 오류 없음\n3. `make test` - 테스트 100% 통과\n4. `make lint-imports` - 계층 위반 없음\n\n**pre-commit 설정:**\n```bash\npre-commit install\n# 커밋 시 자동으로 lint, format 실행\n```",
  "metadata": {
    "category": "개발자 가이드",
    "tags": ["품질", "린팅", "타입체크"]
  }
},
{
  "id": "guide-dev-003",
  "title": "기여 방법 (Contributing)",
  "content": "RAG_Standard에 기여하는 방법입니다.\n\n**기여 절차:**\n1. Fork → Clone\n2. 브랜치 생성: `git checkout -b feature/my-feature`\n3. 코드 작성 + 테스트\n4. 품질 검사: `make lint && make test`\n5. 커밋: 유다시티 스타일\n6. PR 생성\n\n**커밋 메시지 스타일:**\n```\n기능: 새로운 기능 추가\n수정: 버그 수정\n문서: 문서 업데이트\n스타일: 코드 포맷팅\n리팩터: 코드 리팩토링\n테스트: 테스트 추가/수정\n```\n\n**코드 규칙:**\n- 타입 힌트 필수\n- 한국어 docstring\n- 단위 테스트 필수\n- TODO 주석 금지 (발견 즉시 해결)\n\n**PR 체크리스트:**\n- [ ] 테스트 추가/수정\n- [ ] 문서 업데이트\n- [ ] `make lint` 통과\n- [ ] `make test` 통과\n- [ ] 코드 리뷰 반영\n\n**라이선스:** MIT",
  "metadata": {
    "category": "개발자 가이드",
    "tags": ["기여", "PR", "오픈소스"]
  }
}
```

**Step 2: Commit**

```bash
git add quickstart/sample_data.json
git commit -m "문서: 개발자 가이드 3개 추가"
```

---

## Task 7: sample_data.json 최종 통합 및 검증

**Files:**
- Verify: `quickstart/sample_data.json`

**Step 1: 전체 문서 수 확인**

```bash
cat quickstart/sample_data.json | python -c "import json,sys; d=json.load(sys.stdin); print(f'총 문서 수: {len(d[\"documents\"])}')"
```

Expected: `총 문서 수: 25` (기존 5개 + 새 20개)

**Step 2: JSON 유효성 검사**

```bash
python -m json.tool quickstart/sample_data.json > /dev/null && echo "✅ JSON 유효"
```

**Step 3: 카테고리별 분포 확인**

```bash
cat quickstart/sample_data.json | python -c "
import json, sys
from collections import Counter
d = json.load(sys.stdin)
categories = [doc['metadata']['category'] for doc in d['documents']]
for cat, count in Counter(categories).items():
    print(f'{cat}: {count}개')
"
```

Expected:
```
기술 소개: 5개 (기존)
시작하기: 4개
API 사용법: 5개
설정 가이드: 4개
아키텍처: 4개
개발자 가이드: 3개
```

**Step 4: 최종 Commit**

```bash
git add quickstart/sample_data.json
git commit -m "문서: RAG_Standard 사용 가이드 챗봇 데이터 완성 (25개 문서)"
```

---

## Task 8: 통합 테스트 및 최종 검증

**Files:**
- Test: `make fullstack`

**Step 1: 기존 서비스 정리**

```bash
make fullstack-down
make quickstart-down
```

**Step 2: Fullstack 실행 및 데이터 로드**

```bash
make fullstack
```

Expected output:
```
🚀 Fullstack 서비스 시작 중...
...
3️⃣  가이드 챗봇 데이터 로드 중...
📄 25개 문서 로드 중...
✅ 25개 문서 적재 완료!
...
💬 가이드 챗봇 테스트 질문:
   - RAG_Standard 어떻게 설치해?
   - 채팅 API 사용법 알려줘
```

**Step 3: 챗봇 테스트**

```bash
# 설치 관련 질문
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "RAG_Standard 어떻게 설치해?"}'

# API 관련 질문
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "채팅 API 사용법 알려줘"}'

# 설정 관련 질문
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "LLM Provider 변경 방법은?"}'
```

**Step 4: 프론트엔드 테스트**

1. http://localhost:5173 접속
2. 채팅 UI에서 질문 입력 테스트
3. WebSocket 스트리밍 동작 확인

**Step 5: 최종 Commit**

```bash
git add -A
git commit -m "기능: RAG_Standard 사용 가이드 챗봇 완성

- fullstack에 샘플 데이터 자동 로드 추가
- 25개 가이드 문서 (6개 카테고리)
- 설치, API, 설정, 아키텍처, 개발 가이드 포함"
```

---

## 요약

| Task | 설명 | 파일 |
|------|------|------|
| 1 | Makefile fullstack 수정 | `Makefile` |
| 2 | 시작하기 문서 4개 | `sample_data.json` |
| 3 | API 사용법 문서 5개 | `sample_data.json` |
| 4 | 설정 가이드 문서 4개 | `sample_data.json` |
| 5 | 아키텍처 문서 4개 | `sample_data.json` |
| 6 | 개발자 가이드 문서 3개 | `sample_data.json` |
| 7 | 통합 및 검증 | `sample_data.json` |
| 8 | E2E 테스트 | 전체 시스템 |

**총 문서 수:** 25개 (기존 5개 + 신규 20개)
**카테고리:** 6개 (기술소개, 시작하기, API사용법, 설정가이드, 아키텍처, 개발자가이드)
