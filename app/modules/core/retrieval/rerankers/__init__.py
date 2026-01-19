"""
Reranker Module - 검색 결과 리랭킹 모듈

구현체:
- JinaReranker: Jina AI HTTP API 기반 리랭커
- JinaColBERTReranker: Jina ColBERT v2 기반 토큰 수준 리랭커
- CohereReranker: Cohere Rerank API 기반 리랭커 (cross-encoder 방식)
- OpenAILLMReranker: OpenAI 모델 기반 LLM 리랭커 (모델 설정 가능)
- GeminiFlashReranker: Google Gemini 2.5 Flash Lite 기반 LLM 리랭커
- RerankerChain: 다중 리랭커 순차 실행 체인
- RerankerFactory: 설정 기반 리랭커 자동 선택 팩토리
"""

from ..interfaces import IReranker  # 상위 디렉토리의 interfaces.py에서 import
from .cohere_reranker import CohereReranker
from .colbert_reranker import ColBERTRerankerConfig, JinaColBERTReranker
from .factory import SUPPORTED_RERANKERS, RerankerFactory
from .gemini_reranker import GeminiFlashReranker
from .jina_reranker import JinaReranker
from .openai_llm_reranker import OpenAILLMReranker
from .reranker_chain import RerankerChain, RerankerChainConfig

__all__ = [
    "IReranker",
    "JinaReranker",
    "JinaColBERTReranker",
    "ColBERTRerankerConfig",
    "CohereReranker",
    "OpenAILLMReranker",
    "GeminiFlashReranker",
    "RerankerChain",
    "RerankerChainConfig",
    "RerankerFactory",
    "SUPPORTED_RERANKERS",
]

# 조건부 import (선택적 의존성)
try:
    from .local_reranker import LocalReranker

    __all__.append("LocalReranker")
except ImportError:
    pass  # local-reranker 의존성 미설치
