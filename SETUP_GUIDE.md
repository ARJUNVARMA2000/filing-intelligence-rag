# Setup and operations guide

The canonical quick start is in [README.md](README.md). This guide records the operational checks that are easy to miss.

## Local modes

Install Python 3.12 and Node.js 24. Use `APP_ENV=local` and `AUTH_MODE=disabled` only on a developer machine. The API refuses an auth bypass when `APP_ENV` is production. Keep `FIN_RAG_API_BASE=http://localhost:8000`, `FIN_RAG_AUTH_MODE=local`, and `FRONTEND_URL=http://localhost:3000` for local development.

Install both dependency sets from the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
npm --prefix frontend install
Copy-Item .env.example .env
```

Set `OPENAI_API_KEY` in `.env`, then start both services:

```powershell
python scripts/run_local.py
```

The bundled index is restored automatically by the launcher. The Next.js workspace is available at `http://localhost:3000`, with FastAPI at `http://localhost:8000`. If running the processes manually, restore the index once and start each service in its own terminal:

```powershell
python -m zipfile -e chroma_index.zip data/indexes
python -m uvicorn backend.app.main:app --reload --port 8000
npm --prefix frontend run dev
```

Frontend-only verification and production compilation are available with:

```powershell
npm --prefix frontend run test
npm --prefix frontend run build
```

## BFF boundary

The browser talks only to same-origin Next.js `/api` routes. The BFF forwards chat, scope parsing, and health requests to the FastAPI service configured by `FIN_RAG_API_BASE`; its source route validates document paths before redirecting to the backend's public document endpoints.

With `FIN_RAG_AUTH_MODE=local`, the BFF sends no authorization header and the locally configured backend accepts the request. With `FIN_RAG_AUTH_MODE=google`, the BFF uses its runtime service account to mint a Google identity token for the backend audience. Token acquisition remains server-side; never place service credentials, backend tokens, or these settings in `NEXT_PUBLIC_*` variables.

## Production mode

Portfolio deployment:

- [Research workspace](https://filing-intelligence-rag-7pj7nolpla-uc.a.run.app)
- [API readiness](https://filing-intelligence-rag-api-7pj7nolpla-uc.a.run.app/health/ready)
- [Data coverage](https://filing-intelligence-rag-api-7pj7nolpla-uc.a.run.app/health/data)

Production requires:

- `APP_ENV=production`
- `AUTH_MODE=google`
- `FRONTEND_SERVICE_ACCOUNT` set to the exact frontend runtime identity
- `BACKEND_AUDIENCE` set to the canonical backend URL
- `FIN_RAG_AUTH_MODE=google` on the frontend
- one configured generation provider (`LLM_PROVIDER=openai` or `vertexai`)

The Next.js BFF is the production identity boundary. Its runtime service account obtains the Google-signed token accepted by the paid `/chat` routes; browser code never handles that token. The backend can remain network-reachable for public source documents while paid routes verify the BFF identity. For stricter isolation, split source delivery into a separate public service and enforce Cloud Run IAM on the API service.

The default Cloud Build configuration targets the `filing-intelligence-rag-api` and `filing-intelligence-rag` services:

```powershell
gcloud builds submit --config cloudbuild.yaml --project agentic-ai-487000 .
```

## Readiness and diagnosis

- `GET /health` checks the process only.
- `GET /health/ready` verifies that the packaged index opens and contains chunks.
- `GET /health/data` reports source types, document/chunk counts, coverage, and freshness without credentials.
- Every chat response or sanitized error includes `X-Request-ID`; use it to correlate application logs.

Do not put provider exception text, tokens, service-account JSON, or Quartr credentials in bug reports. The UI and API intentionally return sanitized recovery messages.

## Quality gates

Run the same backend and frontend checks enforced by CI:

```powershell
$env:PYTHONDONTWRITEBYTECODE = "1"
python -m ruff check backend scripts tests
python -m ruff format --check backend scripts tests
python -m pytest -q
python -m compileall -q backend scripts tests
npm --prefix frontend run lint
npm --prefix frontend run typecheck
npm --prefix frontend run test
npm --prefix frontend run build
```

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

## Vertex model configuration

The Vertex provider defaults to GA `gemini-3.5-flash-lite` at `VERTEX_LOCATION=global`. Override it with `VERTEX_CHAT_MODEL` and a location supported by that model. Both Cloud Build configurations set the same default explicitly; deploy the updated configuration to replace an existing service-level model override. The Google Gen AI SDK requires version 2.x. Gemini 3.5 Flash-Lite uses fixed sampling defaults, so the client does not send a custom temperature.
