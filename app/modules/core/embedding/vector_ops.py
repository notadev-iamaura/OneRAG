"""
임베딩 벡터 연산 공용 유틸리티

여러 임베더(Gemini, OpenAI 등)가 공통으로 쓰는 순수 벡터 연산을 모은 모듈입니다.

주의:
    여기에는 "구현이 완전히 동일한" 순수 함수만 둡니다. 정규화 본체
    (_normalize_vector 등)는 임베더별로 동작이 의도적으로 다르므로
    (예: OpenAI는 이미 정규화된 벡터를 반환해 재계산을 생략) 각 임베더에
    그대로 두고, 여기서는 공통 분모인 L2 노름 계산만 공유합니다.
"""

import math


def l2_norm(vector: list[float]) -> float:
    """벡터의 L2 노름(유클리드 길이)을 계산한다."""
    return math.sqrt(sum(value * value for value in vector))
