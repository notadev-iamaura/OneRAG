"""
LLM Client Factory - 통합 LLM 클라이언트 관리
모든 LLM 호출을 중앙에서 관리하여 중복 제거 및 일관성 확보
"""

import asyncio
import os
from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator
from typing import Any, Literal

import google.generativeai as genai
from anthropic import Anthropic
from openai import OpenAI

from .logger import get_logger

logger = get_logger(__name__)


class BaseLLMClient(ABC):
    """LLM 클라이언트 기본 인터페이스"""

    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.model: str = config.get("model", "")
        self.temperature = config.get("temperature", 0.0)
        self.max_tokens = config.get("max_tokens", 2048)
        self.timeout = config.get("timeout", 30)

    @abstractmethod
    async def generate_text(
        self, prompt: str, system_prompt: str | None = None, **kwargs: Any
    ) -> str:
        """텍스트 생성 (프롬프트만 전달, 시스템 프롬프트 선택적)"""
        pass

    @abstractmethod
    async def stream_text(
        self, prompt: str, system_prompt: str | None = None, **kwargs: Any
    ) -> AsyncGenerator[str, None]:
        """
        텍스트 스트리밍 생성 (AsyncGenerator)

        Args:
            prompt: 사용자 프롬프트
            system_prompt: 시스템 프롬프트 (선택적)
            **kwargs: 추가 파라미터

        Yields:
            str: 생성된 텍스트 청크
        """
        # 추상 메서드: 하위 클래스에서 구현 필수
        # AsyncGenerator를 위해 yield 필요
        yield ""  # type: ignore[misc]

    async def generate_multimodal(
        self,
        prompt: str,
        images: list[bytes] | None = None,
        image_urls: list[str] | None = None,
        mime_types: list[str] | None = None,
        system_prompt: str | None = None,
        **kwargs: Any,
    ) -> str:
        """
        멀티모달 생성 (텍스트 + 이미지)

        Args:
            prompt: 사용자 프롬프트 (텍스트)
            images: 이미지 바이트 데이터 리스트 (로컬 파일)
            image_urls: 이미지 URL 리스트 (원격 파일)
            mime_types: 각 이미지의 MIME 타입 (image/jpeg, image/png, image/webp 등)
            system_prompt: 시스템 프롬프트 (선택적)
            **kwargs: 추가 파라미터

        Returns:
            생성된 텍스트 응답

        Raises:
            NotImplementedError: 해당 Provider가 멀티모달을 지원하지 않는 경우
        """
        raise NotImplementedError(
            f"{self.__class__.__name__}은(는) 멀티모달 생성을 지원하지 않습니다. "
            "generate_text()를 사용하세요."
        )


