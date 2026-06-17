# 🚀 Railway 환경변수 설정 가이드

## 📋 개요

Railway 배포에서 백엔드 API 연결을 위한 환경변수 설정 방법입니다.

## 🎯 설정할 환경변수

### VITE_API_BASE_URL
- **목적**: 프론트엔드가 백엔드 API를 호출할 때 사용할 기본 URL
- **형식**: `https://your-backend-service.up.railway.app`

## ⚙️ Railway에서 환경변수 설정하기

### 1단계: Railway 대시보드 접속
1. [Railway.app](https://railway.app)에 로그인
2. Simple-RAGchat 프로젝트 선택

### 2단계: 프론트엔드 서비스 선택
1. **Simple-RAG-Frontend** 서비스 클릭
2. 서비스 대시보드로 이동

### 3단계: Variables 탭으로 이동
1. 상단 메뉴에서 **Variables** 탭 클릭
2. 환경변수 관리 페이지로 이동

### 4단계: 백엔드 URL 확인
1. 새 탭에서 Railway 대시보드 열기
2. **Simple-RAG(Backend)** 서비스 선택
3. **Settings** → **Domains** 메뉴
4. **Public Domain** URL 복사
   - 예: `https://your-backend.up.railway.app`

### 5단계: 환경변수 추가
1. 프론트엔드 Variables 페이지로 돌아가기
2. **New Variable** 버튼 클릭
3. 다음 정보 입력:
   ```
   Name: VITE_API_BASE_URL
   Value: https://your-backend.up.railway.app
   ```
4. **Add** 버튼 클릭

### 6단계: 변경사항 적용
1. 환경변수 설정 후 자동으로 재배포 시작
2. Deployments 탭에서 배포 진행상황 확인
3. 배포 완료까지 2-3분 대기

## ✅ 설정 확인

### 브라우저 개발자 도구에서 확인
1. 배포된 프론트엔드 사이트 접속
2. F12 → Console 탭 열기
3. 다음과 같은 로그 확인:
   ```
   ✅ API URL 소스: Railway 환경변수 (VITE_API_BASE_URL)
   🚀 API Configuration: { baseURL: "https://...", environment: "production" }
   ```

### Network 탭에서 API 호출 확인
1. F12 → Network 탭
2. 페이지 새로고침
3. API 요청이 올바른 백엔드 URL로 전송되는지 확인
4. `localhost:8000` 호출이 없는지 확인

## 🔧 트러블슈팅

### API 연결 실패 시
1. **환경변수 확인**: Railway Variables에서 `VITE_API_BASE_URL` 설정 확인
2. **백엔드 URL 확인**: 백엔드 서비스가 정상 실행 중인지 확인
3. **재배포**: 환경변수 변경 후 재배포가 완료되었는지 확인

### 여전히 localhost 호출 시
1. 브라우저 캐시 클리어
2. 배포 로그에서 빌드 과정 확인
3. Console에서 API Configuration 로그 확인

## 📌 추가 정보

### 환경변수 우선순위
1. **VITE_API_BASE_URL** (Railway 환경변수) ← 권장
2. **public/config.js** (런타임 설정)
3. **http://localhost:8000** (개발 폴백)

### 개발 환경
- 로컬 개발 시에는 Vite 프록시가 자동으로 localhost:8000으로 연결
- `.env` 파일의 `VITE_DEV_API_BASE_URL` 설정으로 변경 가능

---

**완료!** 🎉 이제 Railway 프론트엔드가 올바른 백엔드 API와 연결됩니다.