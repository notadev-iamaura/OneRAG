#!/bin/bash

# Railway 자동 배포 스크립트
# 기능: FastAPI Backend, Weaviate, PostgreSQL을 Railway에 배포
# 사용: ./scripts/deploy-railway.sh

set -e  # 에러 발생 시 즉시 중단

echo "🚀 Railway 배포 시작..."
echo ""

# =====================================
# 0. Railway CLI 로그인 확인
# =====================================
echo "📋 Step 0: Railway 로그인 확인"
if ! railway whoami &>/dev/null; then
    echo "❌ Railway에 로그인되어 있지 않습니다."
    echo "다음 명령어로 로그인하세요:"
    echo "  railway login"
    exit 1
fi

RAILWAY_USER=$(railway whoami)
echo "✅ Railway 로그인 확인: $RAILWAY_USER"
echo ""

# =====================================
# 1. 프로젝트 생성 또는 연결
# =====================================
echo "📋 Step 1: Railway 프로젝트 설정"
echo "프로젝트를 생성하시겠습니까? (y/n)"
echo "  y: 새 프로젝트 생성"
echo "  n: 기존 프로젝트 연결"
read -p "선택: " CREATE_PROJECT

if [ "$CREATE_PROJECT" = "y" ]; then
    echo "프로젝트 이름을 입력하세요 (기본값: onerag-chatbot):"
    read -p "프로젝트 이름: " PROJECT_NAME
    PROJECT_NAME=${PROJECT_NAME:-onerag-chatbot}

    echo "프로젝트 생성 중: $PROJECT_NAME"
    railway init --name "$PROJECT_NAME"
else
    echo "기존 프로젝트에 연결합니다."
    railway link
fi

echo "✅ 프로젝트 설정 완료"
echo ""

# =====================================
# 2. FastAPI Backend 서비스 배포
# =====================================
echo "📋 Step 2: FastAPI Backend 배포"
echo "GitHub Repository에서 자동 배포하시겠습니까? (y/n)"
read -p "선택: " DEPLOY_FROM_GITHUB

if [ "$DEPLOY_FROM_GITHUB" = "y" ]; then
    echo "✅ GitHub Repository 배포는 Railway Dashboard에서 수동으로 설정하세요."
    echo "   1. Railway Dashboard → 프로젝트 열기"
    echo "   2. New Service → Deploy from GitHub repo"
    echo "   3. Repository 선택: RAG_Standard"
    echo ""
else
    echo "현재 디렉토리에서 Dockerfile을 사용하여 배포합니다."
    railway up
    echo "✅ Backend 배포 완료"
fi
echo ""

# =====================================
# 3. Weaviate 서비스 배포
# =====================================
echo "📋 Step 3: Weaviate 서비스 배포"
echo "Weaviate 서비스를 생성합니다..."

# Weaviate 서비스 생성 (Docker Image)
echo "⚠️  Railway CLI는 Docker Image 직접 배포를 지원하지 않습니다."
echo "   Weaviate 배포는 Railway Dashboard에서 수동으로 진행하세요:"
echo ""
echo "   1. Railway Dashboard → 프로젝트 열기"
echo "   2. New Service → Docker Image"
echo "   3. Image: semitechnologies/weaviate:1.27.8  (⚠️ Docker Hub 이미지!)"
echo "   4. Deploy 클릭"
echo ""
echo "   주의: cr.weaviate.io는 Railway가 지원하지 않습니다!"
echo ""
echo "Weaviate 배포를 완료하셨습니까? (y/n)"
read -p "완료 여부: " WEAVIATE_DEPLOYED

if [ "$WEAVIATE_DEPLOYED" != "y" ]; then
    echo "❌ Weaviate 배포를 먼저 완료해주세요."
    exit 1
fi

echo "✅ Weaviate 배포 확인 완료"
echo ""

# =====================================
# 4. PostgreSQL 추가 (선택)
# =====================================
echo "📋 Step 4: PostgreSQL 추가 (선택)"
echo "PostgreSQL을 추가하시겠습니까? (y/n)"
read -p "선택: " ADD_POSTGRES

if [ "$ADD_POSTGRES" = "y" ]; then
    echo "PostgreSQL Plugin을 추가합니다..."
    railway add --database postgres
    echo "✅ PostgreSQL 추가 완료"
else
    echo "⏭️  PostgreSQL 추가 건너뛰기"
fi
echo ""

# =====================================
# 5. Backend 환경 변수 설정
# =====================================
echo "📋 Step 5: Backend 환경 변수 설정"
echo "환경 변수를 입력해주세요:"
echo ""

# OPENAI_API_KEY
read -p "OPENAI_API_KEY: " OPENAI_API_KEY
if [ -z "$OPENAI_API_KEY" ]; then
    echo "❌ OPENAI_API_KEY는 필수입니다."
    exit 1
fi

# LANGFUSE_PUBLIC_KEY
read -p "LANGFUSE_PUBLIC_KEY: " LANGFUSE_PUBLIC_KEY
if [ -z "$LANGFUSE_PUBLIC_KEY" ]; then
    echo "❌ LANGFUSE_PUBLIC_KEY는 필수입니다."
    exit 1
fi

# LANGFUSE_SECRET_KEY
read -p "LANGFUSE_SECRET_KEY: " LANGFUSE_SECRET_KEY
if [ -z "$LANGFUSE_SECRET_KEY" ]; then
    echo "❌ LANGFUSE_SECRET_KEY는 필수입니다."
    exit 1
