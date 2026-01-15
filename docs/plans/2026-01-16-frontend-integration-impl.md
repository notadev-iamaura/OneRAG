# Frontend Integration Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** RAG_Standard 백엔드에 moduleRagChat_Front 프론트엔드를 모노레포 방식으로 통합하여 풀스택 시스템 구축

**Architecture:** 프론트엔드를 `/frontend` 디렉토리에 복사하고, 통합 docker-compose로 Weaviate + Backend + Frontend를 원클릭 실행. WebSocket 스키마 불일치 해결 후 환경변수 통합.

**Tech Stack:**
- Backend: FastAPI + Python 3.11 + Weaviate
- Frontend: React 19 + TypeScript 5.8 + Vite
- Container: Docker Compose

---

## Pre-flight Checklist

```bash
# 실행 전 확인 사항
[ ] 현재 디렉토리: /Users/youngouksong/Desktop/youngouk/RAG_Standard
[ ] Git 상태 확인: git status (uncommitted changes 없어야 함)
[ ] 백엔드 테스트 통과: make test
[ ] Docker Desktop 실행 중
```

---

## Task 1: 프론트엔드 폴더 복사

**Files:**
- Create: `frontend/` (전체 디렉토리)
- Modify: `.gitignore` (frontend/node_modules 추가)

**Step 1.1: Git 상태 확인**

```bash
git status
```

Expected: `nothing to commit, working tree clean` 또는 최소한의 변경사항

**Step 1.2: 프론트엔드 복사 (node_modules 제외)**

```bash
rsync -av --progress \
  --exclude 'node_modules' \
  --exclude '.git' \
  --exclude 'dist' \
  --exclude '.env' \
  /Users/youngouksong/Desktop/youngouk/moduleRagChat_Front/ \
  ./frontend/
```

Expected: `frontend/` 디렉토리 생성 (~20MB)

**Step 1.3: 복사 확인**

```bash
ls -la frontend/
du -sh frontend/
```

Expected:
- `package.json`, `src/`, `public/` 등 존재
- 크기 약 10-30MB (node_modules 제외)

**Step 1.4: .gitignore 수정**

`.gitignore` 파일 끝에 추가:

```gitignore
# Frontend
frontend/node_modules/
frontend/dist/
frontend/.env
frontend/.env.local
```

**Step 1.5: 프론트엔드 초기화 테스트**

```bash
cd frontend && npm install && npm run build && cd ..
```

Expected: 빌드 성공, `frontend/dist/` 생성

**Step 1.6: 커밋**

```bash
git add frontend/ .gitignore
git commit -m "feat: 프론트엔드 모노레포 통합 (moduleRagChat_Front)

- React 19 + TypeScript + Vite 프론트엔드 추가
- Feature Flag 시스템 포함
- WebSocket 클라이언트 포함

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Task 2: 통합 docker-compose.yml 작성

**Files:**
- Modify: `docker-compose.yml`
- Create: `frontend/Dockerfile.dev` (개발용)

**Step 2.1: 기존 docker-compose.yml 백업 확인**

```bash
cat docker-compose.yml
```

**Step 2.2: 통합 docker-compose.yml 작성**

`docker-compose.yml` 전체 교체:

```yaml
version: '3.8'

