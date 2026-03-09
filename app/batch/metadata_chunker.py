"""
메타데이터 기반 청킹 파이프라인

구조화된 데이터 속성에서 자연어 콘텐츠를 추출하고
의미 단위로 청킹하여 벡터 저장소에 업로드하기 위한 모듈

청킹 규칙:
1. 섹션 구분자: ————————————— (대시 8개 이상)
2. 섹션 헤더: [정책 규정], [프로모션] 등 대괄호
3. 불릿 리스트: •, - 로 시작하는 항목
4. 청크 크기: ~1,000 토큰 (약 2,000자)
5. 오버랩: 150 토큰 (약 300자)

작성일: 2025-12-03
"""

import re
import time
from dataclasses import dataclass, field

from app.lib.logger import get_logger

logger = get_logger(__name__)


# =============================================================================
# 상수 정의
# =============================================================================

# 섹션 분류 기준 키워드 (기본값)
DEFAULT_SECTION_KEYWORDS: dict[str, list[str]] = {
    "정책": ["취소", "환불", "변경", "패널티"],
    "비용": ["원본", "수정본", "추가금", "비용", "가격", "원", "만원"],
    "구성": ["항목", "구성", "세부", "전체"],
    "혜택": ["프로모션", "혜택", "서비스", "이벤트", "할인", "적용"],
    "위치": ["위치", "주소", "주차", "역", "역세권"],
    "기타": [],  # 분류 안 되면 기타
}

# 토큰 추정 (한글 1자 ≈ 2토큰)
CHARS_PER_TOKEN = 2
MAX_CHUNK_CHARS = 1000 * CHARS_PER_TOKEN  # 약 1,000 토큰
OVERLAP_CHARS = 150 * CHARS_PER_TOKEN  # 약 150 토큰


# =============================================================================
# 데이터 클래스
# =============================================================================


@dataclass
class ChunkMetadata:
    """
    청크 메타데이터

    Weaviate에 저장될 청크의 메타데이터
    """

    entity_id: str  # 고유 ID
    entity_name: str  # 항목명
    category: str  # 카테고리
    section: str  # 섹션 분류 (정책, 비용, 구성 등)
    source_field: str  # 원본 속성 필드명
    chunk_index: int  # 청크 순서
    total_chunks: int  # 전체 청크 수
    token_estimate: int  # 추정 토큰 수


@dataclass
class Chunk:
    """
    청크 데이터

    실제 텍스트 + 메타데이터
    """

    content: str  # 청크 텍스트
    metadata: ChunkMetadata  # 메타데이터


@dataclass
class ChunkingResult:
    """
    청킹 결과

    전체 청킹 처리 결과
    """

    entity_name: str
    total_chunks: int
    chunks: list[Chunk] = field(default_factory=list)
    sections_found: list[str] = field(default_factory=list)
    processing_time_ms: float = 0.0


# =============================================================================
# 섹션 분류기
# =============================================================================


def classify_section(text: str, section_keywords: dict[str, list[str]] | None = None) -> str:
    """
    텍스트를 섹션으로 분류

    키워드 매칭을 통해 해당 청크가 어떤 섹션에 속하는지 판별

    Args:
        text: 분류할 텍스트
        section_keywords: 섹션 분류 키워드 딕셔너리

    Returns:
        섹션명
    """
    text_lower = text.lower()
    keywords_dict = section_keywords or DEFAULT_SECTION_KEYWORDS

    # 각 섹션별 점수 계산
    scores: dict[str, int] = {}
    for section, keywords in keywords_dict.items():
        if not keywords:  # "기타"는 키워드 없음
            continue
        score = sum(1 for kw in keywords if kw in text_lower)
        if score > 0:
            scores[section] = score

    # 가장 높은 점수의 섹션 반환
    if scores:
        return max(scores, key=lambda k: scores[k])

    return "기타"


def extract_section_header(text: str) -> str | None:
    """
    대괄호로 감싼 섹션 헤더 추출

    예: [정책 규정], [프로모션]

    Args:
        text: 텍스트

    Returns:
        섹션 헤더 또는 None
    """
    match = re.search(r"\[([^\]]+)\]", text)
    if match:
        return match.group(1).strip()
    return None


# =============================================================================
# 텍스트 분할기
# =============================================================================


