"""
CacheFactory - 설정 기반 캐시 자동 선택 팩토리

YAML 설정에 따라 적절한 캐시 인스턴스를 생성합니다.
설정에 따라 적절한 캐시를 쉽게 교체할 수 있도록 지원합니다.

사용 예시:
    from app.modules.core.retrieval.cache import CacheFactory

    # YAML 설정 기반 캐시 생성
    cache = CacheFactory.create(config)

    # Semantic 캐시 생성 (embedder 필요)
    cache = CacheFactory.create(config, embedder=embedder)

    # 지원 캐시 조회
    CacheFactory.get_supported_caches()
"""

import os
from typing import Any

from .....lib.logger import get_logger
from ..interfaces import ICacheManager
from .memory_cache import MemoryCacheManager
from .semantic_cache import InMemorySemanticCache, SemanticCacheConfig

logger = get_logger(__name__)


# 지원 캐시 레지스트리
# 새 캐시 추가 시 여기에 등록
SUPPORTED_CACHES: dict[str, dict[str, Any]] = {
    # In-memory LRU 캐시 (단일 인스턴스)
    "memory": {
        "type": "local",
        "class": "MemoryCacheManager",
        "description": "In-memory LRU 캐시 (단일 인스턴스 환경)",
        "requires_embedder": False,
        "default_config": {
            "maxsize": 1000,
            "ttl": 3600,
        },
    },
    # Redis 분산 캐시 (다중 인스턴스)
    "redis": {
        "type": "distributed",
        "class": "RedisCacheManager",
        "description": "Redis 분산 캐시 (다중 인스턴스 환경)",
        "requires_embedder": False,
        "requires_env": "REDIS_URL",
        "default_config": {
            "ttl": 3600,
            "prefix": "rag:",
        },
    },
    # Semantic 캐시 (쿼리 임베딩 유사도 기반)
    "semantic": {
        "type": "semantic",
        "class": "InMemorySemanticCache",
        "description": "쿼리 임베딩 유사도 기반 시맨틱 캐시",
        "requires_embedder": True,
        "default_config": {
            "similarity_threshold": 0.92,
            "max_entries": 1000,
            "ttl": 3600,
        },
    },
}


