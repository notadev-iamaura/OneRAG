"""
RerankerFactory v2 - 3단계 계층 구조 기반 리랭커 팩토리

approach/provider/model 구조로 리랭커를 생성합니다.

approach별 설명:
- llm: 범용 LLM을 사용한 리랭킹 (Gemini, GPT 등)
- cross-encoder: 쿼리+문서를 함께 인코딩하는 전용 리랭커 (Jina Reranker, Cohere)
- late-interaction: 토큰 레벨 상호작용 (ColBERT)

사용 예시:
    from app.modules.core.retrieval.rerankers.factory_v2 import RerankerFactoryV2

    config = {
        "reranking": {
            "approach": "cross-encoder",
            "provider": "jina",
            "jina": {"model": "jina-reranker-v2-base-multilingual"}
        }
    }
    reranker = RerankerFactoryV2.create(config)
"""

import os
from typing import Any

from .....lib.logger import get_logger
from ..interfaces import IReranker

logger = get_logger(__name__)


# ========================================
# 레지스트리 정의
# ========================================

APPROACH_REGISTRY: dict[str, dict[str, Any]] = {
    "llm": {
        "description": "범용 LLM을 사용한 리랭킹 (언어 이해력 기반)",
        "providers": ["google", "openai", "openrouter"],
    },
    "cross-encoder": {
        "description": "Cross-Encoder 전용 리랭커 (쿼리+문서 쌍 인코딩)",
        "providers": ["jina", "cohere", "vertex"],
    },
    "late-interaction": {
        "description": "Late-Interaction 리랭커 (토큰 레벨 상호작용, ColBERT)",
        "providers": ["jina"],
    },
    "local": {
        "description": "로컬 모델 리랭커 (API 키 불필요, sentence-transformers / BGE 다국어)",
        "providers": ["sentence-transformers", "bge"],
    },
}

PROVIDER_REGISTRY: dict[str, dict[str, Any]] = {
    "google": {
        "class": "GeminiFlashReranker",
        "api_key_env": "GOOGLE_API_KEY",
        "default_config": {
            "model": "gemini-flash-lite-latest",
            "max_documents": 20,
            "timeout": 15,
        },
    },
    "openai": {
        "class": "OpenAILLMReranker",
        "api_key_env": "OPENAI_API_KEY",
        "default_config": {
            "model": "gpt-5-nano",
            "max_documents": 20,
            "timeout": 15,
            "verbosity": "low",
            "reasoning_effort": "minimal",
        },
    },
    "jina": {
        "class_cross_encoder": "JinaReranker",
        "class_late_interaction": "JinaColBERTReranker",
        "api_key_env": "JINA_API_KEY",
        "default_config": {
            "model": "jina-reranker-v2-base-multilingual",
            "top_n": 10,
            "timeout": 30,
            "max_documents": 20,
        },
        "default_config_colbert": {
            "model": "jina-colbert-v2",
            "top_n": 10,
            "timeout": 10,
            "max_documents": 20,
        },
    },
    "cohere": {
        "class": "CohereReranker",
        "api_key_env": "COHERE_API_KEY",
        "default_config": {
            "model": "rerank-multilingual-v3.0",
            "top_n": 10,
            "timeout": 30,
        },
    },
    "vertex": {
        "class": "VertexRankingReranker",
        "api_key_env": None,  # Application Default Credentials(ADC) 사용 — 키 불필요
        "default_config": {
            "project_id": None,
            "location": "global",
            "ranking_config": "default_ranking_config",
            "model": "semantic-ranker-default-004",
            "top_n": 10,
            "max_documents": 16,
            "timeout": 1.5,
            "max_retries": 1,
            "ignore_record_details_in_response": True,
            "user_labels": {},
        },
    },
    "openrouter": {
        "class": "OpenRouterReranker",
        "api_key_env": "OPENROUTER_API_KEY",
        "default_config": {
            "model": "google/gemini-2.5-flash-lite",
            "max_documents": 20,
            "timeout": 15,
        },
    },
    "sentence-transformers": {
        "class": None,  # 조건부 로드
        "api_key_env": None,  # API 키 불필요
        "default_config": {
            "model": "cross-encoder/ms-marco-MiniLM-L-12-v2",
            "batch_size": 32,
        },
    },
    "bge": {
        "class": "BGEReranker",
        "api_key_env": None,  # API 키 불필요 (로컬 다국어 모델)
        "default_config": {
            "model": "BAAI/bge-reranker-v2-m3",
            "top_n": 10,
            "max_documents": 16,
            "batch_size": 8,
            "max_length": 384,
            "normalize_scores": True,
            "use_fp16": False,
            "device": None,
        },
    },
}


