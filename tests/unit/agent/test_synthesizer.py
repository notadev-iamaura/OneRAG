"""
AgentSynthesizer 테스트 - 결과 합성

ReAct 패턴에서 "Synthesize" 담당 컴포넌트의 테스트.
도구 실행 결과들을 분석하여 최종 답변을 생성합니다.

테스트 시나리오:
1. 성공적인 답변 생성
2. 소스 정보 추출
3. 실패한 결과 처리
4. 빈 상태 처리
5. 여러 스텝의 결과 통합
"""

from unittest.mock import AsyncMock

import pytest

from app.modules.core.agent.factory import AgentFactory
from app.modules.core.agent.interfaces import (
    AgentConfig,
    AgentState,
    AgentStep,
    ToolCall,
    ToolResult,
)
from app.modules.core.agent.synthesizer import (
    AgentSynthesizer,
    _document_links,
    _expanded_windows,
    _premise_review_passages,
)


def test_document_links_only_use_visible_mentions_of_other_titles():
    evidence = {
        "S1": ({"title": "Rail Manifest"}, ""),
        "S2": ({"title": "North Port (station)"}, ""),
        "S3": ({"title": "Porter"}, ""),
    }
    sentences = {
        "S1.2": ("S1", "The shipment goes through North Port."),
        "S2.1": ("S2", "North Port is a seaport."),
        "S3.1": ("S3", "North Portland has another shipment."),
    }
    assert _document_links(evidence, sentences, {"shipment"}) == ["[S1.2] → S2"]


