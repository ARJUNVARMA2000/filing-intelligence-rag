# Filing Intelligence RAG

## Filing Intelligence RAG rename - 2026-07-17

### Plan

- [x] Inventory repository, documentation, product branding, Cloud Run services, images, and shared-resource boundaries.
- [x] Rename only the standalone GitHub repository and retarget this checkout's origin and push safeguard.
- [x] Replace active portfolio branding and deployment targets with `Filing Intelligence RAG`, `filing-intelligence-rag`, and `filing-intelligence-rag-api` while preserving compatibility identifiers and application behavior.
- [ ] Run the complete local release gate, commit, push, deploy isolated services, and verify CI and live behavior.
- [ ] Remove only superseded standalone `finrag-research*` services/images after the Filing Intelligence RAG deployment passes; verify the shared repository and services remain untouched.

### Acceptance criteria

- The standalone repository is `ARJUNVARMA2000/filing-intelligence-rag`, remains private and parentless, and is the only remote for this checkout.
- The live portfolio application and API use Filing Intelligence RAG service names and URLs, with the same application behavior and data sources as the preceding standalone release.
- Shared `Financial-RAG`, `finrag-frontend`, and `finrag-backend` resources receive no writes or configuration changes.
- Documentation contains only the current Filing Intelligence RAG deployment links and regenerated Filing Intelligence RAG screenshots.
- Local checks, GitHub Actions, Cloud Build, live smoke tests, PDF citation rendering, and local/remote commit parity all pass.

## Portfolio product rebrand - 2026-07-17

### Plan

- [x] Select the product-aligned repository and service names `finrag-research` and `finrag-research-api`.
- [x] Rename the standalone GitHub repository and update its description, homepage, and portfolio topics.
- [x] Remove account-name branding from configuration, documentation, tests, task records, and public URLs.
- [x] Deploy and verify the branded Cloud Run services, then remove the temporary named services and images.
- [x] Run CI and confirm the repository, deployment, and local checkout are synchronized.

### Implementation review

- Renamed the sole-owner repository to `finrag-research`, set a portfolio description and homepage, and added focused financial-analysis, RAG, FastAPI, Streamlit, and Vertex AI topics.
- Removed account-name branding from tracked configuration, documentation, tests, and task records; the product identity is consistently `FinRAG Research`, with `finrag-research` and `finrag-research-api` deployment targets.
- Cloud Build `f584ec84-a8b0-4c26-bf93-22e0eb5aa5a0` succeeded and deployed revisions `finrag-research-00001-j7s` and `finrag-research-api-00001-6cc`, each Ready with 100% traffic and branded image packages.
- Granted the frontend runtime identity `roles/run.invoker` on the portfolio API. Browser QA then returned NVIDIA Q3 FY26 revenue of $57.0 billion and highlighted the cited passage on PDF page 10 with no fallback, overflow, or console entries.
- Verified the temporary account-named Cloud Run services and Artifact Registry packages are absent. Shared services, generic runtime identities, the repository, and the document bucket were left untouched.

## Clean standalone repository separation - 2026-07-17

### Plan

- [x] Confirm the production work currently exists only on a draft branch inside the contributors' repository.
- [x] Create a clean root snapshot so the standalone repository does not inherit shared contributor history.
- [x] Create `finrag-research` and publish the snapshot as `main`.
- [x] Verify repository ownership, README links, CI, live deployment, and local/remote parity.
- [x] Close the old draft PR and remove only `codex/production-rag-overhaul` from the contributors' repository.

### Implementation review

- Created the private, sole-collaborator repository `finrag-research` with a parentless root snapshot, so the shared project's commit and contributor history were not inherited.
- The standalone repository's `main` contains the complete production workspace and links only to the portfolio deployment; its independent GitHub Actions quality workflow passes.
- Repointed this workspace's sole Git remote to the standalone repository and made local `main` track `origin/main`.
- Closed old PR #1, deleted only the old `codex/production-rag-overhaul` branch, and verified the contributors' `main` remains unchanged at `d04b1b1` with its original site link.

## Canonical deployment documentation - 2026-07-17

### Plan

- [x] Verify the restored site and standalone deployment traffic targets independently.
- [x] Make the README present only the portfolio deployment.
- [x] Align setup and freshness documentation with the portfolio endpoints.
- [x] Run tests, validate links, commit, push, and confirm local/remote parity.