# ========================================
# Factory 클래스
# ========================================


class RerankerFactoryV2:
    """
    3단계 계층 구조 기반 리랭커 팩토리

    approach → provider → model 순으로 설정을 해석하여
    적절한 리랭커 인스턴스를 생성합니다.
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
            ValueError: 유효하지 않은 approach-provider 조합 또는 API 키 누락
        """
        reranking_config = config.get("reranking", {})
        approach = reranking_config.get("approach", "cross-encoder")
        provider = reranking_config.get("provider", "jina")

        logger.info(f"🔄 RerankerFactoryV2: approach={approach}, provider={provider}")

        # approach 검증
        if approach not in APPROACH_REGISTRY:
            raise ValueError(
                f"지원하지 않는 approach: {approach}. "
                f"지원 목록: {list(APPROACH_REGISTRY.keys())}"
            )

        # approach-provider 조합 검증
        valid_providers = APPROACH_REGISTRY[approach]["providers"]
        if provider not in valid_providers:
            raise ValueError(
                f"approach '{approach}'에서 provider '{provider}'는 사용할 수 없습니다. "
                f"유효한 provider: {valid_providers}"
            )

        # provider 검증
        if provider not in PROVIDER_REGISTRY:
            raise ValueError(
                f"지원하지 않는 provider: {provider}. "
                f"지원 목록: {list(PROVIDER_REGISTRY.keys())}"
            )

        # 리랭커 생성
        if approach == "llm":
            return RerankerFactoryV2._create_llm_reranker(provider, reranking_config)
        elif approach == "cross-encoder":
            return RerankerFactoryV2._create_cross_encoder_reranker(
                provider, reranking_config
            )
        elif approach == "late-interaction":
            return RerankerFactoryV2._create_late_interaction_reranker(
                provider, reranking_config
            )
        elif approach == "local":
            return RerankerFactoryV2._create_local_reranker(provider, reranking_config)
        else:
            raise ValueError(f"알 수 없는 approach: {approach}")

    @staticmethod
    def _create_llm_reranker(provider: str, config: dict[str, Any]) -> IReranker:
        """LLM approach 리랭커 생성"""
        provider_info = PROVIDER_REGISTRY[provider]
        api_key = os.getenv(provider_info["api_key_env"])

        if not api_key:
            raise ValueError(
                f"{provider_info['api_key_env']} 환경변수가 설정되지 않았습니다. "
                f"API key가 필요합니다."
            )

        provider_config = config.get(provider, {})
        defaults = provider_info["default_config"]

        reranker: IReranker
        if provider == "google":
            from .gemini_reranker import GeminiFlashReranker

            reranker = GeminiFlashReranker(
                api_key=api_key,
                model=provider_config.get("model", defaults["model"]),
                max_documents=provider_config.get(
                    "max_documents", defaults["max_documents"]
                ),
                timeout=provider_config.get("timeout", defaults["timeout"]),
            )
        elif provider == "openai":
            from .openai_llm_reranker import OpenAILLMReranker

            reranker = OpenAILLMReranker(
                api_key=api_key,
                model=provider_config.get("model", defaults["model"]),
                max_documents=provider_config.get(
                    "max_documents", defaults["max_documents"]
                ),
                timeout=provider_config.get("timeout", defaults["timeout"]),
                verbosity=provider_config.get("verbosity", defaults["verbosity"]),
                reasoning_effort=provider_config.get(
                    "reasoning_effort", defaults["reasoning_effort"]
                ),
            )
        elif provider == "openrouter":
            from .openrouter_reranker import OpenRouterReranker

            reranker = OpenRouterReranker(
                api_key=api_key,
                model=provider_config.get("model", defaults["model"]),
                max_documents=provider_config.get(
                    "max_documents", defaults["max_documents"]
                ),
                timeout=provider_config.get("timeout", defaults["timeout"]),
            )
        else:
            raise ValueError(
                f"LLM approach에서 {provider}는 아직 지원되지 않습니다."
            )

        logger.info(f"✅ {reranker.__class__.__name__} 생성 완료")
        return reranker

    @staticmethod
    def _create_cross_encoder_reranker(
        provider: str, config: dict[str, Any]
    ) -> IReranker:
        """Cross-encoder approach 리랭커 생성"""
        provider_info = PROVIDER_REGISTRY[provider]
        # api_key_env가 None인 provider(vertex 등)는 ADC 인증이라 API 키를 강제하지 않는다.
        api_key_env = provider_info["api_key_env"]
        api_key = os.getenv(api_key_env) if api_key_env else None

        if api_key_env and not api_key:
            raise ValueError(
                f"{api_key_env} 환경변수가 설정되지 않았습니다. "
                f"API key가 필요합니다."
            )

        provider_config = config.get(provider, {})
        defaults = provider_info["default_config"]

        reranker: IReranker
        if provider == "jina":
            from .jina_reranker import JinaReranker

            reranker = JinaReranker(
                api_key=str(api_key),
                model=provider_config.get("model", defaults["model"]),
                timeout=provider_config.get("timeout", defaults.get("timeout", 30)),
            )
        elif provider == "cohere":
            from .cohere_reranker import CohereReranker

            reranker = CohereReranker(
                api_key=str(api_key),
                model=provider_config.get("model", defaults["model"]),
                timeout=provider_config.get("timeout", defaults.get("timeout", 30)),
            )
        elif provider == "vertex":
            # ADC(키리스) provider — google-auth 미설치 시 인증 시점에 안내 에러.
            from .vertex_ranking_reranker import VertexRankingReranker

            reranker = VertexRankingReranker(
                project_id=provider_config.get("project_id", defaults["project_id"]),
                location=provider_config.get("location", defaults["location"]),
                ranking_config=provider_config.get(
                    "ranking_config",
                    defaults["ranking_config"],
                ),
                model=provider_config.get("model", defaults["model"]),
                top_n=provider_config.get("top_n", defaults["top_n"]),
                max_documents=provider_config.get(
                    "max_documents",
                    defaults["max_documents"],
                ),
                timeout=provider_config.get("timeout", defaults["timeout"]),
                max_retries=provider_config.get(
                    "max_retries",
                    defaults["max_retries"],
                ),
                ignore_record_details_in_response=provider_config.get(
                    "ignore_record_details_in_response",
                    defaults["ignore_record_details_in_response"],
                ),
                user_labels=provider_config.get("user_labels", defaults["user_labels"]),
            )
        else:
            raise ValueError(
                f"Cross-encoder approach에서 {provider}는 아직 지원되지 않습니다."
            )

        logger.info(f"✅ {reranker.__class__.__name__} 생성 완료")
        return reranker

    @staticmethod
    def _create_late_interaction_reranker(
        provider: str, config: dict[str, Any]
    ) -> IReranker:
        """Late-interaction approach 리랭커 생성"""
        provider_info = PROVIDER_REGISTRY[provider]
        api_key = os.getenv(provider_info["api_key_env"])

        if not api_key:
            raise ValueError(
                f"{provider_info['api_key_env']} 환경변수가 설정되지 않았습니다. "
                f"API key가 필요합니다."
            )

        provider_config = config.get(provider, {})
        defaults = provider_info.get(
            "default_config_colbert", provider_info["default_config"]
        )

        if provider == "jina":
            from .colbert_reranker import ColBERTRerankerConfig, JinaColBERTReranker

            colbert_config = ColBERTRerankerConfig(
                enabled=True,
                api_key=api_key,
                model=provider_config.get("model", defaults["model"]),
                timeout=provider_config.get("timeout", defaults.get("timeout", 10)),
                max_documents=provider_config.get(
                    "max_documents", defaults.get("max_documents", 20)
                ),
            )
            reranker = JinaColBERTReranker(config=colbert_config)
        else:
            raise ValueError(
                f"Late-interaction approach에서 {provider}는 아직 지원되지 않습니다."
            )

        logger.info(f"✅ {reranker.__class__.__name__} 생성 완료")
        return reranker

    @staticmethod
    def _create_local_reranker(
        provider: str, config: dict[str, Any]
    ) -> IReranker:
        """Local approach 리랭커 생성 (API 키 불필요)

        provider 분기:
        - sentence-transformers: 기존 CrossEncoder 리랭커(영어 중심 ms-marco).
        - bge: BAAI/bge-reranker-v2-m3 로컬 다국어 리랭커(timeout/협조적 중단 포함).
        """
        reranker: IReranker
        if provider == "sentence-transformers":
            try:
                from .local_reranker import LocalReranker
            except ImportError:
                raise ImportError(
                    "LocalReranker를 사용하려면 sentence-transformers가 필요합니다. "
                    "설치: uv sync --extra local-embedding"
                )

            # config에서 sentence-transformers 또는 local 키로 설정 조회
            provider_config = config.get(
                "sentence-transformers", config.get("local", {})
            )
            defaults = PROVIDER_REGISTRY["sentence-transformers"]["default_config"]

            reranker = LocalReranker(
                model_name=provider_config.get("model", defaults["model"]),
                batch_size=provider_config.get("batch_size", defaults["batch_size"]),
            )
        elif provider == "bge":
            # 무거운 의존성(torch/transformers)은 BGEReranker 모듈 내부 import 가드로
            # 보호된다. 미설치 환경에서도 모듈 import는 성공하며, 실제 사용(런타임
            # 검증/모델 로드) 시점에 명확한 설치 안내 에러가 발생한다.
            from .bge_reranker import BGEReranker

            provider_config = config.get("bge", {})
            defaults = PROVIDER_REGISTRY["bge"]["default_config"]

            reranker = BGEReranker(
                model_name=provider_config.get("model", defaults["model"]),
                top_n=provider_config.get("top_n", defaults["top_n"]),
                max_documents=provider_config.get(
                    "max_documents", defaults["max_documents"]
                ),
                batch_size=provider_config.get("batch_size", defaults["batch_size"]),
                max_length=provider_config.get("max_length", defaults["max_length"]),
                normalize_scores=provider_config.get(
                    "normalize_scores", defaults["normalize_scores"]
                ),
                use_fp16=provider_config.get("use_fp16", defaults["use_fp16"]),
                device=provider_config.get("device", defaults["device"]),
                # P1-B: BGE 점수 계산 timeout(초). 미설정이면 무제한(기존 동작).
                # reranking.yaml의 bge.timeout으로 조절한다(기본 30초 권장).
                timeout=provider_config.get("timeout"),
            )
        else:
            raise ValueError(
                f"Local approach에서 {provider}는 아직 지원되지 않습니다."
            )

        logger.info(f"✅ {reranker.__class__.__name__} 생성 완료")
        return reranker

    # ========================================
    # 헬퍼 메서드
    # ========================================

    @staticmethod
    def get_approaches() -> list[str]:
        """지원하는 approach 목록 반환"""
        return list(APPROACH_REGISTRY.keys())

    @staticmethod
    def get_providers_for_approach(approach: str) -> list[str]:
        """특정 approach에서 사용 가능한 provider 목록 반환"""
        if approach not in APPROACH_REGISTRY:
            return []
        providers: list[str] = APPROACH_REGISTRY[approach]["providers"]
        return providers

    @staticmethod
    def get_approach_description(approach: str) -> str:
        """approach 설명 반환"""
        if approach not in APPROACH_REGISTRY:
            return "알 수 없는 approach"
        description: str = APPROACH_REGISTRY[approach]["description"]
        return description

    @staticmethod
    def get_all_providers() -> list[str]:
        """모든 provider 목록 반환"""
        return list(PROVIDER_REGISTRY.keys())


