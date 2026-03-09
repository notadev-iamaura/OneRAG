"""
개인정보 보호 모듈 (통합 PII 처리)

모든 PII 처리 시나리오를 하나의 인터페이스로 통합:

주요 컴포넌트:
- PIIProcessor: 통합 Facade (권장 진입점)
- PrivacyMasker: 마스킹 엔진
- WhitelistManager: 화이트리스트 관리자

처리 모드:
- "answer": RAG 답변 마스킹 (실시간, 경량)
- "document": 배치 문서 전처리 (전체 파이프라인)
- "filename": 파일명 마스킹 (API 응답용)

마스킹 대상:
- 개인 전화번호 (010-XXXX-XXXX)
- 한글 이름 (고객/담당자/관리자명)

비마스킹 대상:
- 사업자 전화번호 (지역번호 시작: 02, 031 등)
- 화이트리스트 단어 (담당, 고객, 관리자 등)

사용 예시:
    # 권장: Facade 사용
    >>> from app.modules.core.privacy import PIIProcessor, process_pii
    >>> processor = PIIProcessor()
    >>> result = processor.process("연락처: 010-1234-5678", mode="answer")
    >>> print(result.masked_text)  # "연락처: 010-****-5678"

    # 편의 함수 사용
    >>> result = process_pii("김철수 고객님", mode="answer")
    >>> print(result.masked_text)  # "김** 고객님"

    # 레거시: 직접 masker 사용 (하위 호환성)
    >>> from app.modules.core.privacy import PrivacyMasker
    >>> masker = PrivacyMasker()
    >>> masked = masker.mask_text("연락처: 010-1234-5678")

모듈 통합일: 2025-12-08
"""

# Facade (권장 진입점)
# 마스킹 엔진 (레거시 호환)
from .masker import MaskingResult, PrivacyMasker
from .processor import (
    PIIProcessor,
    PIIProcessResult,
    ProcessMode,
    get_pii_processor,
    process_pii,
    reset_pii_processor,
)

# 화이트리스트 관리자
from .whitelist import (
    DEFAULT_WHITELIST,
    WhitelistManager,
    get_whitelist_manager,
    reset_whitelist_manager,
)

__all__ = [
    # Facade (권장)
    "PIIProcessor",
    "PIIProcessResult",
    "ProcessMode",
    "get_pii_processor",
    "process_pii",
    "reset_pii_processor",
    # 마스킹 엔진 (레거시 호환)
    "PrivacyMasker",
    "MaskingResult",
    # 화이트리스트
    "WhitelistManager",
    "DEFAULT_WHITELIST",
    "get_whitelist_manager",
    "reset_whitelist_manager",
]
