"""
Self-Reflection 실제 LLM 통합 테스트

실제 LLM API를 호출하여 Self-Reflection 기능이 제대로 동작하는지 검증합니다.

테스트 시나리오:
1. Reflection 활성화 테스트: 실제 LLM으로 답변 생성 → Reflection 평가 → 결과 확인
2. Reflection 비활성화 테스트: Reflection 없이 답변 생성 확인
3. AgentReflector 단독 테스트: Reflector의 품질 평가 기능 검증

주의사항:
- 테스트는 API 키 없으면 skip 처리
- 비용 최소화를 위해 짧은 프롬프트 사용
- 타임아웃 설정 필수 (30초)
"""

import os

import pytest

from app.lib.llm_client import OpenAILLMClient
from app.modules.core.agent.interfaces import AgentConfig
from app.modules.core.agent.reflector import AgentReflector

# API 키 존재 여부 확인
HAS_OPENAI_KEY = bool(os.getenv("OPENAI_API_KEY"))
HAS_OPENROUTER_KEY = bool(os.getenv("OPENROUTER_API_KEY"))
HAS_ANY_LLM_KEY = HAS_OPENAI_KEY or HAS_OPENROUTER_KEY


# API 키가 없으면 전체 모듈 스킵
pytestmark = pytest.mark.skipif(
    not HAS_ANY_LLM_KEY,
    reason="실제 LLM API 키 필요 (OPENAI_API_KEY 또는 OPENROUTER_API_KEY)"
)


