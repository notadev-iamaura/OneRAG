"""인프로세스 로컬 스모크 테스트 패키지.

외부 서버/네트워크 없이, 주입된 stub 모듈로 업로드 파이프라인의
상태 전이(upload -> worker -> status -> list -> delete)를 검증한다.
"""
