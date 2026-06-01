# Crawler

A small but production-minded web crawling service: a **FastAPI** backend that
fetches and extracts pages (static `httpx` first, headless **Chromium** when a
page needs JavaScript), a **Postgres** store with full-text search, an **MCP
server** for use from LLM tools, and a **Next.js** dashboard that streams crawl
results live.

```
┌─────────────┐    POST /jobs + SSE     ┌──────────────┐     asyncpg     ┌──────────┐
│ Next.js UI  │ ─────────────────────▶ │  FastAPI API │ ──────────────▶ │ Postgres │
│ (Vercel)    │ ◀───── live pages ───── │  (Railway)   │                 └──────────┘
└─────────────┘                         │  + Chromium  │
                                        │  + MCP stdio │
                                        └──────────────┘
```

## Features

- **Static + JS rendering.** `auto` mode does a fast static fetch and only falls
  back to a headless browser when the page looks empty (SPA shells, etc.).
- **Polite & safe by default.** Honors `robots.txt` + `Crawl-delay`, throttles
  per host, and an **SSRF guard** blocks requests to private/loopback/link-local
  and cloud-metadata addresses (validated on every redirect hop).
- **Resilient.** Bounded retries with backoff, a hard response-size cap,
  content-type gating, and partial-success persistence so one bad page never
  aborts a crawl.
- **Fast.** Shared keep-alive HTTP client, CPU-bound extraction offloaded off the
  event loop, a continuous worker-pool BFS, and a JS renderer that blocks
  images/media/fonts.
- **Live streaming.** Async crawl jobs publish each page over **SSE**; the
  dashboard shows progress as it happens.
- **Markdown + text** output, **Postgres full-text search** (tsvector + GIN),
  structured JSON logs, and a Prometheus `/metrics` endpoint.

## Backend

### Run locally

```bash
pip install -e ".[dev]"
playwright install chromium          # first time only
cp .env.example .env                 # set DATABASE_URL
uvicorn app.api:app --reload
```

### API

| Method | Path                    | Description                                  |
|--------|-------------------------|----------------------------------------------|
| GET    | `/health`               | Liveness (+ DB status)                        |
| GET    | `/readyz`               | Readiness — 503 when the DB is unreachable    |
| GET    | `/metrics`              | Prometheus text metrics                       |
| POST   | `/crawl`                | Synchronous crawl (single page or BFS)        |
| POST   | `/jobs`                 | Start an async crawl, returns `{job_id}`      |
| GET    | `/jobs/{id}`            | Job status + crawled pages                    |
| GET    | `/jobs/{id}/events`     | **SSE** stream of live progress               |
| GET    | `/pages`                | List crawled pages (`limit`, `offset`)        |
| GET    | `/pages/search?q=`      | Full-text search                              |
| GET    | `/pages/{id}`           | One page                                      |

All endpoints except `/health`, `/readyz`, and `/metrics` require the
`X-API-Key` header when `API_KEY` is set.

```bash
curl -X POST localhost:8000/crawl -H 'Content-Type: application/json' \
  -d '{"url":"https://example.com","follow_links":true,"max_pages":20}'
```

### Configuration

See [`.env.example`](.env.example). Notable knobs: `MAX_RESPONSE_BYTES`,
`CRAWL_CONCURRENCY`, `JS_CONCURRENCY`, `PER_HOST_DELAY`, `RESPECT_ROBOTS`,
`BLOCK_PRIVATE_ADDRESSES`, `API_KEY`, `ALLOWED_ORIGINS`, `LOG_LEVEL`.

### MCP server

```bash
python -m app.mcp_server   # exposes crawl / get_page / list_recent / search over stdio
```

### Tests & lint

```bash
pytest -q
ruff check app tests
```

## Frontend (`web/`)

```bash
cd web
npm install
cp .env.example .env.local   # set CRAWLER_API_URL (+ CRAWLER_API_KEY)
npm run dev
```

The dashboard talks to the backend only through server-side routes, so the API
key never reaches the browser. Deploys to Vercel; the backend deploys to Railway
via the included `Dockerfile` / `railway.json`.

## Deployment notes

- The Docker image is based on `mcr.microsoft.com/playwright/python`, which
  bundles Chromium and its system dependencies.
- Railway healthcheck uses `/health` (liveness) so brief DB blips don't trigger
  restart loops; use `/readyz` for readiness gating.
