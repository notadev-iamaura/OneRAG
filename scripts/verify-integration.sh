#!/usr/bin/env bash
# 통합 검증 실행 스크립트
# ============================================================================
# 정적 게이트(lint/mypy/test)를 넘어 실제 외부 서비스(Weaviate, PostgreSQL/pgvector,
# Qdrant)와 optional provider(spaCy 한국어, sentence-transformers)까지 포함해
# integration 테스트를 실행한다.
#
# 사용:
#   ./scripts/verify-integration.sh            # 서비스 기동 → 대기 → 테스트 → 종료
#   KEEP_SERVICES=1 ./scripts/verify-integration.sh   # 종료 시 서비스 유지
#
# 전제:
#   - Docker daemon 실행 중
#   - LLM 키(.env의 GOOGLE_API_KEY 등) — 실 LLM 테스트에 필요(없으면 해당 테스트 skip)
#   - 선택 의존성 설치: uv sync --extra dev --extra local-embedding \
#                               --extra qdrant --extra pgvector
#     (pgvector extra에는 실 DB 연결용 psycopg[binary]가 보강될 예정)
#   - spaCy 한국어 모델: uv pip install <ko_core_news_sm wheel>  (README 참조)
# ============================================================================
set -euo pipefail

COMPOSE_FILE="docker-compose.verify.yml"
export ONERAG_RUN_OPTIONAL_PROVIDER_TESTS=1
# 실모델 게이트: test_local_reranker.py 가 실제 CrossEncoder 모델을 HF에서 받아
# 추론하도록 허용 (CI 기본 게이트에서는 skip — 통합 검증에서만 실행)
export ONERAG_RUN_REAL_MODEL_TESTS=1
export WEAVIATE_URL="${WEAVIATE_URL:-http://localhost:8081}"
export WEAVIATE_GRPC_PORT="${WEAVIATE_GRPC_PORT:-50052}"
export DATABASE_URL="${DATABASE_URL:-postgresql://onerag:onerag-verify@localhost:55432/rag_db}"
# Qdrant 실연결 검증 (verify 스택 호스트 포트 16333 — dev 스택과 충돌 회피)
export QDRANT_URL="${QDRANT_URL:-http://localhost:16333}"
export ENVIRONMENT=test

cleanup() {
  if [ "${KEEP_SERVICES:-0}" != "1" ]; then
    echo "🧹 검증 서비스 종료 (볼륨 포함 — 매 실행 깨끗한 상태 보장)..."
    docker compose -f "$COMPOSE_FILE" down -v
  else
    echo "ℹ️  KEEP_SERVICES=1 — 서비스를 유지합니다 (수동 종료: docker compose -f $COMPOSE_FILE down -v)"
  fi
}
trap cleanup EXIT

echo "🐳 Weaviate + PostgreSQL(pgvector) + Qdrant 기동..."
docker compose -f "$COMPOSE_FILE" up -d --wait

echo "🔬 통합 테스트 실행 (optional provider + 외부 서비스)..."
echo "   WEAVIATE_URL=$WEAVIATE_URL"
echo "   WEAVIATE_GRPC_PORT=$WEAVIATE_GRPC_PORT"
echo "   DATABASE_URL=$DATABASE_URL"
echo "   QDRANT_URL=$QDRANT_URL"

# 1) optional provider 단위 테스트 (spaCy 한국어 NER, 로컬 임베더, 실모델 reranker)
#    test_local_reranker.py 는 ONERAG_RUN_REAL_MODEL_TESTS=1 게이트로만 실행되는
#    실모델(HF CrossEncoder) 추론 검증이다 (sentence-transformers 미설치 시 self-skip)
uv run pytest \
  tests/unit/privacy/test_pii_detector.py \
  tests/unit/retrieval/rerankers/test_local_reranker.py \
  tests/integration/embedding/test_local_embedder_integration.py \
  -p no:warnings -q

# 2) 외부 서비스 연결 integration 테스트
#    tests/integration 하위 전체를 -m integration marker로 수집하므로,
#    신규 tests/integration/vector_stores/ 테스트(pgvector/Qdrant 등)도
#    별도 경로 추가 없이 자동 포함된다.
uv run pytest tests/integration -m integration -p no:warnings -q

echo "✅ 통합 검증 완료"
