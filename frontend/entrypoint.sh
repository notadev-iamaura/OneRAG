#!/bin/sh
# 런타임 환경변수를 config.js / nginx 설정으로 주입하는 엔트리포인트.
#
# 역할(생산자측 배선):
#   1) config.js에 window.RUNTIME_CONFIG를 생성한다.
#      - API_BASE_URL / WS_BASE_URL: 비우면 프론트가 same-origin으로 동작(nginx 프록시 사용).
#      - FEATURES: features.ts(loadFeaturesFromRuntime)가 최우선으로 읽는 Feature Flag.
#      - EMBED_ALLOWED_ORIGINS: useEmbedBridge가 부모 origin 화이트리스트로 사용.
#      - ADMIN_API_KEY: 관리자 쓰기 API(X-API-Key) 자동 주입(비우면 미주입).
#   2) nginx default.conf에 API_PROXY_PASS / FRAME_ANCESTORS / FRAME_OPTIONS_HEADER를 envsubst로 치환한다.
#
# 멀티테넌시(company_id) 등은 OneRAG OSS 범위 밖이므로 주입하지 않는다.

# 환경변수에서 값 가져오기 (VITE_* 우선, 없으면 비-VITE_ 변형, 그래도 없으면 기본값)
API_BASE_URL="${VITE_API_BASE_URL:-${API_BASE_URL:-}}"
WS_BASE_URL="${VITE_WS_BASE_URL:-${WS_BASE_URL:-}}"
# same-origin 모드에서 nginx가 /api, /chat-ws 등을 프록시할 백엔드 주소(말미 슬래시 제거)
API_PROXY_PASS="${API_PROXY_PASS:-${BACKEND_URL:-http://backend:8000}}"
API_PROXY_PASS="${API_PROXY_PASS%/}"
# 관리자 쓰기 API에 사용하는 X-API-Key(비우면 미주입 — 운영자가 수동 입력)
ADMIN_API_KEY="${VITE_ADMIN_API_KEY:-${ADMIN_API_KEY:-}}"
# 관리자 페이지 접근 코드(UX 진입 장벽). 비우면 프론트 기본 코드 사용.
ACCESS_CODE="${VITE_ACCESS_CODE:-${ACCESS_CODE:-1127}}"
# 임베드 허용 부모 origin 화이트리스트(콤마 구분). 비우면 same-origin만 허용.
EMBED_ALLOWED_ORIGINS="${VITE_EMBED_ALLOWED_ORIGINS:-${EMBED_ALLOWED_ORIGINS:-}}"
NODE_ENV="${NODE_ENV:-production}"
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%S.%3NZ")
# iframe 임베드 허용 출처(CSP frame-ancestors). 기본 'self'(same-origin만 임베드 허용).
FRAME_ANCESTORS="${IFRAME_FRAME_ANCESTORS:-'self'}"
# X-Frame-Options는 frame-ancestors와 충돌하므로 기본 미설정.
# 레거시 브라우저용으로 명시하고 싶을 때만 X_FRAME_OPTIONS로 주입한다.
FRAME_OPTIONS_HEADER=""
if [ -n "${X_FRAME_OPTIONS:-}" ]; then
  FRAME_OPTIONS_HEADER="add_header X-Frame-Options \"${X_FRAME_OPTIONS}\" always;"
fi

# 값을 JavaScript 문자열 리터럴에 안전하게 넣기 위한 이스케이프(백슬래시/큰따옴표).
js_string() {
  printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'
}

# VITE_<NAME> → <NAME> 순으로 환경변수 값을 읽어 JS 안전 문자열로 반환한다.
env_value() {
  eval "printf '%s' \"\${$1:-}\""
}

feature_value() {
  value=$(env_value "VITE_$1")
  if [ -z "$value" ]; then
    value=$(env_value "$1")
  fi
  js_string "$value"
}

# 일반 값 이스케이프
API_BASE_URL_JS=$(js_string "$API_BASE_URL")
WS_BASE_URL_JS=$(js_string "$WS_BASE_URL")
ADMIN_API_KEY_JS=$(js_string "$ADMIN_API_KEY")
ACCESS_CODE_JS=$(js_string "$ACCESS_CODE")
EMBED_ALLOWED_ORIGINS_JS=$(js_string "$EMBED_ALLOWED_ORIGINS")
NODE_ENV_JS=$(js_string "$NODE_ENV")
TIMESTAMP_JS=$(js_string "$TIMESTAMP")
RAILWAY_ENVIRONMENT_JS=$(js_string "$RAILWAY_ENVIRONMENT")

