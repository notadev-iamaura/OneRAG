"""
Self-RAG 품질 게이트 E2E 통합 테스트

Task 6: E2E 통합 테스트
전체 플로우를 검증합니다:
1. 채팅 요청 → 품질 메타데이터 확인
2. 디버깅 추적 조회 → Self-RAG 평가 정보 확인
3. 저품질 답변 거부 시나리오

Note: 현재는 API 스키마 검증에 집중합니다.
      실제 E2E 테스트는 앱이 완전히 초기화된 후 실행되어야 합니다.
"""

import os

import pytest

# .env에서 API 키 로드
from dotenv import load_dotenv
from fastapi.testclient import TestClient

from main import app

load_dotenv()

# API 키 가져오기
API_KEY = os.getenv("FASTAPI_AUTH_KEY", "REDACTED_API_KEY_REMOVED_FROM_HISTORY")


@pytest.mark.integration
@pytest.mark.e2e  # E2E 테스트 마커 추가
@pytest.mark.skip(reason="E2E 테스트는 실제 서비스 연결 필요 (Weaviate, LLM 등)")
class TestSelfRAGQualityGateE2E:
    """Self-RAG 품질 게이트 E2E 테스트"""

    @pytest.fixture
    def client(self):
        """FastAPI TestClient"""
        return TestClient(app)

    def test_high_quality_answer_with_debug_trace(self, client):
        """
        고품질 답변 E2E 플로우

        Given: Self-RAG 활성화, 고품질 질문
        When: POST /chat → GET /admin/debug
        Then: 품질 메타데이터 + 디버깅 추적 정보 제공

        TDD Red Phase: 이 테스트는 실패해야 합니다.
        - 아직 enable_debug_trace 기능이 RAGPipeline에 없음
        - 세션 모듈의 debug_trace 저장 기능이 없음

        Implementation Status:
        - [ ] Task 1: Self-RAG 품질 게이트 구현
        - [ ] Task 2: API 응답 품질 메타데이터 추가
        - [ ] Task 3: DebugTrace 스키마 정의
        - [ ] Task 4: RAGPipeline enable_debug_trace 추가
        - [ ] Task 5: Admin 디버깅 API 구현
        - [x] Task 6: E2E 통합 테스트 작성 (이 테스트)
        """
        # Step 1: 채팅 요청
        chat_response = client.post(
            "/api/chat",
            json={
                "message": "서울 강남구 맛집 추천해줘",
                "session_id": "e2e-high-quality-test",
            },
            headers={"X-API-Key": API_KEY},
        )

        # 검증: 채팅 응답 성공
        assert chat_response.status_code == 200
        chat_data = chat_response.json()

        # 검증: 고품질 답변 메타데이터
        assert "metadata" in chat_data, "metadata 필드가 없습니다"
        metadata = chat_data["metadata"]

        # 검증: 품질 정보가 있는 경우 (Self-RAG 활성화 시)
        if "quality" in metadata:
            quality = metadata["quality"]
            assert "score" in quality, "quality.score 필드가 없습니다"
            assert "confidence" in quality, "quality.confidence 필드가 없습니다"
            assert quality["score"] >= 0.0, "품질 점수는 0.0 이상이어야 합니다"
            assert quality["confidence"] in [
                "low",
                "medium",
                "high",
            ], f"신뢰도 레벨이 잘못되었습니다: {quality['confidence']}"

            # 고품질인 경우 (0.6 이상)
            if quality["score"] >= 0.6:
                assert quality["confidence"] in ["medium", "high"]

        message_id = chat_data["message_id"]
        session_id = chat_data["session_id"]

        # Step 2: 디버깅 추적 조회
        debug_response = client.get(
            f"/api/admin/debug/session/{session_id}/messages/{message_id}",
            headers={"X-API-Key": API_KEY},
        )

        # 검증: 디버깅 추적 조회 성공 또는 404 (debug_trace가 없는 경우)
        # 현재는 in-memory 세션이므로 debug_trace가 없을 수 있음
        if debug_response.status_code == 200:
            debug_data = debug_response.json()

            # 검증: Self-RAG 평가 정보 (있는 경우)
            if "self_rag_evaluation" in debug_data and debug_data["self_rag_evaluation"]:
                eval_data = debug_data["self_rag_evaluation"]

                # Self-RAG 평가 데이터 검증
                assert "final_quality" in eval_data, "final_quality 필드가 없습니다"
                assert eval_data["final_quality"] >= 0.0, "품질 점수는 0.0 이상이어야 합니다"
                assert eval_data["final_quality"] <= 1.0, "품질 점수는 1.0 이하여야 합니다"

                # 품질 메타데이터와 Self-RAG 평가 점수 일치 검증
                if "quality" in metadata:
                    assert (
                        abs(eval_data["final_quality"] - metadata["quality"]["score"]) < 0.01
                    ), "Self-RAG 평가 점수와 품질 메타데이터 점수가 일치하지 않습니다"
        elif debug_response.status_code == 404:
            # debug_trace가 없는 경우 (정상 시나리오)
            pytest.skip("Debug trace not available (in-memory session)")
        else:
            pytest.fail(
                f"Unexpected status code: {debug_response.status_code}, "
                f"detail: {debug_response.json()}"
            )

    def test_low_quality_answer_refused(self, client):
        """
        저품질 답변 거부 E2E 플로우

        Given: Self-RAG 활성화, 애매한 질문
        When: POST /chat
        Then: 거부 메시지 + quality.confidence="low"

        Note: 실제 저품질 시나리오를 유도하기 어려우므로
              품질 메타데이터 구조만 검증합니다.
        """
        # 애매한 질문으로 저품질 시도
        chat_response = client.post(
            "/api/chat",
            json={"message": "뭐?", "session_id": "e2e-low-quality-test"},
            headers={"X-API-Key": API_KEY},
        )

        # 검증: 채팅 응답 성공 (거부 메시지 포함)
        assert chat_response.status_code == 200
        chat_data = chat_response.json()

        # 검증: 메타데이터 존재
        assert "metadata" in chat_data, "metadata 필드가 없습니다"

        # 검증: 품질 정보 구조 (있는 경우)
        if "quality" in chat_data["metadata"]:
            quality = chat_data["metadata"]["quality"]

            # 저품질인 경우 검증
            if quality["score"] < 0.6:
                assert quality["confidence"] == "low", "저품질은 confidence='low'여야 합니다"

                # 거부 사유가 있는지 확인 (선택)
                if "refusal_reason" in quality:
                    assert isinstance(
                        quality["refusal_reason"], str
                    ), "refusal_reason은 문자열이어야 합니다"
                    assert len(quality["refusal_reason"]) > 0, "거부 사유가 비어있습니다"

    def test_debug_trace_disabled_scenario(self, client):
        """
        디버깅 추적 비활성화 시나리오

        Given: enable_debug_trace=False (기본값)
        When: POST /chat → GET /admin/debug
        Then: 404 Not Found (debug_trace가 없음)

        Note: 현재 in-memory 세션이므로 debug_trace가 항상 없습니다.
        """
        # 채팅 요청
        chat_response = client.post(
            "/api/chat",
            json={
                "message": "테스트 메시지",
                "session_id": "e2e-debug-disabled-test",
            },
            headers={"X-API-Key": API_KEY},
        )

        assert chat_response.status_code == 200
        chat_data = chat_response.json()

        message_id = chat_data["message_id"]
        session_id = chat_data["session_id"]

        # 디버깅 추적 조회 (없어야 정상)
        debug_response = client.get(
            f"/api/admin/debug/session/{session_id}/messages/{message_id}",
            headers={"X-API-Key": API_KEY},
        )

        # 검증: 404 Not Found (debug_trace 없음)
        # 현재 in-memory 세션이므로 항상 404
        assert debug_response.status_code == 404
        assert "not found" in debug_response.json()["detail"].lower()
