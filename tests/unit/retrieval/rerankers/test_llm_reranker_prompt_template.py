"""
LLM 리랭커 프롬프트 템플릿 외부화/단일화 테스트 (6차 도메인 범용화)

검증 목표:
- (a) prompt_template 미주입 시 코드 내장 기본 프롬프트를 사용한다(회귀 0).
      기본 프롬프트는 외부화 이전 하드코딩 프롬프트와 byte-identical이어야 한다.
- (b) prompt_template 주입 시 해당 템플릿으로 오버라이드된다.
- (c) RerankerFactoryV2가 config의 reranking.<provider>.prompt_template을
      각 LLM 리랭커 생성자에 전달한다.

대상 리랭커:
- GeminiFlashReranker  : 영어 기본, 플레이스홀더 {query} {documents_text} {top_k}
- OpenAILLMReranker    : 영어 기본, 플레이스홀더 {query} {documents_text} {top_k}
- OpenRouterReranker   : 한국어 기본, 플레이스홀더 {query} {docs_text}
"""

from unittest.mock import MagicMock, patch

import pytest

from app.modules.core.retrieval.interfaces import SearchResult

# ────────────────────────────────────────────────────────────────────
# 외부화 이전(하드코딩) 기본 프롬프트의 황금 사본(golden copy).
# 코드 내장 DEFAULT_PROMPT_TEMPLATE가 이 사본과 동치인지 비교하여 회귀 0을 보장한다.
# ────────────────────────────────────────────────────────────────────

# Gemini/OpenAI 공통 영어 프롬프트 (외부화 이전 f-string 본문과 동일)
_GOLDEN_EN_PROMPT = """You are a document ranking expert. Evaluate and rank documents based on their relevance to the query.

Query: "{query}"

Documents:
{documents_text}

Task: Score each document from 0.0 to 1.0 based on relevance to the query.
Select only the top {top_k} most relevant documents.

IMPORTANT: Respond ONLY with valid JSON in this exact format:
{{"results": [{{"index": 0, "score": 0.95}}, {{"index": 2, "score": 0.8}}, {{"index": 1, "score": 0.6}}]}}

Do not include any other text, explanation, or formatting. Only the JSON object."""

# OpenRouter 한국어 프롬프트 (외부화 이전 f-string 본문과 동일)
_GOLDEN_KO_PROMPT = """다음 문서들을 쿼리와의 관련성에 따라 순위를 매겨주세요.

쿼리: {query}

문서들:
{docs_text}

JSON 형식으로 응답해주세요:
{{"rankings": [{{"index": 문서번호, "score": 0.0-1.0 점수}}]}}

점수가 높은 순서대로 정렬하여 응답해주세요."""


@pytest.fixture
def sample_results() -> list[SearchResult]:
    """샘플 검색 결과"""
    return [
        SearchResult(
            id="doc1",
            content="파이썬은 프로그래밍 언어입니다.",
            score=0.7,
            metadata={"source": "test1.md"},
        ),
        SearchResult(
            id="doc2",
            content="자바스크립트는 웹 개발에 사용됩니다.",
            score=0.6,
            metadata={"source": "test2.md"},
        ),
    ]


# ════════════════════════════════════════════════════════════════════
# GeminiFlashReranker
# ════════════════════════════════════════════════════════════════════


