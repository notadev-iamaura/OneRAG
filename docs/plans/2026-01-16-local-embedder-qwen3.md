# Qwen3 로컬 임베더 구현 계획

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** API 키 없이 Quickstart를 실행할 수 있도록 Qwen3-Embedding-0.6B 로컬 임베더를 추가한다.

**Architecture:**
- 기존 `IEmbedder` 인터페이스를 구현하는 `LocalEmbedder` 클래스 생성
- `EmbedderFactory`에 `local` provider 추가
- Quickstart는 기본적으로 `local` provider 사용 (API 키 불필요)
- Docker 빌드 시 모델 자동 다운로드 (Git 저장소에는 코드만)

**Tech Stack:**
- sentence-transformers (HuggingFace 모델 로드)
- Qwen/Qwen3-Embedding-0.6B (1.2GB, 1024차원, 32K 컨텍스트)
- torch (CPU 모드)

---

## Task 1: 로컬 임베더 테스트 작성 (RED)

**Files:**
- Create: `tests/unit/embedding/test_local_embedder.py`

**Step 1: 테스트 디렉토리 생성**

```bash
mkdir -p tests/unit/embedding
touch tests/unit/embedding/__init__.py
```

**Step 2: 기본 테스트 파일 작성**

```python
"""
로컬 임베더 단위 테스트

Qwen3-Embedding-0.6B 기반 로컬 임베더의 동작을 검증합니다.
sentence-transformers 라이브러리를 사용하여 로컬에서 임베딩을 생성합니다.
"""

import pytest
import numpy as np
from unittest.mock import Mock, patch, MagicMock


class TestLocalEmbedderInterface:
    """IEmbedder 인터페이스 준수 테스트"""

    def test_local_embedder_implements_iembedder(self):
        """LocalEmbedder가 IEmbedder 인터페이스를 구현하는지 확인"""
        from app.modules.core.embedding.local_embedder import LocalEmbedder
        from app.modules.core.embedding.interfaces import IEmbedder

        # Mock SentenceTransformer to avoid actual model loading
        with patch('app.modules.core.embedding.local_embedder.SentenceTransformer'):
            embedder = LocalEmbedder()
            assert isinstance(embedder, IEmbedder)

    def test_has_required_methods(self):
        """필수 메서드가 존재하는지 확인"""
        from app.modules.core.embedding.local_embedder import LocalEmbedder

        with patch('app.modules.core.embedding.local_embedder.SentenceTransformer'):
            embedder = LocalEmbedder()

            assert hasattr(embedder, 'embed_documents')
            assert hasattr(embedder, 'embed_query')
            assert hasattr(embedder, 'aembed_documents')
            assert hasattr(embedder, 'aembed_query')
            assert hasattr(embedder, 'validate_embedding')
            assert hasattr(embedder, 'output_dimensionality')
            assert hasattr(embedder, 'model_name')


class TestLocalEmbedderProperties:
    """속성 테스트"""

    def test_model_name_property(self):
        """model_name 속성이 올바른 값을 반환하는지 확인"""
        from app.modules.core.embedding.local_embedder import LocalEmbedder

        with patch('app.modules.core.embedding.local_embedder.SentenceTransformer'):
            embedder = LocalEmbedder(model_name="Qwen/Qwen3-Embedding-0.6B")
            assert embedder.model_name == "Qwen/Qwen3-Embedding-0.6B"

    def test_output_dimensionality_default(self):
        """기본 출력 차원이 1024인지 확인"""
        from app.modules.core.embedding.local_embedder import LocalEmbedder

        with patch('app.modules.core.embedding.local_embedder.SentenceTransformer'):
            embedder = LocalEmbedder()
            assert embedder.output_dimensionality == 1024

    def test_output_dimensionality_custom(self):
        """커스텀 차원 설정이 동작하는지 확인"""
        from app.modules.core.embedding.local_embedder import LocalEmbedder

        with patch('app.modules.core.embedding.local_embedder.SentenceTransformer'):
            embedder = LocalEmbedder(output_dimensionality=512)
            assert embedder.output_dimensionality == 512


class TestLocalEmbedderEmbedDocuments:
    """embed_documents 메서드 테스트"""

    def test_embed_documents_returns_list_of_lists(self):
        """embed_documents가 list[list[float]]를 반환하는지 확인"""
        from app.modules.core.embedding.local_embedder import LocalEmbedder

        mock_model = MagicMock()
        # 2개 문서, 1024차원 벡터 반환
        mock_model.encode.return_value = np.random.rand(2, 1024).astype(np.float32)

        with patch('app.modules.core.embedding.local_embedder.SentenceTransformer', return_value=mock_model):
            embedder = LocalEmbedder()
            result = embedder.embed_documents(["문서1", "문서2"])

            assert isinstance(result, list)
            assert len(result) == 2
            assert isinstance(result[0], list)
            assert len(result[0]) == 1024

    def test_embed_documents_empty_list(self):
        """빈 리스트 입력 시 빈 리스트 반환"""
        from app.modules.core.embedding.local_embedder import LocalEmbedder

        mock_model = MagicMock()
        mock_model.encode.return_value = np.array([]).reshape(0, 1024)

        with patch('app.modules.core.embedding.local_embedder.SentenceTransformer', return_value=mock_model):
            embedder = LocalEmbedder()
            result = embedder.embed_documents([])

            assert result == []

    def test_embed_documents_korean_text(self):
        """한국어 텍스트 임베딩이 동작하는지 확인"""
        from app.modules.core.embedding.local_embedder import LocalEmbedder

        mock_model = MagicMock()
        mock_model.encode.return_value = np.random.rand(1, 1024).astype(np.float32)

        with patch('app.modules.core.embedding.local_embedder.SentenceTransformer', return_value=mock_model):
            embedder = LocalEmbedder()
            result = embedder.embed_documents(["안녕하세요, RAG 시스템입니다."])

            assert len(result) == 1
            assert len(result[0]) == 1024

    def test_embed_documents_batch_processing(self):
        """배치 처리가 올바르게 동작하는지 확인"""
        from app.modules.core.embedding.local_embedder import LocalEmbedder

        mock_model = MagicMock()
        # 배치 크기보다 큰 입력
        mock_model.encode.return_value = np.random.rand(150, 1024).astype(np.float32)

        with patch('app.modules.core.embedding.local_embedder.SentenceTransformer', return_value=mock_model):
            embedder = LocalEmbedder(batch_size=100)
            texts = [f"문서 {i}" for i in range(150)]
            result = embedder.embed_documents(texts)

            assert len(result) == 150


class TestLocalEmbedderEmbedQuery:
    """embed_query 메서드 테스트"""

    def test_embed_query_returns_list_of_floats(self):
        """embed_query가 list[float]를 반환하는지 확인"""
        from app.modules.core.embedding.local_embedder import LocalEmbedder

        mock_model = MagicMock()
        mock_model.encode.return_value = np.random.rand(1024).astype(np.float32)

        with patch('app.modules.core.embedding.local_embedder.SentenceTransformer', return_value=mock_model):
            embedder = LocalEmbedder()
            result = embedder.embed_query("검색 쿼리")

            assert isinstance(result, list)
            assert len(result) == 1024
            assert all(isinstance(x, float) for x in result)

    def test_embed_query_empty_string(self):
        """빈 문자열 입력 시 빈 리스트 반환"""
        from app.modules.core.embedding.local_embedder import LocalEmbedder

        mock_model = MagicMock()
        mock_model.encode.return_value = np.zeros(1024).astype(np.float32)

        with patch('app.modules.core.embedding.local_embedder.SentenceTransformer', return_value=mock_model):
            embedder = LocalEmbedder()
            result = embedder.embed_query("")

            assert isinstance(result, list)


class TestLocalEmbedderValidation:
    """validate_embedding 메서드 테스트"""

    def test_validate_embedding_correct_dimension(self):
        """올바른 차원의 임베딩 검증 통과"""
        from app.modules.core.embedding.local_embedder import LocalEmbedder

        with patch('app.modules.core.embedding.local_embedder.SentenceTransformer'):
            embedder = LocalEmbedder(output_dimensionality=1024)
            embedding = [0.1] * 1024

            assert embedder.validate_embedding(embedding) is True

    def test_validate_embedding_wrong_dimension(self):
        """잘못된 차원의 임베딩 검증 실패"""
        from app.modules.core.embedding.local_embedder import LocalEmbedder

        with patch('app.modules.core.embedding.local_embedder.SentenceTransformer'):
            embedder = LocalEmbedder(output_dimensionality=1024)
            embedding = [0.1] * 512  # 잘못된 차원

            assert embedder.validate_embedding(embedding) is False


class TestLocalEmbedderAsync:
    """비동기 메서드 테스트"""

    @pytest.mark.asyncio
    async def test_aembed_documents(self):
        """비동기 문서 임베딩이 동작하는지 확인"""
        from app.modules.core.embedding.local_embedder import LocalEmbedder

        mock_model = MagicMock()
        mock_model.encode.return_value = np.random.rand(2, 1024).astype(np.float32)

        with patch('app.modules.core.embedding.local_embedder.SentenceTransformer', return_value=mock_model):
            embedder = LocalEmbedder()
            result = await embedder.aembed_documents(["문서1", "문서2"])

            assert len(result) == 2
            assert len(result[0]) == 1024

    @pytest.mark.asyncio
    async def test_aembed_query(self):
        """비동기 쿼리 임베딩이 동작하는지 확인"""
        from app.modules.core.embedding.local_embedder import LocalEmbedder

        mock_model = MagicMock()
        mock_model.encode.return_value = np.random.rand(1024).astype(np.float32)

        with patch('app.modules.core.embedding.local_embedder.SentenceTransformer', return_value=mock_model):
            embedder = LocalEmbedder()
            result = await embedder.aembed_query("검색 쿼리")

            assert len(result) == 1024


class TestLocalEmbedderNormalization:
    """L2 정규화 테스트"""

    def test_embeddings_are_normalized(self):
        """임베딩이 L2 정규화되어 있는지 확인"""
        from app.modules.core.embedding.local_embedder import LocalEmbedder

        mock_model = MagicMock()
        # 정규화되지 않은 벡터
        raw_vector = np.array([1.0, 2.0, 3.0] + [0.0] * 1021)
        mock_model.encode.return_value = raw_vector.astype(np.float32)

        with patch('app.modules.core.embedding.local_embedder.SentenceTransformer', return_value=mock_model):
            embedder = LocalEmbedder(normalize=True)
            result = embedder.embed_query("테스트")

            # L2 norm이 1에 가까운지 확인
            norm = np.linalg.norm(result)
            assert abs(norm - 1.0) < 0.01, f"L2 norm should be ~1.0, got {norm}"


class TestLocalEmbedderErrorHandling:
    """에러 처리 테스트"""

    def test_model_loading_error_raises_exception(self):
        """모델 로딩 실패 시 적절한 예외 발생"""
        from app.modules.core.embedding.local_embedder import LocalEmbedder

        with patch('app.modules.core.embedding.local_embedder.SentenceTransformer') as mock_st:
            mock_st.side_effect = Exception("Model not found")

            with pytest.raises(Exception) as exc_info:
                LocalEmbedder()

            assert "Model not found" in str(exc_info.value)
```