class CacheFactory:
    """
    설정 기반 캐시 팩토리

    YAML 설정 파일의 cache 섹션을 읽어 적절한 캐시를 생성합니다.

    설정 예시 (features/cache.yaml):
        cache:
          provider: "memory"  # memory, redis, semantic
          memory:
            maxsize: 1000
            ttl: 3600
          redis:
            ttl: 3600
            prefix: "rag:"
          semantic:
            similarity_threshold: 0.92
            max_entries: 1000
            ttl: 3600
    """

    @staticmethod
    def create(
        config: dict[str, Any],
        embedder: Any | None = None,
    ) -> ICacheManager:
        """
        설정 기반 캐시 인스턴스 생성

        Args:
            config: 전체 설정 딕셔너리 (cache 섹션 포함)
            embedder: 임베더 인스턴스 (semantic 캐시에 필요)

        Returns:
            ICacheManager 인터페이스를 구현한 캐시 인스턴스

        Raises:
            ValueError: 지원하지 않는 프로바이더인 경우
            ValueError: semantic 캐시인데 embedder가 없는 경우
        """
        cache_config = config.get("cache", {})
        provider = cache_config.get("provider", "memory")

        logger.info(f"🔄 CacheFactory: provider={provider}")

        if provider not in SUPPORTED_CACHES:
            supported = list(SUPPORTED_CACHES.keys())
            raise ValueError(
                f"지원하지 않는 캐시 프로바이더: {provider}. "
                f"지원 목록: {supported}"
            )

        cache_info = SUPPORTED_CACHES[provider]

        # Semantic 캐시는 embedder 필수
        if cache_info.get("requires_embedder") and embedder is None:
            raise ValueError(
                f"{provider} 캐시는 embedder가 필수입니다. "
                "CacheFactory.create(config, embedder=embedder) 형태로 호출하세요."
            )

        if provider == "memory":
            return CacheFactory._create_memory_cache(config, cache_config)
        elif provider == "redis":
            return CacheFactory._create_redis_cache(config, cache_config)
        elif provider == "semantic":
            return CacheFactory._create_semantic_cache(config, cache_config, embedder)
        else:
            # 이 코드는 도달할 수 없지만, 명시적으로 에러 처리
            raise ValueError(f"지원하지 않는 캐시 프로바이더: {provider}")

    @staticmethod
    def _create_memory_cache(
        config: dict[str, Any], cache_config: dict[str, Any]
    ) -> MemoryCacheManager:
        """Memory 캐시 생성"""
        memory_config = cache_config.get("memory", {})
        defaults = SUPPORTED_CACHES["memory"]["default_config"]

        cache = MemoryCacheManager(
            maxsize=memory_config.get("maxsize", defaults["maxsize"]),
            default_ttl=memory_config.get("ttl", defaults["ttl"]),
            enable_stats=True,
        )

        logger.info(
            f"✅ MemoryCacheManager 생성: "
            f"maxsize={memory_config.get('maxsize', defaults['maxsize'])}, "
            f"ttl={memory_config.get('ttl', defaults['ttl'])}"
        )
        return cache

    @staticmethod
    def _create_redis_cache(
        config: dict[str, Any], cache_config: dict[str, Any]
    ) -> MemoryCacheManager:
        """
        Redis 캐시 생성

        Note: Redis 연결 실패 시 또는 REDIS_URL 미설정 시 MemoryCacheManager로 폴백
        """
        redis_url = os.getenv("REDIS_URL")

        if not redis_url:
            logger.warning(
                "⚠️ REDIS_URL 환경변수 없음, MemoryCacheManager로 폴백"
            )
            return CacheFactory._create_memory_cache(config, cache_config)

        try:
            # Redis 캐시 구현 (향후 확장)
            # 현재는 RedisCacheManager를 직접 생성하지 않고 폴백 처리
            # 추후 redis-py 클라이언트 생성 및 RedisCacheManager 인스턴스화 구현 필요
            # from .redis_cache import RedisCacheManager
            # redis_client = Redis.from_url(redis_url)
            # return RedisCacheManager(redis_client=redis_client, ...)
            logger.warning(
                "⚠️ RedisCacheManager 직접 생성 미구현, MemoryCacheManager로 폴백"
            )
            return CacheFactory._create_memory_cache(config, cache_config)
        except Exception as e:
            logger.warning(f"⚠️ Redis 연결 실패: {e}, MemoryCacheManager로 폴백")
            return CacheFactory._create_memory_cache(config, cache_config)

    @staticmethod
    def _create_semantic_cache(
        config: dict[str, Any],
        cache_config: dict[str, Any],
        embedder: Any,
    ) -> InMemorySemanticCache:
        """Semantic 캐시 생성"""
        semantic_config = cache_config.get("semantic", {})
        defaults = SUPPORTED_CACHES["semantic"]["default_config"]

        cache_config_obj = SemanticCacheConfig(
            similarity_threshold=semantic_config.get(
                "similarity_threshold", defaults["similarity_threshold"]
            ),
            max_entries=semantic_config.get("max_entries", defaults["max_entries"]),
            ttl_seconds=semantic_config.get("ttl", defaults["ttl"]),
        )

        cache = InMemorySemanticCache(
            embedder=embedder,
            config=cache_config_obj,
        )

        logger.info(
            f"✅ InMemorySemanticCache 생성: "
            f"threshold={cache_config_obj.similarity_threshold}, "
            f"max_entries={cache_config_obj.max_entries}"
        )
        return cache

    @staticmethod
    def get_supported_caches() -> list[str]:
        """지원하는 모든 캐시 이름 반환"""
        return list(SUPPORTED_CACHES.keys())

    @staticmethod
    def list_caches_by_type(cache_type: str) -> list[str]:
        """
        타입별 캐시 목록 반환

        Args:
            cache_type: 캐시 타입 (local, distributed, semantic)

        Returns:
            해당 타입의 캐시 이름 리스트
        """
        return [
            name
            for name, info in SUPPORTED_CACHES.items()
            if info["type"] == cache_type
        ]

    @staticmethod
    def get_cache_info(name: str) -> dict[str, Any] | None:
        """
        특정 캐시의 상세 정보 반환

        Args:
            name: 캐시 이름

        Returns:
            캐시 정보 딕셔너리 또는 None
        """
        return SUPPORTED_CACHES.get(name)