### Implementation review

- Confirmed the original URLs remain pinned to backend `finrag-backend-00007-kcp` and frontend `finrag-frontend-00006-snv`, while the standalone deployment serves separate revisions with 100% traffic.
- The README contains only the portfolio workspace, readiness, and coverage links; no previous deployment URL or migration history is present.
- Setup and freshness docs use the same portfolio endpoints, and a regression test rejects previous canonical URLs from all user-facing Markdown files.
- Ruff lint/format, `git diff --check`, all 54 tests, and live HTTP checks for all three documented endpoints pass.

## Isolated deployment correction - 2026-07-17

### Plan

- [x] Confirm the intended repository contains the original contributor history and inspect cloud-project ownership.
- [x] Retarget normal and refresh deployment defaults to unique standalone services and public URLs.
- [x] Restore the pre-existing `finrag-*` URLs to their pre-change revisions.
- [x] Run the complete release gate, commit, push, and deploy the isolated services.
- [x] Verify the new application URL, highlighted PDF viewer, logs, GitHub checks, and local/remote parity.

### Implementation review

- The original site is restored to backend revision `finrag-backend-00007-kcp` and frontend revision `finrag-frontend-00006-snv`, each with 100% traffic.
- Both Cloud Build configurations default to isolated service, image, and URL targets; a regression test prevents the old service names from returning as deploy targets.
- Local Ruff lint, Ruff formatting, compilation, YAML parsing, `git diff --check`, and all 53 tests pass before deployment.
- Cloud Build `ef649b8f-9262-4ed2-9bdd-9b47c0adcb89` succeeded and created the first standalone backend and frontend revisions, each Ready with 100% traffic and isolated build-tagged images.
- First-service public invoker bindings were applied explicitly after Cloud Run did not persist `--allow-unauthenticated`; automated smoke then passed with 4,967 indexed chunks and a 597,845-byte source PDF.
- Browser QA on the isolated URL returned NVIDIA Q3 FY26 revenue of $57.0 billion, kept citation URLs on the isolated backend, rendered page 10 with non-zero canvases, visibly highlighted the cited passage, and found no fallback, overflow, or console entries.

## Final highlighted-source redeployment - 2026-07-17

### Plan

- [x] Re-run the complete lint, formatting, test, compilation, dependency, and repository release gates.
- [x] Deploy the corrected backend and frontend images from the clean pushed runtime commit.
- [x] Verify Cloud Run revision readiness, traffic, live RAG behavior, PDF rendering, citation highlighting, browser diagnostics, and error logs.
- [x] Confirm the local branch and upstream branch resolve to the same commit with passing GitHub checks.

### Implementation review

- Upgraded the frontend from Streamlit 1.51.0 to 1.56.0 to remove invalid inherited-theme console warnings without introducing the Starlette dependency boundary used by later releases.
- Runtime commit `f877987` is pushed to `codex/production-rag-overhaul`; GitHub Actions passes and the local/upstream divergence is zero.
- Cloud Build `fa6ade57-c472-4dd1-8604-a29eb6e3ec00` passed all seven steps and deployed backend revision `finrag-backend-00009-cmn` plus frontend revision `finrag-frontend-00008-t5w`, each Ready with 100% traffic and the same build-tagged image.
- Production smoke passed with 4,967 indexed chunks and a 597,845-byte source PDF. A real NVIDIA Q3 FY26 query returned revenue of $57.0 billion, opened page 10, rendered non-zero PDF canvases, and visibly highlighted the cited passage.
- The enhanced viewer showed no fallback or horizontal overflow; frontend and source-viewer consoles were empty, and both new Cloud Run revisions had zero error-level log entries.

## Commit and deployment release - 2026-07-17

### Plan

- [x] Audit the branch, cloud configuration, live services, and pull-request checks.
- [x] Update the README with the current Quartr access model, supported ingestion path, and packaged ticker coverage.
- [x] Run local lint, format, tests, compilation, and repository hygiene checks.
- [x] Commit and push the complete intended worktree.
- [x] Deploy through Cloud Build and verify the live backend and frontend.

### Implementation review