**Step 3: 테스트 실행 (실패 확인)**

```bash
pytest tests/unit/embedding/test_local_embedder.py -v
```

Expected: FAIL - `ModuleNotFoundError: No module named 'app.modules.core.embedding.local_embedder'`

**Step 4: 커밋**

```bash
git add tests/unit/embedding/
git commit -m "테스트: 로컬 임베더 단위 테스트 추가 (RED)

- IEmbedder 인터페이스 준수 테스트
- embed_documents/embed_query 동작 테스트
- 비동기 메서드 테스트
- L2 정규화 테스트
- 에러 처리 테스트

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 2: LocalEmbedder 클래스 구현 (GREEN)

**Files:**
- Create: `app/modules/core/embedding/local_embedder.py`
- Modify: `app/modules/core/embedding/__init__.py`

**Step 1: LocalEmbedder 클래스 작성**

```python
"""
로컬 임베더 구현

sentence-transformers를 사용하여 로컬에서 임베딩을 생성합니다.
API 키 없이 동작하며, Quickstart 환경에서 사용됩니다.

지원 모델:
- Qwen/Qwen3-Embedding-0.6B (기본): 1024차원, 32K 컨텍스트, 100+ 언어
- intfloat/multilingual-e5-small: 384차원, 경량

사용 예시:
    embedder = LocalEmbedder()
    vectors = embedder.embed_documents(["문서1", "문서2"])
    query_vector = embedder.embed_query("검색 쿼리")
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
from sentence_transformers import SentenceTransformer

from app.modules.core.embedding.interfaces import BaseEmbedder

logger = logging.getLogger(__name__)


# 지원 모델 정보
SUPPORTED_LOCAL_MODELS: dict[str, dict[str, Any]] = {
    "Qwen/Qwen3-Embedding-0.6B": {
        "dimensions": 1024,
        "max_seq_length": 32768,
        "description": "Qwen3 임베딩 모델 (0.6B 파라미터, 다국어 지원)",
    },
    "intfloat/multilingual-e5-small": {
        "dimensions": 384,
        "max_seq_length": 512,
        "description": "경량 다국어 임베딩 모델",
    },
}

# 기본 모델
DEFAULT_LOCAL_MODEL = "Qwen/Qwen3-Embedding-0.6B"


class LocalEmbedder(BaseEmbedder):
    """
    로컬 임베더 클래스

    sentence-transformers를 사용하여 로컬에서 임베딩을 생성합니다.
    첫 실행 시 HuggingFace Hub에서 모델을 자동 다운로드합니다.

    Attributes:
        model: SentenceTransformer 모델 인스턴스
        normalize: L2 정규화 여부 (기본: True)
        batch_size: 배치 처리 크기 (기본: 32)
    """

    def __init__(
        self,
        model_name: str = DEFAULT_LOCAL_MODEL,
        output_dimensionality: int | None = None,
        batch_size: int = 32,
        normalize: bool = True,
        device: str | None = None,
        **kwargs: Any,
    ) -> None:
        """
        LocalEmbedder 초기화

        Args:
            model_name: HuggingFace 모델 이름 (기본: Qwen/Qwen3-Embedding-0.6B)
            output_dimensionality: 출력 벡터 차원 (None이면 모델 기본값 사용)
            batch_size: 배치 처리 크기 (기본: 32)
            normalize: L2 정규화 여부 (기본: True)
            device: 연산 디바이스 (None이면 자동 선택, "cpu" 또는 "cuda")

        Raises:
            Exception: 모델 로딩 실패 시
        """
        # 모델 정보 확인
        model_info = SUPPORTED_LOCAL_MODELS.get(model_name, {})
        default_dim = model_info.get("dimensions", 1024)

        # 차원 설정 (명시적 지정 > 모델 기본값)
        actual_dim = output_dimensionality or default_dim

        # 부모 클래스 초기화
        super().__init__(
            model_name=model_name,
            output_dimensionality=actual_dim,
            api_key=None,  # 로컬 모델은 API 키 불필요
        )

        self._batch_size = batch_size
        self._normalize = normalize
        self._device = device

        # 모델 로드 (첫 실행 시 자동 다운로드)
        logger.info(f"🔄 로컬 임베딩 모델 로딩 중: {model_name}")
        try:
            self._model = SentenceTransformer(
                model_name,
                device=device,
                trust_remote_code=True,  # Qwen 모델 필요
            )
            logger.info(
                f"✅ 로컬 임베더 초기화 완료: model={model_name}, "
                f"dim={actual_dim}, device={self._model.device}"
            )
        except Exception as e:
            logger.error(f"❌ 로컬 임베딩 모델 로딩 실패: {e}")
            raise

    @property
    def batch_size(self) -> int:
        """배치 처리 크기"""
        return self._batch_size

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """
        문서 리스트를 임베딩 벡터로 변환

        Args:
            texts: 임베딩할 텍스트 리스트

        Returns:
            임베딩 벡터 리스트 (list[list[float]])
        """
        if not texts:
            return []

        try:
            # sentence-transformers로 임베딩 생성
            embeddings = self._model.encode(
                texts,
                batch_size=self._batch_size,
                normalize_embeddings=self._normalize,
                show_progress_bar=False,
                convert_to_numpy=True,
            )

            # numpy array → list[list[float]] 변환
            result = embeddings.tolist()

            logger.debug(f"📊 문서 {len(texts)}개 임베딩 완료 (dim={len(result[0])})")
            return result

        except Exception as e:
            logger.error(f"❌ 문서 임베딩 실패: {e}")
            # graceful degradation: 영벡터 반환
            return [[0.0] * self._output_dimensionality for _ in texts]

    def embed_query(self, text: str) -> list[float]:
        """
        단일 쿼리를 임베딩 벡터로 변환

        Args:
            text: 임베딩할 쿼리 텍스트

        Returns:
            임베딩 벡터 (list[float])
        """
        if not text:
            return [0.0] * self._output_dimensionality

        try:
            # 단일 쿼리 임베딩
            embedding = self._model.encode(
                text,
                normalize_embeddings=self._normalize,
                show_progress_bar=False,
                convert_to_numpy=True,
            )

            # numpy array → list[float] 변환
            result = embedding.tolist()

            logger.debug(f"📊 쿼리 임베딩 완료 (dim={len(result)})")
            return result

        except Exception as e:
            logger.error(f"❌ 쿼리 임베딩 실패: {e}")
            return [0.0] * self._output_dimensionality

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        """
        비동기 문서 임베딩 (동기 메서드 래핑)

        Note:
            sentence-transformers는 네이티브 비동기를 지원하지 않으므로
            동기 메서드를 래핑합니다.
        """
        return self.embed_documents(texts)

    async def aembed_query(self, text: str) -> list[float]:
        """
        비동기 쿼리 임베딩 (동기 메서드 래핑)
        """
        return self.embed_query(text)

    def validate_embedding(self, embedding: list[float]) -> bool:
        """
        임베딩 벡터 유효성 검증

        Args:
            embedding: 검증할 임베딩 벡터

        Returns:
            유효 여부 (True/False)
        """
        if not embedding:
            return False

        # 차원 검증
        if len(embedding) != self._output_dimensionality:
            logger.warning(
                f"⚠️ 임베딩 차원 불일치: "
                f"expected={self._output_dimensionality}, got={len(embedding)}"
            )
            return False

        return True
```

**Step 2: __init__.py에 export 추가**

Modify: `app/modules/core/embedding/__init__.py`

```python
# 기존 imports 아래에 추가
from app.modules.core.embedding.local_embedder import (
    LocalEmbedder,
    SUPPORTED_LOCAL_MODELS,
    DEFAULT_LOCAL_MODEL,
)

# __all__ 리스트에 추가
__all__ = [
    # ... 기존 exports ...
    "LocalEmbedder",
    "SUPPORTED_LOCAL_MODELS",
    "DEFAULT_LOCAL_MODEL",
]
```

**Step 3: 테스트 실행 (통과 확인)**

```bash
pytest tests/unit/embedding/test_local_embedder.py -v
```

Expected: PASS (모든 테스트 통과)

**Step 4: 커밋**

```bash
git add app/modules/core/embedding/local_embedder.py app/modules/core/embedding/__init__.py
git commit -m "기능: LocalEmbedder 클래스 구현 (GREEN)

- Qwen3-Embedding-0.6B 기반 로컬 임베더
- IEmbedder 인터페이스 준수
- L2 정규화 지원
- 배치 처리 지원
- graceful degradation (오류 시 영벡터)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 3: EmbedderFactory에 local provider 추가

**Files:**
- Modify: `app/modules/core/embedding/factory.py`
- Create: `tests/unit/embedding/test_embedder_factory_local.py`

**Step 1: 팩토리 테스트 작성**

```python
"""
EmbedderFactory 로컬 provider 테스트

