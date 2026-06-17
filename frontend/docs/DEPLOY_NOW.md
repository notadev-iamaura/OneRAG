# 🚨 Railway 재배포 필요

> 상태 검토: 2026-05-13. 이 문서는 과거 Railway 배포 조치 기록입니다. 현재 배포 전 검증은 `npm run build:warning-gate`, `npm run lint`, `npm run test:warning-gate` 및 `docs/STATUS.md`의 CI 상태를 기준으로 합니다.

## 현재 상황
- ✅ 환경 변수 `VITE_API_BASE_URL`이 Railway에서 올바르게 설정됨
- ✅ 코드 개선사항 모두 완료
- ❌ 기존 빌드 파일에 `localhost:8000`이 하드코딩되어 있음

## 해결 방법: Railway 재배포

### Option 1: Git Push로 자동 배포 (권장)
```bash
# 1. 변경사항 커밋
git add .
git commit -m "fix: Railway API URL 연결 문제 해결 - 런타임 설정 추가"

# 2. GitHub에 푸시 (자동 배포 시작됨)
git push origin main
```

### Option 2: Railway CLI로 직접 배포
```bash
# Railway CLI가 설치되어 있다면
railway up
```

### Option 3: Railway 대시보드에서 수동 배포
1. Railway 대시보드 접속
2. 프로젝트 선택 → 프론트엔드 서비스
3. **Deployments** 탭 클릭
4. **Deploy Now** 버튼 클릭

## 배포 후 확인사항

### 1. 브라우저에서 개발자 도구 열기
- F12 키 또는 우클릭 → 검사

### 2. Console 탭에서 확인
배포 성공 시 다음과 같은 로그가 표시됩니다:
```
🚀 API Base URL: https://your-backend.up.railway.app
📍 Current Environment: {
  DEV: false,
  NODE_ENV: "production", 
  VITE_API_BASE_URL: "https://your-backend.up.railway.app",
  currentHost: "your-frontend.up.railway.app"
}
```

### 3. Network 탭에서 API 호출 확인
- API 요청이 `https://your-backend.up.railway.app`으로 가는지 확인
- `localhost:8000`으로 요청이 없는지 확인

## 예상 결과

### Before (현재)
```
❌ POST http://localhost:8000/api/chat/session net::ERR_CONNECTION_REFUSED
❌ GET http://localhost:8000/health net::ERR_CONNECTION_REFUSED
```

### After (재배포 후)
```
✅ POST https://your-backend.up.railway.app/api/chat/session 200 OK
✅ GET https://your-backend.up.railway.app/health 200 OK
```

---

**지금 바로 git push를 실행하면 문제가 해결됩니다!** 🚀