class GoogleLLMClient(BaseLLMClient):
    """Google Gemini 클라이언트"""

    def __init__(self, config: dict[str, Any]):
        super().__init__(config)
        api_key = config.get("api_key")
        if api_key:
            genai.configure(api_key=api_key)
        self.generation_config = {
            "temperature": self.temperature,
            "max_output_tokens": self.max_tokens,
        }

    async def generate_text(
        self, prompt: str, system_prompt: str | None = None, **kwargs: Any
    ) -> str:
        """Gemini 텍스트 생성"""
        try:
            model = genai.GenerativeModel(
                model_name=self.model, system_instruction=system_prompt if system_prompt else None
            )

            # 동기 함수를 비동기로 실행
            response = await asyncio.to_thread(
                model.generate_content,
                prompt,
                generation_config=self.generation_config,  # type: ignore[arg-type]
            )

            return response.text  # type: ignore[no-any-return]
        except Exception as e:
            logger.error(
                "Google LLM 생성 실패",
                extra={
                    "error": str(e),
                    "error_type": type(e).__name__
                },
                exc_info=True
            )
            raise

    async def stream_text(
        self, prompt: str, system_prompt: str | None = None, **kwargs: Any
    ) -> AsyncGenerator[str, None]:
        """
        Gemini 스트리밍 텍스트 생성

        Google Gemini API의 stream=True 옵션을 사용하여
        응답을 청크 단위로 yield합니다.

        Args:
            prompt: 사용자 프롬프트
            system_prompt: 시스템 프롬프트 (선택적)
            **kwargs: 추가 파라미터

        Yields:
            str: 생성된 텍스트 청크
        """
        try:
            model = genai.GenerativeModel(
                model_name=self.model,
                system_instruction=system_prompt if system_prompt else None,
            )

            # stream=True로 스트리밍 응답 요청
            response = model.generate_content(
                prompt,
                generation_config=self.generation_config,  # type: ignore[arg-type]
                stream=True,
            )

            # 청크 단위로 yield (빈 텍스트는 건너뜀)
            for chunk in response:
                if chunk.text:
                    yield chunk.text

        except Exception as e:
            logger.error(
                "Google LLM 스트리밍 실패",
                extra={
                    "error": str(e),
                    "error_type": type(e).__name__
                },
                exc_info=True,
            )
            raise

    async def generate_multimodal(
        self,
        prompt: str,
        images: list[bytes] | None = None,
        image_urls: list[str] | None = None,
        mime_types: list[str] | None = None,
        system_prompt: str | None = None,
        **kwargs: Any,
    ) -> str:
        """
        Gemini 멀티모달 생성 (텍스트 + 이미지)

        최신 google-generativeai SDK 사용하여 이미지와 텍스트를 함께 처리

        Args:
            prompt: 사용자 프롬프트
            images: 이미지 바이트 데이터 리스트
            image_urls: 이미지 URL 리스트 (현재 미지원, 향후 확장)
            mime_types: 각 이미지의 MIME 타입
            system_prompt: 시스템 프롬프트

        Returns:
            생성된 텍스트 응답
        """
        try:
            # 모델 초기화 (시스템 프롬프트 포함)
            model = genai.GenerativeModel(
                model_name=self.model, system_instruction=system_prompt if system_prompt else None
            )

            # 콘텐츠 리스트 구성 (텍스트 + 이미지)
            contents: list[dict[str, Any] | str] = []

            # 이미지 데이터 추가 (바이트 형식)
            if images and mime_types:
                if len(images) != len(mime_types):
                    raise ValueError(
                        f"이미지 개수({len(images)})와 MIME 타입 개수({len(mime_types)})가 일치하지 않습니다"
                    )

                for image_data, mime_type in zip(images, mime_types, strict=False):
                    # Gemini API는 딕셔너리 형태로 이미지 데이터 전달
                    contents.append({"mime_type": mime_type, "data": image_data})
                    logger.debug(
                        "이미지 추가됨",
                        extra={
                            "mime_type": mime_type,
                            "size_bytes": len(image_data)
                        }
                    )

            # 텍스트 프롬프트 추가
            contents.append(prompt)

            logger.info(
                f"멀티모달 요청 시작: 이미지={len(images) if images else 0}개, "
                f"프롬프트 길이={len(prompt)}"
            )

            # 동기 함수를 비동기로 실행
            response = await asyncio.to_thread(
                model.generate_content,
                contents,
                generation_config=self.generation_config,  # type: ignore[arg-type]
            )

            logger.info("멀티모달 응답 수신 완료")
            return response.text  # type: ignore[no-any-return]

        except ValueError as e:
            logger.error(
                "입력 검증 실패",
                extra={
                    "error": str(e),
                    "error_type": type(e).__name__
                },
                exc_info=True
            )
            raise
        except Exception as e:
            logger.error(
                "Google 멀티모달 생성 실패",
                extra={
                    "error": str(e),
                    "error_type": type(e).__name__
                },
                exc_info=True
            )
            raise


