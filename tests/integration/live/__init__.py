"""
라이브 프로바이더 스모크 테스트 패키지.

Pinecone·MongoDB Atlas처럼 컨테이너화가 불가하거나 제한적인 클라우드
프로바이더의 외부 API 계약을 "실제 API"에 대해 실측한다. 문서로만 확인한
계약(예: Pinecone $in 혼합 타입 수용, include_metadata=True 시 top_k 상한)의
잔여 리스크를 주기적으로 해소하는 것이 목적이다.

실행 경로:
- 주간 스케줄 워크플로 전용: .github/workflows/live-provider-smoke.yml
- 기본 CI 게이트(--ignore=tests/integration)와 로컬 verify 스택에서는
  절대 실행되지 않는다.

게이트(모듈 수준 skip):
- ONERAG_RUN_LIVE_PROVIDER_TESTS=1 환경 변수
- 프로바이더별 시크릿 환경 변수 (PINECONE_API_KEY/PINECONE_TEST_INDEX,
  MONGODB_ATLAS_URI 등) — 부재 시 명확한 사유와 함께 깨끗하게 skip 된다.
"""