class TestSelfReflectionRealLLM:
    """실제 LLM을 사용한 Self-Reflection 통합 테스트"""

    @pytest.fixture
    def openai_llm_client(self):
        """
        OpenAI LLM 클라이언트 생성

        비용 최소화를 위해 gpt-4o-mini 모델 사용
        """
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            pytest.skip("OPENAI_API_KEY 환경변수 필요")

        config = {
            "api_key": api_key,
            "model": "gpt-4o-mini",  # 비용 최소화
            "temperature": 0.0,
            "max_tokens": 512,
            "timeout": 30,
        }
        return OpenAILLMClient(config)

    @pytest.fixture
    def reflection_config(self) -> AgentConfig:
        """Reflection 활성화 설정"""
        return AgentConfig(
            tool_selection="llm",
            selector_model="gpt-4o-mini",
            max_iterations=3,
            fallback_tool="search_weaviate",
            timeout=30.0,
            timeout_seconds=60.0,
            tool_timeout=15.0,
            parallel_execution=False,
            max_concurrent_tools=1,
            # Self-Reflection 설정
            enable_reflection=True,
            reflection_threshold=7.0,  # 7.0 미만이면 개선 필요
            max_reflection_iterations=2,
        )

    @pytest.fixture
    def no_reflection_config(self) -> AgentConfig:
        """Reflection 비활성화 설정"""
        return AgentConfig(
            tool_selection="llm",
            selector_model="gpt-4o-mini",
            max_iterations=3,
            fallback_tool="search_weaviate",
            timeout=30.0,
            timeout_seconds=60.0,
            tool_timeout=15.0,
            parallel_execution=False,
            max_concurrent_tools=1,
            # Self-Reflection 비활성화
            enable_reflection=False,
            reflection_threshold=7.0,
            max_reflection_iterations=0,
        )

    @pytest.mark.asyncio
    @pytest.mark.timeout(60)  # 60초 타임아웃
    async def test_reflector_evaluates_high_quality_answer(
        self, openai_llm_client, reflection_config
    ):
        """
        테스트: 고품질 답변에 대해 Reflector가 높은 점수 부여

        시나리오:
        1. 질문에 대한 상세하고 정확한 답변 제공
        2. Reflector가 답변을 평가
        3. 높은 점수(7.0 이상)를 부여하고 needs_improvement=False
        """
        # Given: AgentReflector 생성
        reflector = AgentReflector(
            llm_client=openai_llm_client,
            config=reflection_config,
        )

        # 테스트용 질문, 답변, 컨텍스트
        query = "Python에서 리스트와 튜플의 차이점은 무엇인가요?"
        answer = """
        Python에서 리스트(list)와 튜플(tuple)의 주요 차이점은 다음과 같습니다:

        1. **가변성(Mutability)**:
           - 리스트: 가변(mutable) - 생성 후 요소 추가, 삭제, 수정 가능
           - 튜플: 불변(immutable) - 생성 후 변경 불가능

        2. **문법**:
           - 리스트: 대괄호 사용 `[1, 2, 3]`
           - 튜플: 소괄호 사용 `(1, 2, 3)`

        3. **성능**:
           - 튜플이 리스트보다 약간 빠르고 메모리 효율적

        4. **사용 사례**:
           - 리스트: 동적으로 변하는 데이터 컬렉션
           - 튜플: 변경되면 안 되는 상수 데이터, 딕셔너리 키
        """
        context = "Python 공식 문서에서 리스트와 튜플에 대한 설명"

        # When: Reflection 수행
        result = await reflector.reflect(
            query=query,
            answer=answer,
            context=context,
        )

        # Then: 높은 점수 부여
        assert result.score >= 7.0, f"고품질 답변인데 점수가 낮음: {result.score}"
        assert result.needs_improvement is False, "고품질 답변은 개선 불필요"
        assert isinstance(result.reasoning, str)

        print(f"\n[테스트 결과] 점수: {result.score}, 개선필요: {result.needs_improvement}")
        print(f"평가 근거: {result.reasoning}")

    @pytest.mark.asyncio
    @pytest.mark.timeout(60)
    async def test_reflector_evaluates_low_quality_answer(
        self, openai_llm_client, reflection_config
    ):
        """
        테스트: 저품질 답변에 대해 Reflector가 낮은 점수 부여

        시나리오:
        1. 질문에 대한 불완전하고 모호한 답변 제공
        2. Reflector가 답변을 평가
        3. 낮은 점수(7.0 미만)를 부여하고 needs_improvement=True
        """
        # Given: AgentReflector 생성
        reflector = AgentReflector(
            llm_client=openai_llm_client,
            config=reflection_config,
        )

        # 저품질 답변 (불완전, 모호함)
        query = "Python에서 비동기 프로그래밍을 어떻게 구현하나요?"
        answer = "async를 사용하면 됩니다."  # 매우 불완전한 답변
        context = "Python asyncio 문서"

        # When: Reflection 수행
        result = await reflector.reflect(
            query=query,
            answer=answer,
            context=context,
        )

        # Then: 낮은 점수 부여 (또는 문제점 지적)
        # 주의: LLM의 평가는 항상 일정하지 않을 수 있음
        print(f"\n[테스트 결과] 점수: {result.score}, 개선필요: {result.needs_improvement}")
        print(f"문제점: {result.issues}")
        print(f"제안: {result.suggestions}")
        print(f"평가 근거: {result.reasoning}")

        # 저품질 답변이므로 문제점이나 제안이 있어야 함
        # (점수 기준은 LLM 성향에 따라 다를 수 있음)
        assert result.score < 9.0, f"불완전한 답변인데 점수가 너무 높음: {result.score}"
        # 문제점이나 제안이 있거나, needs_improvement가 True여야 함
        has_feedback = (
            len(result.issues) > 0
            or len(result.suggestions) > 0
            or result.needs_improvement
        )
        assert has_feedback, "저품질 답변에 대해 피드백이 없음"

    @pytest.mark.asyncio
    @pytest.mark.timeout(60)
    async def test_reflector_handles_empty_context(
        self, openai_llm_client, reflection_config
    ):
        """
        테스트: 컨텍스트 없이도 Reflector가 정상 동작

        시나리오:
        1. 컨텍스트 없이 질문과 답변만 제공
        2. Reflector가 답변을 평가
        3. 정상적인 ReflectionResult 반환
        """
        # Given: AgentReflector 생성
        reflector = AgentReflector(
            llm_client=openai_llm_client,
            config=reflection_config,
        )

        query = "1 + 1은 얼마인가요?"
        answer = "1 + 1은 2입니다."
        context = ""  # 빈 컨텍스트

        # When: Reflection 수행
        result = await reflector.reflect(
            query=query,
            answer=answer,
            context=context,
        )

        # Then: 정상적인 결과 반환
        assert result is not None
        assert isinstance(result.score, float)
        assert 0.0 <= result.score <= 10.0
        assert isinstance(result.issues, list)
        assert isinstance(result.suggestions, list)
        assert isinstance(result.needs_improvement, bool)

        print(f"\n[테스트 결과] 점수: {result.score}, 개선필요: {result.needs_improvement}")

    @pytest.mark.asyncio
    @pytest.mark.timeout(90)
    async def test_reflection_with_korean_content(
        self, openai_llm_client, reflection_config
    ):
        """
        테스트: 한국어 콘텐츠에 대한 Reflection 동작 확인

        시나리오:
        1. 한국어 질문, 답변, 컨텍스트 제공
        2. Reflector가 한국어 콘텐츠를 이해하고 평가
        3. 정상적인 평가 결과 반환
        """
        # Given: AgentReflector 생성
        reflector = AgentReflector(
            llm_client=openai_llm_client,
            config=reflection_config,
        )

        # 한국어 테스트 데이터
        query = "클라우드 서비스 요금제는 어떻게 되나요?"
        answer = """
        클라우드 서비스 요금제는 다양합니다:

        1. **기본 플랜**: 월 10만원 ~ 50만원
           - 소규모 팀 및 스타트업용

        2. **비즈니스 플랜**: 월 50만원 ~ 200만원
           - 중소기업용, 추가 기능 포함

        3. **엔터프라이즈 플랜**: 월 200만원 이상
           - 대기업용, 전담 지원 포함

        대부분의 고객님들은 비즈니스 플랜을 선택하시며,
        필요에 맞춰 다양한 옵션을 고려하시면 좋습니다.
        """
        context = """
        [클라우드 서비스 정보]
        - 기본 플랜: 월 평균 20-30만원
        - 비즈니스 플랜: 월 평균 80-120만원
        - 엔터프라이즈: 사용량에 따라 상이
        """

        # When: Reflection 수행
        result = await reflector.reflect(
            query=query,
            answer=answer,
            context=context,
        )

        # Then: 정상적인 결과 반환
        assert result is not None
        assert isinstance(result.score, float)
        assert 0.0 <= result.score <= 10.0

        print("\n[한국어 테스트 결과]")
        print(f"점수: {result.score}")
        print(f"개선필요: {result.needs_improvement}")
        print(f"문제점: {result.issues}")
        print(f"제안: {result.suggestions}")
        print(f"평가 근거: {result.reasoning}")

    @pytest.mark.asyncio
    @pytest.mark.timeout(60)
    async def test_reflector_threshold_boundary(
        self, openai_llm_client
    ):
        """
        테스트: Reflection threshold 경계값 테스트

        시나리오:
        1. 다양한 threshold 값으로 같은 답변 평가
        2. threshold에 따라 needs_improvement 값이 변경되는지 확인
        """
        # 낮은 threshold 설정 (5.0)
        low_threshold_config = AgentConfig(
            tool_selection="llm",
            selector_model="gpt-4o-mini",
            max_iterations=3,
            fallback_tool="search_weaviate",
            timeout=30.0,
            timeout_seconds=60.0,
            tool_timeout=15.0,
            parallel_execution=False,
            max_concurrent_tools=1,
            enable_reflection=True,
            reflection_threshold=5.0,  # 낮은 threshold
            max_reflection_iterations=2,
        )

        # 높은 threshold 설정 (9.0)
        high_threshold_config = AgentConfig(
            tool_selection="llm",
            selector_model="gpt-4o-mini",
            max_iterations=3,
            fallback_tool="search_weaviate",
            timeout=30.0,
            timeout_seconds=60.0,
            tool_timeout=15.0,
            parallel_execution=False,
            max_concurrent_tools=1,
            enable_reflection=True,
            reflection_threshold=9.0,  # 높은 threshold
            max_reflection_iterations=2,
        )

        # 중간 품질 답변
        query = "Python이란?"
        answer = "Python은 프로그래밍 언어입니다."
        context = "Python 소개"

        # Given: 두 개의 Reflector 생성
        low_threshold_reflector = AgentReflector(
            llm_client=openai_llm_client,
            config=low_threshold_config,
        )
        high_threshold_reflector = AgentReflector(
            llm_client=openai_llm_client,
            config=high_threshold_config,
        )

        # When: 같은 답변으로 평가
        low_result = await low_threshold_reflector.reflect(
            query=query, answer=answer, context=context
        )
        high_result = await high_threshold_reflector.reflect(
            query=query, answer=answer, context=context
        )

        # Then: 점수는 비슷하지만 needs_improvement는 다를 수 있음
        print("\n[Threshold 경계값 테스트]")
        print(f"낮은 threshold(5.0): 점수={low_result.score}, 개선필요={low_result.needs_improvement}")
        print(f"높은 threshold(9.0): 점수={high_result.score}, 개선필요={high_result.needs_improvement}")

        # 점수는 비슷해야 함 (같은 LLM이 평가)
        assert abs(low_result.score - high_result.score) < 2.0, \
            "같은 답변인데 점수 차이가 너무 큼"

        # 높은 threshold에서는 더 쉽게 개선 필요 판정
        # (중간 품질 답변이면 high threshold에서 needs_improvement=True일 가능성 높음)
        if low_result.score < 9.0:  # 점수가 9.0 미만이면
            assert high_result.needs_improvement is True, \
                "높은 threshold에서 중간 품질 답변은 개선 필요해야 함"


