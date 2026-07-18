# Financial data freshness

The application now supports incremental ingestion from the supported Quartr Public API. It does **not** scrape `web.quartr.com` or reuse browser cookies. Quartr web/Pro access and Quartr Public API access are separate entitlements; obtain an API key and the required reports/transcripts datasets in the [Quartr Portal](https://portal.quartr.dev/).

This choice is deliberate. Quartr documents the Public API as the product-integration surface, while its Pro terms prohibit scraping, bulk extraction, systematic caching, and using web-app data to maintain a database. Relevant official references:

- [API authentication](https://quartr.com/docs/rest-api/auth)
- [Reports endpoint](https://quartr.com/docs/api-reference/reports/list-reports)
- [Transcripts endpoint](https://quartr.com/docs/api-reference/transcripts/list-transcripts)
- [Incremental synchronization](https://quartr.com/docs/rest-api/fetching-data)
- [Data availability targets](https://quartr.com/docs/data-overview)
- [Quartr Pro terms](https://quartr.com/terms-of-service)

## Local refresh

Copy `.env.example` to `.env`, set `QUARTR_API_KEY`, and select the company universe:

```powershell
$env:QUARTR_API_KEY = "..."
python scripts/sync_quartr.py --tickers AAPL,AMZN,NVDA --lookback-days 730
python scripts/build_index.py --all --fresh
```

The sync process:

1. Queries reports and transcripts independently with `updatedAfter` watermarks.
2. Overlaps each incremental window by five minutes and deduplicates by stable Quartr resource ID and `updatedAt`.
3. Downloads report PDFs and the documented transcript JSON format.
4. Stores a sidecar with source ID, event date, Quartr timestamps, fetch time, canonical URL, and SHA-256.
5. Advances a dataset/ticker watermark only after every cursor page and file succeeds.

State is stored in `data/processed/quartr_sync_state.json`. Keep that file and `data/raw` in durable storage for scheduled builds. Use `--full` to ignore watermarks and reconcile the configured lookback window.

`python scripts/build_index.py --all --fresh` replaces the collection before rebuilding. Incremental indexing also deletes all prior chunks for each stable `doc_id` before upsert, so shortened or revised documents cannot leave orphaned evidence.

## Production operation

[`cloudbuild.refresh.yaml`](cloudbuild.refresh.yaml) is a scheduled-refresh build definition. Before enabling it:

1. Create a Secret Manager secret named `quartr-api-key` and grant the Cloud Build service account access.
2. Set `_TICKERS`, `_REGION`, `_REPOSITORY`, `_BACKEND_SERVICE`, `_BACKEND_URL`, and `_FRONTEND_URL` substitutions. The document bucket follows the existing `$PROJECT_ID-finrag-documents` convention.
3. Ensure the build account can read/write the document bucket, push Artifact Registry images, and deploy Cloud Run.
4. Create a scheduled Cloud Build trigger at the cadence appropriate for the subscription. Hourly polling is a sensible fallback even if Quartr webhooks are added later.

The build restores the prior watermark/raw corpus from Cloud Storage, synchronizes Quartr, rebuilds a clean Chroma artifact, uploads the source documents and state, and deploys a new immutable backend revision. This avoids mutating Cloud Run's ephemeral filesystem.

The checked-in defaults target the portfolio `filing-intelligence-rag-api` deployment. Review every substitution before starting a refresh because the selected backend service and document bucket are mutated by the build.

## Monitoring

- [`GET /health/ready`](https://filing-intelligence-rag-api-7pj7nolpla-uc.a.run.app/health/ready) is the inexpensive platform readiness check for index availability.
- [`GET /health/data`](https://filing-intelligence-rag-api-7pj7nolpla-uc.a.run.app/health/data) returns source coverage, latest provider update, fetch age, and ticker/period coverage.
- `DATA_MAX_AGE_HOURS` controls when the corpus is labeled stale (default: 168 hours).

The endpoint reports `unknown` for the legacy bundled snapshot because it predates fetch/provenance metadata. After the first supported sync and rebuild it reports `fresh` or `stale` from indexed `fetched_at` values.
