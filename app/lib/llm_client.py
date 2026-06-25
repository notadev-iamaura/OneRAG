"""
LLM Client Factory - 통합 LLM 클라이언트 관리
모든 LLM 호출을 중앙에서 관리하여 중복 제거 및 일관성 확보
"""

import asyncio
import os
import threading
from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator
from typing import Any, Literal

import google.generativeai as genai
from anthropic import Anthropic
from openai import OpenAI

from .langfuse_client import langfuse_context, observe
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

    def _resolve_params(self, **kwargs: Any) -> tuple[str, float, int]:
        """kwargs에서 런타임 오버라이드 파라미터 추출 (OpenAI 호환 API 지원)"""
        model = kwargs.get("model") or self.model
        temp = kwargs.get("temperature")
        temperature = float(temp) if temp is not None else self.temperature
        max_tok = kwargs.get("max_tokens")
        max_tokens = int(max_tok) if max_tok is not None else self.max_tokens
        return model, temperature, max_tokens

    # ------------------------------------------------------------------
    # Langfuse generation 계측 공통 헬퍼
    # ------------------------------------------------------------------
    # 모든 provider의 generate_text/stream_text가 @observe(as_type="generation")로
    # 감싸지며, LLM 응답에서 추출한 model/usage(토큰)를 아래 헬퍼로 현재 generation
    # observation에 기록한다. Langfuse는 등록된 모델 가격표로 호출 단위 비용을 자동
    # 계산하므로, llm_client를 경유하는 모든 호출(/v1·Agent·쿼리확장·라우터 등)의
    # 토큰/비용이 일괄 추적된다.
    #
    # 의도적으로 input/output 텍스트는 기록하지 않는다(capture_input/output=False).
    # llm_client는 저수준이라 PII 마스킹 책임이 없으므로, 텍스트 관측은 상위
    # GenerationModule(마스킹 후)에 맡기고 여기서는 비용 메트릭만 남긴다.
    def _emit_generation(
        self,
        *,
        model: str,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        total_tokens: int = 0,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> None:
        """현재 Langfuse generation observation에 model/usage/파라미터를 기록한다.

        LANGFUSE 비활성(ENVIRONMENT=test 등) 시 langfuse_context는 더미 no-op이며,
        기록 실패가 LLM 호출을 깨뜨리지 않도록 예외를 흡수한다(graceful degradation).
        """
        try:
            usage: dict[str, Any] | None = None
            if total_tokens or prompt_tokens or completion_tokens:
                usage = {
                    "input": prompt_tokens,
                    "output": completion_tokens,
                    "total": total_tokens or (prompt_tokens + completion_tokens),
                    "unit": "TOKENS",
                }
            obs_kwargs: dict[str, Any] = {"model": model}
            if usage is not None:
                obs_kwargs["usage"] = usage
            params: dict[str, Any] = {}
            if temperature is not None:
                params["temperature"] = temperature
            if max_tokens is not None:
                params["max_tokens"] = max_tokens
            if params:
                obs_kwargs["model_parameters"] = params
            langfuse_context.update_current_observation(**obs_kwargs)
        except Exception as e:  # noqa: BLE001 - 관측 실패는 비치명적(graceful degradation)
            logger.debug(f"Langfuse generation 기록 건너뜀: {e}")

    @staticmethod
    def _usage_openai(response: Any) -> tuple[int, int, int]:
        """OpenAI 호환 응답에서 (prompt, completion, total) 토큰을 추출한다."""
        u = getattr(response, "usage", None)
        if not u:
            return (0, 0, 0)
        return (
            getattr(u, "prompt_tokens", 0) or 0,
            getattr(u, "completion_tokens", 0) or 0,
            getattr(u, "total_tokens", 0) or 0,
        )

    @staticmethod
    def _usage_anthropic(response: Any) -> tuple[int, int, int]:
        """Anthropic 응답에서 (prompt, completion, total) 토큰을 추출한다."""
        u = getattr(response, "usage", None)
        if not u:
            return (0, 0, 0)
        inp = getattr(u, "input_tokens", 0) or 0
        out = getattr(u, "output_tokens", 0) or 0
        return (inp, out, inp + out)

    @staticmethod
    def _usage_google(response: Any) -> tuple[int, int, int]:
        """Google Gemini 응답에서 (prompt, completion, total) 토큰을 추출한다."""
        u = getattr(response, "usage_metadata", None)
        if not u:
            return (0, 0, 0)
        return (
            getattr(u, "prompt_token_count", 0) or 0,
            getattr(u, "candidates_token_count", 0) or 0,
            getattr(u, "total_token_count", 0) or 0,
        )

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

    @observe(
        as_type="generation",
        name="LLM Generation (Google)",
        capture_input=False,
        capture_output=False,
    )
    async def generate_text(
        self, prompt: str, system_prompt: str | None = None, **kwargs: Any
    ) -> str:
        """Gemini 텍스트 생성"""
        try:
            model_name, temperature, max_tokens = self._resolve_params(**kwargs)
            model = genai.GenerativeModel(
                model_name=model_name, system_instruction=system_prompt if system_prompt else None
            )
            gen_config = {
                "temperature": temperature,
                "max_output_tokens": max_tokens,
            }

            # 동기 함수를 비동기로 실행
            response = await asyncio.to_thread(
                model.generate_content,
                prompt,
                generation_config=gen_config,  # type: ignore[arg-type]
            )

            p, c, t = self._usage_google(response)
            self._emit_generation(
                model=model_name,
                prompt_tokens=p,
                completion_tokens=c,
                total_tokens=t,
                temperature=temperature,
                max_tokens=max_tokens,
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

    @observe(
        as_type="generation",
        name="LLM Generation (Google, streaming)",
        capture_input=False,
        capture_output=False,
    )
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
            model_name, temperature, max_tokens = self._resolve_params(**kwargs)
            model = genai.GenerativeModel(
                model_name=model_name,
                system_instruction=system_prompt if system_prompt else None,
            )
            gen_config = {
                "temperature": temperature,
                "max_output_tokens": max_tokens,
            }

            # stream=True로 스트리밍 응답 요청
            response = model.generate_content(
                prompt,
                generation_config=gen_config,  # type: ignore[arg-type]
                stream=True,
            )

            # 청크 단위로 yield (빈 텍스트는 건너뜀). usage_metadata는 청크/응답에 누적된다.
            p = c = t = 0
            for chunk in response:
                cu = getattr(chunk, "usage_metadata", None)
                if cu is not None:
                    p = getattr(cu, "prompt_token_count", 0) or p
                    c = getattr(cu, "candidates_token_count", 0) or c
                    t = getattr(cu, "total_token_count", 0) or t
                if chunk.text:
                    yield chunk.text

            # 스트림 종료 후 응답 누적 usage도 시도(있으면 우선)
            ru = getattr(response, "usage_metadata", None)
            if ru is not None:
                p = getattr(ru, "prompt_token_count", 0) or p
                c = getattr(ru, "candidates_token_count", 0) or c
                t = getattr(ru, "total_token_count", 0) or t
            self._emit_generation(
                model=model_name,
                prompt_tokens=p,
                completion_tokens=c,
                total_tokens=t,
                temperature=temperature,
                max_tokens=max_tokens,
            )

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

    @observe(
        as_type="generation",
        name="LLM Generation (Google, multimodal)",
        capture_input=False,
        capture_output=False,
    )
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
            p, c, t = self._usage_google(response)
            self._emit_generation(
                model=self.model,
                prompt_tokens=p,
                completion_tokens=c,
                total_tokens=t,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            )
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

    @observe(
        as_type="generation",
        name="LLM Generation (OpenAI)",
        capture_input=False,
        capture_output=False,
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
            model, temperature, max_tokens = self._resolve_params(**kwargs)
            messages: list[dict[str, str]] = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})

            # Reasoning 모델 (o1, GPT-5)은 max_completion_tokens 사용
            # Reasoning 모델은 temperature 파라미터 지원 안 함
            # 일반 GPT 모델 (GPT-4 등)은 max_tokens 사용
            is_reasoning_model = model.startswith("o1") or model.startswith("gpt-5")

            api_params = {"model": model, "messages": messages, "timeout": self.timeout}

            # Reasoning 모델 (o1, GPT-5)은 max_completion_tokens 파라미터 사용, temperature 제외
            # GPT-5는 추가로 verbosity, reasoning_effort 파라미터 지원
            # 일반 GPT 모델은 max_tokens와 temperature 사용
            if is_reasoning_model:
                api_params["max_completion_tokens"] = max_tokens
                # GPT-5만 verbosity와 reasoning_effort 지원 (o1은 미지원)
                if model.startswith("gpt-5"):
                    api_params["verbosity"] = self.verbosity
                    api_params["reasoning_effort"] = self.reasoning_effort
                    logger.debug(
                        f"GPT-5 파라미터: verbosity={self.verbosity}, "
                        f"reasoning_effort={self.reasoning_effort}"
                    )
            else:
                api_params["max_tokens"] = max_tokens
                api_params["temperature"] = temperature

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

            p, c, t = self._usage_openai(response)
            self._emit_generation(
                model=model,
                prompt_tokens=p,
                completion_tokens=c,
                total_tokens=t,
                temperature=temperature,
                max_tokens=max_tokens,
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

    @observe(
        as_type="generation",
        name="LLM Generation (OpenAI, streaming)",
        capture_input=False,
        capture_output=False,
    )
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
            model, temperature, max_tokens = self._resolve_params(**kwargs)
            messages: list[dict[str, str]] = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})

            # Reasoning 모델 분기 처리 (generate_text와 일관성 유지)
            is_reasoning_model = model.startswith("o1") or model.startswith("gpt-5")

            api_params: dict[str, Any] = {
                "model": model,
                "messages": messages,
                "stream": True,
                # 스트리밍에서도 정확한 토큰 usage를 마지막 청크로 받는다(Langfuse 비용)
                "stream_options": {"include_usage": True},
            }

            if is_reasoning_model:
                api_params["max_completion_tokens"] = max_tokens
            else:
                api_params["max_tokens"] = max_tokens
                api_params["temperature"] = temperature

            # stream=True로 스트리밍 응답 요청
            response = self.client.chat.completions.create(**api_params)  # type: ignore[arg-type]

            # 청크 단위로 yield (빈 콘텐츠는 건너뜀). usage 청크(choices 빔)에서 토큰 추출.
            p = c = t = 0
            for chunk in response:  # type: ignore[union-attr]
                cu = getattr(chunk, "usage", None)
                if cu is not None:
                    p = getattr(cu, "prompt_tokens", 0) or 0
                    c = getattr(cu, "completion_tokens", 0) or 0
                    t = getattr(cu, "total_tokens", 0) or 0
                if chunk.choices and chunk.choices[0].delta.content:  # type: ignore[union-attr]
                    yield chunk.choices[0].delta.content  # type: ignore[union-attr]
            self._emit_generation(
                model=model,
                prompt_tokens=p,
                completion_tokens=c,
                total_tokens=t,
                temperature=temperature,
                max_tokens=max_tokens,
            )

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

    @observe(
        as_type="generation",
        name="LLM Generation (Anthropic)",
        capture_input=False,
        capture_output=False,
    )
    async def generate_text(
        self, prompt: str, system_prompt: str | None = None, **kwargs: Any
    ) -> str:
        """Claude 텍스트 생성"""
        try:
            model, temperature, max_tokens = self._resolve_params(**kwargs)
            response = await asyncio.to_thread(
                self.client.messages.create,  # type: ignore[arg-type]
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                system=system_prompt if system_prompt else "",
                messages=[{"role": "user", "content": prompt}],
            )

            p, c, t = self._usage_anthropic(response)
            self._emit_generation(
                model=model,
                prompt_tokens=p,
                completion_tokens=c,
                total_tokens=t,
                temperature=temperature,
                max_tokens=max_tokens,
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

    @observe(
        as_type="generation",
        name="LLM Generation (Anthropic, streaming)",
        capture_input=False,
        capture_output=False,
    )
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
            model, temperature, max_tokens = self._resolve_params(**kwargs)
            # Anthropic 스트리밍 API 사용 (with 문으로 리소스 관리)
            with self.client.messages.stream(
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,  # generate_text와 일관성 유지
                system=system_prompt if system_prompt else "",
                messages=[{"role": "user", "content": prompt}],
            ) as stream:
                # content_block_delta 이벤트만 처리
                for event in stream:
                    if event.type == "content_block_delta":
                        yield event.delta.text  # type: ignore[union-attr]

                # 스트림 소비 완료 후 최종 메시지에서 토큰 usage 추출(Langfuse 비용)
                try:
                    final = stream.get_final_message()
                    fu = getattr(final, "usage", None)
                    if fu is not None:
                        inp = getattr(fu, "input_tokens", 0) or 0
                        out = getattr(fu, "output_tokens", 0) or 0
                        self._emit_generation(
                            model=model,
                            prompt_tokens=inp,
                            completion_tokens=out,
                            total_tokens=inp + out,
                            temperature=temperature,
                            max_tokens=max_tokens,
                        )
                except Exception as ue:  # noqa: BLE001 - usage 추출 실패는 비치명적
                    logger.debug(f"Anthropic 스트리밍 usage 추출 건너뜀: {ue}")

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

    @observe(
        as_type="generation",
        name="LLM Generation (OpenRouter)",
        capture_input=False,
        capture_output=False,
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
            model, temperature, max_tokens = self._resolve_params(**kwargs)
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})

            # OpenRouter는 OpenAI와 동일한 파라미터 사용
            # Reasoning 모델 (o1, gpt-5 등)은 별도 처리 필요
            is_reasoning_model = "o1" in model.lower() or "gpt-5" in model.lower()

            api_params = {
                "model": model,  # OpenRouter 형식: openai/gpt-4o, anthropic/claude-3.5-sonnet
                "messages": messages,
                "timeout": self.timeout,
            }

            # Reasoning 모델은 max_completion_tokens 사용, 일반 모델은 max_tokens 사용
            if is_reasoning_model:
                api_params["max_completion_tokens"] = max_tokens
            else:
                api_params["max_tokens"] = max_tokens
                api_params["temperature"] = temperature

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

            p, c, t = self._usage_openai(response)
            self._emit_generation(
                model=model,
                prompt_tokens=p,
                completion_tokens=c,
                total_tokens=t,
                temperature=temperature,
                max_tokens=max_tokens,
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

    @observe(
        as_type="generation",
        name="LLM Generation (OpenRouter, streaming)",
        capture_input=False,
        capture_output=False,
    )
    async def stream_text(
        self, prompt: str, system_prompt: str | None = None, **kwargs: Any
    ) -> AsyncGenerator[str, None]:
        """
        OpenRouter 스트리밍 텍스트 생성

        OpenAI SDK 호환 API의 stream=True 옵션으로 청크 단위 응답을 yield합니다.

        Args:
            prompt: 사용자 프롬프트
            system_prompt: 시스템 프롬프트 (선택적)
            **kwargs: 추가 파라미터 (model, temperature, max_tokens 오버라이드)

        Yields:
            str: 생성된 텍스트 청크
        """
        try:
            model, temperature, max_tokens = self._resolve_params(**kwargs)
            messages: list[dict[str, str]] = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})

            # Reasoning 모델 분기 (generate_text와 동일 로직)
            is_reasoning_model = "o1" in model.lower() or "gpt-5" in model.lower()

            api_params: dict[str, Any] = {
                "model": model,
                "messages": messages,
                "stream": True,
                "timeout": self.timeout,
                # 스트리밍에서도 정확한 토큰 usage를 마지막 청크로 받는다(Langfuse 비용)
                "stream_options": {"include_usage": True},
            }

            if is_reasoning_model:
                api_params["max_completion_tokens"] = max_tokens
            else:
                api_params["max_tokens"] = max_tokens
                api_params["temperature"] = temperature

            # OpenAI SDK의 스트리밍 응답 (OpenRouter도 동일 인터페이스)
            response = self.client.chat.completions.create(**api_params)  # type: ignore[arg-type]

            # 청크 단위로 yield (빈 콘텐츠는 건너뜀). usage 청크(choices 빔)에서 토큰 추출.
            p = c = t = 0
            for chunk in response:  # type: ignore[union-attr]
                cu = getattr(chunk, "usage", None)
                if cu is not None:
                    p = getattr(cu, "prompt_tokens", 0) or 0
                    c = getattr(cu, "completion_tokens", 0) or 0
                    t = getattr(cu, "total_tokens", 0) or 0
                if chunk.choices and chunk.choices[0].delta.content:  # type: ignore[union-attr]
                    yield chunk.choices[0].delta.content  # type: ignore[union-attr]
            self._emit_generation(
                model=model,
                prompt_tokens=p,
                completion_tokens=c,
                total_tokens=t,
                temperature=temperature,
                max_tokens=max_tokens,
            )

        except Exception as e:
            logger.error(
                "OpenRouter LLM 스트리밍 실패",
                extra={"error": str(e), "error_type": type(e).__name__},
                exc_info=True,
            )
            raise


