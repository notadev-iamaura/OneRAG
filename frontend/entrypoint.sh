#!/bin/sh
# Railway 런타임 환경변수를 config.js로 생성하는 스크립트

# 환경변수에서 값 가져오기 (기본값 설정)
API_BASE_URL="${VITE_API_BASE_URL:-}"
WS_BASE_URL="${VITE_WS_BASE_URL:-}"
ACCESS_CODE="${VITE_ACCESS_CODE:-1127}"
NODE_ENV="${NODE_ENV:-production}"
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%S.%3NZ")

# config.js 생성
cat > /usr/share/nginx/html/config.js << EOF
// Railway 런타임 설정 (자동 생성됨)
window.RUNTIME_CONFIG = {
  "API_BASE_URL": "${API_BASE_URL}",
  "WS_BASE_URL": "${WS_BASE_URL}",
  "NODE_ENV": "${NODE_ENV}",
  "TIMESTAMP": "${TIMESTAMP}",
  "RAILWAY_ENVIRONMENT": "${RAILWAY_ENVIRONMENT}",
  "ACCESS_CODE": "${ACCESS_CODE}"
};

console.log('Railway Runtime Config Loaded');
EOF

echo "========================================="
echo "✅ Railway Runtime Config Generated"
echo "========================================="
echo "📋 ACCESS_CODE: configured"
echo "🌐 API_BASE_URL: ${API_BASE_URL}"
echo "========================================="

# nginx 설정 파일 생성 (포트 치환)
envsubst '${PORT}' < /etc/nginx/conf.d/default.conf.template > /etc/nginx/conf.d/default.conf

# nginx 실행
exec nginx -g 'daemon off;'
