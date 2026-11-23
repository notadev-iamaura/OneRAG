#!/usr/bin/env python
"""
CI/CD 자동 평가 스크립트

Golden Dataset을 대상으로 배치 평가를 실행하고 결과를 출력합니다.
CI/CD 파이프라인에서 품질 게이트로 사용됩니다.

사용법:
    # 기본 실행 (internal 평가기)
    python scripts/run_eval.py

    # Ragas 평가기 사용
    python scripts/run_eval.py --provider ragas

    # 특정 데이터셋 지정
    python scripts/run_eval.py --dataset data/eval_set.json

    # 최소 품질 임계값 설정
    python scripts/run_eval.py --threshold 0.8

    # pytest와 함께 사용 (마커 필터링)
    pytest -m eval

종료 코드:
    0: 평가 통과 (평균 점수 >= threshold)
    1: 평가 실패 (평균 점수 < threshold)
    2: 실행 오류
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

# 프로젝트 루트를 PYTHONPATH에 추가
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


async def load_dataset(dataset_path: str) -> list[dict]:
    """
    Golden Dataset 로드

    Args:
        dataset_path: 데이터셋 파일 경로 (JSON)

    Returns:
        평가 샘플 리스트
    """
    path = Path(dataset_path)
    if not path.exists():
        raise FileNotFoundError(f"평가 데이터셋이 없습니다: {dataset_path}")

    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    # 형식 검증
    samples = data.get("samples") if isinstance(data, dict) else data
    if not isinstance(samples, list) or not samples:
        raise ValueError(f"평가 문항 목록이 비어 있거나 올바르지 않습니다: {dataset_path}")
    for index, sample in enumerate(samples, 1):
        if not isinstance(sample, dict) or not all(
            isinstance(sample.get(key), str) and sample[key].strip() for key in ("query", "answer")
        ):
            raise ValueError(f"문항 {index}: query와 answer가 필요합니다")
        context = sample.get("context")
        if isinstance(context, str):
            sample["context"] = [context]
        elif not isinstance(context, list) or not all(isinstance(s, str) for s in context):
            raise ValueError(f"문항 {index}: context 문자열 또는 목록이 필요합니다")
    return samples


async def run_evaluation(
    samples: list[dict],
    provider: str = "internal",
    threshold: float = 0.7,
) -> dict:
    """
    배치 평가 실행

    Args:
        samples: 평가 샘플 리스트
        provider: 평가기 종류 ("internal" 또는 "ragas")
        threshold: 최소 품질 임계값

    Returns:
        평가 결과 딕셔너리
    """
    from app.core.di_container import create_evaluator_instance
    from app.lib.config_loader import load_config
    from app.lib.llm_client import LLMClientFactory

    if not samples:
        raise ValueError("평가할 문항이 없습니다")
    config = load_config()
    config["evaluation"] = {**config.get("evaluation", {}), "enabled": True, "provider": provider}
    llm_factory = LLMClientFactory(config) if provider == "internal" else None
    if llm_factory is not None:
        llm_factory.get_client(provider="openrouter")
    evaluator = await create_evaluator_instance(config, llm_factory)
    if evaluator is None or not evaluator.is_available():
        raise RuntimeError(f"평가기를 사용할 수 없습니다: {provider}")

    print(f"\n📊 배치 평가 시작 ({provider} 평가기)")
    print(f"   샘플 수: {len(samples)}")
    print(f"   임계값: {threshold}")
    print("-" * 50)

    # 평가 실행
    results = await evaluator.batch_evaluate(samples)
    if len(results) != len(samples):
        raise RuntimeError("평가 결과와 요청 문항 수가 다릅니다")
    for index, result in enumerate(results, 1):
        if not result.raw_scores:
            raise RuntimeError(f"문항 {index}의 유효한 채점 결과가 없습니다")

    # 통계 계산
    if results:
        avg_faithfulness = sum(r.faithfulness for r in results) / len(results)
        avg_relevance = sum(r.relevance for r in results) / len(results)
        avg_overall = sum(r.overall for r in results) / len(results)
        min_overall = min(r.overall for r in results)
        max_overall = max(r.overall for r in results)
    else:
        avg_faithfulness = avg_relevance = avg_overall = 0.0
        min_overall = max_overall = 0.0

    # 결과 출력
    print("\n📈 평가 결과:")
    print(f"   평균 충실도 (Faithfulness): {avg_faithfulness:.4f}")
    print(f"   평균 관련성 (Relevance):    {avg_relevance:.4f}")
    print(f"   평균 종합 (Overall):        {avg_overall:.4f}")
    print(f"   최소 점수: {min_overall:.4f}, 최대 점수: {max_overall:.4f}")
    print("-" * 50)

    # 개별 결과 출력
    if len(samples) <= 10:
        print("\n📝 개별 결과:")
        for i, (sample, result) in enumerate(zip(samples, results, strict=True)):
            status = "✅" if result.overall >= threshold else "❌"
            print(f"   {i+1}. {status} {sample.get('query', 'N/A')[:30]}...")
            print(f"      → 충실도: {result.faithfulness:.2f}, 관련성: {result.relevance:.2f}, 종합: {result.overall:.2f}")

    # 통과 여부 판정
    passed = avg_overall >= threshold
    failed_count = sum(1 for r in results if r.overall < threshold)

    print("\n" + "=" * 50)
    if passed:
        print(f"✅ 평가 통과! (평균: {avg_overall:.4f} >= {threshold})")
    else:
        print(f"❌ 평가 실패! (평균: {avg_overall:.4f} < {threshold})")
        print(f"   실패한 샘플: {failed_count}/{len(results)}")
    print("=" * 50)

    return {
        "passed": passed,
        "avg_faithfulness": avg_faithfulness,
        "avg_relevance": avg_relevance,
        "avg_overall": avg_overall,
        "min_overall": min_overall,
        "max_overall": max_overall,
        "sample_count": len(results),
        "failed_count": failed_count,
    }


def main() -> None:
    """메인 함수"""
    parser = argparse.ArgumentParser(
        description="RAG 시스템 품질 평가 스크립트",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
예시:
  python scripts/run_eval.py
  python scripts/run_eval.py --provider ragas --threshold 0.8
  python scripts/run_eval.py --dataset data/golden_dataset.json
        """,
    )
    parser.add_argument(
        "--provider",
        type=str,
        default="internal",
        choices=["internal", "ragas"],
        help="평가기 종류 (기본값: internal)",
    )
    parser.add_argument(
        "--dataset",
        type=str,
        default="data/eval_set.json",
        help="Golden Dataset 경로 (기본값: data/eval_set.json)",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.7,
        help="최소 품질 임계값 (기본값: 0.7)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="결과 저장 파일 경로 (JSON)",
    )

    args = parser.parse_args()

    try:
        # 데이터셋 로드
        samples = asyncio.run(load_dataset(args.dataset))

        # 평가 실행
        result = asyncio.run(
            run_evaluation(
                samples=samples,
                provider=args.provider,
                threshold=args.threshold,
            )
        )

        # 결과 저장
        if args.output:
            output_path = Path(args.output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
            print(f"\n📁 결과 저장됨: {args.output}")

        # 종료 코드
        sys.exit(0 if result["passed"] else 1)

    except Exception as e:
        print(f"\n❌ 실행 오류: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(2)


if __name__ == "__main__":
    main()