# ========================================
# 레거시 호환 코드
# ========================================

# 레거시 SUPPORTED_RERANKERS 별칭 (기존 코드 호환용)
SUPPORTED_RERANKERS: dict[str, dict[str, Any]] = {
    "gemini-flash": {
        "type": "llm",
        "class": "GeminiFlashReranker",
        "description": "Google Gemini Flash Lite 기반 LLM 리랭커",
        "requires_api_key": "GOOGLE_API_KEY",
        "approach": "llm",
        "provider": "google",
        "default_config": {
            "model": "gemini-flash-lite-latest",
            "max_documents": 20,
            "timeout": 15,
        },
    },
    "openai-llm": {
        "type": "llm",
        "class": "OpenAILLMReranker",
        "description": "OpenAI 모델 기반 LLM 리랭커",
        "requires_api_key": "OPENAI_API_KEY",
        "approach": "llm",
        "provider": "openai",
        "default_config": {
            "model": "gpt-5-nano",
            "max_documents": 20,
            "timeout": 15,
            "verbosity": "low",
            "reasoning_effort": "minimal",
        },
    },
    "jina": {
        "type": "api",
        "class": "JinaReranker",
        "description": "Jina AI Reranker API",
        "requires_api_key": "JINA_API_KEY",
        "approach": "cross-encoder",
        "provider": "jina",
        "default_config": {
            "model": "jina-reranker-v2-base-multilingual",
            "endpoint": "https://api.jina.ai/v1/rerank",
            "timeout": 30.0,
        },
    },
    "jina-colbert": {
        "type": "colbert",
        "class": "JinaColBERTReranker",
        "description": "Jina ColBERT v2 Late-Interaction 리랭커",
        "requires_api_key": "JINA_API_KEY",
        "approach": "late-interaction",
        "provider": "jina",
        "default_config": {
            "model": "jina-colbert-v2",
            "top_n": 10,
            "timeout": 10,
            "max_documents": 20,
        },
    },
    "cohere": {
        "type": "api",
        "class": "CohereReranker",
        "description": "Cohere Rerank API (100+ 언어 지원)",
        "requires_api_key": "COHERE_API_KEY",
        "approach": "cross-encoder",
        "provider": "cohere",
        "default_config": {
            "model": "rerank-multilingual-v3.0",
            "top_n": 10,
            "timeout": 30,
        },
    },
}