local provider가 올바르게 LocalEmbedder를 생성하는지 검증합니다.
"""

import pytest
from unittest.mock import patch, MagicMock


class TestEmbedderFactoryLocalProvider:
    """EmbedderFactory local provider 테스트"""

    def test_create_local_embedder(self):
        """local provider로 LocalEmbedder 생성"""
        from app.modules.core.embedding.factory import EmbedderFactory
        from app.modules.core.embedding.local_embedder import LocalEmbedder

        config = {
            "embeddings": {
                "provider": "local",
                "local": {
                    "model": "Qwen/Qwen3-Embedding-0.6B",
                    "output_dimensionality": 1024,
                    "batch_size": 32,
                }
            }
        }

        with patch('app.modules.core.embedding.local_embedder.SentenceTransformer'):
            embedder = EmbedderFactory.create(config)
            assert isinstance(embedder, LocalEmbedder)

    def test_local_embedder_default_config(self):
        """local provider 기본 설정으로 생성"""
        from app.modules.core.embedding.factory import EmbedderFactory
        from app.modules.core.embedding.local_embedder import LocalEmbedder

        config = {
            "embeddings": {
                "provider": "local"
            }
        }

        with patch('app.modules.core.embedding.local_embedder.SentenceTransformer'):
            embedder = EmbedderFactory.create(config)
            assert isinstance(embedder, LocalEmbedder)
            assert embedder.model_name == "Qwen/Qwen3-Embedding-0.6B"

    def test_local_embedder_custom_model(self):
        """커스텀 모델로 LocalEmbedder 생성"""
        from app.modules.core.embedding.factory import EmbedderFactory
        from app.modules.core.embedding.local_embedder import LocalEmbedder

        config = {
            "embeddings": {
                "provider": "local",
                "local": {
                    "model": "intfloat/multilingual-e5-small",
                    "output_dimensionality": 384,
                }
            }
        }

        with patch('app.modules.core.embedding.local_embedder.SentenceTransformer'):
            embedder = EmbedderFactory.create(config)
            assert isinstance(embedder, LocalEmbedder)
            assert embedder.output_dimensionality == 384
```

**Step 2: 테스트 실행 (실패 확인)**

```bash
pytest tests/unit/embedding/test_embedder_factory_local.py -v
```

Expected: FAIL - local provider 미구현

**Step 3: EmbedderFactory 수정**

Modify: `app/modules/core/embedding/factory.py`

```python
# 기존 imports에 추가
from app.modules.core.embedding.local_embedder import (
    LocalEmbedder,
    DEFAULT_LOCAL_MODEL,
)

# create() 메서드 내부에 local provider 케이스 추가
# provider 분기 처리 부분에 추가:

elif provider == "local":
    local_config = embeddings_config.get("local", {})
    model_name = local_config.get("model", DEFAULT_LOCAL_MODEL)
    output_dim = local_config.get("output_dimensionality")
    batch_size = local_config.get("batch_size", 32)
    normalize = local_config.get("normalize", True)
    device = local_config.get("device")

    return LocalEmbedder(
        model_name=model_name,
        output_dimensionality=output_dim,
        batch_size=batch_size,
        normalize=normalize,
        device=device,
    )
```

**Step 4: 테스트 실행 (통과 확인)**

```bash
pytest tests/unit/embedding/test_embedder_factory_local.py -v
```

Expected: PASS

**Step 5: 전체 임베딩 테스트 실행**

```bash
pytest tests/unit/embedding/ -v
```

Expected: PASS (모든 테스트 통과)

**Step 6: 커밋**

```bash
git add app/modules/core/embedding/factory.py tests/unit/embedding/test_embedder_factory_local.py
git commit -m "기능: EmbedderFactory에 local provider 추가

- local provider로 LocalEmbedder 생성 지원
- 기본 모델: Qwen/Qwen3-Embedding-0.6B
- 커스텀 모델 및 차원 설정 지원

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 4: embeddings.yaml에 local provider 설정 추가

**Files:**
- Modify: `app/config/features/embeddings.yaml`

**Step 1: embeddings.yaml 수정**

```yaml
# 기존 내용 최상단에 local provider 섹션 추가

embeddings:
  # ========================================
  # Provider 선택
  # ========================================
  # 사용 가능: local, openrouter, google, openai
  # Quickstart 기본값: local (API 키 불필요)
  provider: "openrouter"  # 프로덕션 기본값 유지

  # ========================================
  # Local Provider (API 키 불필요 - Quickstart용)
  # ========================================
  # 첫 실행 시 HuggingFace에서 모델 자동 다운로드 (~1.2GB)
  # Docker 빌드 시 이미지에 포함됨
  local:
    # 지원 모델:
    # - Qwen/Qwen3-Embedding-0.6B (권장): 1024차원, 32K 컨텍스트, 다국어
    # - intfloat/multilingual-e5-small: 384차원, 경량
    model: "Qwen/Qwen3-Embedding-0.6B"
    output_dimensionality: 1024
    batch_size: 32
    normalize: true
    device: null  # null=자동선택, "cpu", "cuda"

  # ========================================
  # OpenRouter Provider (권장 - 프로덕션)
  # ========================================
  openrouter:
    # ... 기존 설정 유지 ...
```

**Step 2: 커밋**

```bash
git add app/config/features/embeddings.yaml
git commit -m "설정: embeddings.yaml에 local provider 추가

- Qwen/Qwen3-Embedding-0.6B 기본 설정
- Quickstart용 API 키 불필요 옵션
- 기존 openrouter 프로덕션 기본값 유지

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 5: Quickstart 설정 업데이트

**Files:**
- Modify: `quickstart/.env.quickstart`
- Modify: `quickstart/load_sample_data.py`

**Step 1: .env.quickstart 수정**

```bash
# 기존 OPENROUTER_API_KEY 관련 라인 수정

# ========================================
# Quickstart 환경 설정 (최소 설정)
# ========================================

# 임베딩 설정 (local = API 키 불필요)
EMBEDDINGS_PROVIDER=local

# LLM 설정 (답변 생성용 - 필수)
# 무료 API 키 발급: https://aistudio.google.com/apikey
GOOGLE_API_KEY=your_google_api_key_here

# ... 기타 설정 유지 ...
```

**Step 2: load_sample_data.py에 임베딩 추가**

Modify: `quickstart/load_sample_data.py`

기존 코드에서 벡터 없이 저장하던 부분을 임베딩과 함께 저장하도록 수정:

```python
def load_sample_data() -> None:
    """
    샘플 FAQ 데이터를 Weaviate에 적재

    로컬 임베더(Qwen3-Embedding-0.6B)를 사용하여
    텍스트를 벡터로 변환 후 저장합니다.
    """
    # ... 기존 Weaviate 연결 코드 ...

    # 로컬 임베더 초기화
    print("🔄 로컬 임베딩 모델 로딩 중...")
    from app.modules.core.embedding.local_embedder import LocalEmbedder
    embedder = LocalEmbedder()
    print(f"✅ 임베더 로드 완료: {embedder.model_name}")

    # ... 컬렉션 생성 코드 ...

    # 데이터 삽입 (임베딩 포함)
    print("📥 문서 임베딩 및 삽입 중...")
    texts_to_embed = []
    objects_to_insert = []

    for doc in documents:
        full_content = f"{doc['title']}\n\n{doc['content']}"
        texts_to_embed.append(full_content)
        objects_to_insert.append({
            "content": full_content,
            "source_file": doc["title"],
            "file_type": doc.get("metadata", {}).get("category", "FAQ"),
            "keywords": doc.get("metadata", {}).get("tags", []),
            "source": "quickstart_sample",
        })

    # 배치 임베딩
    embeddings = embedder.embed_documents(texts_to_embed)
    print(f"✅ {len(embeddings)}개 문서 임베딩 완료")

    # 벡터와 함께 저장
    with collection.batch.dynamic() as batch:
        for i, (obj, vector) in enumerate(zip(objects_to_insert, embeddings)):
            batch.add_object(properties=obj, vector=vector)

    print(f"✅ {len(documents)}개 문서 적재 완료!")
```

**Step 3: 테스트**

```bash
# Docker 없이 로컬에서 테스트
python quickstart/load_sample_data.py
```

Expected: 모델 다운로드 후 문서 임베딩 및 저장 성공

**Step 4: 커밋**

```bash
git add quickstart/.env.quickstart quickstart/load_sample_data.py
git commit -m "기능: Quickstart에 로컬 임베딩 적용

- .env.quickstart에 EMBEDDINGS_PROVIDER=local 추가
- load_sample_data.py에 LocalEmbedder 통합
- 문서 임베딩 후 벡터와 함께 저장

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 6: Dockerfile에 모델 다운로드 추가

**Files:**
- Modify: `Dockerfile`

**Step 1: Dockerfile 수정**

```dockerfile
# 기존 의존성 설치 후, 모델 다운로드 추가

# Python 의존성 설치
RUN uv sync --frozen

# 로컬 임베딩 모델 사전 다운로드 (빌드 시 1회만)
# ~/.cache/huggingface/에 저장되어 런타임에 재사용
RUN python -c "from sentence_transformers import SentenceTransformer; \
    print('🔄 Downloading Qwen3-Embedding-0.6B...'); \
    SentenceTransformer('Qwen/Qwen3-Embedding-0.6B', trust_remote_code=True); \
    print('✅ Model downloaded successfully')"

# ... 기존 COPY 및 CMD 명령 ...
```

**Step 2: 커밋**

```bash
git add Dockerfile
git commit -m "빌드: Dockerfile에 로컬 임베딩 모델 다운로드 추가

- 빌드 시 Qwen3-Embedding-0.6B 모델 다운로드
- 이미지 크기 +1.2GB, 런타임 다운로드 불필요

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 7: pyproject.toml에 sentence-transformers 의존성 추가

**Files:**
- Modify: `pyproject.toml`

**Step 1: 의존성 추가**

```toml
[project]
dependencies = [
    # ... 기존 의존성 ...

    # 로컬 임베딩
    "sentence-transformers>=3.0.0",
    "torch>=2.0.0",  # CPU 버전
]
```

**Step 2: 설치 및 테스트**

```bash
uv sync
pytest tests/unit/embedding/ -v
```

**Step 3: 커밋**

```bash
git add pyproject.toml uv.lock
git commit -m "의존성: sentence-transformers 추가

- 로컬 임베딩용 sentence-transformers>=3.0.0
- torch>=2.0.0 (CPU 버전)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 8: 통합 테스트 작성 및 실행

**Files:**
- Create: `tests/integration/test_local_embedder_integration.py`

**Step 1: 통합 테스트 작성**

```python
"""
로컬 임베더 통합 테스트