# Feature Flag 값(features.ts의 실제 키 목록과 1:1 일치 — chatbot/documentManagement/admin/prompts/analysis/privacy)
FEATURE_CHATBOT_JS=$(feature_value FEATURE_CHATBOT)
FEATURE_CHATBOT_STREAMING_JS=$(feature_value FEATURE_CHATBOT_STREAMING)
FEATURE_CHATBOT_HISTORY_JS=$(feature_value FEATURE_CHATBOT_HISTORY)
FEATURE_CHATBOT_SESSION_JS=$(feature_value FEATURE_CHATBOT_SESSION)
FEATURE_CHATBOT_MARKDOWN_JS=$(feature_value FEATURE_CHATBOT_MARKDOWN)
FEATURE_DOCUMENTS_JS=$(feature_value FEATURE_DOCUMENTS)
FEATURE_DOCUMENTS_UPLOAD_JS=$(feature_value FEATURE_DOCUMENTS_UPLOAD)
FEATURE_DOCUMENTS_BULK_DELETE_JS=$(feature_value FEATURE_DOCUMENTS_BULK_DELETE)
FEATURE_DOCUMENTS_SEARCH_JS=$(feature_value FEATURE_DOCUMENTS_SEARCH)
FEATURE_DOCUMENTS_PAGINATION_JS=$(feature_value FEATURE_DOCUMENTS_PAGINATION)
FEATURE_DOCUMENTS_DND_JS=$(feature_value FEATURE_DOCUMENTS_DND)
FEATURE_DOCUMENTS_PREVIEW_JS=$(feature_value FEATURE_DOCUMENTS_PREVIEW)
FEATURE_ADMIN_JS=$(feature_value FEATURE_ADMIN)
FEATURE_ADMIN_USERS_JS=$(feature_value FEATURE_ADMIN_USERS)
FEATURE_ADMIN_STATS_JS=$(feature_value FEATURE_ADMIN_STATS)
FEATURE_ADMIN_QDRANT_JS=$(feature_value FEATURE_ADMIN_QDRANT)
FEATURE_ADMIN_ACCESS_JS=$(feature_value FEATURE_ADMIN_ACCESS)
FEATURE_PROMPTS_JS=$(feature_value FEATURE_PROMPTS)
FEATURE_PROMPTS_TEMPLATES_JS=$(feature_value FEATURE_PROMPTS_TEMPLATES)
FEATURE_PROMPTS_HISTORY_JS=$(feature_value FEATURE_PROMPTS_HISTORY)
FEATURE_ANALYSIS_JS=$(feature_value FEATURE_ANALYSIS)
FEATURE_ANALYSIS_REALTIME_JS=$(feature_value FEATURE_ANALYSIS_REALTIME)
FEATURE_ANALYSIS_EXPORT_JS=$(feature_value FEATURE_ANALYSIS_EXPORT)
FEATURE_ANALYSIS_VIZ_JS=$(feature_value FEATURE_ANALYSIS_VIZ)
FEATURE_PRIVACY_JS=$(feature_value FEATURE_PRIVACY)
FEATURE_PRIVACY_MASK_PHONE_JS=$(feature_value FEATURE_PRIVACY_MASK_PHONE)

