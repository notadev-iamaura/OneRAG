"""
RerankerFactory - 설정 기반 리랭커 자동 선택 팩토리

YAML 설정에 따라 적절한 리랭커 인스턴스를 생성합니다.
설정에 따라 적절한 리랭커를 쉽게 교체할 수 있도록 지원합니다.

사용 예시:
    from app.modules.core.retrieval.rerankers import RerankerFactory

    # YAML 설정 기반 리랭커 생성
    reranker = RerankerFactory.create(config)

    # 지원 리랭커 조회
    RerankerFactory.get_supported_rerankers()
    RerankerFactory.list_rerankers_by_type("llm")

지원 리랭커:
    - gemini-flash: Google Gemini Flash Lite 기반 LLM 리랭커 (빠름, 고품질)
    - jina: Jina AI Reranker API (다국어 지원, 균형잡힌 성능)
    - jina-colbert: Jina ColBERT v2 Late-Interaction 리랭커 (토큰 수준 정밀 매칭)
"""

import os
from typing import Any

from .....lib.logger import get_logger
from ..interfaces import IReranker
from .colbert_reranker import ColBERTRerankerConfig, JinaColBERTReranker
from .gemini_reranker import GeminiFlashReranker
from .jina_reranker import JinaReranker
from .openai_llm_reranker import OpenAILLMReranker

logger = get_logger(__name__)


# 지원 리랭커 레지스트리
# 새 리랭커 추가 시 여기에 등록
SUPPORTED_RERANKERS: dict[str, dict[str, Any]] = {
    # LLM 기반 리랭커 (고품질, 빠름)
    "gemini-flash": {
        "type": "llm",
        "class": "GeminiFlashReranker",
        "description": "Google Gemini Flash Lite 기반 LLM 리랭커 (빠름, 고품질)",
        "requires_api_key": "GOOGLE_API_KEY",
        "default_config": {
            "model": "gemini-flash-lite-latest",
            "max_documents": 20,
            "timeout": 15,
        },
    },
    # OpenAI LLM 기반 리랭커 (모델 설정 가능)
    "openai-llm": {
        "type": "llm",
        "class": "OpenAILLMReranker",
        "description": "OpenAI 모델 기반 LLM 리랭커 (gpt-5-nano, gpt-4o-mini 등)",
        "requires_api_key": "OPENAI_API_KEY",
        "default_config": {
            "model": "gpt-5-nano",
            "max_documents": 20,
            "timeout": 15,
            "verbosity": "low",
            "reasoning_effort": "minimal",
        },
    },
    # API 기반 리랭커 (균형)
    "jina": {
        "type": "api",
        "class": "JinaReranker",
        "description": "Jina AI Reranker API (다국어 지원, 균형잡힌 성능)",
        "requires_api_key": "JINA_API_KEY",
        "default_config": {
            "model": "jina-reranker-v2-base-multilingual",
            "endpoint": "https://api.jina.ai/v1/rerank",
            "timeout": 30.0,
        },
    },
    # ColBERT 기반 리랭커 (토큰 수준 정밀도)
    "jina-colbert": {
        "type": "colbert",
        "class": "JinaColBERTReranker",
        "description": "Jina ColBERT v2 Late-Interaction 리랭커 (토큰 수준 정밀 매칭)",
        "requires_api_key": "JINA_API_KEY",
        "default_config": {
            "model": "jina-colbert-v2",
            "top_n": 10,
            "timeout": 10,
            "max_documents": 20,
        },
    },
}