class OllamaLLMClient(BaseLLMClient):
    """
    Ollama 로컬 LLM 클라이언트

    Ollama는 로컬에서 LLM을 실행하는 오픈소스 도구입니다.
    OpenAI 호환 API를 제공하므로 OpenAI SDK로 호출할 수 있습니다.
    API 키 없이 완전한 "에어갭(Air-Gapped)" 모드를 지원합니다.

    기본 설정:
    - base_url: http://localhost:11434/v1
    - api_key: "not-needed" (Ollama는 인증 불필요)
    - 기본 모델: llama3.2 (Ollama에서 가장 많이 사용)

    사용법:
        # Ollama 설치 후 모델 다운로드
        ollama pull llama3.2

        # config 설정
        config = {"model": "llama3.2", "base_url": "http://localhost:11434"}
        client = OllamaLLMClient(config)

    참고: https://ollama.com/
    """

    # Ollama API 기본 설정
    DEFAULT_BASE_URL = "http://localhost:11434"
    OPENAI_COMPAT_PATH = "/v1"

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self.base_url = config.get("base_url", self.DEFAULT_BASE_URL)
        self.model = config.get("model", "llama3.2")

        # OpenAI 호환 클라이언트 초기화 (지연 로딩)
        self._client: OpenAI | None = None

        logger.info(
            "Ollama 클라이언트 생성 완료",
            extra={
                "base_url": self.base_url,
                "model": self.model,
            },
        )

    def _get_client(self) -> OpenAI:
        """OpenAI 호환 클라이언트 지연 초기화"""
        if self._client is None:
            self._client = OpenAI(
                base_url=f"{self.base_url}{self.OPENAI_COMPAT_PATH}",
                api_key="not-needed",  # Ollama는 API 키 불필요
                timeout=self.timeout,
                max_retries=0,
            )
        return self._client

    @observe(
        as_type="generation",
        name="LLM Generation (Ollama)",
        capture_input=False,
        capture_output=False,
    )
    async def generate_text(
        self, prompt: str, system_prompt: str | None = None, **kwargs: Any
    ) -> str:
        """
        Ollama 텍스트 생성 (OpenAI 호환 API 사용)

        Args:
            prompt: 사용자 프롬프트
            system_prompt: 시스템 프롬프트 (선택적)

        Returns:
            생성된 텍스트
        """
        try:
            model, temperature, max_tokens = self._resolve_params(**kwargs)
            client = self._get_client()
            messages: list[dict[str, str]] = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})

            create_fn = client.chat.completions.create
            response = await asyncio.to_thread(
                create_fn,  # type: ignore[arg-type]
                model=model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
            )

            p, c, t = self._usage_openai(response)
            self._emit_generation(
                model=model,
                prompt_tokens=p,
                completion_tokens=c,
                total_tokens=t,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            return response.choices[0].message.content or ""
        except Exception as e:
            logger.error(
                "Ollama LLM 생성 실패",
                extra={
                    "error": str(e),
                    "error_type": type(e).__name__,
                    "base_url": self.base_url,
                    "model": self.model,
                },
                exc_info=True,
            )
            raise

    @observe(
        as_type="generation",
        name="LLM Generation (Ollama, streaming)",
        capture_input=False,
        capture_output=False,
    )
    async def stream_text(
        self, prompt: str, system_prompt: str | None = None, **kwargs: Any
    ) -> AsyncGenerator[str, None]:
        """
        Ollama 스트리밍 텍스트 생성

        Args:
            prompt: 사용자 프롬프트
            system_prompt: 시스템 프롬프트 (선택적)

        Yields:
            str: 생성된 텍스트 청크
        """
        try:
            model, temperature, max_tokens = self._resolve_params(**kwargs)
            client = self._get_client()
            messages: list[dict[str, str]] = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})

            response = client.chat.completions.create(
                model=model,
                messages=messages,  # type: ignore[arg-type]
                max_tokens=max_tokens,
                temperature=temperature,
                stream=True,
                # 스트리밍에서도 정확한 토큰 usage를 마지막 청크로 받는다(Langfuse 비용)
                stream_options={"include_usage": True},
            )

            p = c = t = 0
            for chunk in response:  # type: ignore[union-attr]
                cu = getattr(chunk, "usage", None)
                if cu is not None:
                    p = getattr(cu, "prompt_tokens", 0) or 0
                    c = getattr(cu, "completion_tokens", 0) or 0
                    t = getattr(cu, "total_tokens", 0) or 0
                if chunk.choices and chunk.choices[0].delta.content:  # type: ignore[union-attr]
                    yield chunk.choices[0].delta.content  # type: ignore[union-attr]
            self._emit_generation(
                model=model,
                prompt_tokens=p,
                completion_tokens=c,
                total_tokens=t,
                temperature=temperature,
                max_tokens=max_tokens,
            )

        except Exception as e:
            logger.error(
                "Ollama LLM 스트리밍 실패",
                extra={"error": str(e), "error_type": type(e).__name__},
                exc_info=True,
            )
            raise

    async def health_check(self) -> bool:
        """
        Ollama 서버 가용성 확인

        /api/tags 엔드포인트로 서버 상태를 확인합니다.

        Returns:
            서버가 정상이면 True
        """
        import httpx

        try:
            async with httpx.AsyncClient(timeout=5) as client:
                response = await client.get(f"{self.base_url}/api/tags")
                return bool(response.status_code == 200)
        except Exception:
            return False

    async def list_models(self) -> list[str]:
        """
        설치된 Ollama 모델 목록 반환

        Returns:
            모델 이름 리스트
        """
        import httpx

        try:
            async with httpx.AsyncClient(timeout=5) as client:
                response = await client.get(f"{self.base_url}/api/tags")
                if response.status_code == 200:
                    data = response.json()
                    return [m["name"] for m in data.get("models", [])]
        except Exception as e:
            logger.warning(
                "Ollama 모델 목록 조회 실패",
                extra={"error": str(e)},
            )
        return []