class OpenAILLMClient(BaseLLMClient):
    """OpenAI GPT 클라이언트"""

    def __init__(self, config: dict[str, Any]):
        super().__init__(config)
        import httpx

        self.client = OpenAI(
            api_key=config.get("api_key"),
            timeout=self.timeout,
            max_retries=0,  # 재시도 없이 바로 폴백
            http_client=httpx.Client(
                timeout=httpx.Timeout(self.timeout, connect=10.0),
                limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
            ),
        )
        # GPT-5 전용 파라미터
        self.verbosity = config.get("verbosity", "medium")  # low, medium, high
        self.reasoning_effort = config.get(
            "reasoning_effort", "medium"
        )  # minimal, low, medium, high
        logger.info(
            f"OpenAI 클라이언트 생성 완료 (timeout={self.timeout}s, max_retries=0, "
            f"verbosity={self.verbosity}, reasoning_effort={self.reasoning_effort})"
        )

    async def generate_text(
        self, prompt: str, system_prompt: str | None = None, **kwargs: Any
    ) -> str:
        """OpenAI 텍스트 생성"""
        import time

        start_time = time.time()
        logger.info(
            "OpenAI API 요청 시작",
            extra={
                "model": self.model,
                "prompt_length": len(prompt)
            }
        )
        try:
            messages: list[dict[str, str]] = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})

            # Reasoning 모델 (o1, GPT-5)은 max_completion_tokens 사용
            # Reasoning 모델은 temperature 파라미터 지원 안 함
            # 일반 GPT 모델 (GPT-4 등)은 max_tokens 사용
            is_reasoning_model = self.model.startswith("o1") or self.model.startswith("gpt-5")

            api_params = {"model": self.model, "messages": messages, "timeout": self.timeout}

            # Reasoning 모델 (o1, GPT-5)은 max_completion_tokens 파라미터 사용, temperature 제외
            # GPT-5는 추가로 verbosity, reasoning_effort 파라미터 지원
            # 일반 GPT 모델은 max_tokens와 temperature 사용
            if is_reasoning_model:
                api_params["max_completion_tokens"] = self.max_tokens
                # GPT-5만 verbosity와 reasoning_effort 지원 (o1은 미지원)
                if self.model.startswith("gpt-5"):
                    api_params["verbosity"] = self.verbosity
                    api_params["reasoning_effort"] = self.reasoning_effort
                    logger.debug(
                        f"GPT-5 파라미터: verbosity={self.verbosity}, "
                        f"reasoning_effort={self.reasoning_effort}"
                    )
            else:
                api_params["max_tokens"] = self.max_tokens
                api_params["temperature"] = self.temperature

            response = await asyncio.to_thread(
                self.client.chat.completions.create, **api_params  # type: ignore[arg-type]
            )

            elapsed = time.time() - start_time
            logger.info(
                "OpenAI API 응답 성공",
                extra={
                    "elapsed_seconds": round(elapsed, 1),
                    "model": self.model
                }
            )

            return response.choices[0].message.content or ""
        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(
                "OpenAI LLM 생성 실패",
                extra={
                    "elapsed_seconds": round(elapsed, 1),
                    "error": str(e),
                    "error_type": type(e).__name__
                },
                exc_info=True
            )
            raise

    async def stream_text(
        self, prompt: str, system_prompt: str | None = None, **kwargs: Any
    ) -> AsyncGenerator[str, None]:
        """
        OpenAI 스트리밍 텍스트 생성

        stream=True 옵션을 사용하여 응답을 청크 단위로 yield합니다.

        Args:
            prompt: 사용자 프롬프트
            system_prompt: 시스템 프롬프트 (선택적)
            **kwargs: 추가 파라미터

        Yields:
            str: 생성된 텍스트 청크
        """
        try:
            messages: list[dict[str, str]] = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})

            # Reasoning 모델 분기 처리 (generate_text와 일관성 유지)
            # Reasoning 모델 (o1, GPT-5)은 max_completion_tokens 사용, temperature 미지원
            # 일반 GPT 모델은 max_tokens와 temperature 사용
            is_reasoning_model = self.model.startswith("o1") or self.model.startswith("gpt-5")

            api_params: dict[str, Any] = {
                "model": self.model,
                "messages": messages,
                "stream": True,
            }

            if is_reasoning_model:
                api_params["max_completion_tokens"] = self.max_tokens
            else:
                api_params["max_tokens"] = self.max_tokens
                api_params["temperature"] = self.temperature

            # stream=True로 스트리밍 응답 요청
            response = self.client.chat.completions.create(**api_params)  # type: ignore[arg-type]

            # 청크 단위로 yield (빈 콘텐츠는 건너뜀)
            for chunk in response:  # type: ignore[union-attr]
                if chunk.choices and chunk.choices[0].delta.content:  # type: ignore[union-attr]
                    yield chunk.choices[0].delta.content  # type: ignore[union-attr]

        except Exception as e:
            logger.error(
                "OpenAI LLM 스트리밍 실패",
                extra={"error": str(e), "error_type": type(e).__name__},
                exc_info=True,
            )
            raise