class TestGeminiPromptTemplate:
    """Gemini 리랭커 프롬프트 템플릿 검증"""

    def test_default_template_is_byte_identical_to_golden(self) -> None:
        """(a) 기본 템플릿이 외부화 이전 하드코딩 프롬프트와 byte-identical"""
        from app.modules.core.retrieval.rerankers.gemini_reranker import (
            GeminiFlashReranker,
        )

        assert GeminiFlashReranker.DEFAULT_PROMPT_TEMPLATE == _GOLDEN_EN_PROMPT

    def test_no_injection_falls_back_to_default(self) -> None:
        """(a) prompt_template 미주입 시 코드 기본값으로 폴백"""
        from app.modules.core.retrieval.rerankers.gemini_reranker import (
            GeminiFlashReranker,
        )

        reranker = GeminiFlashReranker(api_key="test-key")
        assert reranker.prompt_template == GeminiFlashReranker.DEFAULT_PROMPT_TEMPLATE

    def test_injection_overrides_default(self) -> None:
        """(b) prompt_template 주입 시 해당 템플릿 사용"""
        from app.modules.core.retrieval.rerankers.gemini_reranker import (
            GeminiFlashReranker,
        )

        custom = 'Rank "{query}" over:\n{documents_text}\nTop {top_k}.'
        reranker = GeminiFlashReranker(api_key="test-key", prompt_template=custom)
        assert reranker.prompt_template == custom

    @pytest.mark.asyncio
    async def test_default_rendered_prompt_matches_golden(
        self, sample_results: list[SearchResult]
    ) -> None:
        """(a) 미주입 시 실제 호출에 들어가는 프롬프트가 황금 사본 렌더링과 동일"""
        from app.modules.core.retrieval.rerankers.gemini_reranker import (
            GeminiFlashReranker,
        )

        with patch("httpx.AsyncClient.post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "candidates": [
                    {"content": {"parts": [{"text": '{"results": []}'}]}}
                ]
            }
            mock_post.return_value = mock_response

            reranker = GeminiFlashReranker(api_key="test-key")
            await reranker.rerank(query="파이썬이란?", results=sample_results, top_k=3)

            # 실제 전송된 프롬프트 추출
            sent_body = mock_post.call_args.kwargs["json"]
            sent_prompt = sent_body["contents"][0]["parts"][0]["text"]

            # 문서 텍스트는 rerank 내부에서 동일 규칙으로 생성됨 → golden 렌더링과 비교
            documents_text = ""
            for i, r in enumerate(sample_results):
                preview = r.content[:250].replace("\n", " ").strip()
                documents_text += f"\n[{i}] {preview}..."
            expected = _GOLDEN_EN_PROMPT.format(
                query="파이썬이란?", documents_text=documents_text, top_k=3
            )
            assert sent_prompt == expected

    @pytest.mark.asyncio
    async def test_injected_prompt_is_used_in_request(
        self, sample_results: list[SearchResult]
    ) -> None:
        """(b) 주입한 템플릿이 실제 호출 본문에 반영"""
        from app.modules.core.retrieval.rerankers.gemini_reranker import (
            GeminiFlashReranker,
        )

        custom = "CUSTOM q={query} docs={documents_text} k={top_k}"
        with patch("httpx.AsyncClient.post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "candidates": [
                    {"content": {"parts": [{"text": '{"results": []}'}]}}
                ]
            }
            mock_post.return_value = mock_response

            reranker = GeminiFlashReranker(api_key="test-key", prompt_template=custom)
            await reranker.rerank(query="hi", results=sample_results, top_k=2)

            sent_prompt = mock_post.call_args.kwargs["json"]["contents"][0]["parts"][0][
                "text"
            ]
            assert sent_prompt.startswith("CUSTOM q=hi docs=")
            assert "k=2" in sent_prompt
            # 영어 기본 프롬프트의 고정 문구가 없어야 함
            assert "document ranking expert" not in sent_prompt


# ════════════════════════════════════════════════════════════════════
# OpenAILLMReranker
# ════════════════════════════════════════════════════════════════════