class VertexLLMClient(BaseLLMClient):
    """Vertex AI Gemini 클라이언트 (OpenAI 호환 endpoint + ADC 인증, 선택적 provider).

    GOOGLE_API_KEY 없이 Application Default Credentials(ADC, 서비스 계정/워크로드 ID)로
    인증한다. GCP(Cloud Run/GKE) 운영처럼 키 배포 없이 동작해야 하는 환경에서, 내부
    보조 LLM 경로(쿼리 재작성/확장 등)에 Vertex 인증을 llm_factory로 제공한다.

    의존성: google-auth(ADC 토큰 발급)는 코어 의존성이 아닌 선택적 extra(`vertex`)다.
    미설치 환경에서도 모듈 import는 성공하며, 인증 시점에 친절한 설치 안내 에러를 던진다.

    개선점: _refresh_token을 threading.Lock으로 직렬화해, 멀티스레드
    동시 갱신 시 토큰이 순간 None이 되는 race를 차단한다(임베딩 provider와 일관).
    """

    _BASE_URL_TEMPLATE = (
        "https://aiplatform.googleapis.com/v1/projects/{project_id}"
        "/locations/{location}/endpoints/openapi"
    )
    _AUTH_SCOPES = ["https://www.googleapis.com/auth/cloud-platform"]
    _DEFAULT_LOCATION = "us-central1"
    _DEFAULT_MODEL = "google/gemini-2.5-flash"
    # google-auth 미설치 시 사용자에게 보여줄 설치 안내 메시지.
    _INSTALL_HINT = (
        "Vertex AI LLM을 사용하려면 google-auth가 필요합니다. "
        "설치: uv sync --extra vertex"
    )

    def __init__(self, config: dict[str, Any]):
        """ADC 기반 Vertex AI OpenAI 호환 클라이언트를 초기화한다.

        Args:
            config: llm.vertex 섹션 설정(project_id/location/default_model 등).

        Raises:
            ValueError: project_id를 설정/환경변수에서 해석할 수 없는 경우.
            RuntimeError: google-auth 미설치(설치 안내 포함).
        """
        super().__init__(config)
        import httpx

        self._credentials: Any = None
        # 동시 토큰 갱신 race 차단용 lock(임베딩 provider 패턴과 일관).
        self._token_lock = threading.Lock()
        self.model = self._normalize_model(
            self.model or config.get("default_model") or self._DEFAULT_MODEL
        )
        project_id = self._resolve_project_id(config)
        location = self._resolve_location(config)
        base_url = config.get("base_url") or self._BASE_URL_TEMPLATE.format(
            project_id=project_id, location=location
        )
        self.client = OpenAI(
            base_url=base_url,
            api_key=self._refresh_token(),
            timeout=self.timeout,
            max_retries=0,  # 재시도 없이 상위 fallback에 위임
            http_client=httpx.Client(
                timeout=httpx.Timeout(self.timeout, connect=10.0),
                limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
            ),
        )
        logger.info(
            "Vertex AI 클라이언트 생성 완료",
            extra={"model": self.model, "location": location},
        )

    @staticmethod
    def _resolve_project_id(config: dict[str, Any]) -> str:
        """project_id를 설정 → Vertex/Google Cloud 표준 환경변수 순으로 해석한다."""
        project_id = (
            config.get("project_id")
            or os.getenv("VERTEX_AI_PROJECT_ID")
            or os.getenv("GOOGLE_CLOUD_PROJECT")
            or os.getenv("GCLOUD_PROJECT")
        )
        if not project_id:
            raise ValueError(
                "Vertex AI 프로젝트 ID가 설정되지 않았습니다. "
                "llm.vertex.project_id 또는 VERTEX_AI_PROJECT_ID/GOOGLE_CLOUD_PROJECT를 "
                "설정하세요."
            )
        return str(project_id)

    @classmethod
    def _resolve_location(cls, config: dict[str, Any]) -> str:
        """location을 환경변수/설정 폴백 순으로 해석한다."""
        return str(
            os.getenv("VERTEX_AI_GENERATION_LOCATION")
            or config.get("location")
            or os.getenv("VERTEX_AI_LOCATION")
            or os.getenv("GOOGLE_CLOUD_LOCATION")
            or cls._DEFAULT_LOCATION
        )

    def _refresh_token(self) -> str:
        """ADC 토큰을 발급/갱신한다(만료 시 자동 refresh, lock으로 직렬화).

        google-auth가 선택적 의존성이므로 지연 import + 가드로 처리한다.

        Returns:
            유효한 OAuth2 액세스 토큰 문자열.

        Raises:
            RuntimeError: google-auth 미설치(설치 안내 포함).
            ValueError: 토큰을 가져오지 못한 경우.
        """
        try:
            from google.auth import default as google_auth_default
            from google.auth.transport.requests import Request
        except ImportError as error:  # google-auth 미설치(vertex extra 없음)
            raise RuntimeError(self._INSTALL_HINT) from error

        # 여러 스레드가 동시 호출해도 자격증명 공유/갱신이 안전하도록 직렬화한다.
        with self._token_lock:
            if self._credentials is None:
                self._credentials, _ = google_auth_default(scopes=self._AUTH_SCOPES)
            if not self._credentials.valid:
                self._credentials.refresh(Request())
            token = getattr(self._credentials, "token", None)
            if not token:
                raise ValueError(
                    "Vertex AI 인증 토큰을 가져오지 못했습니다. "
                    "GOOGLE_APPLICATION_CREDENTIALS 또는 ADC를 확인하세요."
                )
            return str(token)

    @classmethod
    def _normalize_model(cls, model: str) -> str:
        """모델명에 google/ 접두사를 부여해 Vertex OpenAI 호환 형식으로 정규화한다."""
        if not model:
            return cls._DEFAULT_MODEL
        if model.startswith("google/"):
            return model
        if model.startswith("gemini-"):
            return f"google/{model}"
        return model

    @observe(
        as_type="generation",
        name="LLM Generation (Vertex)",
        capture_input=False,
        capture_output=False,
    )
    async def generate_text(
        self, prompt: str, system_prompt: str | None = None, **kwargs: Any
    ) -> str:
        """Vertex AI Gemini 텍스트 생성 (OpenAI 호환). 호출마다 ADC 토큰을 갱신한다."""
        self.client.api_key = self._refresh_token()
        model, temperature, max_tokens = self._resolve_params(**kwargs)
        model = self._normalize_model(model)
        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        api_params: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "timeout": self.timeout,
        }
        # reasoning_effort 전달(Vertex Gemini는 thinking 예산을 이 값으로 제어).
        # thinking 모델은 추론에 토큰을 소진해 짧은 max_tokens로는 출력이 굶겨 빈 응답이
        # 되는 회귀가 있다. 호출측이 reasoning_effort="low"를 주면 추론을 최소화해 짧은
        # 출력(예: 한 줄 재작성)이 안정적으로 생성된다.
        reasoning_effort = kwargs.get("reasoning_effort")
        if reasoning_effort:
            api_params["reasoning_effort"] = reasoning_effort
        response = await asyncio.to_thread(
            self.client.chat.completions.create,
            **api_params,  # type: ignore[arg-type]
        )
        p, c, t = self._usage_openai(response)
        self._emit_generation(
            model=model,
            prompt_tokens=p,
            completion_tokens=c,
            total_tokens=t,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        # 방어적 None 처리: thinking(추론) 모델은 max_tokens가 부족하면 추론에 토큰을
        # 모두 소진해 choices가 비거나 message/content가 None으로 반환될 수 있다.
        # 이 경우 AttributeError로 상위 fallback을 무의미하게 유발하는 대신, 빈 문자열로
        # graceful 반환한다(호출측이 원본 폴백 등으로 처리). finish_reason을 로깅한다.
        if not response.choices:
            logger.warning("Vertex 응답 choices 비어있음", extra={"model": model})
            return ""
        choice = response.choices[0]
        message = getattr(choice, "message", None)
        content = getattr(message, "content", None) if message is not None else None
        if not content:
            logger.warning(
                "Vertex 응답 content 비어있음(추론 토큰 소진 가능)",
                extra={
                    "model": model,
                    "finish_reason": getattr(choice, "finish_reason", None),
                    "max_tokens": max_tokens,
                },
            )
            return ""
        return str(content)

    @observe(
        as_type="generation",
        name="LLM Generation (Vertex, streaming)",
        capture_input=False,
        capture_output=False,
    )
    async def stream_text(
        self, prompt: str, system_prompt: str | None = None, **kwargs: Any
    ) -> AsyncGenerator[str, None]:
        """Vertex AI Gemini 스트리밍 생성 (OpenAI 호환 stream=True)."""
        self.client.api_key = self._refresh_token()
        model, temperature, max_tokens = self._resolve_params(**kwargs)
        model = self._normalize_model(model)
        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        response = self.client.chat.completions.create(
            model=model,
            messages=messages,  # type: ignore[arg-type]
            stream=True,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=self.timeout,
            # 스트리밍에서도 정확한 토큰 usage를 마지막 청크로 받는다(Langfuse 비용)
            stream_options={"include_usage": True},
        )
        p = c = t = 0
        for chunk in response:  # type: ignore[union-attr]
            cu = getattr(chunk, "usage", None)
            if cu is not None:
                p = getattr(cu, "prompt_tokens", 0) or 0
                c = getattr(cu, "completion_tokens", 0) or 0
                t = getattr(cu, "total_tokens", 0) or 0
            if chunk.choices and chunk.choices[0].delta.content:  # type: ignore[union-attr]
                yield chunk.choices[0].delta.content  # type: ignore[union-attr]
        self._emit_generation(
            model=model,
            prompt_tokens=p,
            completion_tokens=c,
            total_tokens=t,
            temperature=temperature,
            max_tokens=max_tokens,
        )


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
        "ollama": OllamaLLMClient,  # Ollama 로컬 LLM
        "vertex": VertexLLMClient,  # Vertex AI Gemini (ADC 인증, api_key 불필요)
    }

    # 환경 변수 자동 매핑
    _ENV_VAR_MAPPING: dict[str, str] = {
        "google": "GOOGLE_API_KEY",
        "openai": "OPENAI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "openrouter": "OPENROUTER_API_KEY",  # OpenRouter API 키
        "ollama": "OLLAMA_BASE_URL",  # Ollama 서버 URL (API 키 불필요)
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
                    runtime_api_key = self._load_admin_provider_key(provider_name)
                    if runtime_api_key:
                        provider_config["api_key"] = runtime_api_key
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

    @staticmethod
    def _load_admin_provider_key(provider: str) -> str | None:
        try:
            from app.api.admin_ai_settings_store import get_admin_ai_settings_store

            return get_admin_ai_settings_store().get_provider_key(provider)
        except Exception:
            return None

    def get_client(
        self,
        provider: Literal[
            "google", "openai", "anthropic", "openrouter", "ollama", "vertex"
        ]
        | None = None,
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

        # ✅ #5 수정: model은 provider별로 다르므로 선호 provider에만 적용한다.
        # 폴백 provider로 전환되면 해당 provider의 기본 model(self.model)을 사용해야 하며,
        # 동일 model 문자열을 모든 provider에 전달하면 invalid-model로 폴백이 깨진다.
        pinned_model = kwargs.pop("model", None)

        last_error = None
        for provider in providers_to_try:
            if provider not in self._clients:
                continue

            try:
                client = self._clients[provider]
                # 선호 provider이고 model이 명시된 경우에만 model을 오버라이드한다.
                call_kwargs = dict(kwargs)
                if pinned_model is not None and provider == preferred_provider:
                    call_kwargs["model"] = pinned_model
                text = await client.generate_text(
                    prompt=prompt, system_prompt=system_prompt, **call_kwargs
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