services:
  # ============================================
  # Weaviate Vector Database
  # ============================================
  weaviate:
    image: cr.weaviate.io/semitechnologies/weaviate:1.24.1
    restart: unless-stopped
    ports:
      - "8088:8080"
      - "50051:50051"
    environment:
      QUERY_DEFAULTS_LIMIT: 25
      AUTHENTICATION_ANONYMOUS_ACCESS_ENABLED: 'true'
      PERSISTENCE_DATA_PATH: '/var/lib/weaviate'
      DEFAULT_VECTORIZER_MODULE: 'none'
      ENABLE_MODULES: ''
      CLUSTER_HOSTNAME: 'node1'
    volumes:
      - weaviate_data:/var/lib/weaviate
    healthcheck:
      test: ["CMD", "wget", "--spider", "-q", "http://localhost:8080/v1/.well-known/ready"]
      interval: 10s
      timeout: 5s
      retries: 5

  # ============================================
  # Backend API (FastAPI)
  # ============================================
  backend:
    build:
      context: .
      dockerfile: Dockerfile
    restart: unless-stopped
    ports:
      - "8000:8000"
    environment:
      - ENVIRONMENT=development
      - WEAVIATE_URL=http://weaviate:8080
      - WEAVIATE_GRPC_URL=weaviate:50051
    env_file:
      - .env
    depends_on:
      weaviate:
        condition: service_healthy
    volumes:
      - ./app:/app/app:ro
      - ./logs:/app/logs
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 3

  # ============================================
  # Frontend (React + Vite)
  # ============================================
  frontend:
    build:
      context: ./frontend
      dockerfile: Dockerfile
    restart: unless-stopped
    ports:
      - "5173:80"
    environment:
      - VITE_API_BASE_URL=http://localhost:8000
      - VITE_WS_BASE_URL=ws://localhost:8000
    depends_on:
      backend:
        condition: service_healthy

  # ============================================
  # Frontend Dev Server (개발용)
  # ============================================
  frontend-dev:
    image: node:20-alpine
    working_dir: /app
    command: sh -c "npm install && npm run dev -- --host 0.0.0.0"
    ports:
      - "5000:5000"
    environment:
      - VITE_API_BASE_URL=http://backend:8000
      - VITE_DEV_API_BASE_URL=http://backend:8000
      - VITE_WS_BASE_URL=ws://backend:8000
      - VITE_DEV_WS_BASE_URL=ws://backend:8000
    volumes:
      - ./frontend:/app
      - frontend_node_modules:/app/node_modules
    depends_on:
      - backend
    profiles:
      - dev

volumes:
  weaviate_data:
  frontend_node_modules:
```

**Step 2.3: 프론트엔드 프로덕션 Dockerfile 확인/수정**

`frontend/Dockerfile` 확인:

```bash
cat frontend/Dockerfile
```

필요시 수정 (nginx 기반):

```dockerfile
# Build stage
FROM node:20-alpine AS builder

WORKDIR /app

# 의존성 설치
COPY package*.json ./
RUN npm ci --legacy-peer-deps

# 소스 복사 및 빌드
COPY . .
RUN npm run build

# Production stage
FROM nginx:alpine

# nginx 설정 복사
COPY nginx.conf /etc/nginx/nginx.conf

# 빌드 결과물 복사
COPY --from=builder /app/dist /usr/share/nginx/html

# 런타임 설정 스크립트
COPY entrypoint.sh /entrypoint.sh
COPY generate-config.js /generate-config.js
RUN chmod +x /entrypoint.sh

EXPOSE 80

ENTRYPOINT ["/entrypoint.sh"]
CMD ["nginx", "-g", "daemon off;"]
```

**Step 2.4: docker-compose 문법 검증**

```bash
docker compose config
```

Expected: YAML 파싱 성공, 에러 없음

**Step 2.5: 커밋**

```bash
git add docker-compose.yml
git commit -m "feat: 통합 docker-compose 작성 (Weaviate + Backend + Frontend)

- Weaviate 벡터 DB 서비스
- FastAPI 백엔드 서비스 (healthcheck 포함)
- React 프론트엔드 프로덕션 서비스
- 개발용 frontend-dev 서비스 (--profile dev)

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Task 3: WebSocket 타입 수정 (TDD)

**Files:**
- Modify: `frontend/src/types/chatStreaming.ts`
- Modify: `frontend/src/services/chatWebSocketService.ts`

**Step 3.1: 현재 타입 파일 백업 확인**

```bash
cat frontend/src/types/chatStreaming.ts
```

**Step 3.2: chatStreaming.ts 수정 (백엔드 스키마에 맞춤)**

`frontend/src/types/chatStreaming.ts` 전체 교체:

