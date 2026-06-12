"""실연결(Live) 벡터 스토어 통합 테스트 패키지.

배경: 직전 사이클에서 pinecone 회귀가 mock 기반 테스트만으로 CI를 통과했다.
mock 사각지대를 없애기 위해 각 스토어를 실제 엔진(Qdrant/PostgreSQL/Chroma)에
연결해 저장-검색-조회-삭제 계약을 검증한다.

설계 원칙:
- 합성 벡터(고정 시드, 8차원)를 사용해 임베딩 API 없이 hermetic하게 실행
- 전 테스트 `pytest.mark.integration` — verify 스택(-m integration)에서만 수집
- 서비스 미가용/환경변수 미설정/클라이언트 미설치 시 각 모듈이 명확한
  사유와 함께 스스로 skip (기본 개발 환경에서 실패 없이 깨끗해야 함)
- 고유 이름(uuid 접미사) 컬렉션/테이블 사용 후 try/finally로 teardown 보장
"""