- README, freshness coverage, per-ticker health reporting, and the citation viewer are included in the release candidate.
- Local release gates pass with Ruff, format, compilation, Cloud Build schema checks, `git diff --check`, and 52 tests.
- Runtime release commits `0f820c1` and `a422459` were pushed to `codex/production-rag-overhaul`; GitHub quality checks pass on the final runtime commit.
- Final Cloud Build `bebc60d9-ed5b-42bd-892b-ea28a9a9d693` passed all seven steps and deployed backend revision `finrag-backend-00007-kcp` plus frontend revision `finrag-frontend-00006-snv`, each Ready with 100% traffic.
- Live smoke opened 4,967 indexed chunks and streamed a 597,845-byte source PDF. Browser QA returned NVIDIA Q3 FY26 revenue of $57.0 billion with five sources, highlighted the cited sentence on page 1, and found no console or Cloud Run error entries.
- The deployed legacy corpus correctly reports freshness `unknown` for all 15 tickers. An actual Quartr refresh remains unavailable until the separate API entitlement and `quartr-api-key` secret are supplied.

## Highlighted source viewer repair - 2026-07-17

### Scope and acceptance criteria

- Opening a highlighted citation renders the source PDF inside the citation viewer instead of leaving a blank or perpetually loading canvas.
- The viewer opens the cited page, searches for the cited phrase when a text layer is available, and keeps a readable excerpt visible when exact in-PDF highlighting is unavailable.
- PDF.js uses a compatible, internally consistent release and asset layout; failure falls back to a clearly labeled native PDF viewer with a direct open/download action.
- Document responses preserve inline rendering and support the loading behavior used by both PDF.js and browser-native viewers.
- The viewer is responsive, accessible, visually consistent with the analyst workspace, and covered by focused automated and browser-level checks.

### Plan

- [x] Reproduce and document the current PDF.js/asset-loading failure and baseline representative PDFs.
- [x] Replace the brittle viewer bootstrap with one supported PDF.js integration and an explicit native fallback.
- [x] Refine the citation viewer layout, loading/error states, controls, page navigation, and excerpt presentation.
- [x] Add focused tests for response headers, escaped viewer data, correct PDF.js assets, page targeting, and fallback markup.
- [x] Run lint/format, targeted and full tests, PDF rendering checks, and browser QA against a real citation viewer route.

### Implementation review

- Replaced incompatible legacy PDF.js script paths with the 4.2.67 ES-module build, viewer stylesheet, worker, CMaps, and standard fonts from one CDN release.
- Added page navigation, fit-width zoom controls, exact-text search with a bounded no-match state, sanitized source excerpts, encoded route IDs, and a lazy native-PDF fallback.
- Preserved inline document delivery and exposed range-related headers required by embedded PDF readers.
- Renamed the evidence-ledger action to `View cited page` so the UI does not promise a highlight before the viewer confirms an exact text match.

### Verification evidence

- Focused document/deployment tests cover source-path safety, inline headers, PDF.js assets, page targeting, fallback markup, and script escaping.
- Ruff lint, Ruff format check, `git diff --check`, and the full local suite pass with 52 tests.
- Poppler rendered the representative 13-page NVIDIA filing successfully; the first page was inspected with no clipping, broken glyphs, or layout defects.
- Local browser QA rendered a real 30-page NVIDIA deck with 30 PDF pages, non-zero canvases, correct page-1 highlighting, and no console warnings or errors.
- A page-3 citation opened on page 3 and settled to an explicit no-match state when its extracted phrase differed from the PDF text layer.
- Desktop and 390 px mobile checks show no horizontal overflow; the native fallback remained hidden during successful enhanced rendering.

## Scope and acceptance criteria

- Preserve and complete the existing frontend, fresh-data, and GCP work in the repository.
- Replace brittle or misleading pipeline behavior with explicit, typed, testable components.
- Make ingestion, retrieval, citations, provider selection, configuration, and failure modes deterministic and observable.
- Deliver an analyst-quality interface with clear research scope, trustworthy evidence, and useful empty/error states.
- Make local development, CI, index refreshes, and production deployment reproducible from documented commands.
- Require automated tests, lint/format checks, artifact validation, browser QA, and live deployment smoke tests before completion.

## Plan

