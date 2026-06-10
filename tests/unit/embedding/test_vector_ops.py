"""
임베딩 벡터 연산 공용 유틸 테스트 (보류②(a) 개선)

목적:
    두 임베더에 중복 정의돼 있던 _l2_norm을 공용 l2_norm으로 추출한 뒤,
    값이 정확히 보존되는지 검증한다. 정규화 본체는 의도적으로 다르므로
    추출하지 않았고, 공통 분모인 L2 노름만 공유한다.
"""

from __future__ import annotations

import math

import pytest

from app.modules.core.embedding.vector_ops import l2_norm


def test_l2_norm_basic() -> None:
    """L2 노름이 유클리드 길이와 일치해야 한다."""
    assert l2_norm([3.0, 4.0]) == pytest.approx(5.0)
    assert l2_norm([0.0, 0.0]) == 0.0
    assert l2_norm([1.0]) == pytest.approx(1.0)


def test_l2_norm_matches_math_formula() -> None:
    """추출 전 인라인 공식과 부동소수점 단위로 동일해야 한다."""
    vec = [0.1, -0.2, 0.3, 0.4, -0.5]
    expected = math.sqrt(sum(v * v for v in vec))
    assert l2_norm(vec) == expected


def test_both_embedders_share_same_l2_norm() -> None:
    """두 임베더가 공용 l2_norm을 alias로 가리켜 동일 함수를 쓴다."""
    from app.modules.core.embedding import gemini_embedder, openai_embedder

    # 두 모듈의 _l2_norm은 공용 l2_norm과 동일 객체여야 한다 (중복 제거 확인)
    assert gemini_embedder._l2_norm is l2_norm
    assert openai_embedder._l2_norm is l2_norm


def test_normalization_bodies_remain_distinct() -> None:
    """정규화 본체는 의도적으로 달라야 한다 (OpenAI만 norm≈1 생략)."""
    from app.modules.core.embedding.openai_embedder import _normalize_vector_values

    # 이미 정규화된 벡터(norm≈1)는 OpenAI에서 원본 그대로 반환 (재계산 생략)
    unit = [0.6, 0.8]  # norm = 1.0
    assert _normalize_vector_values(unit) is unit
