"""
평가 컨텍스트 문서 라벨 외부화 테스트 (15차 범용화)

self_rag/evaluator와 internal_evaluator가 평가 프롬프트의 {context_text}를
조립할 때 쓰던 한국어 문서 라벨('문서 {i+1}:')을 config(document_label_template)로
외부화한 변경을 검증한다. 평가 프롬프트 템플릿은 이미 외부화됐는데 이 라벨만
한국어로 남던 비대칭을 해소한다. 미설정 시 byte 동치(회귀 0).
"""

from app.modules.core.evaluation.internal_evaluator import InternalEvaluator
from app.modules.core.self_rag.evaluator import LLMQualityEvaluator


class TestSelfRagEvaluatorLabel:
    def test_default_korean_label(self):
        """미설정 시 한국어 기본 라벨 '문서 N:' (회귀 0)."""
        ev = LLMQualityEvaluator(api_key=None)
        prompt = ev._build_evaluation_prompt("q", "a", ["doc1", "doc2"])
        assert "문서 1:\ndoc1" in prompt
        assert "문서 2:\ndoc2" in prompt

    def test_override_label(self):
        """document_label_template 주입 시 라벨이 바뀐다(언어 일관성)."""
        ev = LLMQualityEvaluator(api_key=None, document_label_template="[Doc {index}]")
        prompt = ev._build_evaluation_prompt("q", "a", ["doc1"])
        assert "[Doc 1]\ndoc1" in prompt
        assert "문서 1:" not in prompt


class TestInternalEvaluatorLabel:
    def test_default_korean_label(self):
        ev = InternalEvaluator(llm_client=None)
        prompt = ev._build_prompt("q", "a", ["doc1", "doc2"])
        assert "문서 1:\ndoc1" in prompt
        assert "문서 2:\ndoc2" in prompt

    def test_override_label(self):
        ev = InternalEvaluator(llm_client=None, document_label_template="[Doc {index}]")
        prompt = ev._build_prompt("q", "a", ["doc1"])
        assert "[Doc 1]\ndoc1" in prompt
        assert "문서 1:" not in prompt