# config.js 생성
# - parseBool/parseEmbedAllowedOrigins는 브라우저에서 실행되며, 기본값은 features.ts의 DEFAULT_FEATURES와 일치시킨다.
# - ADMIN_API_KEY는 값이 있을 때만 RUNTIME_CONFIG에 포함한다(빈 키 노출 방지).
cat > /usr/share/nginx/html/config.js << EOF
// 런타임 설정 (자동 생성됨 — 직접 수정하지 말 것)
window.RUNTIME_CONFIG = (() => {
  // 콤마 구분 문자열을 origin 배열로 변환(빈 값 제거, 와일드카드 미지원)
  const parseEmbedAllowedOrigins = () => {
    const raw = "${EMBED_ALLOWED_ORIGINS_JS}";
    if (!raw) return [];
    return raw.split(',').map((origin) => origin.trim()).filter(Boolean);
  };

  // 문자열을 boolean으로 안전 변환. 비어 있으면 features.ts 기본값을 따른다.
  const parseBool = (value, defaultValue) => {
    const normalized = String(value || '').trim().toLowerCase();
    if (!normalized) return defaultValue;
    return normalized === 'true' || normalized === '1' || normalized === 'yes';
  };

  const config = {
    "API_BASE_URL": "${API_BASE_URL_JS}",
    "WS_BASE_URL": "${WS_BASE_URL_JS}",
    "ACCESS_CODE": "${ACCESS_CODE_JS}",
    "EMBED_ALLOWED_ORIGINS": parseEmbedAllowedOrigins(),
    "NODE_ENV": "${NODE_ENV_JS}",
    "TIMESTAMP": "${TIMESTAMP_JS}",
    "RAILWAY_ENVIRONMENT": "${RAILWAY_ENVIRONMENT_JS}",
    // features.ts의 FeatureConfig 키와 동일 구조. DEFAULT_FEATURES 기본값과 일치시킨다.
    "FEATURES": {
      "chatbot": {
        "enabled": parseBool("${FEATURE_CHATBOT_JS}", true),
        "streaming": parseBool("${FEATURE_CHATBOT_STREAMING_JS}", true),
        "history": parseBool("${FEATURE_CHATBOT_HISTORY_JS}", true),
        "sessionManagement": parseBool("${FEATURE_CHATBOT_SESSION_JS}", true),
        "markdown": parseBool("${FEATURE_CHATBOT_MARKDOWN_JS}", true)
      },
      "documentManagement": {
        "enabled": parseBool("${FEATURE_DOCUMENTS_JS}", false),
        "upload": parseBool("${FEATURE_DOCUMENTS_UPLOAD_JS}", false),
        "bulkDelete": parseBool("${FEATURE_DOCUMENTS_BULK_DELETE_JS}", false),
        "search": parseBool("${FEATURE_DOCUMENTS_SEARCH_JS}", false),
        "pagination": parseBool("${FEATURE_DOCUMENTS_PAGINATION_JS}", false),
        "dragAndDrop": parseBool("${FEATURE_DOCUMENTS_DND_JS}", false),
        "preview": parseBool("${FEATURE_DOCUMENTS_PREVIEW_JS}", false)
      },
      "admin": {
        "enabled": parseBool("${FEATURE_ADMIN_JS}", false),
        "userManagement": parseBool("${FEATURE_ADMIN_USERS_JS}", false),
        "systemStats": parseBool("${FEATURE_ADMIN_STATS_JS}", false),
        "qdrantManagement": parseBool("${FEATURE_ADMIN_QDRANT_JS}", false),
        "accessControl": parseBool("${FEATURE_ADMIN_ACCESS_JS}", false)
      },
      "prompts": {
        "enabled": parseBool("${FEATURE_PROMPTS_JS}", false),
        "templates": parseBool("${FEATURE_PROMPTS_TEMPLATES_JS}", false),
        "history": parseBool("${FEATURE_PROMPTS_HISTORY_JS}", false)
      },
      "analysis": {
        "enabled": parseBool("${FEATURE_ANALYSIS_JS}", false),
        "realtime": parseBool("${FEATURE_ANALYSIS_REALTIME_JS}", false),
        "export": parseBool("${FEATURE_ANALYSIS_EXPORT_JS}", false),
        "visualization": parseBool("${FEATURE_ANALYSIS_VIZ_JS}", false)
      },
      "privacy": {
        "enabled": parseBool("${FEATURE_PRIVACY_JS}", true),
        "maskPhoneNumbers": parseBool("${FEATURE_PRIVACY_MASK_PHONE_JS}", true)
      }
    }
  };

  // 관리자 키는 주입된 경우에만 포함한다(빈 값 노출 방지).
  const adminApiKey = "${ADMIN_API_KEY_JS}";
  if (adminApiKey) {
    config.ADMIN_API_KEY = adminApiKey;
  }

  return config;
})();

console.log('Runtime Config Loaded');
EOF

echo "========================================="
echo "Runtime Config Generated"
echo "========================================="
echo "API_BASE_URL: ${API_BASE_URL:-'(empty -> same-origin proxy)'}"
echo "API_PROXY_PASS: ${API_PROXY_PASS}"
echo "FRAME_ANCESTORS: ${FRAME_ANCESTORS}"
# 접근 코드/관리자 키 값은 로그에 노출하지 않고 설정 여부만 표시한다.
if [ -n "${ACCESS_CODE}" ]; then echo "ACCESS_CODE: (set)"; else echo "ACCESS_CODE: (unset -> default)"; fi
if [ -n "${ADMIN_API_KEY}" ]; then echo "ADMIN_API_KEY: (set)"; else echo "ADMIN_API_KEY: (unset)"; fi
echo "EMBED_ALLOWED_ORIGINS: ${EMBED_ALLOWED_ORIGINS:-'(empty -> same-origin only)'}"
echo "========================================="

# nginx 설정 파일 생성 (PORT + 프록시/프레임 변수 치환)
# envsubst가 nginx 자체 변수($uri, $http_upgrade 등)를 건드리지 않도록 치환 대상 변수만 명시한다.
export PORT FRAME_ANCESTORS FRAME_OPTIONS_HEADER API_PROXY_PASS
envsubst '${PORT} ${FRAME_ANCESTORS} ${FRAME_OPTIONS_HEADER} ${API_PROXY_PASS}' \
  < /etc/nginx/conf.d/default.conf.template > /etc/nginx/conf.d/default.conf

# nginx 실행
exec nginx -g 'daemon off;'