fi

# FASTAPI_AUTH_KEY 생성
FASTAPI_AUTH_KEY=$(openssl rand -hex 32)
echo "생성된 FASTAPI_AUTH_KEY: $FASTAPI_AUTH_KEY"

echo ""
echo "환경 변수를 설정합니다..."

# Backend 서비스 선택 (첫 번째 서비스로 가정)
echo "Backend 서비스 이름을 입력하세요 (기본값: onerag-chatbot):"
read -p "서비스 이름: " BACKEND_SERVICE
BACKEND_SERVICE=${BACKEND_SERVICE:-onerag-chatbot}

# 환경 변수 설정 (Railway CLI v4.x)
railway variables --set "OPENAI_API_KEY=$OPENAI_API_KEY"
railway variables --set "LANGFUSE_PUBLIC_KEY=$LANGFUSE_PUBLIC_KEY"
railway variables --set "LANGFUSE_SECRET_KEY=$LANGFUSE_SECRET_KEY"
railway variables --set "FASTAPI_AUTH_KEY=$FASTAPI_AUTH_KEY"
railway variables --set "WEAVIATE_URL=http://weaviate.railway.internal:8080"
railway variables --set "WEAVIATE_GRPC_HOST=weaviate.railway.internal"
railway variables --set "WEAVIATE_GRPC_PORT=50051"
railway variables --set "LANGFUSE_ENABLED=true"
railway variables --set "LANGFUSE_HOST=https://cloud.langfuse.com"
railway variables --set "LOG_LEVEL=INFO"
railway variables --set "DEBUG=false"

echo "✅ Backend 환경 변수 설정 완료"
echo ""

# =====================================
# 6. Weaviate 환경 변수 설정
# =====================================
echo "📋 Step 6: Weaviate 환경 변수 설정"
echo "Weaviate 서비스 이름을 입력하세요 (기본값: weaviate):"
read -p "서비스 이름: " WEAVIATE_SERVICE
WEAVIATE_SERVICE=${WEAVIATE_SERVICE:-weaviate}

echo "Weaviate 환경 변수를 설정합니다..."

# Weaviate 서비스로 전환하여 환경 변수 설정
railway service "$WEAVIATE_SERVICE"

# 환경 변수 설정 (Railway CLI v4.x)
railway variables --set "ENABLE_TOKENIZER_KAGOME_KR=true"
railway variables --set "PERSISTENCE_DATA_PATH=/var/lib/weaviate"
railway variables --set "AUTHENTICATION_ANONYMOUS_ACCESS_ENABLED=true"
railway variables --set "QUERY_DEFAULTS_LIMIT=25"
railway variables --set "LOG_LEVEL=info"

echo "✅ Weaviate 환경 변수 설정 완료"
echo ""

# Backend 서비스로 다시 전환
railway service "$BACKEND_SERVICE"

# =====================================
# 7. Weaviate Volume 추가
# =====================================
echo "📋 Step 7: Weaviate Volume 추가"
echo "Weaviate Volume을 추가합니다..."

# Weaviate 서비스로 전환
railway service "$WEAVIATE_SERVICE"

# Volume 추가 (10GB)
echo "⚠️  Railway CLI로는 Volume 추가가 제한적입니다."
echo "   Railway Dashboard에서 수동으로 Volume을 추가하세요:"
echo ""
echo "   1. Railway Dashboard → Weaviate Service → Volumes"
echo "   2. Add Volume 클릭"
echo "   3. Mount Path: /var/lib/weaviate"
echo "   4. Size: 10GB"
echo "   5. Add 클릭"
echo ""
echo "Volume 추가를 완료하셨습니까? (y/n)"
read -p "완료 여부: " VOLUME_ADDED

if [ "$VOLUME_ADDED" != "y" ]; then
    echo "⚠️  나중에 Volume을 추가하세요."
fi

# Backend 서비스로 다시 전환
railway service "$BACKEND_SERVICE"

echo "✅ Volume 설정 확인 완료"
echo ""

# =====================================
# 8. 배포 완료 및 검증
# =====================================
echo "📋 Step 8: 배포 완료 및 검증"
echo ""
echo "✅ Railway 배포가 완료되었습니다!"
echo ""
echo "=========================================="
echo "배포 정보"
echo "=========================================="
echo "프로젝트: $(railway status 2>/dev/null | grep 'Project' || echo '정보 없음')"
echo "Backend Service: $BACKEND_SERVICE"
echo "Weaviate Service: $WEAVIATE_SERVICE"
echo ""
echo "=========================================="
echo "다음 단계"
echo "=========================================="
echo ""
echo "1. Railway Dashboard에서 배포 상태 확인:"
echo "   https://railway.app"
echo ""
echo "2. Backend Public URL 확인:"
echo "   railway domain"
echo ""
echo "3. Health Check 테스트:"
echo "   curl https://YOUR-APP.railway.app/health"
echo ""
echo "4. FAQ 데이터 업로드:"
echo "   python scripts/upload_all_openai.py"
echo ""
echo "5. RAG 파이프라인 테스트:"
echo "   python scripts/test_rag_quick.py"
echo ""
echo "=========================================="
echo "환경 변수 백업"
echo "=========================================="
echo "FASTAPI_AUTH_KEY: $FASTAPI_AUTH_KEY"
echo ""
echo "⚠️  이 키를 안전한 곳에 저장하세요!"
echo ""
echo "🎉 배포 완료!"