class AnthropicLLMClient(BaseLLMClient):
    """Anthropic Claude 클라이언트"""

    def __init__(self, config: dict[str, Any]):
        super().__init__(config)
        self.client = Anthropic(api_key=config.get("api_key"))

    async def generate_text(
        self, prompt: str, system_prompt: str | None = None, **kwargs: Any
    ) -> str:
        """Claude 텍스트 생성"""
        try:
            response = await asyncio.to_thread(
                self.client.messages.create,  # type: ignore[arg-type]
                model=self.model,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                system=system_prompt if system_prompt else "",
                messages=[{"role": "user", "content": prompt}],
            )

            # TextBlock만 text 속성을 가지므로 타입 체크
            content_block = response.content[0]
            if hasattr(content_block, "text"):
                return str(content_block.text)  # type: ignore[union-attr]
            return ""
        except Exception as e:
            logger.error(
                "Anthropic LLM 생성 실패",
                extra={
                    "error": str(e),
                    "error_type": type(e).__name__
                },
                exc_info=True
            )
            raise

    async def stream_text(
        self, prompt: str, system_prompt: str | None = None, **kwargs: Any
    ) -> AsyncGenerator[str, None]:
        """
        Anthropic 스트리밍 텍스트 생성

        messages.stream() API를 사용하여 응답을 청크 단위로 yield합니다.
        content_block_delta 이벤트만 처리하여 텍스트를 추출합니다.

        Args:
            prompt: 사용자 프롬프트
            system_prompt: 시스템 프롬프트 (선택적)
            **kwargs: 추가 파라미터

        Yields:
            str: 생성된 텍스트 청크
        """
        try:
            # Anthropic 스트리밍 API 사용 (with 문으로 리소스 관리)
            with self.client.messages.stream(
                model=self.model,
                max_tokens=self.max_tokens,
                temperature=self.temperature,  # generate_text와 일관성 유지
                system=system_prompt if system_prompt else "",
                messages=[{"role": "user", "content": prompt}],
            ) as stream:
                # content_block_delta 이벤트만 처리
                for event in stream:
                    if event.type == "content_block_delta":
                        yield event.delta.text  # type: ignore[union-attr]

        except Exception as e:
            logger.error(
                "Anthropic LLM 스트리밍 실패",
                extra={"error": str(e), "error_type": type(e).__name__},
                exc_info=True,
            )
            raise


