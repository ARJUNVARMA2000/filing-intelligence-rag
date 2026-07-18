# Financial RAG production architecture

## Objective

Turn the repository into a reproducible, evidence-first financial research system. A successful request must follow one inspectable path:

`validated question -> normalized scope -> candidate retrieval -> evidence ranking -> bounded context -> cited answer -> validated evidence ledger`

## Architectural decisions

### 1. Index contract

- Chroma's bundled `all-MiniLM-L6-v2` embedding is the current persisted-index contract (384 dimensions).
- The contract is explicit in code and an index manifest; ingestion must not call or bill an unrelated embedding provider.
- Index writes are batched, verified, and replace stale collections when a full rebuild is requested.
- Parser/chunker/index schema versions and corpus statistics are recorded with the artifact.

### 2. Provenance-preserving ingestion

- PDF narrative extraction excludes detected table regions; tables are emitted once as atomic blocks.
- HTML parsing walks meaningful elements in document order and avoids nested parent/child duplication.
- Chunk metadata is derived from `Block.lines`, including page, line, section, block IDs, block type, and table ID.
- Configuration flags must affect behavior; abandoned commented implementations are removed.

### 3. Retrieval and citations

- Requests are normalized and bounded before retrieval.
- Dense retrieval fetches a wider candidate set, then deterministic ranking removes duplicate passages and rewards exact query-term, ticker, period, and section signals.
- Context sources receive stable `[S1]` identifiers. The model must cite these identifiers inline.
- Only source identifiers actually present in the answer are returned in the evidence ledger. If the model omits citations, the service returns the ranked evidence with an explicit validation signal rather than inventing claim provenance.

### 4. API and provider boundaries

- Pydantic schemas constrain question size, ticker format, period format, retrieval depth, and model selection.
- Provider clients share one typed result/error contract and have bounded timeouts/output sizes.
- Unexpected provider failures are logged with a request ID and returned as sanitized non-200 errors.
- Production auth fails closed; local bypass requires an explicit auth mode.
- Expensive dependencies are cached and constructed once per process.

### 5. Product and operations

- The Streamlit workspace remains evidence-first and never exposes raw exception strings.
- Health is cheap; readiness validates configuration and the packaged index count.
- CI runs formatting/lint, deterministic unit/integration tests, and compilation.
- Documentation describes the implementation that actually exists and provides working local, indexing, evaluation, and deployment commands.

## Verification gates

- Unit tests: schemas, query parsing, chunk provenance, ranking, citation selection, auth mode, and sanitized failures.
- Integration tests: FastAPI health/chat behavior with injected fakes and Streamlit landing/conversation states.
- Artifact checks: manifest schema, non-empty collection, source count, metadata completeness, and archive layout.
- Quality checks: Ruff, compileall, pytest, container configuration validation, and a final diff/repository-hygiene review.