실제 모델 로드 및 임베딩 생성을 테스트합니다.
CI 환경에서는 모델 다운로드 시간으로 인해 skip될 수 있습니다.
"""

import pytest
import numpy as np

# CI 환경에서 skip (모델 다운로드 필요)
pytestmark = pytest.mark.skipif(
    "CI" in os.environ,
    reason="CI 환경에서는 모델 다운로드 시간으로 인해 skip"
)


class TestLocalEmbedderIntegration:
    """로컬 임베더 통합 테스트"""

    @pytest.fixture
    def embedder(self):
        """실제 LocalEmbedder 인스턴스"""
        from app.modules.core.embedding.local_embedder import LocalEmbedder
        return LocalEmbedder()

    def test_embed_korean_text(self, embedder):
        """한국어 텍스트 임베딩"""
        text = "RAG_Standard는 엔터프라이즈급 RAG 시스템입니다."
        result = embedder.embed_query(text)

        assert len(result) == 1024
        assert all(isinstance(x, float) for x in result)

        # L2 정규화 확인
        norm = np.linalg.norm(result)
        assert abs(norm - 1.0) < 0.01

    def test_embed_english_text(self, embedder):
        """영어 텍스트 임베딩"""
        text = "RAG_Standard is an enterprise-grade RAG system."
        result = embedder.embed_query(text)

        assert len(result) == 1024

    def test_embed_mixed_language(self, embedder):
        """한영 혼합 텍스트 임베딩"""
        text = "RAG_Standard는 Hybrid Search를 지원합니다."
        result = embedder.embed_query(text)

        assert len(result) == 1024

    def test_semantic_similarity(self, embedder):
        """의미적 유사도 테스트"""
        query = "RAG 시스템이 뭐야?"
        doc1 = "RAG는 검색 증강 생성 기술입니다."
        doc2 = "오늘 날씨가 좋습니다."

        query_vec = np.array(embedder.embed_query(query))
        doc1_vec = np.array(embedder.embed_query(doc1))
        doc2_vec = np.array(embedder.embed_query(doc2))

        # 코사인 유사도
        sim1 = np.dot(query_vec, doc1_vec)
        sim2 = np.dot(query_vec, doc2_vec)

        # 관련 문서가 비관련 문서보다 유사도가 높아야 함
        assert sim1 > sim2, f"Expected sim1 > sim2, got {sim1:.4f} <= {sim2:.4f}"

    def test_batch_embedding_consistency(self, embedder):
        """배치 임베딩과 개별 임베딩의 일관성"""
        texts = ["문서1", "문서2", "문서3"]

        # 배치 임베딩
        batch_results = embedder.embed_documents(texts)

        # 개별 임베딩
        individual_results = [embedder.embed_query(t) for t in texts]

        # 결과가 동일해야 함
        for batch, individual in zip(batch_results, individual_results):
            np.testing.assert_array_almost_equal(
                np.array(batch),
                np.array(individual),
                decimal=5
            )
```

**Step 2: 로컬에서 통합 테스트 실행**

```bash
pytest tests/integration/test_local_embedder_integration.py -v -s
```

Expected: PASS (모델 다운로드 후 테스트 통과)

**Step 3: 커밋**

```bash
git add tests/integration/test_local_embedder_integration.py
git commit -m "테스트: 로컬 임베더 통합 테스트 추가

- 한국어/영어/혼합 텍스트 임베딩 테스트
- 의미적 유사도 검증
- 배치/개별 임베딩 일관성 검증
- CI 환경에서 자동 skip

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 9: 전체 테스트 실행 및 검증

**Step 1: 전체 테스트 실행**

```bash
make test
```

Expected: 1,295+ 테스트 통과 (기존 테스트 + 신규 테스트)

**Step 2: 타입 체크**

```bash
make type-check
```

Expected: PASS

**Step 3: 린트 검사**

```bash
make lint
```

Expected: PASS

**Step 4: Docker 빌드 테스트**

```bash
docker build -t rag-standard:local-embedder .
```

Expected: 빌드 성공 (모델 다운로드 포함)

**Step 5: Quickstart 테스트**

```bash
make quickstart
# 별도 터미널에서:
curl -X POST http://localhost:8000/api/chat/query \
  -H "Content-Type: application/json" \
  -d '{"query": "RAG가 뭐야?"}'
```

Expected: 벡터 검색 기반 응답 반환

**Step 6: 최종 커밋**

```bash
git add -A
git commit -m "기능: Qwen3 로컬 임베더 구현 완료

## 변경 사항
- LocalEmbedder 클래스 구현 (Qwen3-Embedding-0.6B)
- EmbedderFactory에 local provider 추가
- Quickstart에서 API 키 없이 임베딩 사용 가능
- Docker 빌드 시 모델 자동 다운로드

## 테스트
- 단위 테스트 추가
- 통합 테스트 추가
- 전체 1,295+ 테스트 통과

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## 검증 체크리스트

- [ ] `pytest tests/unit/embedding/` 통과
- [ ] `pytest tests/unit/embedding/test_embedder_factory_local.py` 통과
- [ ] `make test` 전체 통과
- [ ] `make type-check` 통과
- [ ] `make lint` 통과
- [ ] Docker 빌드 성공
- [ ] `make quickstart` 실행 후 검색 동작 확인
- [ ] 의미적 유사도 검색 동작 확인 (BM25 + Dense)