class RerankerFactory:
    """
    레거시 호환용 RerankerFactory

    새 코드에서는 RerankerFactoryV2 사용을 권장합니다.
    이 클래스는 기존 코드와의 호환성을 위해 유지됩니다.
    """

    @staticmethod
    def create(config: dict[str, Any]) -> IReranker:
        """
        레거시 설정 기반 리랭커 생성

        Args:
            config: 전체 설정 딕셔너리

        Returns:
            IReranker 인스턴스
        """
        reranking_config = config.get("reranking", {})

        # 새 설정 구조(approach/provider)가 있으면 v2 팩토리 사용
        if "approach" in reranking_config:
            return RerankerFactoryV2.create(config)

        # 레거시 설정 구조 처리 (default_provider 또는 provider 필드)
        # 레거시 기본값은 gemini-flash였음
        default_provider = reranking_config.get(
            "default_provider",
            reranking_config.get("provider", "gemini-flash")
        )

        # 레거시 provider를 새 approach/provider로 변환
        legacy_mapping = {
            "gemini-flash": ("llm", "google"),
            "gemini_flash": ("llm", "google"),
            "openai-llm": ("llm", "openai"),
            "openai_llm": ("llm", "openai"),
            "jina": ("cross-encoder", "jina"),
            "jina-colbert": ("late-interaction", "jina"),
            "jina_colbert": ("late-interaction", "jina"),
        }

        if default_provider in legacy_mapping:
            approach, provider = legacy_mapping[default_provider]

            # 레거시 openai_llm 설정을 새 openai 설정으로 변환
            openai_config = reranking_config.get("openai_llm", {})

            new_config = {
                "reranking": {
                    **reranking_config,
                    "approach": approach,
                    "provider": provider,
                    "openai": openai_config if openai_config else None,
                }
            }
            return RerankerFactoryV2.create(new_config)

        raise ValueError(f"지원하지 않는 리랭커: {default_provider}")

    @staticmethod
    def get_supported_rerankers() -> list[str]:
        """지원하는 리랭커 목록 반환"""
        return list(SUPPORTED_RERANKERS.keys())

    @staticmethod
    def list_rerankers_by_type(reranker_type: str) -> list[str]:
        """특정 타입의 리랭커 목록 반환"""
        return [
            name
            for name, info in SUPPORTED_RERANKERS.items()
            if info.get("type") == reranker_type
        ]

    @staticmethod
    def get_reranker_info(name: str) -> dict[str, Any] | None:
        """특정 리랭커 정보 반환"""
        return SUPPORTED_RERANKERS.get(name)
