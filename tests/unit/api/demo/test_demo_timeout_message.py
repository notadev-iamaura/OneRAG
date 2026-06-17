"""
데모 스트리밍 타임아웃 메시지 외부화 테스트 (11차 범용화)

demo_pipeline의 TimeoutError 분기 사용자 안내 메시지가 한국어로
하드코딩돼 형제 메시지(DEMO_* env)와 비대칭이던 것을, 동일 패턴으로
DEMO_STREAM_TIMEOUT_MESSAGE env 외부화한 변경을 검증한다(회귀 0).
"""

from app.api.demo import demo_pipeline


class TestDemoTimeoutMessage:
    def test_default_korean_message(self):
        """미설정 시 한국어 기본 메시지 (회귀 0)."""
        assert (
            demo_pipeline.DEFAULT_STREAM_TIMEOUT_MESSAGE
            == "답변 생성이 지연되고 있습니다. 잠시 후 다시 시도해주세요."
        )
        # 모듈 로드 시 env 미설정이면 기본값과 동일
        assert demo_pipeline.STREAM_TIMEOUT_MESSAGE == demo_pipeline.DEFAULT_STREAM_TIMEOUT_MESSAGE

    def test_resolve_prompt_env_override(self, monkeypatch):
        """_resolve_prompt가 env로 메시지를 오버라이드한다."""
        monkeypatch.setenv("DEMO_STREAM_TIMEOUT_MESSAGE", "Generation is delayed. Try again.")
        resolved = demo_pipeline._resolve_prompt(
            "DEMO_STREAM_TIMEOUT_MESSAGE", demo_pipeline.DEFAULT_STREAM_TIMEOUT_MESSAGE
        )
        assert resolved == "Generation is delayed. Try again."

    def test_resolve_prompt_blank_env_keeps_default(self, monkeypatch):
        monkeypatch.setenv("DEMO_STREAM_TIMEOUT_MESSAGE", "   ")
        resolved = demo_pipeline._resolve_prompt(
            "DEMO_STREAM_TIMEOUT_MESSAGE", demo_pipeline.DEFAULT_STREAM_TIMEOUT_MESSAGE
        )
        assert resolved == demo_pipeline.DEFAULT_STREAM_TIMEOUT_MESSAGE
