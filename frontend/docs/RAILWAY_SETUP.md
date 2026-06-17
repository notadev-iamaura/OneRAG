# Railway 백엔드-프론트엔드 연결 가이드

## 프로젝트 ID: 48161f96-0d5a-48ec-ba45-41f15878bc54

## 서비스 구성
- **백엔드**: Simple-RAG (ID: 9453d8a2-4dfe-4013-9149-5f0fcb2f14dd)
- **프론트엔드**: Simple-RAG-Frontend (ID: acf866b5-a650-452c-b55b-ed91523e0a0e)

## 설정 단계

### 1. 백엔드 서비스 URL 확인

1. Railway 대시보드에서 **Simple-RAG** 서비스 선택
2. **Settings** → **Networking** → **Public Domain** 확인
3. 도메인 복사 (예: `your-backend.up.railway.app`)

### 2. 프론트엔드 환경 변수 설정

1. Railway 대시보드에서 **Simple-RAG-Frontend** 서비스 선택
2. **Variables** 탭 클릭
3. **New Variable** 버튼 클릭
4. 다음 변수들 추가:

```bash
# 필수 환경 변수 - Railway 대시보드에서 설정
VITE_API_BASE_URL=https://[백엔드-도메인]
VITE_WS_BASE_URL=wss://[백엔드-도메인]

# 예시 (실제 백엔드 도메인으로 교체 필요)
VITE_API_BASE_URL=https://your-backend.up.railway.app
VITE_WS_BASE_URL=wss://your-backend.up.railway.app
```

**중요**: 
- 환경 변수는 반드시 Railway 대시보드에서 설정해야 합니다.
- 환경 변수 설정 후 서비스가 자동으로 재배포됩니다.
- VITE_ 접두사가 있는 변수만 빌드 시점에 포함됩니다.

### 3. 백엔드 CORS 설정

백엔드 서비스에서 프론트엔드 도메인 허용:

1. **Simple-RAG** 서비스의 **Variables** 탭
2. 다음 환경 변수 추가:

```bash
CORS_ORIGINS=https://your-frontend.up.railway.app
```

### 4. 재배포

환경 변수 설정 후 자동으로 재배포됩니다.
변경사항이 적용되지 않으면:

1. 각 서비스의 **Deployments** 탭
2. **Redeploy** 버튼 클릭

## 연결 확인

### 프론트엔드에서 확인
1. https://your-frontend.up.railway.app 접속
2. 브라우저 개발자 도구 (F12) 열기
3. Console 탭에서 에러 확인
4. Network 탭에서 API 호출 확인

### 예상되는 API 엔드포인트
- Health Check: `GET /health`
- Chat API: `POST /api/chat`
- Document Upload: `POST /api/upload`
- Stats: `GET /api/stats`

## 문제 해결

### 1. CORS 에러
- 백엔드의 CORS_ORIGINS 환경 변수 확인
- 프론트엔드 도메인이 정확히 포함되어 있는지 확인

### 2. Connection Refused
- 백엔드 서비스가 실행 중인지 확인
- VITE_API_BASE_URL이 올바른지 확인
- https:// 프로토콜 사용 확인

### 3. 404 Not Found
- API 엔드포인트 경로 확인
- 백엔드 라우팅 설정 확인

### 4. 빈 화면
- 브라우저 콘솔에서 JavaScript 에러 확인
- 네트워크 탭에서 리소스 로딩 확인

## Railway 내부 네트워킹 (선택사항)

Railway 내부 네트워크를 사용하면 더 빠른 통신이 가능합니다:

1. 백엔드 서비스의 내부 호스트명 확인
   - 형식: `[서비스명].[프로젝트명].railway.internal`
   - 예: `simple-rag.simple-ragchat.railway.internal`

2. 프론트엔드 환경 변수 업데이트:
```bash
# 내부 네트워크 사용 (Railway 내부에서만)
VITE_API_BASE_URL=http://simple-rag.railway.internal:8000
```

**주의**: 내부 네트워크는 Railway 서비스 간에만 작동하며, 브라우저에서는 접근할 수 없습니다.

## 모니터링

### Railway 대시보드
- **Metrics**: CPU, 메모리 사용량 확인
- **Logs**: 실시간 로그 모니터링
- **Deployments**: 배포 상태 및 히스토리

### 추천 모니터링 도구
- Sentry: 에러 트래킹
- LogDNA: 로그 관리
- New Relic: APM 모니터링