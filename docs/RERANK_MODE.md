# Reranker mode and migration

`RERANK_MODE=legacy|jev` selects one reranker per worker lifetime. Unset means
`legacy`; an explicitly empty value is a startup error. Whitespace and case are
normalized. `legacy_observe` is reserved and unsupported.

legacy 에서는 **리랭킹 단계의** Jev 생성·호출이 0이다.
jev 에서는 **리랭킹 단계의** 기존 리랭커 생성·호출이 0이다.

These guarantees cover the reranking stage only, specifically the object created
by `RerankerFactoryV2` and its calls. **RERANK_MODE does NOT control Self-RAG
precheck or the answer-generation LLM.** Precheck can call TypeSafe even in legacy
mode. For zero TypeSafe HTTP calls across the app, use `RERANK_MODE=legacy` together
with `self_rag.precheck.mode=off`. Jev mode does not turn off Gemini answer generation.

## Turn Jev on

Set these in the deployment environment, then restart workers:

```dotenv
# Jev ON (the existing reranker is OFF in the reranking stage)
RERANK_MODE=jev
TYPESAFE_API_KEY=<key issued by TypeSafe>
# Optional: TYPESAFE_JEV_MODEL=jev-1.13.0
```

Keep `reranking.enabled=true`. Jev requires a nonblank key or startup fails.
Document passages are sent to TypeSafe. Jev ignores the legacy `approach/provider`
selection and runs in enforce mode. It filters relevance while preserving retrieval
order and scores, retaining at least `min_keep` within `top_n`. A successful Jev
judgment uses `min_relevance` instead of the downstream retrieval `min_score` filter;
rerank fusion is bypassed. Compare retrieval and answer quality before production use.

On errors, batch deadlines, or an open circuit, Jev returns retrieval order bounded
by `top_n`, marked as fallback, without calling an existing reranker. Repeated failed
batches (including timeouts) open the circuit. Already-sent HTTP cannot be recalled.

`legacy` uses the configured `approach/provider`, including local models; the shipped
default is `llm/google`. Missing legacy API keys retain graceful degradation with
`effective_reranker=none`. Exception fallbacks now also respect `top_n`; normal
legacy behavior is unchanged. `reranking.enabled=false` constructs neither reranker
and skips key checks, while malformed mode values still fail.

The base Compose file reads deployment settings from its optional `.env` file.
The production Compose file passes `RERANK_MODE` through without inserting a default,
and forwards the TypeSafe key/model. Supply production values through its environment.
Never put real keys in version control or logs.

## Upgrade existing deployments

| Previous config, with no new mode | Upgrade behavior |
| --- | --- |
| Normal `approach: llm` (or another existing approach) | legacy, unchanged |
| `approach: decision` + shadow/off/unspecified | **Migration error; startup stops** |
| `approach: decision` + enforce + key | Jev with deprecation warning |
| `approach: decision` + enforce without key | Startup fails |

There is no silent migration from decision+shadow/off to Gemini. Explicitly choose
`RERANK_MODE=legacy` or `RERANK_MODE=jev`, then change `approach` from `decision` to
a supported legacy selection (for example `llm/google`) for future rollback.
Explicit legacy with a stale decision approach selects `llm/google` with a warning.

`TYPESAFE_JEV_MODE` is deprecated. During compatibility, the resolver reads it directly
from the environment even though its YAML substitution was removed. It takes
precedence over an old literal `typesafe.mode`. An explicit new mode overrides both
old settings with a warning. Remove `TYPESAFE_JEV_MODE`, `typesafe.mode`, and
`typesafe.shadow_background` from new deployments. Schema defaults for the last two
are `None`, and the factory never forwards them. Decision compatibility is scheduled
for removal after two releases; the next release will announce that removal.

Before deploying, use the new checkout/image with the intended deployment environment:

```bash
uv run python -m app.modules.core.retrieval.rerankers.mode --check
```

This creates no reranker and makes no network calls. It reports effective mode,
source, warnings, and key presence (never key values). Configuration errors exit 1.
Environment `RERANK_MODE` wins over a literal YAML `reranking.mode` with a conflict
warning. The YAML placeholder's empty default is not evidence of an explicit choice;
the resolver uses the environment snapshot to detect an explicitly empty variable.

## Rolling transition and rollback

1. Deploy an explicit `RERANK_MODE=jev` or `RERANK_MODE=legacy` and run the preflight.
2. Start new workers; check `reranker_mode_resolved` logs for `effective` and `pid`,
   plus readiness. In legacy mode also verify that the intended reranker exists.
3. Move traffic, then drain and terminate old workers.
4. Transition is complete only when all surviving workers report the same mode.
   During rolling deployment, old and new workers coexist. Each request stays in
   one mode, but service-wide zero-call guarantees apply only after old workers exit.
5. If an immediate cutoff is required, stop traffic to old workers first.
6. Roll back by explicitly setting `RERANK_MODE=legacy` and repeating this procedure.
   Do not roll back by deleting the variable. Environment changes do not replace an
   already-created singleton; restart workers.

Rerank result cache keys include the mode, so a new worker cannot hit an old-mode
result. Multi-worker rollout validation and production quality comparisons remain
deployment checks, separate from the unit isolation tests.
