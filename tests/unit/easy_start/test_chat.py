"""
Rich CLI 챗봇 단위 테스트

CLI 챗봇의 핵심 함수를 테스트합니다.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestBuildUserPrompt:
    """사용자 프롬프트 구성 테스트"""

    def test_includes_query_and_documents(self):
        """
        프롬프트에 질문과 문서 내용이 포함되는지 확인

        Given: 질문과 문서 리스트
        When: build_user_prompt() 호출
        Then: 프롬프트에 질문, 문서 내용, 문서 번호 포함
        """
        from easy_start.chat import build_user_prompt

        documents = [
            {"content": "RAG는 검색 증강 생성입니다."},
            {"content": "하이브리드 검색은 Dense + Sparse 결합입니다."},
        ]

        prompt = build_user_prompt("RAG란?", documents)

        assert "RAG란?" in prompt
        assert "RAG는 검색 증강 생성입니다." in prompt
        assert "하이브리드 검색은 Dense + Sparse 결합입니다." in prompt
        assert "문서 1" in prompt
        assert "문서 2" in prompt

    def test_empty_documents(self):
        """
        빈 문서 리스트로 프롬프트 구성

        Given: 빈 문서 리스트
        When: build_user_prompt() 호출
        Then: 질문은 포함되고 에러 없이 반환
        """
        from easy_start.chat import build_user_prompt

        prompt = build_user_prompt("테스트 질문", [])

        assert "테스트 질문" in prompt
        assert "참고문서" in prompt

    def test_missing_content_field(self):
        """
        content 필드가 없는 문서 처리

        Given: content 필드 없는 문서
        When: build_user_prompt() 호출
        Then: 빈 문자열로 대체되어 에러 없이 동작
        """
        from easy_start.chat import build_user_prompt

        documents = [{"title": "제목만"}]
        prompt = build_user_prompt("질문", documents)

        assert "질문" in prompt


class TestSearchDocuments:
    """검색 함수 테스트"""

    @pytest.mark.asyncio
    async def test_calls_retriever(self):
        """
        retriever.search()를 올바르게 호출하는지 확인

        Given: Mock retriever
        When: search_documents() 호출
        Then: retriever.search()가 쿼리와 함께 호출됨
        """
        from easy_start.chat import search_documents

        mock_retriever = AsyncMock()
        mock_retriever.search.return_value = []

        results = await search_documents("테스트 쿼리", retriever=mock_retriever)

        mock_retriever.search.assert_called_once()
        assert isinstance(results, list)
        assert results == []

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_retriever(self):
        """
        retriever가 None일 때 빈 리스트 반환

        Given: retriever=None
        When: search_documents() 호출
        Then: 빈 리스트 반환
        """
        from easy_start.chat import search_documents

        results = await search_documents("쿼리", retriever=None)
        assert results == []

    @pytest.mark.asyncio
    async def test_converts_search_results_to_dicts(self):
        """
        SearchResult 객체를 dict로 올바르게 변환

        Given: SearchResult 속성을 가진 Mock 객체
        When: search_documents() 호출
        Then: content, score, source, metadata가 포함된 dict 리스트 반환
        """
        from easy_start.chat import search_documents

        mock_sr = MagicMock()
        mock_sr.content = "테스트 내용"
        mock_sr.score = 0.95
        mock_sr.id = "doc-001"
        mock_sr.metadata = {"category": "FAQ"}

        mock_retriever = AsyncMock()
        mock_retriever.search.return_value = [mock_sr]

        results = await search_documents("쿼리", retriever=mock_retriever)

        assert len(results) == 1
        assert results[0]["content"] == "테스트 내용"
        assert results[0]["score"] == 0.95
        assert results[0]["source"] == "doc-001"
        assert results[0]["metadata"] == {"category": "FAQ"}

    @pytest.mark.asyncio
    async def test_handles_missing_attributes_gracefully(self):
        """
        SearchResult에 속성이 없을 때 기본값 사용

        Given: 일부 속성이 없는 Mock 객체
        When: search_documents() 호출
        Then: getattr 기본값으로 안전하게 변환
        """
        from easy_start.chat import search_documents

        mock_sr = MagicMock(spec=[])  # 빈 spec으로 모든 속성 없음

        mock_retriever = AsyncMock()
        mock_retriever.search.return_value = [mock_sr]

        results = await search_documents("쿼리", retriever=mock_retriever)

        assert len(results) == 1
        assert results[0]["content"] == ""
        assert results[0]["score"] == 0.0
        assert results[0]["source"] == ""
        assert results[0]["metadata"] == {}


class TestResolveLlmProviders:
    """LLM provider 결정 로직 테스트"""

    def test_both_keys_returns_gemini_first(self):
        """
        두 키 모두 있을 때 Gemini이 리스트 첫 번째

        Given: GOOGLE_API_KEY와 OPENROUTER_API_KEY 모두 설정
        When: _resolve_llm_providers() 호출
        Then: Gemini이 첫 번째, OpenRouter가 두 번째
        """
        from easy_start.chat import _resolve_llm_providers

        with patch.dict("os.environ", {
            "GOOGLE_API_KEY": "google-key",
            "OPENROUTER_API_KEY": "openrouter-key",
        }):
            result = _resolve_llm_providers()

        assert len(result) == 2
        assert result[0][3] == "Gemini"
        assert result[0][1] == "google-key"
        assert result[1][3] == "OpenRouter"
        assert result[1][1] == "openrouter-key"

    def test_openrouter_only(self):
        """
        OpenRouter 키만 있을 때 OpenRouter만 반환

        Given: OPENROUTER_API_KEY만 설정
        When: _resolve_llm_providers() 호출
        Then: OpenRouter provider 1개 반환
        """
        from easy_start.chat import _resolve_llm_providers

        with patch.dict("os.environ", {"OPENROUTER_API_KEY": "or-key"}, clear=True):
            result = _resolve_llm_providers()

        assert len(result) == 1
        assert result[0][3] == "OpenRouter"
        assert "openrouter" in result[0][0]

    def test_gemini_only(self):
        """
        Gemini 키만 있을 때 Gemini만 반환

        Given: GOOGLE_API_KEY만 설정
        When: _resolve_llm_providers() 호출
        Then: Gemini provider 1개 반환
        """
        from easy_start.chat import _resolve_llm_providers

        with patch.dict("os.environ", {"GOOGLE_API_KEY": "g-key"}, clear=True):
            result = _resolve_llm_providers()

        assert len(result) == 1
        assert result[0][3] == "Gemini"

    def test_no_keys(self):
        """
        키가 하나도 없을 때 빈 리스트 반환

        Given: API 키 미설정
        When: _resolve_llm_providers() 호출
        Then: 빈 리스트
        """
        from easy_start.chat import _resolve_llm_providers

        with patch.dict("os.environ", {}, clear=True):
            result = _resolve_llm_providers()

        assert result == []


class TestGenerateAnswer:
    """LLM 답변 생성 테스트"""

    @pytest.mark.asyncio
    async def test_returns_none_without_api_key(self):
        """
        API 키 미설정 시 None 반환

        Given: GOOGLE_API_KEY, OPENROUTER_API_KEY 모두 미설정
        When: generate_answer() 호출
        Then: None 반환
        """
        from easy_start.chat import generate_answer

        with patch.dict("os.environ", {}, clear=True):
            result = await generate_answer("테스트", [{"content": "문서"}])

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_openai_not_installed(self):
        """
        openai 패키지 미설치 시 None 반환

        Given: openai import 실패
        When: generate_answer() 호출
        Then: None 반환
        """
        from easy_start.chat import generate_answer

        with (
            patch.dict("os.environ", {"GOOGLE_API_KEY": "fake-key"}),
            patch("builtins.__import__", side_effect=ImportError("no openai")),
        ):
            result = await generate_answer("테스트", [])

        assert result is None


class TestFormatLlmError:
    """LLM 에러 포맷 테스트"""

    def test_quota_error_gemini(self):
        """Gemini 429 할당량 초과 에러 메시지"""
        from easy_start.chat import _format_llm_error

        error = Exception("Error code: 429 - quota exceeded")
        msg = _format_llm_error(error, "Gemini")

        assert "한도" in msg or "초과" in msg
        assert "aistudio" in msg

    def test_quota_error_openrouter(self):
        """OpenRouter 429 할당량 초과 에러 메시지"""
        from easy_start.chat import _format_llm_error

        error = Exception("Error code: 429 - quota exceeded")
        msg = _format_llm_error(error, "OpenRouter")

        assert "한도" in msg or "초과" in msg
        assert "openrouter.ai" in msg

    def test_auth_error_gemini(self):
        """Gemini 401 인증 실패 에러 메시지"""
        from easy_start.chat import _format_llm_error

        error = Exception("Error code: 401 - unauthorized")
        msg = _format_llm_error(error, "Gemini")

        assert "인증" in msg or "API 키" in msg
        assert "GOOGLE_API_KEY" in msg

    def test_auth_error_openrouter(self):
        """OpenRouter 인증 실패 에러 메시지"""
        from easy_start.chat import _format_llm_error

        error = Exception("Error code: 401 - unauthorized")
        msg = _format_llm_error(error, "OpenRouter")

        assert "OPENROUTER_API_KEY" in msg

    def test_timeout_error(self):
        """타임아웃 에러 메시지"""
        from easy_start.chat import _format_llm_error

        error = Exception("Connection timed out")
        msg = _format_llm_error(error)

        assert "시간" in msg or "초과" in msg

    def test_generic_error(self):
        """알 수 없는 에러 메시지"""
        from easy_start.chat import _format_llm_error

        error = ValueError("unexpected error")
        msg = _format_llm_error(error)

        assert "ValueError" in msg

    def test_default_provider_is_gemini(self):
        """provider_name 미지정 시 기본값은 Gemini"""
        from easy_start.chat import _format_llm_error

        error = Exception("Error code: 401 - unauthorized")
        msg = _format_llm_error(error)

        assert "GOOGLE_API_KEY" in msg


class TestCheckLlmAvailable:
    """LLM 가용성 확인 테스트"""

    def test_available_with_google_key(self):
        """Google API 키 설정 시 (True, "Gemini") 반환"""
        from easy_start.chat import _check_llm_available

        with patch.dict("os.environ", {"GOOGLE_API_KEY": "test-key"}, clear=True):
            available, name = _check_llm_available()

        assert available is True
        assert name == "Gemini"

    def test_available_with_openrouter_key(self):
        """OpenRouter API 키 설정 시 (True, "OpenRouter") 반환"""
        from easy_start.chat import _check_llm_available

        with patch.dict("os.environ", {"OPENROUTER_API_KEY": "or-key"}, clear=True):
            available, name = _check_llm_available()

        assert available is True
        assert name == "OpenRouter"

    def test_available_with_both_keys(self):
        """두 키 모두 설정 시 (True, "Gemini+OpenRouter") 반환"""
        from easy_start.chat import _check_llm_available

        with patch.dict("os.environ", {
            "GOOGLE_API_KEY": "g-key",
            "OPENROUTER_API_KEY": "or-key",
        }, clear=True):
            available, name = _check_llm_available()

        assert available is True
        assert name == "Gemini+OpenRouter"

    def test_unavailable_without_key(self):
        """API 키 미설정 시 (False, "") 반환"""
        from easy_start.chat import _check_llm_available

        with patch.dict("os.environ", {}, clear=True):
            available, name = _check_llm_available()

        assert available is False
        assert name == ""
