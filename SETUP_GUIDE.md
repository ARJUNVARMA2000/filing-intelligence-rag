# Setup and operations guide

The canonical quick start is in [README.md](README.md). This guide records the operational checks that are easy to miss.

## Local modes

Use `APP_ENV=local` and `AUTH_MODE=disabled` only on a developer machine. The API refuses an auth bypass when `APP_ENV` is production. When the frontend and backend are run separately, keep `FIN_RAG_API_BASE=http://localhost:8000` and `FIN_RAG_AUTH_MODE=local`.

The bundled index is restored automatically by `python scripts/run_local.py`. If running the processes manually, restore it once with:

```powershell
python -m zipfile -e chroma_index.zip data/indexes
```

## Production mode

Portfolio deployment:

- [Research workspace](https://finrag-research-7pj7nolpla-uc.a.run.app)
- [API readiness](https://finrag-research-api-7pj7nolpla-uc.a.run.app/health/ready)
- [Data coverage](https://finrag-research-api-7pj7nolpla-uc.a.run.app/health/data)

Production requires:

- `APP_ENV=production`
- `AUTH_MODE=google`
- `FRONTEND_SERVICE_ACCOUNT` set to the exact frontend runtime identity
- `BACKEND_AUDIENCE` set to the canonical backend URL
- `FIN_RAG_AUTH_MODE=google` on the frontend
- one configured generation provider (`LLM_PROVIDER=openai` or `vertexai`)

The backend can remain network-reachable for public source documents while the paid `/chat` routes verify a Google-signed identity token. For stricter isolation, split source delivery into a separate public service and enforce Cloud Run IAM on the API service.

The default Cloud Build configuration targets the `finrag-research-api` and `finrag-research` services:

```powershell
gcloud builds submit --config cloudbuild.yaml --project agentic-ai-487000 .
```

## Readiness and diagnosis

- `GET /health` checks the process only.
- `GET /health/ready` verifies that the packaged index opens and contains chunks.
- `GET /health/data` reports source types, document/chunk counts, coverage, and freshness without credentials.
- Every chat response or sanitized error includes `X-Request-ID`; use it to correlate application logs.

Do not put provider exception text, tokens, service-account JSON, or Quartr credentials in bug reports. The UI and API intentionally return sanitized recovery messages.

## Corpus rebuild checklist

1. Synchronize or place source files under `data/raw/<ticker>/`.
2. Confirm source sidecars contain stable IDs, source type, event/update timestamps, canonical URL, and hash.
3. Run `python scripts/build_index.py --all --fresh`.
4. Verify the collection and generated index manifest.
5. Run the full quality gates from the README.
6. Recreate `chroma_index.zip` from `data/indexes/chroma` only after validation.
7. Smoke-test a quantitative answer, a qualitative answer, a refusal/no-data path, and the cited document file.

## Evaluation

Start the backend, provide the required OpenRouter key, then run the controlled evaluation CLI against an existing question set:

```powershell
python scripts/run_eval.py --csv data/eval/questions_finaleval.csv --models claude-sonnet-4.5
```

Evaluation is a cost-bearing operation and model names are restricted to `backend/app/models_registry.py`. Keep retrieval failures separate from answer-quality scores and record the index/prompt configuration with each result set.
