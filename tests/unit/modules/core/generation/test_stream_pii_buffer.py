"""
스트리밍 PII 마스킹 버퍼 결함 수정 검증 테스트 (P1)

검증 대상 결함:
    (1) 공백 전용 flush: 공백 없는 출력(일본어/중국어, 코드블록, 긴 URL)은
        스트림 종료까지 단 한 청크도 emit되지 않고 버퍼가 무한 증가한다.
    (2) 분할 경계 마스킹 유출: 한국어 이름 패턴은 공백을 가로질러
        lookahead하므로, 마지막 공백에서 분할하면 emit된 prefix에
        접미사 문맥이 없어 실명이 마스킹 없이 유출된다.

테스트 컨벤션:
    - AsyncMock 금지: 시그니처를 가진 가짜 객체(strict-signature 스텁) 사용
      (test_streaming_fallback_pii.py 픽스처 재사용/확장)
    - PrivacyMasker는 실제 구현 사용 (마스킹이 실제로 동작해야 의미 있는 테스트)
"""

from __future__ import annotations

from typing import Any

import pytest

from app.modules.core.generation.generator import GenerationModule
from app.modules.core.privacy.masker import PrivacyMasker


class _Delta:
    """LLM 스트림 청크의 delta 스텁"""

    def __init__(self, content: str) -> None:
        self.content = content


class _Choice:
    """LLM 스트림 청크의 choice 스텁"""

    def __init__(self, content: str) -> None:
        self.delta = _Delta(content)


class _Chunk:
    """LLM 스트림 청크 스텁"""

    def __init__(self, content: str) -> None:
        self.choices = [_Choice(content)]


def _build_gen(chunks: list[str], state: dict[str, bool] | None = None) -> GenerationModule:
    """
    스트리밍 테스트용 GenerationModule 스텁 빌더

    Args:
        chunks: LLM이 순서대로 내보낼 텍스트 청크 목록
        state: 입력 소진 추적용 가변 상태 딕셔너리.
               입력 청크가 모두 소비되면 state["input_done"] = True로 설정된다.

    Returns:
        실제 PrivacyMasker가 연결된 GenerationModule 인스턴스
    """
    gen = GenerationModule.__new__(GenerationModule)
    gen._privacy_enabled = True  # type: ignore[attr-defined]
    gen.privacy_masker = PrivacyMasker()  # type: ignore[attr-defined]
    gen.default_model = "m1"  # type: ignore[attr-defined]
    gen.auto_fallback = False  # type: ignore[attr-defined]
    gen.fallback_models = []  # type: ignore[attr-defined]
    gen.stats = {  # type: ignore[attr-defined]
        "total_generations": 0,
        "fallback_count": 0,
        "error_count": 0,
    }

    def _create(**kw: Any) -> object:
        # 더미 stream 객체 (실제 순회는 _iterate_stream_chunks 스텁이 담당)
        return object()

    class _Client:
        class chat:
            class completions:
                create = staticmethod(_create)

    gen.client = _Client()  # type: ignore[attr-defined]

    async def _build_prompt(*args: object, **kwargs: object) -> tuple[str, str]:
        return ("sys", "user")

    gen._build_prompt = _build_prompt  # type: ignore[assignment]
    gen._get_model_settings = lambda m, o: {  # type: ignore[assignment]
        "max_tokens": 100,
        "temperature": 0.3,
        "timeout": 5,
    }
    gen._update_stats = lambda *a, **k: None  # type: ignore[assignment]

    async def _iterate(stream: Any) -> Any:
        for c in chunks:
            yield _Chunk(c)
        # 입력 청크 소진 시점 기록 (done 이전 emit 개수 검증용)
        if state is not None:
            state["input_done"] = True

    gen._iterate_stream_chunks = _iterate  # type: ignore[assignment]
    return gen


