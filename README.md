# Crawler

A fast web crawling service: a FastAPI backend (static fetch with headless-browser
fallback), a Postgres-backed store with full-text search, an MCP server, and a
Next.js dashboard.

## Architecture

```
web/ (Next.js, Vercel)  ──►  app/ (FastAPI, Railway)  ──►  Postgres
                                   │
                                   └── app/mcp_server.py (MCP over stdio)
```

## Backend

```bash
pip install -e ".[dev]"
playwright install chromium        # for JS rendering
uvicorn app.api:app --reload
```

### Rendering modes

- **auto** — fetch static HTML first; fall back to Chromium only when the page
  looks empty (client-rendered). Best default.
- **static** — plain HTTP fetch. Fastest, no JavaScript.
- **js** — always render with Chromium (images/media/fonts blocked, contexts
  pooled, for speed).

HTML parsing runs in worker threads so heavy extraction never blocks the event
loop, and transient network failures (incl. 5xx) are retried with backoff.

### Extraction

Beyond title/text/links, each page yields a Markdown rendering plus structured
metadata: OpenGraph, JSON-LD, canonical URL, language, author, and publish date.

### Caching

With `RECRAWL_MAX_AGE > 0`, recently stored pages are served without refetching.
Otherwise the crawler sends `If-None-Match`/`If-Modified-Since` and reuses stored
content on a `304`.

### Security & politeness

- **SSRF protection** (`BLOCK_PRIVATE_ADDRESSES`): resolves hosts and refuses
  private/loopback/link-local/metadata addresses, validating every redirect hop.
- Respects `robots.txt` and its `Crawl-delay` by default.
- Optional per-host delay; skips non-HTML and oversized responses.
- In-memory rate limiting (`RATE_LIMIT_PER_MINUTE`); fails closed in production
  if `API_KEY` is unset.

### Observability

Structured JSON logs, Prometheus metrics at `/metrics`, and optional Sentry
(`pip install '.[sentry]'` + `SENTRY_DSN`).

### API

| Method | Path | Description |
| ------ | ---- | ----------- |
| GET    | `/health` | Liveness + DB connectivity |
| GET    | `/metrics` | Prometheus metrics |
| POST   | `/crawl` | Synchronous crawl (single page / small BFS) |
| POST   | `/crawl/jobs` | Submit a background crawl (optional `webhook_url`) |
| GET    | `/crawl/jobs` | List recent jobs |
| GET    | `/crawl/jobs/{id}` | Poll job status / results |
| GET    | `/crawl/jobs/{id}/stream` | Live progress via Server-Sent Events |
| GET    | `/pages` | List stored pages (paginated, `X-Total-Count` header) |
| GET    | `/pages/export?format=` | Export all pages as `json`/`csv`/`md` |
| GET    | `/pages/search?q=` | Ranked full-text search |
| GET    | `/pages/{id}` | Fetch one page |
| GET    | `/pages/{id}/html` | Raw stored HTML |
| DELETE | `/pages/{id}` | Delete one page |

All endpoints except `/health` require `X-API-Key` when `API_KEY` is set.

Schema changes are applied automatically on startup by the migration runner in
`app/migrations.py`.

## Frontend

```bash
cd web
npm install
CRAWLER_API_URL=http://localhost:8000 npm run dev
```

Long crawls run as background jobs streamed over SSE with a live progress bar.
Pages can be browsed (paginated), searched, viewed, exported (JSON/CSV/MD),
bulk-deleted, and inspected as raw HTML. Includes dark mode, a ⌘K command
palette, toasts, and a responsive mobile drawer.

## Tests

```bash
pytest -q                                   # backend unit tests (no DB/browser)
RUN_DB_TESTS=1 pytest tests/test_integration_db.py   # needs a live Postgres
cd web && npm run typecheck && npm run build
```

CI runs the unit suite, a Postgres-backed integration suite, lint, and the web
build on every push and pull request.