class OpenRouterLLMClient(BaseLLMClient):
    """
    OpenRouter 통합 클라이언트

    OpenRouter는 300+ AI 모델을 단일 API로 제공하는 통합 게이트웨이입니다.
    OpenAI SDK와 100% 호환되며, base_url만 변경하여 사용합니다.

    지원 모델 예시:
    - openai/gpt-4o, openai/gpt-4o-mini
    - anthropic/claude-3.5-sonnet, anthropic/claude-3-opus
    - google/gemini-2.0-flash-exp, google/gemini-pro
    - meta-llama/llama-3.1-70b-instruct
    - mistralai/mistral-large

    참고: https://openrouter.ai/docs
    """

    # OpenRouter API 기본 URL
    OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

    def __init__(self, config: dict[str, Any]):
        super().__init__(config)
        import httpx

        # OpenRouter API 키 (환경변수 또는 config에서 가져옴)
        api_key = config.get("api_key") or os.getenv("OPENROUTER_API_KEY")
        if not api_key:
            raise ValueError(
                "OpenRouter API 키가 필요합니다. "
                "환경변수 OPENROUTER_API_KEY를 설정하거나 config에 api_key를 추가하세요."
            )

        # OpenAI SDK를 OpenRouter base_url로 초기화
        self.client = OpenAI(
            base_url=self.OPENROUTER_BASE_URL,
            api_key=api_key,
            timeout=self.timeout,
            max_retries=0,  # 재시도 없이 폴백 처리
            http_client=httpx.Client(
                timeout=httpx.Timeout(self.timeout, connect=10.0),
                limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
            ),
            # OpenRouter 권장 헤더 (선택적)
            default_headers={
                "HTTP-Referer": config.get("site_url", ""),
                "X-Title": config.get("app_name", "RAG-Chatbot"),
            },
        )

        logger.info(
            "OpenRouter 클라이언트 생성 완료",
            extra={
                "model": self.model,
                "timeout_seconds": self.timeout
            }
        )

    async def generate_text(
        self, prompt: str, system_prompt: str | None = None, **kwargs: Any
    ) -> str:
        """
        OpenRouter를 통한 텍스트 생성

        OpenAI SDK 호환 API를 사용하므로 동일한 인터페이스 제공
        """
        import time

        start_time = time.time()
        logger.info(
            "OpenRouter API 요청 시작",
            extra={
                "model": self.model,
                "prompt_length": len(prompt)
            }
        )

        try:
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})

            # OpenRouter는 OpenAI와 동일한 파라미터 사용
            # Reasoning 모델 (o1, gpt-5 등)은 별도 처리 필요
            is_reasoning_model = "o1" in self.model.lower() or "gpt-5" in self.model.lower()

            api_params = {
                "model": self.model,  # OpenRouter 형식: openai/gpt-4o, anthropic/claude-3.5-sonnet
                "messages": messages,
                "timeout": self.timeout,
            }

            # Reasoning 모델은 max_completion_tokens 사용, 일반 모델은 max_tokens 사용
            if is_reasoning_model:
                api_params["max_completion_tokens"] = self.max_tokens
            else:
                api_params["max_tokens"] = self.max_tokens
                api_params["temperature"] = self.temperature

            response = await asyncio.to_thread(
                self.client.chat.completions.create, **api_params  # type: ignore[arg-type]
            )

            elapsed = time.time() - start_time
            logger.info(
                "OpenRouter API 응답 성공",
                extra={
                    "elapsed_seconds": round(elapsed, 1),
                    "model": self.model
                }
            )

            return response.choices[0].message.content or ""

        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(
                "OpenRouter LLM 생성 실패",
                extra={
                    "elapsed_seconds": round(elapsed, 1),
                    "error": str(e),
                    "error_type": type(e).__name__
                },
                exc_info=True
            )
            raise

    async def stream_text(
        self, prompt: str, system_prompt: str | None = None, **kwargs: Any
    ) -> AsyncGenerator[str, None]:
        """
        OpenRouter 스트리밍 텍스트 생성 (향후 구현 예정)

        현재는 NotImplementedError를 발생시킵니다.
        """
        raise NotImplementedError(
            "OpenRouterLLMClient.stream_text()는 아직 구현되지 않았습니다. "
            "GoogleLLMClient를 사용하거나 향후 업데이트를 기다려주세요."
        )
        yield  # AsyncGenerator 타입 힌트를 위해 필요


