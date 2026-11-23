import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.modules.core.generation.korean_evidence_routing import KoreanConditionalEvidenceSelector
from app.modules.core.generation.korean_evidence_selection import (
    FEATURES,
    KoreanEvidenceSelector,
    features,
    sentences,
)


@pytest.mark.asyncio
async def test_prioritize_evidence_preserves_distant_sentences_and_original_offsets() -> None:
    article = "자료가 공개됐다.\n봄꽃 축제의 후원 기관은 시립도서관이다. 이후 기금이 조성됐다. 행사는 마감됐다."
    doc = {"id": "one", "title": "공개 자료", "content": article}
    selector = KoreanEvidenceSelector("lexical")
    model = AsyncMock()
    model.generate_text.return_value = "[1.2] 시립도서관"
    found = await selector.read(model, "봄꽃 축제의 후원 기관은?", [doc])
    assert found and article[found["start"]:found["end"]] == found["answer"] == "시립도서관"
    assert article[found["quote_start"]:found["quote_end"]] == found["quote"]
    prompt = model.generate_text.call_args.kwargs["prompt"]
    assert prompt.splitlines()[0].split(": ")[1].startswith("[1.2]")
    lines = [line for line in prompt.splitlines() if line.startswith("[")]
    assert [line.split("]")[0] for line in lines] == ["[1.1", "[1.2", "[1.3", "[1.4"]
    model.generate_text.return_value = "NONE"
    assert await selector.read(model, "누가 비행했나?", [doc]) is None
    model.generate_text.return_value = "[1.1] 시립도서관"
    with pytest.raises(ValueError, match="absent"):
        await selector.read(model, "후원 기관은?", [doc])


def test_features_are_bounded_and_coefficients_are_validated(tmp_path: Path) -> None:
    lines = sentences("지난달 2명이 참여했다. 올해는 12명이 참여했다.")
    rows = features("올해 12명이 참여했나?", lines)
    assert len(rows) == 2 and all(len(row) == len(FEATURES) for row in rows)
    assert all(0 <= f <= 1 for row in rows for f in row)
    params = tmp_path / "weights.json"
    params.write_text(json.dumps({"features": list(FEATURES), "coefficients": [float("nan")] * len(FEATURES)}))
    with pytest.raises(ValueError, match="coefficients"):
        KoreanEvidenceSelector("trained", params)


@pytest.mark.asyncio
@pytest.mark.parametrize("cut,show", [(10., False), (-10., True)])
async def test_conditional_reader_changes_only_prompt_priority(tmp_path: Path, cut: float, show: bool) -> None:
    coeffs, cal = tmp_path / "coeffs.json", tmp_path / "cal.json"
    coeffs.write_text(json.dumps({"features": list(FEATURES), "coefficients": [0.] * len(FEATURES)}))
    cal.write_text(json.dumps({"cut": cut}))
    reader = KoreanConditionalEvidenceSelector(coeffs, cal)
    model = AsyncMock()
    model.generate_text.return_value = "[1.1] 부산"
    out = await reader.read(model, "개최 도시는?", [{"id": "one", "content": "부산 개최.", "title": "일정"}])
    assert out is not None and (out["answer"], out["start"], out["end"]) == ("부산", 0, 2)
    assert model.generate_text.call_args.kwargs["prompt"].startswith("질문과 관련될 수 있는 원문 문장") == show
