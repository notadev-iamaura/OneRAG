#!/bin/sh
# Docker 진입점 스크립트
# 목적: 환경변수 확장 및 애플리케이션 실행
# 중요: main.py를 직접 호출하여 PORT 환경변수를 올바르게 처리

# 0. logs 디렉토리 생성 (존재하지 않으면)
mkdir -p /app/logs

# 1. LLM API 키 확인 및 안내
if [ -z "$GOOGLE_API_KEY" ] && [ -z "$OPENAI_API_KEY" ] && [ -z "$ANTHROPIC_API_KEY" ]; then
    echo ""
    echo "╔══════════════════════════════════════════════════════════════════╗"
    echo "║  ⚠️  LLM API 키가 설정되지 않았습니다                            ║"
    echo "╠══════════════════════════════════════════════════════════════════╣"
    echo "║                                                                  ║"
    echo "║  RAG 시스템의 답변 생성 기능을 사용하려면 API 키가 필요합니다.   ║"
    echo "║                                                                  ║"
    echo "║  🔑 Gemini API 키 발급 (무료, 30초):                             ║"
    echo "║     https://aistudio.google.com/apikey                           ║"
    echo "║                                                                  ║"
    echo "║  📝 설정 방법:                                                   ║"
    echo "║     1. .env 파일에 추가: GOOGLE_API_KEY=\"your-api-key\"           ║"
    echo "║     2. 컨테이너 재시작: docker compose restart api               ║"
    echo "║                                                                  ║"
    echo "║  ℹ️  검색 기능은 API 키 없이도 사용 가능합니다.                   ║"
    echo "║                                                                  ║"
    echo "╚══════════════════════════════════════════════════════════════════╝"
    echo ""
fi

# 2. 배치 크롤러 백그라운드 실행 (명시적 opt-in)
if [ "${START_BATCH_CRAWLER:-false}" = "true" ]; then
    echo "🚀 Starting batch crawler in background..."
    # stdout과 파일에 동시 출력 (Railway 로그에서도 확인 가능)
    python -m app.batch.main 2>&1 | tee /app/logs/batch-startup.log &
    BATCH_PID=$!
    echo "✅ Batch crawler started (PID: $BATCH_PID)"
    echo "📋 Batch logs: /app/logs/batch-startup.log"
else
    echo "ℹ️  Batch crawler disabled. Set START_BATCH_CRAWLER=true to enable it."
fi

# 3. FastAPI 서버 시작
echo "🌐 Starting FastAPI server..."
exec python main.py
