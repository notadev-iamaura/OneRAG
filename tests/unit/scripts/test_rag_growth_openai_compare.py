import traceback
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.modules.core.generation.grounded_span import _INSTRUCTIONS
from scripts import rag_growth_openai_compare as bench

KW = {"temperature": 0, "max_tokens": 100, "require_complete": True}


def client_for(response=None, error=None):
    create = AsyncMock(return_value=response, side_effect=error)
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


def completion(text="NONE", finish="stop"):
    return SimpleNamespace(
        model=bench.MODEL, id="public-completion", _request_id="public-request",
        choices=[SimpleNamespace(message=SimpleNamespace(content=text), finish_reason=finish)],
        usage=SimpleNamespace(model_dump=lambda: {"prompt_tokens": 20, "completion_tokens": 1, "total_tokens": 21}),
    )


def paid(client, directory, question="public example"):
    sha = bench.fingerprint(bench.messages(question, _INSTRUCTIONS, KW))
    return bench.PaidQuestion(client, directory, "public_case", "frozen_policy", sha)


@pytest.mark.asyncio
async def test_exact_public_prompt_uses_fixed_provider_parameters_and_caches_completed_response(tmp_path):
    client = client_for(completion())
    first = paid(client, tmp_path)
    raw = await first.generate_text(prompt="public example", system_prompt=_INSTRUCTIONS, **KW)
    assert raw == "NONE"
    client.chat.completions.create.assert_awaited_once_with(
        messages=bench.messages("public example", _INSTRUCTIONS, KW), model="gpt-5.4-2026-03-05",
        temperature=0, reasoning_effort="none", max_completion_tokens=100, store=False,
    )
    assert first.record["provider_model"] == bench.MODEL
    assert first.record["usage"]["total_tokens"] == 21
    assert first.record["finish_reason"] == "stop"
    rec = paid(client, tmp_path)
    assert await rec.generate_text(prompt="public example", system_prompt=_INSTRUCTIONS, **KW) == "NONE"
    assert client.chat.completions.create.await_count == 1


@pytest.mark.asyncio
async def test_different_document_or_extra_generation_can_never_be_sent(tmp_path):
    client = client_for(completion())
    with pytest.raises(bench.ProviderBlocked, match="Unexpected"):
        await paid(client, tmp_path).generate_text(prompt="different text", system_prompt=_INSTRUCTIONS, **KW)
    with pytest.raises(bench.ProviderBlocked, match="registered"):
        await paid(client, tmp_path).generate_text(prompt="public example", system_prompt="other use", **KW)
    client.chat.completions.create.assert_not_awaited()
    assert not list(tmp_path.iterdir())
    one = paid(client, tmp_path)
    await one.generate_text(prompt="public example", system_prompt=_INSTRUCTIONS, **KW)
    with pytest.raises(bench.ProviderBlocked, match="repeated"):
        await one.generate_text(prompt="public example", system_prompt=_INSTRUCTIONS, **KW)
    assert client.chat.completions.create.await_count == 1


@pytest.mark.asyncio
async def test_provider_failure_is_sanitized_halts_and_cannot_rebill(tmp_path):
    class Unauthorized(Exception):
        status_code = 401

    canary = "synthetic-sensitive-error-fragment"
    client = client_for(error=Unauthorized(canary))
    with pytest.raises(bench.ProviderBlocked) as exc:
        await paid(client, tmp_path).generate_text(prompt="public example", system_prompt=_INSTRUCTIONS, **KW)
    assert "401" in str(exc.value) and canary not in "".join(traceback.format_exception(exc.value))
    assert canary not in (tmp_path / "public_case.failure.json").read_text()
    with pytest.raises(bench.ProviderBlocked, match="unresolved"):
        await paid(client, tmp_path).generate_text(prompt="public example", system_prompt=_INSTRUCTIONS, **KW)
    assert client.chat.completions.create.await_count == 1


@pytest.mark.asyncio
async def test_truncated_literal_is_an_error_even_on_cache_recovery(tmp_path):
    client = client_for(completion("NONE", "length"))
    for _ in range(2):
        with pytest.raises(ValueError, match="Incomplete"):
            await paid(client, tmp_path).generate_text(prompt="public example", system_prompt=_INSTRUCTIONS, **KW)
    assert client.chat.completions.create.await_count == 1
    assert bench.read(tmp_path / "public_case.response.json")["finish_reason"] == "length"


def test_only_pinned_development_inputs_are_loaded(tmp_path, monkeypatch):
    questions = [{"id": f"klue-mrc-v1_dev_{i:05d}", "question": f"Fixture question {i}?"} for i in range(80)]
    corpus = [{"id": str(i), "title": f"Article {i}", "content": f"Fixture text {i}."} for i in range(512)]
    labels = [{"id": q["id"], "answerable": i % 2 == 0, "answers": [str(i)] if i % 2 == 0 else []}
              for i, q in enumerate(questions)]
    parts = {"questions": questions, "corpus": corpus, "labels": labels}
    panels = tmp_path / "panels"
    panels.mkdir()
    manifest = {}
    for name, rows in parts.items():
        path = panels / f"dev.{name}.json"
        bench.persist(path, rows)
        manifest[path.name] = bench.digest(path)
    bench.persist(panels / "reservation.json", {"files": manifest})
    (tmp_path / "qwen").mkdir()
    ids = [q["id"] for q in questions[:24]]
    bench.persist(tmp_path / "qwen/prior-comparison-plan.json", {"ids": ids})
    monkeypatch.setattr(bench, "EVIDENCE", tmp_path)
    monkeypatch.setattr(bench, "ASSETS", {key: bench.digest(tmp_path / key)
                                        for key in ("panels/reservation.json", "qwen/prior-comparison-plan.json")})
    parts, screen = bench.inputs()
    assert screen == ids and parts["questions"] == questions and parts["corpus"] == corpus
    (panels / "dev.corpus.json").write_text("[]")
    with pytest.raises(ValueError, match="Public development file changed"):
        bench.inputs()
    (panels / "reservation.json").write_text("{}")
    with pytest.raises(ValueError, match="registered public input changed"):
        bench.inputs()


@pytest.mark.asyncio
async def test_environment_cannot_override_the_endpoint(monkeypatch):
    monkeypatch.setenv("OPENAI_BASE_URL", "https://unrelated.invalid/api")
    monkeypatch.setenv("OPENAI_ORG_ID", "unrelated")
    async with bench.provider_client("explicit-test-value") as client:
        assert str(client.base_url) == "https://api.openai.com/v1/"
        assert client.max_retries == 0 and client.organization is None and client.project is None
        assert client._client.follow_redirects is False and client._client.trust_env is False