def split_by_delimiter(text: str, delimiter_pattern: str = r"[—]{4,}|[-]{8,}") -> list[str]:
    """
    구분자로 텍스트 분할

    구조화 데이터에서 자주 사용되는 구분자:
    - ———————————— (대시 여러 개)
    - -------- (하이픈 여러 개)

    Args:
        text: 분할할 텍스트
        delimiter_pattern: 정규식 구분자 패턴

    Returns:
        분할된 텍스트 리스트
    """
    # 구분자로 분할
    sections = re.split(delimiter_pattern, text)

    # 빈 섹션 제거 및 트리밍
    return [s.strip() for s in sections if s.strip()]


def split_by_section_header(text: str) -> list[tuple[str, str]]:
    """
    섹션 헤더([...])로 텍스트 분할

    Args:
        text: 분할할 텍스트

    Returns:
        [(섹션명, 내용)] 리스트
    """
    # 대괄호 섹션 헤더 패턴
    pattern = r"(\[[^\]]+\])"
    parts = re.split(pattern, text)

    results: list[tuple[str, str]] = []
    current_header = "일반"

    for part in parts:
        part = part.strip()
        if not part:
            continue

        # 헤더인 경우
        if re.match(r"^\[[^\]]+\]$", part):
            current_header = part.strip("[]")
        else:
            # 내용인 경우
            results.append((current_header, part))

    return results


def split_into_chunks(
    text: str,
    max_chars: int = MAX_CHUNK_CHARS,
    overlap_chars: int = OVERLAP_CHARS,
) -> list[str]:
    """
    텍스트를 최대 크기 + 오버랩으로 청킹

    Args:
        text: 분할할 텍스트
        max_chars: 최대 청크 크기 (문자 수)
        overlap_chars: 오버랩 크기 (문자 수)

    Returns:
        청크 리스트
    """
    if len(text) <= max_chars:
        return [text]

    chunks: list[str] = []
    start = 0

    while start < len(text):
        # 청크 끝 위치
        end = start + max_chars

        if end >= len(text):
            # 마지막 청크
            chunks.append(text[start:])
            break

        # 문장/줄 경계에서 자르기 시도
        # 우선순위: 줄바꿈 > 마침표 > 불릿
        cut_patterns = ["\n", ".", "•", "-"]

        best_cut = end
        for pattern in cut_patterns:
            # 청크 끝 부근에서 구분자 찾기
            search_start = max(start + max_chars - 200, start)
            pos = text.rfind(pattern, search_start, end)
            if pos > start:
                best_cut = pos + 1  # 구분자 포함
                break

        chunks.append(text[start:best_cut].strip())

        # 다음 시작점 (오버랩 적용)
        start = max(best_cut - overlap_chars, best_cut)

    return chunks


# =============================================================================
# 메인 청킹 파이프라인
# =============================================================================


