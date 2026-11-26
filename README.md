# genui-backend

FastAPI service for [genui](https://github.com/kyumna/genui). It turns a prompt into a validated JSON component tree using free LLM tiers, streams it over SSE, and stores shared UIs in Postgres.

## Endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/api/generate/stream` | Stream a summary, then the UI (SSE) |
| POST | `/api/generate` | Same, non-streaming |
| POST | `/api/layouts` | Save a UI, returns a share slug |
| GET | `/api/layouts/{slug}` | Load a saved UI |
| GET | `/health` | Health check |

## How it works

- **Providers:** Gemini first, Groq as fallback. Order and model IDs are set by environment variables.
- **Output contract:** the model writes a short summary, a `---UI---` line, then JSON. The summary streams live; the JSON is buffered, validated with Pydantic, and retried once with the validation error if it is invalid.
- **Safety:** strict component allow-list, max depth 6, max 150 nodes, 100 KB cap on saved UIs, invalid colors dropped, per-IP rate limits.
- **Storage:** Neon Postgres through psycopg 3 with a pooled connection. The table is created on startup.

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
cp .env.example .env             # then fill in the keys
uvicorn app.main:app --reload
```

Without any API keys it returns a canned mock UI. Without `DATABASE_URL` sharing is disabled.

## Environment

See `.env.example`: `ALLOWED_ORIGINS`, `GEMINI_API_KEY`, `GROQ_API_KEY`, `PROVIDER_ORDER`, `GEMINI_MODEL`, `GROQ_MODEL`, `RATE_LIMIT_PER_MINUTE`, `SAVE_RATE_LIMIT_PER_MINUTE`, `DATABASE_URL`.

## Tests

```bash
pytest -q
```

Database tests run only when `TEST_DATABASE_URL` is set.

## Deploy

`render.yaml` describes a Render free web service. Set the secret variables in the Render dashboard. Free instances sleep after 15 minutes, so the first request after idle takes about a minute.