class TestOpenAIPromptTemplate:
    """OpenAI LLM 리랭커 프롬프트 템플릿 검증"""

    def test_default_template_is_byte_identical_to_golden(self) -> None:
        """(a) 기본 템플릿이 외부화 이전 하드코딩 프롬프트와 byte-identical"""
        from app.modules.core.retrieval.rerankers.openai_llm_reranker import (
            OpenAILLMReranker,
        )

        assert OpenAILLMReranker.DEFAULT_PROMPT_TEMPLATE == _GOLDEN_EN_PROMPT

    def test_no_injection_falls_back_to_default(self) -> None:
        """(a) prompt_template 미주입 시 코드 기본값으로 폴백"""
        from app.modules.core.retrieval.rerankers.openai_llm_reranker import (
            OpenAILLMReranker,
        )

        with patch("openai.OpenAI"):
            reranker = OpenAILLMReranker(api_key="test-key")
            assert (
                reranker.prompt_template == OpenAILLMReranker.DEFAULT_PROMPT_TEMPLATE
            )

    def test_injection_overrides_default(self) -> None:
        """(b) prompt_template 주입 시 해당 템플릿 사용"""
        from app.modules.core.retrieval.rerankers.openai_llm_reranker import (
            OpenAILLMReranker,
        )

        custom = 'Rank "{query}" over:\n{documents_text}\nTop {top_k}.'
        with patch("openai.OpenAI"):
            reranker = OpenAILLMReranker(api_key="test-key", prompt_template=custom)
            assert reranker.prompt_template == custom

    @pytest.mark.asyncio
    async def test_default_rendered_prompt_matches_golden(
        self, sample_results: list[SearchResult]
    ) -> None:
        """(a) 미주입 시 responses.create input에 황금 렌더링이 포함됨"""
        from app.modules.core.retrieval.rerankers.openai_llm_reranker import (
            OpenAILLMReranker,
        )

        captured: dict[str, str] = {}

        def _fake_create(**kwargs: object) -> MagicMock:
            captured["input"] = str(kwargs["input"])
            resp = MagicMock()
            resp.output_text = '{"results": []}'
            resp.usage = None
            return resp

        with patch("openai.OpenAI") as mock_openai:
            mock_client = MagicMock()
            mock_client.responses.create.side_effect = _fake_create
            mock_openai.return_value = mock_client

            reranker = OpenAILLMReranker(api_key="test-key")
            await reranker.rerank(query="질문", results=sample_results, top_k=5)

        documents_text = ""
        for i, r in enumerate(sample_results):
            preview = r.content[:250].replace("\n", " ").strip()
            documents_text += f"\n[{i}] {preview}..."
        expected_prompt = _GOLDEN_EN_PROMPT.format(
            query="질문", documents_text=documents_text, top_k=5
        )
        # input_text는 prompt를 그대로 감싸므로 황금 프롬프트가 포함되어야 함
        assert expected_prompt in captured["input"]

    @pytest.mark.asyncio
    async def test_injected_prompt_is_used_in_request(
        self, sample_results: list[SearchResult]
    ) -> None:
        """(b) 주입한 템플릿이 실제 input에 반영"""
        from app.modules.core.retrieval.rerankers.openai_llm_reranker import (
            OpenAILLMReranker,
        )

        custom = "CUSTOM q={query} docs={documents_text} k={top_k}"
        captured: dict[str, str] = {}

        def _fake_create(**kwargs: object) -> MagicMock:
            captured["input"] = str(kwargs["input"])
            resp = MagicMock()
            resp.output_text = '{"results": []}'
            resp.usage = None
            return resp

        with patch("openai.OpenAI") as mock_openai:
            mock_client = MagicMock()
            mock_client.responses.create.side_effect = _fake_create
            mock_openai.return_value = mock_client

            reranker = OpenAILLMReranker(api_key="test-key", prompt_template=custom)
            await reranker.rerank(query="hi", results=sample_results, top_k=2)

        assert "CUSTOM q=hi docs=" in captured["input"]
        assert "k=2" in captured["input"]
        assert "document ranking expert" not in captured["input"]


# ════════════════════════════════════════════════════════════════════
# OpenRouterReranker
# ════════════════════════════════════════════════════════════════════


class TestOpenRouterPromptTemplate:
    """OpenRouter 리랭커 프롬프트 템플릿 검증 (한국어 기본, top_k 없음)"""

    def test_default_template_is_byte_identical_to_golden(self) -> None:
        """(a) 기본 템플릿이 외부화 이전 하드코딩 한국어 프롬프트와 byte-identical"""
        from app.modules.core.retrieval.rerankers.openrouter_reranker import (
            OpenRouterReranker,
        )

        assert OpenRouterReranker.DEFAULT_PROMPT_TEMPLATE == _GOLDEN_KO_PROMPT

    def test_no_injection_falls_back_to_default(self) -> None:
        """(a) prompt_template 미주입 시 코드 기본값으로 폴백"""
        from app.modules.core.retrieval.rerankers.openrouter_reranker import (
            OpenRouterReranker,
        )

        reranker = OpenRouterReranker(api_key="test-key")
        assert (
            reranker.prompt_template == OpenRouterReranker.DEFAULT_PROMPT_TEMPLATE
        )

    def test_default_build_prompt_matches_golden(
        self, sample_results: list[SearchResult]
    ) -> None:
        """(a) 미주입 시 _build_prompt 출력이 황금 렌더링과 byte-identical"""
        from app.modules.core.retrieval.rerankers.openrouter_reranker import (
            OpenRouterReranker,
        )

        reranker = OpenRouterReranker(api_key="test-key")
        rendered = reranker._build_prompt("쿼리테스트", sample_results)

        docs_text = "\n".join(
            f"[{i}] {doc.content[:500]}" for i, doc in enumerate(sample_results)
        )
        expected = _GOLDEN_KO_PROMPT.format(query="쿼리테스트", docs_text=docs_text)
        assert rendered == expected

    def test_injection_overrides_build_prompt(
        self, sample_results: list[SearchResult]
    ) -> None:
        """(b) prompt_template 주입 시 _build_prompt가 해당 템플릿 사용"""
        from app.modules.core.retrieval.rerankers.openrouter_reranker import (
            OpenRouterReranker,
        )

        custom = "CUSTOM q={query} docs={docs_text}"
        reranker = OpenRouterReranker(api_key="test-key", prompt_template=custom)
        rendered = reranker._build_prompt("hi", sample_results)

        assert rendered.startswith("CUSTOM q=hi docs=")
        # 한국어 기본 프롬프트의 고정 문구가 없어야 함
        assert "순위를 매겨주세요" not in rendered