@pytest.mark.asyncio
async def test_spaceless_long_stream_emits_before_done() -> None:
    """
    결함 1 검증: 공백 없는 장문 스트리밍도 done 이전에 점진적으로 emit돼야 한다.

    Given: 공백이 전혀 없는 1200자('あ' 반복)를 50자 청크로 공급
    When: stream_answer() 순회
    Then: 입력 소진(done) 이전에 2개 이상의 청크가 yield되고,
          전체 연결 결과는 mask(전체 텍스트)와 동일해야 한다.
          (수정 전 코드는 공백이 없어 done 이전 emit이 0개)
    """
    full_text = "あ" * 1200
    chunk_size = 50
    chunks = [full_text[i : i + chunk_size] for i in range(0, len(full_text), chunk_size)]
    state: dict[str, bool] = {"input_done": False}
    gen = _build_gen(chunks, state=state)

    pieces: list[str] = []
    pieces_before_done = 0
    async for piece in gen.stream_answer("질문", [{"content": "doc"}]):
        if not state["input_done"]:
            pieces_before_done += 1
        pieces.append(piece)

    # done 이전에 최소 2개 청크가 emit돼야 함 (무한 버퍼/스트리밍 정지 방지)
    assert pieces_before_done >= 2, (
        f"공백 없는 출력이 스트림 종료까지 버퍼에 갇힘: "
        f"done 이전 emit {pieces_before_done}개 (기대: 2개 이상)"
    )
    # 분할이 마스킹 결과를 바꾸지 않아야 함 (전체 일괄 마스킹과 동일)
    expected = PrivacyMasker().mask_text(full_text)
    assert "".join(pieces) == expected, "분할 emit 결과가 전체 마스킹 결과와 다름"


@pytest.mark.asyncio
async def test_boundary_name_masking_no_leak() -> None:
    """
    결함 2 검증: SOFT_FLUSH 경계에 걸친 한국어 이름이 유출되지 않아야 한다.

    Given: 패딩 76자 + '김철수 ' 청크로 버퍼가 정확히 80자(임계) 도달,
           이름 접미사('고객님')는 다음 청크에 도착
    When: stream_answer() 순회
    Then: 모든 yield 연결 결과 == mask(전체 텍스트), 즉 실명 미노출.
          (수정 전 코드는 마지막 공백에서 분할해 '...김철수'가
           lookahead 문맥 없이 emit되어 실명 유출)
    """
    # 패딩 76자: 공백 포함·공백 종료, PII 없음 ("가나다 " = 4자 x 19회)
    # 공백으로 끝나야 이름 런이 정확히 '김철수' 3자가 되어 '김**' 마스킹을 검증할 수 있다
    padding = "가나다 " * 19
    chunks = [padding, "김철수 ", "고객님 이용해 주셔서 감사합니다."]
    full_text = "".join(chunks)
    gen = _build_gen(chunks)

    pieces: list[str] = []
    async for piece in gen.stream_answer("질문", [{"content": "doc"}]):
        pieces.append(piece)

    joined = "".join(pieces)
    expected = PrivacyMasker().mask_text(full_text)
    # 전체 일괄 마스킹과 동일해야 함 (분할이 마스킹을 우회하면 불일치)
    assert joined == expected, f"경계 분할로 마스킹 결과 변형: {joined!r} != {expected!r}"
    # 실명이 어떤 emit 조각에도 노출되지 않아야 함
    assert "김철수" not in joined, "분할 경계에서 실명 유출 발생"
    assert "김**" in joined, "이름 마스킹이 적용되지 않음"


@pytest.mark.asyncio
async def test_emergency_flush_no_boundary_phone_leak() -> None:
    """
    결함 3 검증(비상 경로): HARD_CAP*2 전체 flush가 보류 꼬리를 폐기해
    경계 스패닝 전화번호가 평문 유출되지 않아야 한다.

    Given: 공백 없는 연속 전화번호 2600자('010-1234-5678' x 200)를
           첫 1자 + 13자 단위 청크로 공급. 청크 정렬상 분할 한계점(limit)이
           항상 전화번호 토큰 중간에 떨어져 등식 검사가 실패하고,
           버퍼가 HARD_CAP*2(1024자)에 도달해 비상 경로가 발동한다.
    When: stream_answer() 순회
    Then: 모든 emit 연결 결과에 평문 전화번호 0건이어야 한다.
          (수정 전 코드는 비상 경로가 버퍼 전체(부분 전화번호 꼬리 포함)를
           방출 → 꼬리 '...0'과 다음 flush 선두 '10-1234-5678'이 클라이언트
           재조립 시 평문 '010-1234-5678'로 결합되어 유출)
          또한 진행성 보장: 입력 소진(done) 이전에 2개 이상 emit돼야 한다.
    """
    full_text = "010-1234-5678" * 200
    # 첫 1자 + 13자 청크: 버퍼 길이가 항상 13으로 나눈 나머지 1이 되어
    # limit(=len-32)이 항상 전화번호 중간(나머지 8)에 떨어지도록 고정
    chunks = [full_text[:1]] + [full_text[i : i + 13] for i in range(1, len(full_text), 13)]
    state: dict[str, bool] = {"input_done": False}
    gen = _build_gen(chunks, state=state)

    pieces: list[str] = []
    pieces_before_done = 0
    async for piece in gen.stream_answer("질문", [{"content": "doc"}]):
        if not state["input_done"]:
            pieces_before_done += 1
        pieces.append(piece)

    joined = "".join(pieces)
    # 핵심: 평문 전화번호가 단 1건도 재조립되지 않아야 함
    assert "010-1234-5678" not in joined, (
        "비상 flush 경계에서 부분 전화번호가 평문으로 재조립 유출됨"
    )
    # 분할이 마스킹 결과를 바꾸지 않아야 함 (전체 일괄 마스킹과 동일)
    expected = PrivacyMasker().mask_text(full_text)
    assert joined == expected, "비상 분할 emit 결과가 전체 마스킹 결과와 다름"
    # 진행성 보장: 비상 경로에서도 done 이전에 점진 emit이 이루어져야 함
    assert pieces_before_done >= 2, (
        f"비상 경로에서 스트리밍 진행 정지: done 이전 emit {pieces_before_done}개"
    )