```typescript
/**
 * 채팅 스트리밍 WebSocket 메시지 프로토콜 타입 정의
 *
 * RAG_Standard 백엔드의 app/api/schemas/websocket.py와 동기화
 * 수정일: 2026-01-16
 */

import { Source } from './index';

// ============================================
// 클라이언트 → 서버 메시지 타입
// ============================================

/**
 * 클라이언트에서 서버로 전송하는 메시지
 * 백엔드: app/api/schemas/websocket.py - ClientMessage
 */
export interface ChatWebSocketRequest {
  type: 'message';
  message_id: string;
  content: string;
  session_id: string;
}

// ============================================
// 서버 → 클라이언트 메시지 타입
// 백엔드 스키마와 100% 일치하도록 수정
// ============================================

/**
 * 스트리밍 시작 메시지
 * 백엔드: StreamStartEvent
 */
export interface StreamStartMessage {
  type: 'stream_start';
  message_id: string;
  session_id: string;   // 백엔드에서 전송
  timestamp: string;    // ISO 8601 형식
}

/**
 * 스트리밍 토큰 메시지
 * 백엔드: StreamTokenEvent
 */
export interface StreamTokenMessage {
  type: 'stream_token';
  message_id: string;
  token: string;
  index: number;        // 0부터 시작하는 토큰 인덱스
}

/**
 * 스트리밍 소스 메시지
 * 백엔드: StreamSourcesEvent
 */
export interface StreamSourcesMessage {
  type: 'stream_sources';
  message_id: string;
  sources: Source[];
}

/**
 * 스트리밍 완료 메시지
 * 백엔드: StreamEndEvent
 *
 * ⚠️ 주의: 백엔드는 플랫 구조 (metadata 중첩 없음)
 */
export interface StreamEndMessage {
  type: 'stream_end';
  message_id: string;
  total_tokens: number;       // 백엔드 필드명 그대로
  processing_time_ms: number; // 백엔드 필드명 그대로
}

/**
 * 스트리밍 에러 메시지
 * 백엔드: WSStreamErrorEvent
 *
 * ⚠️ 주의: 백엔드 필드명과 일치시킴
 */
export interface StreamErrorMessage {
  type: 'stream_error';
  message_id: string;
  error_code: string;     // 백엔드: error_code (예: GEN-001)
  message: string;        // 백엔드: message (사용자 친화적)
  solutions: string[];    // 백엔드: solutions (해결 방법 목록)
}

/**
 * 서버에서 클라이언트로 전송되는 모든 메시지 타입 (Union Type)
 */
export type ChatWebSocketResponse =
  | StreamStartMessage
  | StreamTokenMessage
  | StreamSourcesMessage
  | StreamEndMessage
  | StreamErrorMessage;

// ============================================
// 상태 타입
// ============================================

/**
 * 스트리밍 연결/처리 상태
 */
export type StreamingState = 'idle' | 'connecting' | 'streaming' | 'error';

/**
 * 스트리밍 중인 메시지의 상태
 */
export interface StreamingMessage {
  id: string;
  content: string;
  sources?: Source[];
  state: StreamingState;
  error?: string;
  /** 토큰 인덱스 (순서 검증용) */
  lastTokenIndex?: number;
}

// ============================================
// 이벤트 타입 (서비스 내부용)
// ============================================

export interface ConnectionEventData {
  connected: boolean;
}

export interface ReconnectFailedEventData {
  attempts: number;
  maxAttempts: number;
}

export type EventCallback = (data: unknown) => void;

// ============================================
// 레거시 호환성 (Deprecated)
// ============================================

/**
 * @deprecated StreamEndMessage로 대체됨
 * 기존 metadata 구조는 더 이상 사용하지 않음
 */
export interface StreamMetadata {
  processing_time: number;
  tokens_used: number;
  model_info?: {
    provider: string;
    model: string;
    generation_time: number;
  };
}
```

**Step 3.3: chatWebSocketService.ts 핸들러 수정**

`frontend/src/services/chatWebSocketService.ts` 의 `handleMessage` 메서드 수정:

`handleMessage` 메서드를 찾아서 다음으로 교체:

```typescript
  /**
   * 수신 메시지 처리
   * 백엔드 스키마에 맞게 수정됨 (2026-01-16)
   */
  private handleMessage(event: MessageEvent): void {
    try {
      const data: ChatWebSocketResponse = JSON.parse(event.data);
      logger.log('📨 Chat WebSocket 메시지:', data.type, data.message_id);

      // 스트리밍 종료 상태 업데이트
      if (data.type === 'stream_end' || data.type === 'stream_error') {
        this.state = 'idle';
      }

      // stream_end 처리 (백엔드 플랫 구조)
      if (data.type === 'stream_end') {
        const endData = data as StreamEndMessage;
        logger.log('스트리밍 완료:', {
          totalTokens: endData.total_tokens,
          processingTimeMs: endData.processing_time_ms,
        });
      }

      // stream_error 처리 (백엔드 구조)
      if (data.type === 'stream_error') {
        const errorData = data as StreamErrorMessage;
        logger.error(`스트리밍 에러 [${errorData.error_code}]:`, errorData.message);
        logger.log('해결 방법:', errorData.solutions);
      }

      // 타입별 이벤트 발생
      this.emit(data.type, data);

      // 범용 message 이벤트도 발생
      this.emit('message', data);
    } catch (error) {
      logger.error('❌ Chat WebSocket 메시지 파싱 오류:', error, event.data);
      this.emit('parse_error', { error, rawData: event.data });
    }
  }
```

**Step 3.4: TypeScript 타입 체크**

```bash
cd frontend && npx tsc --noEmit && cd ..
```

Expected: 타입 에러 없음

**Step 3.5: 프론트엔드 빌드 테스트**

```bash
cd frontend && npm run build && cd ..
```

Expected: 빌드 성공

**Step 3.6: 커밋**

```bash
git add frontend/src/types/chatStreaming.ts frontend/src/services/chatWebSocketService.ts
git commit -m "fix: WebSocket 타입을 백엔드 스키마와 동기화

- StreamEndMessage: metadata 중첩 → 플랫 구조
- StreamErrorMessage: error/code → error_code/message/solutions
- StreamStartMessage: session_id, timestamp 필드 추가
- StreamTokenMessage: index 필드 추가
- 레거시 StreamMetadata deprecated 처리

백엔드 참조: app/api/schemas/websocket.py

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Task 4: 환경변수 통합

**Files:**
- Create: `.env.fullstack.example`
- Modify: `frontend/.env.example`

**Step 4.1: 통합 환경변수 템플릿 생성**

`.env.fullstack.example` 생성:

```env
# ============================================
# RAG_Standard Fullstack Environment
# 통합 환경변수 템플릿 (백엔드 + 프론트엔드)
# ============================================

# ============================================
# 1. LLM Provider (택 1)
# ============================================

# Google Gemini (권장 - 무료 티어 제공)
GOOGLE_API_KEY=your_google_api_key_here

# OpenAI (선택)
# OPENAI_API_KEY=your_openai_api_key_here

# Anthropic Claude (선택)
# ANTHROPIC_API_KEY=your_anthropic_api_key_here

# ============================================
# 2. 벡터 DB (Weaviate)
# ============================================
WEAVIATE_URL=http://localhost:8088
WEAVIATE_GRPC_URL=localhost:50051

# ============================================
# 3. 백엔드 설정
# ============================================
ENVIRONMENT=development
FASTAPI_AUTH_KEY=your_secure_api_key_here

# ============================================
# 4. 프론트엔드 설정 (Vite)
# ============================================
VITE_API_BASE_URL=http://localhost:8000
VITE_WS_BASE_URL=ws://localhost:8000
VITE_API_KEY=your_secure_api_key_here

# ============================================
# 5. Feature Flags (프론트엔드)
# ============================================
VITE_FEATURE_CHATBOT=true
VITE_FEATURE_CHATBOT_STREAMING=true
VITE_FEATURE_DOCUMENTS=true
VITE_FEATURE_DOCUMENTS_UPLOAD=true
VITE_FEATURE_ADMIN=true
VITE_FEATURE_PROMPTS=true

# ============================================
# 6. 선택적 서비스
# ============================================
# MongoDB (세션 저장용)
# MONGODB_URI=mongodb://localhost:27017/rag_standard

# Langfuse (관측성)
# LANGFUSE_PUBLIC_KEY=your_key
# LANGFUSE_SECRET_KEY=your_secret
# LANGFUSE_HOST=https://cloud.langfuse.com
```

**Step 4.2: 프론트엔드 .env.example 동기화**

`frontend/.env.example` 내용 확인 후 백엔드 설정과 일치시킴:

```bash
cat frontend/.env.example
```

**Step 4.3: .gitignore에 새 환경변수 파일 추가**

`.gitignore`에 추가:

```gitignore
# Fullstack env
.env.fullstack
```

**Step 4.4: 커밋**

```bash
git add .env.fullstack.example .gitignore
git commit -m "docs: 통합 환경변수 템플릿 추가 (.env.fullstack.example)