class MetadataChunker:
    """
    메타데이터 기반 청킹 파이프라인

    구조화된 데이터 속성에서 자연어 콘텐츠를 추출하고
    의미 단위로 청킹
    """

    def __init__(
        self,
        max_chunk_chars: int = MAX_CHUNK_CHARS,
        overlap_chars: int = OVERLAP_CHARS,
        target_fields: list[str] | None = None,
        section_keywords: dict[str, list[str]] | None = None,
    ):
        """
        청커 초기화

        Args:
            max_chunk_chars: 최대 청크 크기 (문자)
            overlap_chars: 오버랩 크기 (문자)
            target_fields: 청킹 대상 속성 필드 목록
            section_keywords: 섹션 분류 키워드 딕셔너리
        """
        self.max_chunk_chars = max_chunk_chars
        self.overlap_chars = overlap_chars
        self.target_fields = target_fields or [
            "비용",
            "정책",
            "구성",
            "혜택",
        ]
        self.section_keywords = section_keywords or DEFAULT_SECTION_KEYWORDS

        logger.info(
            f"MetadataChunker 초기화: max={max_chunk_chars}자, overlap={overlap_chars}자, "
            f"target_fields={len(self.target_fields)}개, section_keywords={len(self.section_keywords)}개"
        )

    def _extract_content_from_properties(
        self,
        properties: dict,
    ) -> list[tuple[str, str]]:
        """
        속성에서 청킹 대상 콘텐츠 추출

        Args:
            properties: 구조화된 데이터 속성

        Returns:
            [(필드명, 콘텐츠)] 리스트
        """
        results: list[tuple[str, str]] = []

        for field_name, value in properties.items():
            # 청킹 대상 필드만 처리
            is_target = any(target in field_name for target in self.target_fields)
            if not is_target:
                continue

            # 값 추출
            if isinstance(value, str) and value.strip():
                results.append((field_name, value.strip()))
            elif isinstance(value, list):
                # 파일 목록 등은 건너뛰기
                continue

        return results

    def _chunk_field_content(
        self,
        field_name: str,
        content: str,
        entity_id: str,
        entity_name: str,
        category: str,
    ) -> list[Chunk]:
        """
        단일 필드 콘텐츠를 청킹

        Args:
            field_name: 속성 필드명
            content: 콘텐츠 텍스트
            entity_id: 항목 ID
            entity_name: 항목명
            category: 카테고리

        Returns:
            청크 리스트
        """
        chunks: list[Chunk] = []

        # 1단계: 구분자로 분할
        sections = split_by_delimiter(content)

        # 2단계: 각 섹션을 추가 청킹
        all_text_chunks: list[tuple[str, str]] = []  # (섹션명, 텍스트)

        for section_text in sections:
            # 섹션 헤더로 추가 분할
            header_sections = split_by_section_header(section_text)

            if header_sections:
                for _header, text in header_sections:
                    # 크기 제한 적용
                    sub_chunks = split_into_chunks(text, self.max_chunk_chars, self.overlap_chars)
                    for sub_chunk in sub_chunks:
                        section_class = classify_section(sub_chunk, self.section_keywords)
                        all_text_chunks.append((section_class, sub_chunk))
            else:
                # 헤더 없이 그냥 분할
                sub_chunks = split_into_chunks(
                    section_text, self.max_chunk_chars, self.overlap_chars
                )
                for sub_chunk in sub_chunks:
                    section_class = classify_section(sub_chunk, self.section_keywords)
                    all_text_chunks.append((section_class, sub_chunk))

        # 3단계: Chunk 객체 생성
        total_chunks = len(all_text_chunks)

        for idx, (section, text) in enumerate(all_text_chunks):
            # 항목명 prefix 추가
            prefixed_content = f"[{entity_name}] {text}"

            metadata = ChunkMetadata(
                entity_id=entity_id,
                entity_name=entity_name,
                category=category,
                section=section,
                source_field=field_name,
                chunk_index=idx,
                total_chunks=total_chunks,
                token_estimate=len(text) // CHARS_PER_TOKEN,
            )

            chunks.append(Chunk(content=prefixed_content, metadata=metadata))

        return chunks

    def chunk_entity_data(
        self,
        entity_id: str,
        entity_name: str,
        category: str,
        properties: dict,
    ) -> ChunkingResult:
        """
        항목 데이터를 청킹

        Args:
            entity_id: 항목 고유 ID
            entity_name: 항목명
            category: 카테고리
            properties: 구조화된 데이터 속성

        Returns:
            ChunkingResult 객체
        """
        start_time = time.time()

        # 콘텐츠 추출
        contents = self._extract_content_from_properties(properties)

        if not contents:
            logger.warning(f"청킹 대상 콘텐츠 없음: {entity_name}")
            return ChunkingResult(
                entity_name=entity_name,
                total_chunks=0,
                chunks=[],
                sections_found=[],
                processing_time_ms=0,
            )

        # 각 필드별 청킹
        all_chunks: list[Chunk] = []
        sections_found: set[str] = set()

        for field_name, content in contents:
            field_chunks = self._chunk_field_content(
                field_name=field_name,
                content=content,
                entity_id=entity_id,
                entity_name=entity_name,
                category=category,
            )
            all_chunks.extend(field_chunks)

            # 발견된 섹션 추적
            for chunk in field_chunks:
                sections_found.add(chunk.metadata.section)

        elapsed_ms = (time.time() - start_time) * 1000

        logger.info(
            f"✅ 청킹 완료: {entity_name} → {len(all_chunks)}개 청크, "
            f"섹션: {list(sections_found)}, {elapsed_ms:.1f}ms"
        )

        return ChunkingResult(
            entity_name=entity_name,
            total_chunks=len(all_chunks),
            chunks=all_chunks,
            sections_found=list(sections_found),
            processing_time_ms=elapsed_ms,
        )


# =============================================================================
# 테스트 함수
# =============================================================================


def test_chunker():
    """청커 테스트"""
    properties = {
        "내용": """샘플 데이터 내용입니다.
다양한 서비스 옵션을 제공합니다.
""",
    }

    chunker = MetadataChunker()
    result = chunker.chunk_entity_data(
        entity_id="test-001",
        entity_name="샘플 항목",
        category="샘플 카테고리",
        properties=properties,
    )

    print(f"\n{'='*60}")
    print(f"테스트 결과: {result.entity_name}")
    print(f"{'='*60}")
    print(f"총 청크 수: {result.total_chunks}")
    print(f"발견된 섹션: {result.sections_found}")
    print(f"처리 시간: {result.processing_time_ms:.1f}ms")


if __name__ == "__main__":
    test_chunker()