class LLMClientFactory:
    """
    LLM 클라이언트 팩토리

    Registry Pattern을 사용하여 Provider 추가 시 코드 수정 최소화
    """

    # Provider 클래스 매핑 (Registry)
    _PROVIDER_REGISTRY: dict[str, type[BaseLLMClient]] = {
        "google": GoogleLLMClient,
        "openai": OpenAILLMClient,
        "anthropic": AnthropicLLMClient,
        "openrouter": OpenRouterLLMClient,  # OpenRouter 통합 게이트웨이
    }

    # 환경 변수 자동 매핑
    _ENV_VAR_MAPPING: dict[str, str] = {
        "google": "GOOGLE_API_KEY",
        "openai": "OPENAI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "openrouter": "OPENROUTER_API_KEY",  # OpenRouter API 키
    }

    def __init__(self, config: dict[str, Any]):
        """
        Args:
            config: LLM 설정 (config['llm'] 섹션)
        """
        self.config = config
        self._clients: dict[str, BaseLLMClient] = {}
        self._initialize_clients()

    def _initialize_clients(self) -> None:
        """
        모든 제공자의 클라이언트 동적 초기화

        개선사항 (v3.2.0):
        - Registry Pattern으로 하드코딩 제거
        - 환경 변수 자동 매핑
        - 새 Provider 추가 시 _PROVIDER_REGISTRY만 수정
        """
        llm_config = self.config.get("llm", {})

        # Registry를 순회하며 동적 초기화
        for provider_name, client_class in self._PROVIDER_REGISTRY.items():
            # YAML 설정에 Provider가 있는지 확인
            if provider_name not in llm_config:
                continue

            try:
                provider_config = llm_config[provider_name].copy()

                # 환경 변수 자동 주입 (api_key가 없으면)
                if "api_key" not in provider_config:
                    env_var = self._ENV_VAR_MAPPING.get(provider_name)
                    if env_var:
                        api_key = os.getenv(env_var)
                        if api_key:
                            provider_config["api_key"] = api_key

                # 클라이언트 인스턴스 생성
                self._clients[provider_name] = client_class(provider_config)
                logger.info(
                    "LLM 클라이언트 초기화 완료",
                    extra={"provider": provider_name}
                )

            except Exception as e:
                logger.warning(
                    "LLM 클라이언트 초기화 실패",
                    extra={
                        "provider": provider_name,
                        "error": str(e),
                        "error_type": type(e).__name__
                    }
                )

        # CRITICAL: 최소 1개 LLM 제공자는 필수로 초기화되어야 함
        if not self._clients:
            error_msg = (
                "❌ CRITICAL: 모든 LLM 제공자 초기화 실패!\n"
                "최소 1개 LLM 제공자(Google/OpenAI/Anthropic)가 필요합니다.\n"
                f"설정된 제공자: {list(llm_config.keys())}\n"
                "API 키를 확인해주세요."
            )
            logger.error(error_msg)
            raise RuntimeError(error_msg)

        logger.info(
            "LLM 초기화 완료",
            extra={
                "success_count": len(self._clients),
                "providers": list(self._clients.keys())
            }
        )

    def get_client(
        self, provider: Literal["google", "openai", "anthropic", "openrouter"] | None = None
    ) -> BaseLLMClient:
        """
        LLM 클라이언트 가져오기

        Args:
            provider: 제공자 (None이면 default_provider 사용)

        Returns:
            LLM 클라이언트

        Raises:
            ValueError: 클라이언트가 초기화되지 않음
        """
        if provider is None:
            provider = self.config.get("llm", {}).get("default_provider", "google")

        if provider not in self._clients:
            raise ValueError(f"LLM 클라이언트가 초기화되지 않음: {provider}")

        return self._clients[provider]

    async def generate_with_fallback(
        self,
        prompt: str,
        system_prompt: str | None = None,
        preferred_provider: str | None = None,
        **kwargs: Any,
    ) -> tuple[str, str]:
        """
        폴백 지원 텍스트 생성

        Args:
            prompt: 사용자 프롬프트
            system_prompt: 시스템 프롬프트 (선택적)
            preferred_provider: 선호 제공자

        Returns:
            (생성된 텍스트, 사용된 제공자)
        """
        llm_config = self.config.get("llm", {})
        fallback_enabled = llm_config.get("auto_fallback", True)
        fallback_order = llm_config.get("fallback_order", ["google", "openai", "anthropic"])

        # 선호 제공자를 첫 번째로
        if preferred_provider:
            providers_to_try = [preferred_provider] + [
                p for p in fallback_order if p != preferred_provider
            ]
        else:
            providers_to_try = fallback_order

        # 폴백 비활성화 시 첫 번째만 시도
        if not fallback_enabled:
            providers_to_try = providers_to_try[:1]

        last_error = None
        for provider in providers_to_try:
            if provider not in self._clients:
                continue

            try:
                client = self._clients[provider]
                text = await client.generate_text(
                    prompt=prompt, system_prompt=system_prompt, **kwargs
                )
                logger.info(
                    "LLM 생성 성공",
                    extra={"provider": provider}
                )
                return text, provider
            except Exception as e:
                logger.warning(
                    "LLM 실패, 폴백 진행",
                    extra={
                        "provider": provider,
                        "error": str(e),
                        "error_type": type(e).__name__
                    }
                )
                last_error = e
                continue

        raise RuntimeError(f"모든 LLM 제공자 실패. 마지막 에러: {last_error}")


# 전역 팩토리 인스턴스 (main.py에서 초기화)
_global_factory: LLMClientFactory | None = None


def initialize_llm_factory(config: dict[str, Any]) -> None:
    """전역 LLM 팩토리 초기화"""
    global _global_factory
    _global_factory = LLMClientFactory(config)
    logger.info("전역 LLM 팩토리 초기화 완료")


def get_llm_factory() -> LLMClientFactory:
    """전역 LLM 팩토리 가져오기"""
    if _global_factory is None:
        raise RuntimeError("LLM 팩토리가 초기화되지 않음. initialize_llm_factory() 호출 필요")
    return _global_factory