# ════════════════════════════════════════════════════════════════════
# RerankerFactoryV2 배선 (config → reranker.prompt_template)
# ════════════════════════════════════════════════════════════════════


class TestFactoryPromptTemplateWiring:
    """팩토리가 config의 prompt_template을 리랭커에 전달하는지 검증"""

    @patch.dict("os.environ", {"GOOGLE_API_KEY": "test-key"})
    def test_factory_passes_template_to_google(self) -> None:
        """(c) reranking.google.prompt_template → GeminiFlashReranker"""
        from app.modules.core.retrieval.rerankers.factory import RerankerFactoryV2

        custom = "GGL {query} {documents_text} {top_k}"
        config = {
            "reranking": {
                "approach": "llm",
                "provider": "google",
                "google": {"prompt_template": custom},
            }
        }
        reranker = RerankerFactoryV2.create(config)
        assert reranker.prompt_template == custom  # type: ignore[attr-defined]

    @patch.dict("os.environ", {"GOOGLE_API_KEY": "test-key"})
    def test_factory_omits_template_falls_back_to_default(self) -> None:
        """(c·회귀 0) prompt_template 미설정 시 코드 기본값 유지"""
        from app.modules.core.retrieval.rerankers.factory import RerankerFactoryV2
        from app.modules.core.retrieval.rerankers.gemini_reranker import (
            GeminiFlashReranker,
        )

        config = {
            "reranking": {
                "approach": "llm",
                "provider": "google",
                "google": {"model": "gemini-flash-lite-latest"},
            }
        }
        reranker = RerankerFactoryV2.create(config)
        assert (
            reranker.prompt_template  # type: ignore[attr-defined]
            == GeminiFlashReranker.DEFAULT_PROMPT_TEMPLATE
        )

    @patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"})
    def test_factory_passes_template_to_openai(self) -> None:
        """(c) reranking.openai.prompt_template → OpenAILLMReranker"""
        from app.modules.core.retrieval.rerankers.factory import RerankerFactoryV2

        custom = "OAI {query} {documents_text} {top_k}"
        config = {
            "reranking": {
                "approach": "llm",
                "provider": "openai",
                "openai": {"prompt_template": custom},
            }
        }
        with patch("openai.OpenAI"):
            reranker = RerankerFactoryV2.create(config)
        assert reranker.prompt_template == custom  # type: ignore[attr-defined]

    @patch.dict("os.environ", {"OPENROUTER_API_KEY": "test-key"})
    def test_factory_passes_template_to_openrouter(self) -> None:
        """(c) reranking.openrouter.prompt_template → OpenRouterReranker"""
        from app.modules.core.retrieval.rerankers.factory import RerankerFactoryV2

        custom = "OR {query} {docs_text}"
        config = {
            "reranking": {
                "approach": "llm",
                "provider": "openrouter",
                "openrouter": {"prompt_template": custom},
            }
        }
        reranker = RerankerFactoryV2.create(config)
        assert reranker.prompt_template == custom  # type: ignore[attr-defined]

    @patch.dict("os.environ", {"OPENROUTER_API_KEY": "test-key"})
    def test_factory_omits_template_openrouter_default(self) -> None:
        """(c·회귀 0) openrouter prompt_template 미설정 시 한국어 기본값 유지"""
        from app.modules.core.retrieval.rerankers.factory import RerankerFactoryV2
        from app.modules.core.retrieval.rerankers.openrouter_reranker import (
            OpenRouterReranker,
        )

        config = {
            "reranking": {
                "approach": "llm",
                "provider": "openrouter",
            }
        }
        reranker = RerankerFactoryV2.create(config)
        assert (
            reranker.prompt_template  # type: ignore[attr-defined]
            == OpenRouterReranker.DEFAULT_PROMPT_TEMPLATE
        )
