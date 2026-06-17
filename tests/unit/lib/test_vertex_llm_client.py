"""VertexLLMClient(app/lib/llm_client.py) 단위 테스트.

목적: ADC(키리스) 기반 선택적 Vertex AI LLM provider를 llm_factory 경로(쿼리
재작성/확장 등 내부 보조 LLM)에서 사용할 수 있도록 추가된 VertexLLMClient의 핵심
동작을 vertex extra 미설치 환경에서도 검증한다(OpenAI/google.auth 모킹).

특히 thinking(추론) 모델 회귀를 방어한다: gemini 계열 thinking 모델은 max_tokens가
부족하면 추론에 토큰을 모두 소진해 choices/message/content가 None으로 truncated
반환될 수 있다. 이때 AttributeError로 상위 fallback을 무의미하게 유발하는 대신,
graceful하게 빈 문자열을 반환해야 한다.

또한 원본 대비 개선점인 토큰 갱신 race lock(threading.Lock) 직렬화도 검증한다.
"""

import threading
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


def _make_vertex_client(create_return: Any) -> Any:
    """OpenAI/ADC를 모킹해 VertexLLMClient를 생성한다.

    Args:
        create_return: client.chat.completions.create가 반환할 mock 응답 객체.

    Returns:
        생성된 VertexLLMClient 인스턴스(내부 OpenAI 클라이언트는 mock).
    """
    from app.lib.llm_client import VertexLLMClient

    mock_creds = MagicMock()
    mock_creds.valid = True
    mock_creds.token = "fake-adc-token"

    mock_openai = MagicMock()
    mock_openai.chat.completions.create.return_value = create_return

    with (
        patch("app.lib.llm_client.OpenAI", return_value=mock_openai),
        patch("google.auth.default", return_value=(mock_creds, "test-project")),
    ):
        client = VertexLLMClient(
            {
                "project_id": "test-project",
                "location": "us-central1",
                "default_model": "google/gemini-2.5-flash",
                "timeout": 60,
                "max_tokens": 1024,
            }
        )
    return client


def _response_with_content(content: str | None) -> Any:
    """choices[0].message.content를 가진 OpenAI 호환 응답 mock 생성."""
    msg = MagicMock()
    msg.content = content
    choice = MagicMock()
    choice.message = msg
    choice.finish_reason = "stop" if content else "length"
    resp = MagicMock()
    resp.choices = [choice]
    return resp


class TestVertexLLMClientGenerateText:
    """generate_text의 정상/None/빈 응답 처리 검증."""

    @pytest.mark.asyncio
    async def test_returns_content_on_success(self) -> None:
        """정상 응답이면 content 문자열을 그대로 반환한다."""
        client = _make_vertex_client(_response_with_content("RAG란 검색 증강 생성이다."))
        result = await client.generate_text("RAG란?")
        assert result == "RAG란 검색 증강 생성이다."

    @pytest.mark.asyncio
    async def test_none_message_returns_empty_string(self) -> None:
        """choices[0].message가 None(추론 토큰 소진)이면 AttributeError 없이 ''를 반환한다."""
        choice = MagicMock()
        choice.message = None
        choice.finish_reason = "length"
        resp = MagicMock()
        resp.choices = [choice]

        client = _make_vertex_client(resp)
        result = await client.generate_text("질문", max_tokens=128)
        assert result == ""

    @pytest.mark.asyncio
    async def test_none_content_returns_empty_string(self) -> None:
        """message.content가 None이면 ''를 반환한다(truncated 응답 방어)."""
        client = _make_vertex_client(_response_with_content(None))
        result = await client.generate_text("질문", max_tokens=128)
        assert result == ""

    @pytest.mark.asyncio
    async def test_empty_choices_returns_empty_string(self) -> None:
        """choices가 비어 있으면 IndexError 없이 ''를 반환한다."""
        resp = MagicMock()
        resp.choices = []
        client = _make_vertex_client(resp)
        result = await client.generate_text("질문")
        assert result == ""

    @pytest.mark.asyncio
    async def test_reasoning_effort_passed_through(self) -> None:
        """reasoning_effort kwargs가 OpenAI 호환 호출 파라미터로 전달된다."""
        client = _make_vertex_client(_response_with_content("ok"))
        await client.generate_text("질문", reasoning_effort="low")
        _, kwargs = client.client.chat.completions.create.call_args
        assert kwargs["reasoning_effort"] == "low"


class TestVertexLLMClientModelNormalization:
    """모델명 정규화 검증(google/ 접두사 자동 부여)."""

    def test_normalize_model_adds_google_prefix(self) -> None:
        from app.lib.llm_client import VertexLLMClient

        assert VertexLLMClient._normalize_model("gemini-2.5-flash") == (
            "google/gemini-2.5-flash"
        )
        assert VertexLLMClient._normalize_model("google/gemini-2.5-flash") == (
            "google/gemini-2.5-flash"
        )


class TestVertexLLMClientTokenLock:
    """원본 대비 개선: 토큰 갱신을 lock으로 직렬화(동시 갱신 race 차단)."""

    def test_refresh_token_serializes_concurrent_refresh(self) -> None:
        client = _make_vertex_client(_response_with_content("ok"))

        credentials = MagicMock()
        credentials.valid = False

        def _do_refresh(_request: object) -> None:
            credentials.token = "tok-locked"
            credentials.valid = True

        credentials.refresh = MagicMock(side_effect=_do_refresh)
        client._credentials = credentials

        results: list[str] = []
        errors: list[Exception] = []

        def worker() -> None:
            try:
                results.append(client._refresh_token())
            except Exception as error:  # noqa: BLE001 - 테스트에서 모든 실패 수집
                errors.append(error)

        threads = [threading.Thread(target=worker) for _ in range(16)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert not errors
        assert results == ["tok-locked"] * 16
        # lock 으로 직렬화되어 refresh 는 최초 1회만 일어난다.
        assert credentials.refresh.call_count == 1


class TestLLMClientFactoryVertexRegistration:
    """LLMClientFactory가 vertex provider를 등록/초기화하는지 검증."""

    def test_vertex_registered_in_provider_registry(self) -> None:
        from app.lib.llm_client import LLMClientFactory, VertexLLMClient

        assert LLMClientFactory._PROVIDER_REGISTRY["vertex"] is VertexLLMClient

    def test_factory_initializes_vertex_client_keyless(self) -> None:
        """vertex 섹션이 설정에 있으면 API 키 없이도 클라이언트가 초기화된다."""
        from app.lib.llm_client import LLMClientFactory

        mock_creds = MagicMock()
        mock_creds.valid = True
        mock_creds.token = "fake-adc-token"

        with (
            patch("app.lib.llm_client.OpenAI", return_value=MagicMock()),
            patch("google.auth.default", return_value=(mock_creds, "test-project")),
        ):
            factory = LLMClientFactory(
                {
                    "llm": {
                        "default_provider": "vertex",
                        "vertex": {
                            "project_id": "test-project",
                            "location": "us-central1",
                            "default_model": "google/gemini-2.5-flash",
                        },
                    }
                }
            )

        client = factory.get_client("vertex")
        assert client.__class__.__name__ == "VertexLLMClient"
