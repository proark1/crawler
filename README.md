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
- **js** — always render with Chromium.

HTML parsing runs in worker threads so heavy extraction never blocks the event
loop, and transient network failures are retried with exponential backoff.

### Politeness & safety

- Respects `robots.txt` by default (`RESPECT_ROBOTS`).
- Optional per-host delay (`PER_HOST_DELAY`).
- Skips non-HTML and oversized responses (`MAX_RESPONSE_BYTES`).

### API

| Method | Path | Description |
| ------ | ---- | ----------- |
| GET    | `/health` | Liveness + DB connectivity |
| POST   | `/crawl` | Synchronous crawl (single page / small BFS) |
| POST   | `/crawl/jobs` | Submit a background crawl, returns a job id |
| GET    | `/crawl/jobs/{id}` | Poll job status / results |
| GET    | `/pages` | List stored pages (paginated, `X-Total-Count` header) |
| GET    | `/pages/search?q=` | Ranked full-text search |
| GET    | `/pages/{id}` | Fetch one page |
| DELETE | `/pages/{id}` | Delete one page |

All endpoints except `/health` require `X-API-Key` when `API_KEY` is set.

## Frontend

```bash
cd web
npm install
CRAWLER_API_URL=http://localhost:8000 npm run dev
```

Long crawls run as background jobs with a live progress bar. Pages can be
browsed (with pagination), searched, viewed, and deleted.

## Tests

```bash
pytest -q            # backend unit tests (no DB/browser needed)
cd web && npm run typecheck && npm run build
```

CI runs both suites on every push and pull request.
