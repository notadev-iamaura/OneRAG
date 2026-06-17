"""
Chunking Strategies - 문서 청킹 전략 모듈

문서를 청크로 분할하는 다양한 전략을 제공:
- BaseChunker: 추상 베이스 클래스
- SimpleChunker: 1:1 매핑 청킹 (FAQ용)
- SemanticChunker: 의미 기반 청킹 (Guidebook용, Phase 2)
- ConversationChunker: 대화 로그 청킹 (Phase 2)

사용 예시:
    from app.modules.core.documents.chunking import SimpleChunker

    chunker = SimpleChunker()
    chunks = chunker.chunk(document)
"""

from .base import BaseChunker
from .simple_chunker import SimpleChunker

__all__ = [
    "BaseChunker",
    "SimpleChunker",
]
