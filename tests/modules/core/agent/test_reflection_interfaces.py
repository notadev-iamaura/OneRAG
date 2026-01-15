"""
ReflectionResult 데이터 클래스 테스트

Self-Reflection 기능의 핵심 데이터 구조인 ReflectionResult의 생성,
기본값 처리, 경계값 동작을 검증합니다.
"""
import pytest
from app.modules.core.agent.interfaces import ReflectionResult


class TestReflectionResult:
    """ReflectionResult 데이터 클래스 테스트"""

    def test_reflection_result_creation(self):
        """ReflectionResult 기본 생성 테스트"""
        # Given: 모든 필드가 지정된 값
        # When: ReflectionResult 생성
        result = ReflectionResult(
            score=8.5,
            issues=[],
            suggestions=[],
            needs_improvement=False,
            reasoning="답변이 질문에 정확히 답변함"
        )

        # Then: 모든 필드가 정확히 설정됨
        assert result.score == 8.5
        assert result.issues == []
        assert result.suggestions == []
        assert result.needs_improvement is False
        assert result.reasoning == "답변이 질문에 정확히 답변함"

    def test_reflection_result_with_issues(self):
        """이슈가 있는 ReflectionResult 테스트"""
        # Given: 문제점과 개선 제안이 있는 저품질 답변
        # When: ReflectionResult 생성
        result = ReflectionResult(
            score=4.0,
            issues=["정보 누락", "불확실한 내용 포함"],
            suggestions=["추가 검색 필요", "출처 확인 필요"],
            needs_improvement=True,
            reasoning="답변에 누락된 정보가 있음"
        )

        # Then: 이슈와 제안이 올바르게 저장됨
        assert result.score == 4.0
        assert len(result.issues) == 2
        assert "정보 누락" in result.issues
        assert "불확실한 내용 포함" in result.issues
        assert len(result.suggestions) == 2
        assert "추가 검색 필요" in result.suggestions
        assert result.needs_improvement is True
        assert result.reasoning == "답변에 누락된 정보가 있음"

    def test_reflection_result_default_values(self):
        """ReflectionResult 기본값 테스트"""
        # Given: 필수 필드만 지정
        # When: ReflectionResult 생성 (선택적 필드는 기본값 사용)
        result = ReflectionResult(
            score=7.0,
            needs_improvement=False
        )

        # Then: 선택적 필드는 기본값으로 설정됨
        assert result.score == 7.0
        assert result.needs_improvement is False
        assert result.issues == []
        assert result.suggestions == []
        assert result.reasoning == ""

    def test_reflection_result_score_boundary_low(self):
        """점수 최저 경계값(0.0) 테스트"""
        # Given/When: 최저 점수로 생성
        result = ReflectionResult(score=0.0, needs_improvement=True)

        # Then: 0.0 점수가 정확히 저장됨
        assert result.score == 0.0
        assert result.needs_improvement is True

    def test_reflection_result_score_boundary_high(self):
        """점수 최고 경계값(10.0) 테스트"""
        # Given/When: 최고 점수로 생성
        result = ReflectionResult(score=10.0, needs_improvement=False)

        # Then: 10.0 점수가 정확히 저장됨
        assert result.score == 10.0
        assert result.needs_improvement is False

    def test_reflection_result_immutable_default_lists(self):
        """기본 리스트가 공유되지 않음을 검증 (mutable default 방지)"""
        # Given: 두 개의 ReflectionResult 인스턴스
        result1 = ReflectionResult(score=5.0, needs_improvement=True)
        result2 = ReflectionResult(score=6.0, needs_improvement=False)

        # When: 한 인스턴스의 리스트를 수정
        result1.issues.append("테스트 이슈")
        result1.suggestions.append("테스트 제안")

        # Then: 다른 인스턴스에 영향 없음 (리스트가 공유되지 않음)
        assert result1.issues == ["테스트 이슈"]
        assert result2.issues == []
        assert result1.suggestions == ["테스트 제안"]
        assert result2.suggestions == []
