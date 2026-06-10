#!/usr/bin/env bash
# 통합 검증 실행 스크립트
# ============================================================================
# 정적 게이트(lint/mypy/test)를 넘어 실제 외부 서비스(Weaviate, PostgreSQL)와
# optional provider(spaCy 한국어, sentence-transformers)까지 포함해 integration
# 테스트를 실행한다.
#
# 사용:
#   ./scripts/verify-integration.sh            # 서비스 기동 → 대기 → 테스트 → 종료
#   KEEP_SERVICES=1 ./scripts/verify-integration.sh   # 종료 시 서비스 유지
#
# 전제:
#   - Docker daemon 실행 중
#   - LLM 키(.env의 GOOGLE_API_KEY 등) — 실 LLM 테스트에 필요(없으면 해당 테스트 skip)
#   - 선택 의존성 설치: uv sync --extra dev --extra local-embedding
#                       uv pip install <ko_core_news_sm wheel>  (README 참조)
# ============================================================================
set -euo pipefail

COMPOSE_FILE="docker-compose.verify.yml"
export ONERAG_RUN_OPTIONAL_PROVIDER_TESTS=1
export WEAVIATE_URL="${WEAVIATE_URL:-http://localhost:8080}"
export DATABASE_URL="${DATABASE_URL:-postgresql://onerag:onerag-verify@localhost:5432/rag_db}"
export ENVIRONMENT=test

cleanup() {
  if [ "${KEEP_SERVICES:-0}" != "1" ]; then
    echo "🧹 검증 서비스 종료..."
    docker compose -f "$COMPOSE_FILE" down
  else
    echo "ℹ️  KEEP_SERVICES=1 — 서비스를 유지합니다 (수동 종료: docker compose -f $COMPOSE_FILE down -v)"
  fi
}
trap cleanup EXIT

echo "🐳 Weaviate + PostgreSQL 기동..."
docker compose -f "$COMPOSE_FILE" up -d --wait

echo "🔬 통합 테스트 실행 (optional provider + 외부 서비스)..."
echo "   WEAVIATE_URL=$WEAVIATE_URL"
echo "   DATABASE_URL=$DATABASE_URL"

# 1) optional provider 단위 테스트 (spaCy 한국어 NER, 로컬 임베더)
uv run pytest \
  tests/unit/privacy/test_pii_detector.py \
  tests/integration/embedding/test_local_embedder_integration.py \
  -p no:warnings -q

# 2) 외부 서비스 연결 integration 테스트
uv run pytest tests/integration -m integration -p no:warnings -q

echo "✅ 통합 검증 완료"
