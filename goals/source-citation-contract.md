# Source Citation Contract Goal

## Goal ID

`source-citation-contract`

## Objective

Make OneRAG return provider-neutral, stable, and UI-friendly source citations
across local RAG, SQL search, and managed provider modes while preserving the
existing `Source` response fields for backward compatibility.

## Why This Is Priority 2

Open-source users need predictable citations before they can safely build
frontends, audits, exports, and evaluation tooling on top of OneRAG. The current
surface exposes useful fields, but provider-specific metadata names such as
`page`, `page_number`, `chunk`, `chunk_index`, `source_file`, `filename`, and
Grok citation payloads are not normalized into one contract.

## Target Contract

Every chat source should expose these normalized fields when available:

- `source_id`: stable provider-neutral citation identifier
- `document_id`: underlying document/file identifier
- `document_name`: display name, also mirrored to existing `document`
- `page`: normalized page number from `page`, `page_number`, or `page_index`
- `chunk`: normalized chunk number from `chunk` or `chunk_index`
- `section`: heading/section label when available
- `source_uri`: URL, file URI, or provider citation URI when available
- `score`: normalized score, mirrored from existing `relevance`
- `metadata`: provider-neutral metadata payload

## Done Criteria

This goal is complete only when:

1. Existing `Source` consumers remain backward compatible.
2. Local RAG sources normalize `page_number` and `chunk_index`.
3. Grok managed citations normalize string and object citation payloads.
4. SQL sources receive the same baseline citation identifiers.
5. Targeted backend tests prove the contract.
6. Ruff or an equivalent syntax/static gate passes for touched Python files.

## Harness Execution

- Bundle: RAG Quality
- Evidence model: local paired audit because subagents were not explicitly
  requested for this turn.
- Verification: targeted unit tests around `RAGPipeline.format_sources`,
  Grok answer mode citation formatting, and source schema compatibility.