def test_expanded_search_allocates_each_document_a_sentence_and_keeps_its_position():
    docs = {
        f"S{i}": ["Regular service.", "A late shipment.", "Harbor timetable."] for i in range(1, 9)
    }
    titles = {ref: f"Timetable {ref}" for ref in docs}
    windows = _expanded_windows(docs, titles, {"late", "shipment"})
    assert windows.keys() == docs.keys()
    assert all(1 in indices and indices == sorted(set(indices)) for indices in windows.values())


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("response", "status", "expected"),
    [
        (
            "Friday [S1.1].\n[S1.1, S1.2]",
            "verified_quotes",
            ["Arrival is Friday.", "Dispatch is Thursday."],
        ),
        (
            "EVIDENCE: [S1.1] [S1.2]\nANSWER: Friday.",
            "verified_quotes",
            ["Arrival is Friday.", "Dispatch is Thursday."],
        ),
        (
            "FACT: [S1.1]\nFACT: [S1.2]\nANSWER: Friday.",
            "verified_quotes",
            ["Arrival is Friday.", "Dispatch is Thursday."],
        ),
        ("FACT: [S1.1]\nFACT: [S2.2]\nANSWER: Friday.", "invalid_citation", []),
        ("근거: [S1.1] Arrival is Friday.\n답: Friday.", "verified_quotes", ["Arrival is Friday."]),
        ("참고 문장: [S1.1]\n정답: Friday.", "verified_quotes", ["Arrival is Friday."]),
        ("참고 문장: [S9.1]\n정답: Friday.", "invalid_citation", []),
        ("EVIDENCE: [S1.1] Arrival is Sunday.\nANSWER: Friday.", "invalid_citation", []),
        ("EVIDENCE: INSUFFICIENT\nANSWER: 근거 부족", "insufficient", []),
        ("EVIDENCE: [S9.1]\nANSWER: 근거 부족", "invalid_citation", []),
        ("INSUFFICIENT\n[S9.1]", "invalid_citation", []),
        ("EVIDENCE: [S1.1] [S1.7]\nANSWER: Friday.", "invalid_citation", []),
        ("Friday [S9.1].\n[S1.1]", "invalid_citation", []),
        ("Friday [S7.x].\n[S1.1]", "invalid_citation", []),
        ("Friday\n[S1.1] [S1.3]", "invalid_citation", []),
        ("Friday", "invalid_citation", []),
        ("INSUFFICIENT\nSEARCH: dispatch note", "insufficient", []),
    ],
)
async def test_grounded_sentence_references(response, status, expected):
    client = AsyncMock()
    client.generate_text.return_value = response
    language = "English" if response.startswith("FACT:") else "한국어"
    synth = AgentSynthesizer(client, AgentConfig(require_evidence_quotes=True, output_language=language))
    docs = [{"id": "manifest", "content": "Arrival is Friday. Dispatch is Thursday."}]
    result = ToolResult("read", "search", True, data=docs)
    state = AgentState("When does it arrive?", steps=[AgentStep(1, "", [], [result])])
    answer, sources = await synth.synthesize(state)
    assert state.grounding_status == status
    assert [s for source in sources for s in source["cited_sentences"]] == expected
    if expected:
        assert answer == "Friday."
    if "SEARCH:" in response:
        assert state.followup_queries == ["dispatch note"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("options", "decision", "expected_status", "expected_calls"),
    [
        ({}, "", "verified_quotes", 1),
        ({"verify_question_conditions": True}, "OK", "verified_quotes", 2),
        ({"verify_question_conditions": True}, "MISSING: 겨울", "insufficient", 2),
        ({"verify_question_conditions": True}, "MISSING: 공항", "error", 2),
        ({"verify_question_conditions": True, "verify_premise_mismatch": True},
         "MISSING: 겨울", "insufficient", 2),
    ],
)
async def test_korean_condition_review_requires_opt_in(options, decision, expected_status, expected_calls):
    config = AgentFactory.create_config({"mcp": {"agent": {"require_evidence_quotes": True, **options}}})
    client = AsyncMock()
    client.generate_text.side_effect = ["EVIDENCE: [S1.1]\nANSWER: 금요일", decision]
    result = ToolResult("read", "search", True, data=[{"id": "timetable", "content": "도착일은 금요일이다."}])
    state = AgentState("겨울 열차의 도착일은 언제인가요?", steps=[AgentStep(1, "", [], [result])])
    answer, sources = await AgentSynthesizer(client, config).synthesize(state)
    assert state.grounding_status == expected_status
    assert client.generate_text.await_count == expected_calls
    if expected_status == "verified_quotes":
        assert answer == "금요일"
        assert sources[0]["cited_sentences"] == ["도착일은 금요일이다."]
    else:
        assert answer == "근거 부족"
        assert not sources
        assert bool(state.followup_queries) == (expected_status == "insufficient")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("question", "passage", "reply", "review", "status"),
    [
        (
            "은하재단이 받은 상은?", "해솔재단은 푸른상을 받았다. 은하재단은 상을 수여했다.",
            "푸른상", "CONFLICT: [S1.2] | 은하재단이 받은 | 은하재단은 상을 수여했다", "insufficient",
        ),
        (
            "모든 구간에 지급되는 보조금은?", "일부 구간에 4만원을 지급한다.",
            "4만원", "CONFLICT: [S1.1] | 모든 구간 | 일부 구간", "insufficient",
        ),
        (
            "전시를 관람할 수 있는 기간은?", "전시는 2028년 3월 개막한다.",
            "2028년 3월", "CONFLICT: [S1.1] | 관람할 수 있는 기간 | 개막한다", "insufficient",
        ),
        (
            "한서진이 피고인으로 송치된 날짜는?", "한서진은 3월 4일 피의자로 소환됐다.",
            "3월 4일", "CONFLICT: [S1.1] | 피고인으로 송치된 | 피의자로 소환됐다", "insufficient",
        ),
        (
            "시의회가 예산을 승인한 날짜는?", "시의회는 7월 1일 예산을 제안했다.",
            "7월 1일", "CONFLICT: [S1.1] | 승인한 | 예산을 제안했다", "insufficient",
        ),
        (
            "시의회가 예산을 승인한 날짜는?", "시의회는 7월 1일 예산을 가결했다.",
            "7월 1일", "OK", "verified_quotes",
        ),
        (
            "은하재단이 받은 상은?", "해솔재단은 푸른상을 받았다. 은하재단은 해솔재단이 쓰던 이름이다.",
            "푸른상", "OK", "verified_quotes",
        ),
        (
            "시상식은 어느 요일에 열리나?", "행사는 매주 화요일에 열린다.",
            "화요일", None, "verified_quotes",
        ),
        (
            "모든 구간에 지급되는 보조금은?", "올해 3월 1일부터 모든 구간에 보조금 4만원을 지급한다.",
            "4만원", None, "verified_quotes",
        ),
        (
            "모든 구간에 지급되는 보조금은?", "일부 구간에 4만원을 지급한다.",
            "4만원", "CONFLICT: [S1.8] | 모든 구간 | 일부 구간", "error",
        ),
        (
            "모든 구간에 지급되는 보조금은?", "일부 구간에 4만원을 지급한다.",
            "4만원", "CONFLICT: [S1.1] | 모든 구간 | 시범 운영", "error",
        ),
        (
            "모든 구간에 지급되는 보조금은?", "일부 구간에 4만원을 지급한다.",
            "4만원", "CONFLICT: [S1.1] | 신규 구간 | 일부 구간", "error",
        ),
        (
            "모든 구간에 지급되는 보조금은?", "일부 구간에 4만원을 지급한다.",
            "4만원", "CONFLICT: [S1.1] | 모든 구간 | 4만원", "error",
        ),
        (
            "모든 구간에 지급되는 보조금은?", "일부 구간에 4만원을 지급한다.",
            "4만원", "CONFLICT:\n[S1.1] | 모든 구간 | 일부 구간", "error",
        ),
    ],
)
async def test_korean_premise_review(question, passage, reply, review, status):
    config = AgentFactory.create_config(
        {"mcp": {"agent": {"require_evidence_quotes": True, "verify_premise_mismatch": True}}}
    )
    client = AsyncMock()
    client.generate_text.side_effect = [f"근거: [S1.1]\n답: {reply}", review]
    result = ToolResult("read", "search", True, data=[{"id": "archive", "content": passage}])
    state = AgentState(question, steps=[AgentStep(1, "", [], [result])])
    answer, sources = await AgentSynthesizer(client, config).synthesize(state)
    assert client.generate_text.await_count == (2 if review else 1)
    assert state.grounding_status == status
    assert not state.followup_queries
    if status == "verified_quotes":
        assert answer == reply
        assert sources[0]["cited_sentences"] == [passage.split(". ")[0].rstrip(".") + "."]
    else:
        assert answer == "근거 부족"
        assert sources == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("language", "first_response", "status"),
    [
        ("English", "FACT: [S1.1]\nANSWER: 4만원", "verified_quotes"),
        ("한국어", "근거: [S9.9]\n답: 4만원", "invalid_citation"),
        ("한국어", "INSUFFICIENT\nSEARCH: 다른 구간 지원금", "insufficient"),
    ],
)
async def test_premise_review_preserves_other_paths(language, first_response, status):
    config = AgentConfig(output_language=language, require_evidence_quotes=True, verify_premise_mismatch=True)
    client = AsyncMock()
    client.generate_text.return_value = first_response
    result = ToolResult("read", "search", True, data=[{"id": "note", "content": "일부 구간에 4만원을 지급한다."}])
    state = AgentState("모든 구간의 지원금은?", steps=[AgentStep(1, "", [], [result])])
    await AgentSynthesizer(client, config).synthesize(state)
    assert state.grounding_status == status
    assert state.followup_queries == (["다른 구간 지원금"] if status == "insufficient" else [])
    client.generate_text.assert_awaited_once()


