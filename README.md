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
metadata: OpenGraph, JSON-LD (incl. Article and Product fields — price,
currency, availability, brand), canonical URL, language, author, and publish
date. Site crawls seed discovery from the site's **sitemap(s)** (robots `Sitemap:`
lines or `/sitemap.xml`, following sitemap-index files) in addition to in-page
links, and dedupe via `rel=canonical`. The dashboard's **Domains** view
shows which engine tier works per host and where bot protection was hit.

### Anti-bot (tiered fetch strategy)

Bot-protected sites (Cloudflare, DataDome, PerimeterX, Imperva, Akamai) are
handled by escalating engines: pooled httpx → `curl_cffi` browser TLS/HTTP-2
impersonation → stealth headless browser → challenge solver. A block detector
decides when to escalate, and each domain remembers the tier that worked. See
[`ANTIBOT.md`](ANTIBOT.md). Optional engines:

```bash
pip install '.[impersonate]'   # curl_cffi TLS/JA3 impersonation (Tier 1)
pip install '.[stealth]'       # patchright stealth browser (Tier 2)
```

Performance: a shared pooled HTTP/2 keep-alive client (no per-page handshakes),
a TTL DNS cache, and image/media/font blocking in the browser tier.

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
| GET    | `/metrics` | Prometheus metrics (incl. per-vendor/tier block counts) |
| GET    | `/stats` | Index aggregates: total / errored / bot-blocked pages |
| POST   | `/crawl` | Synchronous crawl (single page / small BFS) |
| POST   | `/crawl/jobs` | Submit a background crawl (optional `webhook_url`) |
| GET    | `/crawl/jobs` | List recent jobs |
| GET    | `/crawl/jobs/{id}` | Poll job status / results |
| GET    | `/crawl/jobs/{id}/stream` | Live progress via Server-Sent Events |
| GET    | `/domains` | Per-domain anti-bot strategy the crawler has learned |
| GET    | `/pages` | List stored pages (paginated, `X-Total-Count` header) |
| GET    | `/pages/export?format=` | Export all pages as `json`/`csv`/`md` |
| GET    | `/pages/search?q=` | Ranked full-text search |
| GET    | `/pages/by-url?url=` | Fetch one page by exact URL |
| GET    | `/pages/{id}` | Fetch one page |
| GET    | `/pages/{id}/html` | Raw stored HTML |
| DELETE | `/pages/{id}` | Delete one page |

All endpoints except `/health` require `X-API-Key` when `API_KEY` is set.

Interactive, always-current API docs are served by FastAPI at **`/docs`**
(Swagger UI) and **`/redoc`**, with the raw schema at **`/openapi.json`**.

The REST API and the MCP server share one crawl implementation
(`app/service.py`), so both apply identical SSRF, robots, caching, and
persistence behavior. Schema changes are applied automatically on startup by the
migration runner in `app/migrations.py`.

## MCP server

A stdio [Model Context Protocol](https://modelcontextprotocol.io) server exposes
the crawler to MCP clients (Claude Desktop, IDEs, etc.):

```bash
python -m app.mcp_server
```

| Tool | Arguments | Description |
| ---- | --------- | ----------- |
| `crawl` | `url`, `render`, `follow_links`, `max_depth`, `max_pages`, `same_host_only`, `store` | Crawl a URL (or same-host BFS); returns text, Markdown, links, metadata |
| `get_page` | `url` | Retrieve a stored page (no raw HTML) |
| `get_page_html` | `url` | Retrieve the stored raw HTML |
| `list_recent` | `limit` | Recently crawled pages |
| `search` | `query`, `limit` | Full-text search |
| `recent_jobs` | `limit` | Recent background crawl jobs |
| `stats` | — | Index statistics (total pages) |
| `delete_page` | `url` | Delete a stored page |

Example Claude Desktop config (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "crawler": {
      "command": "python",
      "args": ["-m", "app.mcp_server"],
      "env": { "DATABASE_URL": "postgresql://postgres:postgres@localhost:5432/crawler" }
    }
  }
}
```

See `SECURITY.md` for the threat model (SSRF, DNS-rebinding mitigation, auth,
rate limiting). All tunables are documented in `.env.example`.

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