- 백엔드 + 프론트엔드 통합 설정
- LLM Provider 설정 (Gemini, OpenAI, Claude)
- Weaviate 연결 설정
- Feature Flag 설정

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Task 5: 통합 Makefile 명령어 추가

**Files:**
- Modify: `Makefile`

**Step 5.1: Makefile에 프론트엔드 명령어 추가**

`Makefile` 끝에 추가:

```makefile
# ============================================
# Frontend Commands
# ============================================

.PHONY: frontend-install frontend-dev frontend-build frontend-lint

frontend-install:
	cd frontend && npm install

frontend-dev:
	cd frontend && npm run dev

frontend-build:
	cd frontend && npm run build

frontend-lint:
	cd frontend && npm run lint

# ============================================
# Fullstack Commands (Docker Compose)
# ============================================

.PHONY: fullstack fullstack-dev fullstack-down fullstack-logs fullstack-build

## fullstack: 프로덕션 모드 실행 (Weaviate + Backend + Frontend)
fullstack:
	docker compose up -d weaviate backend frontend

## fullstack-dev: 개발 모드 실행 (프론트엔드 핫리로드)
fullstack-dev:
	docker compose --profile dev up -d

## fullstack-down: 모든 서비스 종료
fullstack-down:
	docker compose --profile dev down

## fullstack-logs: 로그 확인
fullstack-logs:
	docker compose logs -f

## fullstack-build: 모든 이미지 빌드
fullstack-build:
	docker compose build --no-cache
```

**Step 5.2: Makefile 문법 검증**

```bash
make -n fullstack
```

Expected: 명령어 출력 (실제 실행 안 함)

**Step 5.3: 커밋**

```bash
git add Makefile
git commit -m "feat: Makefile에 프론트엔드 및 풀스택 명령어 추가

- frontend-install/dev/build/lint 명령어
- fullstack: 프로덕션 모드 (Weaviate + Backend + Frontend)
- fullstack-dev: 개발 모드 (핫리로드)
- fullstack-down/logs/build 유틸리티

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Task 6: 전체 빌드 및 테스트 검증

**Step 6.1: 백엔드 테스트 실행**

```bash
make test
```

Expected: 1,300+ 테스트 통과

**Step 6.2: 프론트엔드 빌드 테스트**

```bash
make frontend-build
```

Expected: 빌드 성공, `frontend/dist/` 생성

**Step 6.3: Docker Compose 빌드 테스트**

```bash
docker compose build
```

Expected: 모든 이미지 빌드 성공

**Step 6.4: 통합 실행 테스트 (선택적)**

```bash
make fullstack
sleep 30  # 서비스 시작 대기
curl http://localhost:8000/health
curl http://localhost:5173
make fullstack-down
```

Expected:
- 백엔드 헬스체크 성공
- 프론트엔드 페이지 로드

**Step 6.5: 최종 커밋 (태그)**

```bash
git add -A
git commit -m "chore: 프론트엔드 통합 완료 (v1.1.0)

모노레포 구조:
- /app: FastAPI 백엔드
- /frontend: React 프론트엔드

통합 기능:
- docker-compose로 원클릭 실행
- WebSocket 스키마 동기화 완료
- 환경변수 템플릿 통합
- Makefile 명령어 추가

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"

git tag -a v1.1.0 -m "프론트엔드 통합 릴리스"
```

---

## Post-Implementation Checklist

```bash
[ ] 백엔드 테스트 전체 통과: make test
[ ] 프론트엔드 빌드 성공: make frontend-build
[ ] Docker Compose 빌드 성공: docker compose build
[ ] 통합 실행 테스트 성공: make fullstack
[ ] Git 커밋 완료 (6개 커밋)
[ ] 태그 생성: v1.1.0
```

---

## Rollback Plan

통합 실패 시 롤백:

```bash
# 1. Docker 서비스 종료
make fullstack-down

# 2. 프론트엔드 폴더 삭제
rm -rf frontend/

# 3. 변경사항 되돌리기
git checkout HEAD~6 -- docker-compose.yml Makefile .gitignore

# 4. 태그 삭제 (필요시)
git tag -d v1.1.0
```

---

**Plan Complete**