def test_premise_review_bounds_evidence_without_dropping_original_citations():
    question = "모든 역의 개통 날짜는?"
    segments = [f"일부 역의 기록 {i}. " + "글" * 1100 for i in range(12)]
    labels = [f"S2.{i}" for i in [2, 4, 6, 8, 10]]
    shown = _premise_review_passages(question, "2027년", "노선도", "S2", segments, labels)
    assert set(labels) <= shown.keys()
    assert len(shown) <= 6
    assert max(map(len, shown.values())) <= 900
    assert not _premise_review_passages(
        question, "2027년", "노선도", "S2", segments, [*labels, "S2.9", "S2.11"]
    )


class TestAgentSynthesizer:
    """AgentSynthesizer 테스트"""

    @pytest.fixture
    def mock_llm_client(self):
        """Mock LLM 클라이언트"""
        client = AsyncMock()
        client.generate_text = AsyncMock()
        return client

    @pytest.fixture
    def agent_config(self):
        """에이전트 설정"""
        return AgentConfig()

    @pytest.fixture
    def synthesizer(self, mock_llm_client, agent_config):
        """AgentSynthesizer 인스턴스"""
        return AgentSynthesizer(
            llm_client=mock_llm_client,
            config=agent_config,
        )

    def _create_state_with_results(self) -> AgentState:
        """테스트용 성공 결과가 있는 상태 생성"""
        state = AgentState(original_query="파이썬 튜토리얼 알려줘")

        tool_call = ToolCall(
            tool_name="search_weaviate",
            arguments={"query": "파이썬"},
        )
        tool_result = ToolResult(
            call_id=tool_call.call_id,
            tool_name="search_weaviate",
            success=True,
            data={
                "documents": [
                    {
                        "content": "파이썬 기초 강좌입니다",
                        "metadata": {"source": "doc1.md", "title": "파이썬 기초"},
                    },
                    {
                        "content": "파이썬 고급 문법",
                        "metadata": {"source": "doc2.md", "title": "파이썬 고급"},
                    },
                ]
            },
        )

        state.steps.append(
            AgentStep(
                step_number=1,
                reasoning="검색 수행",
                tool_calls=[tool_call],
                tool_results=[tool_result],
            )
        )

        return state

    @pytest.mark.asyncio
    async def test_synthesizer_generates_answer(
        self, synthesizer, mock_llm_client
    ):
        """
        최종 답변 생성 테스트

        LLM을 사용하여 도구 결과를 바탕으로 답변을 생성해야 합니다.
        """
        # LLM 응답 설정
        mock_llm_client.generate_text.return_value = """
        파이썬 튜토리얼을 찾았습니다.

        1. 파이썬 기초 강좌 - 초보자용
        2. 파이썬 고급 문법 - 중급자용

        더 자세한 내용은 문서를 참고하세요.
        """

        state = self._create_state_with_results()

        # synthesize 호출
        answer, sources = await synthesizer.synthesize(state)

        # 검증
        assert answer is not None
        assert len(answer) > 0
        assert "파이썬" in answer
        # LLM이 호출되었는지 확인
        mock_llm_client.generate_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_synthesizer_extracts_sources(
        self, synthesizer, mock_llm_client
    ):
        """
        소스 추출 테스트

        도구 결과에서 메타데이터를 파싱하여 소스 정보를 추출해야 합니다.
        """
        mock_llm_client.generate_text.return_value = "답변입니다."

        state = self._create_state_with_results()

        answer, sources = await synthesizer.synthesize(state)

        # 소스가 추출되었는지 확인
        assert len(sources) == 2
        assert sources[0]["source"] == "doc1.md"
        assert sources[1]["source"] == "doc2.md"

    @pytest.mark.asyncio
    async def test_synthesizer_handles_failed_results(
        self, synthesizer, mock_llm_client
    ):
        """
        실패한 결과 처리 테스트

        도구 실행이 실패한 경우에도 적절히 처리해야 합니다.
        """
        mock_llm_client.generate_text.return_value = (
            "검색에 실패했지만, 가능한 정보를 제공합니다."
        )

        state = AgentState(original_query="테스트")
        state.steps.append(
            AgentStep(
                step_number=1,
                reasoning="검색 시도",
                tool_calls=[
                    ToolCall(tool_name="search_weaviate", arguments={})
                ],
                tool_results=[
                    ToolResult(
                        call_id="test",
                        tool_name="search_weaviate",
                        success=False,
                        error="타임아웃",
                    )
                ],
            )
        )

        answer, sources = await synthesizer.synthesize(state)

        # 실패해도 답변은 생성됨
        assert answer is not None
        # 실패한 결과에서는 소스가 없음
        assert len(sources) == 0

    @pytest.mark.asyncio
    async def test_synthesizer_handles_empty_state(
        self, synthesizer, mock_llm_client
    ):
        """
        빈 상태 처리 테스트

        도구 실행 결과가 없는 경우에도 적절히 처리해야 합니다.
        """
        mock_llm_client.generate_text.return_value = (
            "관련 정보를 찾지 못했습니다."
        )

        state = AgentState(original_query="테스트")
        # 스텝 없음 - 빈 상태

        answer, sources = await synthesizer.synthesize(state)

        assert answer is not None
        assert len(sources) == 0

    @pytest.mark.asyncio
    async def test_synthesizer_uses_all_results(
        self, synthesizer, mock_llm_client
    ):
        """
        모든 스텝의 결과 활용 테스트

        여러 스텝에 걸친 모든 도구 결과를 합성에 활용해야 합니다.
        """
        mock_llm_client.generate_text.return_value = "종합 답변입니다."

        state = AgentState(original_query="복잡한 질문")

        # 첫 번째 스텝
        state.steps.append(
            AgentStep(
                step_number=1,
                reasoning="첫 번째 검색",
                tool_calls=[
                    ToolCall(tool_name="search_weaviate", arguments={})
                ],
                tool_results=[
                    ToolResult(
                        call_id="step1",
                        tool_name="search_weaviate",
                        success=True,
                        data={
                            "documents": [
                                {
                                    "content": "첫 번째 결과",
                                    "metadata": {"source": "a.md"},
                                }
                            ]
                        },
                    )
                ],
            )
        )

        # 두 번째 스텝
        state.steps.append(
            AgentStep(
                step_number=2,
                reasoning="두 번째 검색",
                tool_calls=[ToolCall(tool_name="query_sql", arguments={})],
                tool_results=[
                    ToolResult(
                        call_id="step2",
                        tool_name="query_sql",
                        success=True,
                        data={
                            "documents": [
                                {
                                    "content": "두 번째 결과",
                                    "metadata": {"source": "b.md"},
                                }
                            ]
                        },
                    )
                ],
            )
        )

        answer, sources = await synthesizer.synthesize(state)

        # 두 스텝의 결과가 모두 포함되어야 함
        assert len(sources) == 2
        source_files = [s["source"] for s in sources]
        assert "a.md" in source_files
        assert "b.md" in source_files

    @pytest.mark.asyncio
    async def test_synthesizer_deduplicates_sources(
        self, synthesizer, mock_llm_client
    ):
        """
        중복 소스 제거 테스트

        같은 소스가 여러 번 나와도 한 번만 포함되어야 합니다.
        """
        mock_llm_client.generate_text.return_value = "답변입니다."

        state = AgentState(original_query="테스트")
        state.steps.append(
            AgentStep(
                step_number=1,
                reasoning="검색",
                tool_calls=[
                    ToolCall(tool_name="search_weaviate", arguments={})
                ],
                tool_results=[
                    ToolResult(
                        call_id="test",
                        tool_name="search_weaviate",
                        success=True,
                        data={
                            "documents": [
                                {
                                    "content": "내용1",
                                    "metadata": {"source": "same.md"},
                                },
                                {
                                    "content": "내용2",
                                    "metadata": {"source": "same.md"},
                                },
                                {
                                    "content": "내용3",
                                    "metadata": {"source": "different.md"},
                                },
                            ]
                        },
                    )
                ],
            )
        )

        answer, sources = await synthesizer.synthesize(state)

        # 중복 제거되어 2개만 남아야 함
        assert len(sources) == 2
        source_files = [s["source"] for s in sources]
        assert "same.md" in source_files
        assert "different.md" in source_files

    @pytest.mark.asyncio
    async def test_synthesizer_handles_llm_error(
        self, synthesizer, mock_llm_client
    ):
        """
        LLM 에러 처리 테스트

        LLM 호출 실패 시 적절한 에러 메시지를 반환해야 합니다.
        """
        mock_llm_client.generate_text.side_effect = Exception("LLM 에러")

        state = self._create_state_with_results()

        answer, sources = await synthesizer.synthesize(state)

        # 에러 발생해도 기본 응답 반환
        assert answer is not None
        assert "오류" in answer or "죄송" in answer

    @pytest.mark.asyncio
    async def test_synthesizer_initialization_validation(self, agent_config):
        """
        초기화 유효성 검사 테스트

        필수 의존성이 없으면 에러가 발생해야 합니다.
        """
        with pytest.raises(ValueError, match="llm_client"):
            AgentSynthesizer(llm_client=None, config=agent_config)

    @pytest.mark.asyncio
    async def test_synthesizer_limits_content_length(
        self, synthesizer, mock_llm_client
    ):
        """
        결과 내용 길이 제한 테스트

        너무 긴 내용은 적절히 잘라서 LLM에 전달해야 합니다.
        """
        mock_llm_client.generate_text.return_value = "요약 답변"

        state = AgentState(original_query="테스트")
        # 매우 긴 내용 생성
        long_content = "A" * 10000
        state.steps.append(
            AgentStep(
                step_number=1,
                reasoning="검색",
                tool_calls=[
                    ToolCall(tool_name="search_weaviate", arguments={})
                ],
                tool_results=[
                    ToolResult(
                        call_id="test",
                        tool_name="search_weaviate",
                        success=True,
                        data={
                            "documents": [
                                {
                                    "content": long_content,
                                    "metadata": {"source": "test.md"},
                                }
                            ]
                        },
                    )
                ],
            )
        )

        answer, sources = await synthesizer.synthesize(state)

        # 정상적으로 처리되어야 함
        assert answer is not None
        # LLM에 전달된 프롬프트 확인
        call_args = mock_llm_client.generate_text.call_args
        prompt = call_args.kwargs.get("prompt", "")
        # 전달된 내용이 원본보다 짧아야 함 (잘림)
        assert len(prompt) < len(long_content) + 1000