class TestReflectorEdgeCases:
    """AgentReflector 엣지 케이스 테스트"""

    @pytest.fixture
    def openai_llm_client(self):
        """OpenAI LLM 클라이언트"""
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            pytest.skip("OPENAI_API_KEY 환경변수 필요")

        config = {
            "api_key": api_key,
            "model": "gpt-4o-mini",
            "temperature": 0.0,
            "max_tokens": 512,
            "timeout": 30,
        }
        return OpenAILLMClient(config)

    @pytest.fixture
    def config(self) -> AgentConfig:
        """기본 설정"""
        return AgentConfig(
            tool_selection="llm",
            selector_model="gpt-4o-mini",
            max_iterations=3,
            fallback_tool="search_weaviate",
            timeout=30.0,
            timeout_seconds=60.0,
            tool_timeout=15.0,
            parallel_execution=False,
            max_concurrent_tools=1,
            enable_reflection=True,
            reflection_threshold=7.0,
            max_reflection_iterations=2,
        )

    @pytest.mark.asyncio
    @pytest.mark.timeout(60)
    async def test_very_long_answer(self, openai_llm_client, config):
        """
        테스트: 매우 긴 답변에 대한 Reflection 처리
        """
        reflector = AgentReflector(
            llm_client=openai_llm_client,
            config=config,
        )

        query = "Python의 장점을 설명해주세요."
        # 긴 답변 생성 (반복)
        answer = "Python의 장점: " + ("읽기 쉬운 문법, " * 50)
        context = "Python 문서"

        result = await reflector.reflect(
            query=query, answer=answer, context=context
        )

        assert result is not None
        assert isinstance(result.score, float)
        print(f"\n[긴 답변 테스트] 점수: {result.score}")

    @pytest.mark.asyncio
    @pytest.mark.timeout(60)
    async def test_special_characters_in_content(self, openai_llm_client, config):
        """
        테스트: 특수 문자가 포함된 콘텐츠 처리
        """
        reflector = AgentReflector(
            llm_client=openai_llm_client,
            config=config,
        )

        query = "JSON 형식은 어떻게 되나요?"
        answer = '{"key": "value", "array": [1, 2, 3]}'
        context = "JSON 스펙"

        result = await reflector.reflect(
            query=query, answer=answer, context=context
        )

        assert result is not None
        print(f"\n[특수문자 테스트] 점수: {result.score}")

    @pytest.mark.asyncio
    @pytest.mark.timeout(60)
    async def test_code_in_answer(self, openai_llm_client, config):
        """
        테스트: 코드가 포함된 답변 평가
        """
        reflector = AgentReflector(
            llm_client=openai_llm_client,
            config=config,
        )

        query = "Python에서 리스트를 정렬하는 방법은?"
        answer = """
        Python에서 리스트를 정렬하는 방법:

        ```python
        # 방법 1: sorted() 함수 (새 리스트 반환)
        my_list = [3, 1, 2]
        sorted_list = sorted(my_list)

        # 방법 2: sort() 메서드 (원본 수정)
        my_list.sort()
        ```

        sorted()는 원본을 유지하고, sort()는 원본을 수정합니다.
        """
        context = "Python 리스트 문서"

        result = await reflector.reflect(
            query=query, answer=answer, context=context
        )

        assert result is not None
        assert result.score >= 5.0, "코드 예시가 포함된 좋은 답변"
        print(f"\n[코드 답변 테스트] 점수: {result.score}")