@pytest.mark.asyncio
async def test_emergency_backoff_preserves_holdback_tail() -> None:
    """
    결함 3 검증(후퇴 탐색): 비상 경로가 안전 분할점을 후퇴 탐색으로 찾아
    보류 꼬리(HOLDBACK)를 유지해야 한다.

    Given: 공백 없는 연속 전화번호 1027자 뒤에 '김철수 고객님 ...'이 이어지는
           스트림. 비상 flush 시점(버퍼 1028자)의 보류 꼬리에 이름 선두('김')가
           걸쳐 있고, 나머지('철수')와 접미사('고객님')는 이후 청크로 도착한다.
    When: stream_answer() 순회
    Then: 후퇴 탐색이 전화번호 경계(안전점)를 찾아 prefix만 emit하고
          보류 꼬리를 유지 → 이름이 접미사 문맥과 결합된 뒤 '김**'로 마스킹.
          (수정 전 코드는 버퍼 전체를 방출해 '김'이 고립 → 이후 '철수'만
           부분 마스킹('철*')되어 전체 마스킹 결과('김**')와 불일치)
    """
    full_text = "010-1234-5678" * 79 + "김철수 고객님 감사합니다."
    chunks = [full_text[:1]] + [full_text[i : i + 13] for i in range(1, len(full_text), 13)]
    gen = _build_gen(chunks)

    pieces: list[str] = []
    async for piece in gen.stream_answer("질문", [{"content": "doc"}]):
        pieces.append(piece)

    joined = "".join(pieces)
    expected = PrivacyMasker().mask_text(full_text)
    # 보류 꼬리가 유지돼야 이름이 완전한 문맥에서 마스킹됨
    assert joined == expected, (
        f"비상 경로가 보류 꼬리를 폐기해 마스킹 결과 변형: ...{joined[-40:]!r}"
    )
    assert "김**" in joined, "보류 꼬리 폐기로 이름 마스킹이 불완전함"
    assert "김철수" not in joined, "비상 flush 경계에서 실명 유출 발생"
    assert "010-1234-5678" not in joined, "비상 flush 경계에서 전화번호 유출 발생"


@pytest.mark.asyncio
async def test_short_answer_single_final_flush_regression() -> None:
    """
    회귀 검증: 짧은 답변(<80자)은 기존처럼 스트림 종료 시 1회 flush돼야 한다.

    Given: 총 길이 80자 미만의 청크들 (이름 PII 포함)
    When: stream_answer() 순회
    Then: 정확히 1개의 청크가 yield되고, 결과는 mask(전체)와 동일
    """
    chunks = ["안녕하세요 ", "김철수 고객님"]
    full_text = "".join(chunks)
    gen = _build_gen(chunks)

    pieces: list[str] = []
    async for piece in gen.stream_answer("질문", [{"content": "doc"}]):
        pieces.append(piece)

    # 짧은 답변은 종료 시 1회 flush (기존 동작 유지)
    assert len(pieces) == 1, f"짧은 답변 flush 횟수 변경: {len(pieces)}회 (기대: 1회)"
    expected = PrivacyMasker().mask_text(full_text)
    assert pieces[0] == expected
    assert "김철수" not in pieces[0]