class RerankerFactory:
    """
    설정 기반 리랭커 팩토리

    YAML 설정 파일의 reranking 섹션을 읽어 적절한 리랭커를 생성합니다.

    설정 예시 (features/reranking.yaml):
        reranking:
          provider: "gemini-flash"  # gemini-flash, jina, jina-colbert
          gemini:
            model: "gemini-flash-lite-latest"
            max_documents: 20
            timeout: 15
          jina:
            model: "jina-reranker-v2-base-multilingual"
          colbert:
            model: "jina-colbert-v2"
            top_n: 10
    """

    @staticmethod
    def create(config: dict[str, Any]) -> IReranker:
        """
        설정 기반 리랭커 인스턴스 생성

        Args:
            config: 전체 설정 딕셔너리 (reranking 섹션 포함)

        Returns:
            IReranker 인터페이스를 구현한 리랭커 인스턴스

        Raises:
            ValueError: 지원하지 않는 프로바이더인 경우
            ValueError: 필수 API 키가 없는 경우
        """
        reranking_config = config.get("reranking", {})
        provider = reranking_config.get("provider", "gemini-flash")

        logger.info(f"🔄 RerankerFactory: provider={provider}")

        if provider not in SUPPORTED_RERANKERS:
            supported = list(SUPPORTED_RERANKERS.keys())
            raise ValueError(
                f"지원하지 않는 리랭커 프로바이더: {provider}. "
                f"지원 목록: {supported}"
            )

        if provider == "gemini-flash":
            return RerankerFactory._create_gemini_reranker(config, reranking_config)
        elif provider == "jina":
            return RerankerFactory._create_jina_reranker(config, reranking_config)
        elif provider == "jina-colbert":
            return RerankerFactory._create_colbert_reranker(config, reranking_config)
        elif provider == "openai-llm":
            return RerankerFactory._create_openai_llm_reranker(config, reranking_config)
        else:
            # SUPPORTED_RERANKERS 검사 통과 후 여기 도달 불가 (안전장치)
            raise ValueError(f"지원하지 않는 리랭커 프로바이더: {provider}")

    @staticmethod
    def _create_gemini_reranker(
        config: dict[str, Any], reranking_config: dict[str, Any]
    ) -> GeminiFlashReranker:
        """Gemini Flash 리랭커 생성"""
        gemini_config = reranking_config.get("gemini", {})
        defaults = SUPPORTED_RERANKERS["gemini-flash"]["default_config"]

        # API 키 확인
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise ValueError("GOOGLE_API_KEY 환경변수가 설정되지 않았습니다.")

        # 설정값 추출 (기본값 폴백)
        model = gemini_config.get("model", defaults["model"])
        max_documents = gemini_config.get("max_documents", defaults["max_documents"])
        timeout = gemini_config.get("timeout", defaults["timeout"])

        reranker = GeminiFlashReranker(
            api_key=api_key,
            model=model,
            max_documents=max_documents,
            timeout=timeout,
        )

        logger.info(
            f"✅ GeminiFlashReranker 생성: model={model}, "
            f"max_documents={max_documents}, timeout={timeout}"
        )
        return reranker

    @staticmethod
    def _create_jina_reranker(
        config: dict[str, Any], reranking_config: dict[str, Any]
    ) -> JinaReranker:
        """Jina 리랭커 생성"""
        jina_config = reranking_config.get("jina", {})
        defaults = SUPPORTED_RERANKERS["jina"]["default_config"]

        # API 키 확인
        api_key = os.getenv("JINA_API_KEY")
        if not api_key:
            raise ValueError("JINA_API_KEY 환경변수가 설정되지 않았습니다.")

        # 설정값 추출 (기본값 폴백)
        # 주의: JinaReranker는 top_n을 생성자에서 받지 않음 (rerank 메서드에서 처리)
        model = jina_config.get("model", defaults["model"])
        endpoint = jina_config.get("endpoint", defaults["endpoint"])
        timeout = jina_config.get("timeout", defaults["timeout"])

        reranker = JinaReranker(
            api_key=api_key,
            model=model,
            endpoint=endpoint,
            timeout=timeout,
        )

        logger.info(
            f"✅ JinaReranker 생성: model={model}, endpoint={endpoint}"
        )
        return reranker

    @staticmethod
    def _create_colbert_reranker(
        config: dict[str, Any], reranking_config: dict[str, Any]
    ) -> JinaColBERTReranker:
        """Jina ColBERT 리랭커 생성"""
        colbert_config = reranking_config.get("colbert", {})
        defaults = SUPPORTED_RERANKERS["jina-colbert"]["default_config"]

        # API 키 확인
        api_key = os.getenv("JINA_API_KEY")
        if not api_key:
            raise ValueError("JINA_API_KEY 환경변수가 설정되지 않았습니다.")

        # ColBERTRerankerConfig dataclass로 설정 생성
        reranker_config = ColBERTRerankerConfig(
            enabled=True,
            api_key=api_key,
            model=colbert_config.get("model", defaults["model"]),
            timeout=colbert_config.get("timeout", defaults["timeout"]),
            max_documents=colbert_config.get("max_documents", defaults["max_documents"]),
        )

        reranker = JinaColBERTReranker(config=reranker_config)

        logger.info(
            f"✅ JinaColBERTReranker 생성: model={reranker_config.model}, "
            f"max_documents={reranker_config.max_documents}"
        )
        return reranker

    @staticmethod
    def _create_openai_llm_reranker(
        config: dict[str, Any], reranking_config: dict[str, Any]
    ) -> OpenAILLMReranker:
        """OpenAI LLM 리랭커 생성"""
        openai_config = reranking_config.get("openai_llm", {})
        defaults = SUPPORTED_RERANKERS["openai-llm"]["default_config"]

        # API 키 확인
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY 환경변수가 설정되지 않았습니다.")

        # 설정값 추출 (기본값 폴백)
        model = openai_config.get("model", defaults["model"])
        max_documents = openai_config.get("max_documents", defaults["max_documents"])
        timeout = openai_config.get("timeout", defaults["timeout"])
        verbosity = openai_config.get("verbosity", defaults["verbosity"])
        reasoning_effort = openai_config.get("reasoning_effort", defaults["reasoning_effort"])

        reranker = OpenAILLMReranker(
            api_key=api_key,
            model=model,
            max_documents=max_documents,
            timeout=timeout,
            verbosity=verbosity,
            reasoning_effort=reasoning_effort,
        )

        logger.info(
            f"✅ OpenAILLMReranker 생성: model={model}, "
            f"max_documents={max_documents}, timeout={timeout}"
        )
        return reranker

    @staticmethod
    def get_supported_rerankers() -> list[str]:
        """지원하는 모든 리랭커 이름 반환"""
        return list(SUPPORTED_RERANKERS.keys())

    @staticmethod
    def list_rerankers_by_type(reranker_type: str) -> list[str]:
        """
        타입별 리랭커 목록 반환

        Args:
            reranker_type: 리랭커 타입 (llm, api, colbert)

        Returns:
            해당 타입의 리랭커 이름 리스트
        """
        return [
            name
            for name, info in SUPPORTED_RERANKERS.items()
            if info["type"] == reranker_type
        ]

    @staticmethod
    def get_reranker_info(name: str) -> dict[str, Any] | None:
        """
        특정 리랭커의 상세 정보 반환

        Args:
            name: 리랭커 이름

        Returns:
            리랭커 정보 딕셔너리 또는 None
        """
        return SUPPORTED_RERANKERS.get(name)