- [x] Baseline the repository, uncommitted work, tests, deployed services, and runtime behavior.
- [x] Document the target architecture and prioritize backend, RAG, frontend, and operations gaps.
- [x] Harden API schemas, configuration, security boundaries, provider limits, error handling, and dependency construction.
- [x] Rewrite parsing/chunking where needed and preserve page, line, section, table, and source provenance.
- [x] Improve query understanding, retrieval/ranking, context assembly, bounded history, and citation integrity.
- [x] Complete the institutional research workspace and resilient frontend API boundary.
- [x] Add Quartr synchronization, watermarks, source sidecars, freshness health, and immutable refresh automation.
- [x] Add professional dependency manifests, containers, CI/deployment gates, observability, and accurate documentation.
- [x] Rebuild and clean-extract the packaged index with complete provenance metadata.
- [x] Capture desktop/mobile product screenshots and remove stale documentation claims.
- [x] Run the complete release verification matrix.
- [x] Create a release branch, commit, and push the complete intended worktree.
- [x] Deploy the backend/frontend and verify the live release end to end.

## Implementation review

- Replaced the paid-and-discarded embedding path with an explicit 384-dimensional Chroma MiniLM contract, compatibility validation, and a schema-v2 index manifest.
- Rewrote active PDF/HTML parsing and chunking to avoid duplicated table/nested content, preserve reading order, keep tables atomic, and carry source provenance.
- Added deterministic query scope parsing, correct fiscal-token handling, optional filters, `LATEST`, bounded conversation history, wider retrieval, duplicate suppression, lexical+dense ranking, `[S#]` contexts, and answer-bound citation selection.
- Hardened request schemas, model allowlists, provider timeouts/retries/output limits, local/production auth modes, CORS, dependency caching, request IDs, sanitized failures, source-path confinement, and streamed GCS responses.
- Removed the duplicated formatter that could mutate financial values. The frontend now preserves answer text, escapes dynamic HTML, sanitizes transport failures, and reports actual service readiness.
- Rebuilt the Streamlit product as a responsive institutional research workspace with scope controls, an evidence ledger, accessible focus/reduced-motion states, and desktop/mobile product captures.
- Added cursor-based Quartr report/transcript synchronization, overlap-safe watermarks, stable IDs, SHA-256 sidecars, source timestamps, stale-document cleanup, and `/health/data` freshness reporting.
- Split backend/frontend/dev dependencies, pinned the persisted-index compatibility boundary, added Ruff/Pytest configuration, GitHub CI, Cloud Build quality gates, non-root containers, safe first-run index restoration, and accurate setup/operations documentation.
- Removed tracked Python bytecode, macOS metadata, obsolete environment configuration, and abandoned commented implementations.

## Verification evidence

- Release gate: 44 tests passed; Ruff lint passed; all 60 Python files are formatted; GitHub Actions and both Cloud Build YAML files parsed; the clean dependency dry-run resolved; Markdown links and stale-marker checks passed; and `git diff --check` passed.
- The rebuilt archive contains 4,967 chunks across 128 documents and 15 tickers, with the expected 384-dimensional cosine embedding and exact manifest count after a clean extraction.
- Provenance coverage: page start/end 100%, line start/end 100%, section 94.1%, and table IDs on 1,681 table-derived chunks.
- Filtered NVDA Q3-2026 retrieval returns three evidence candidates from the rebuilt collection.
- Browser QA passes at 1280×720 and 390 px mobile width with no horizontal overflow; the deployed landing, answer, evidence ledger, and source viewer also pass with no console errors.
- Docker definitions are covered by Cloud Build because the local Docker Desktop engine is unavailable in this environment.
- GitHub branch `codex/production-rag-overhaul` is pushed with draft PR #1; the latest GitHub Actions quality run passes with current Node 24-compatible action releases.
- Cloud Build `6df9d9e6-870d-4ecc-8e5a-2a7a74a3ccfe` passed in 7m55s and deployed `finrag-backend-00005-mpk` plus `finrag-frontend-00004-nlr`, each Ready with 100% traffic.
- Live smoke verification opened 4,967 indexed chunks, streamed the 597,845-byte citation PDF, rejected unauthenticated paid routes, and rendered the production workspace.
- A real UI request returned NVIDIA Q3 FY26 revenue of $57.0 billion with six validated citations; the evidence ledger showed page/line provenance and the highlighted viewer loaded successfully.
- Post-deployment log audit found zero error entries for either new Cloud Run revision, and the deployed-page browser console contained no errors.
