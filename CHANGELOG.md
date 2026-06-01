# Changelog

All notable changes to this project are documented here. Dates are UTC.

## 0.5.0

Hardening and API-completeness pass focused on sustained-load reliability,
correctness edges, and operability.

### Reliability
- Per-host bookkeeping (politeness locks, cookie jars, robots parsers) is now
  bounded via an LRU/TTL cache (`app/lrucache.py`) — no more unbounded growth on
  high-cardinality crawls. robots.txt is re-fetched after `ROBOTS_CACHE_TTL`.
- Dedicated headless-browser contexts are closed even if their setup fails.
- Database pool gained a bounded acquire timeout and per-query command timeout;
  `PostgresError` and pool-acquire timeouts now return **503** instead of 500.
- New `/ready` readiness probe (503 when the DB is unreachable); `/health`
  remains a liveness probe.
- Prometheus HTTP metrics label by route template, fixing label-cardinality
  growth from per-id paths.

### Correctness
- Redirect-loop detection in the static and impersonation fetch paths.
- 404/410 responses are never classified as bot blocks, avoiding wasteful tier
  escalation on custom not-found pages.

### API
- All endpoints are also served under `/{API_VERSION}` (default `/v1`).
- `POST /crawl/batch` submits many URLs as individual jobs.
- `DELETE /crawl/jobs/{id}` cancels a running job (new `cancelled` status).
- `Idempotency-Key` header on job creation returns the original job on retry.
- Job responses cap embedded pages at `JOB_PAGES_INLINE_LIMIT` (count stays exact).

### Jobs
- Webhook delivery is HMAC-SHA256 signed (`WEBHOOK_SECRET`) and retried with
  exponential backoff.

### Dashboard
- Live, indeterminate crawl progress; mid-crawl cancel; timezone-correct
  timestamps (no hydration mismatch); auto-refreshing sidebar stats; clearer,
  actionable error messages; command-palette focus trap and reduced-motion
  support; empty-state calls-to-action.

## 0.4.0

A series of improvements taking the service from a minimal crawler to a
production-grade, bot-resilient scraping platform.

### Crawling & anti-bot
- **Tiered, escalating fetch engine**: pooled httpx → `curl_cffi` browser
  TLS/JA3 + HTTP/2 impersonation → stealth headless browser (patchright) →
  FlareSolverr challenge solver. Engines that aren't installed are skipped.
- **Block detection** for Cloudflare, DataDome, PerimeterX, Imperva, Akamai,
  Turnstile/hCaptcha/reCAPTCHA — by status, headers, and challenge HTML.
- **Per-domain strategy memory**: remembers the lowest engine tier that worked;
  blocks raise the starting tier and rotate the proxy.
- **Proxy rotation** (sticky-per-host, rotate-on-block, SSRF-validated) and
  per-host **cookie persistence**.
- **Adaptive per-host concurrency** (AIMD) and a **circuit breaker**.
- **Discovery**: sitemap.xml / robots `Sitemap:` seeding (index-following);
  `rel=canonical` and **content-hash** dedup.

### Extraction
- Threaded/process-pool extraction (never blocks the event loop).
- Markdown output; OpenGraph/JSON-LD (Article + Product) metadata; canonical,
  language, author, publish date.
- **PDF** text extraction; **word count / reading time**; best-effort
  **language detection**.

### Performance
- Shared pooled **HTTP/2** keep-alive client; TTL **DNS cache**; image/media/
  font blocking in the browser tier.

### Caching
- Conditional re-crawl (ETag / Last-Modified / 304) with a freshness TTL, and
  **per-page `Cache-Control: max-age`** honoring.

### Platform & API
- **Durable background jobs** (Postgres-mirrored) with completion **webhooks**,
  an **SSE** progress stream, a jobs list, and a startup **reaper** for orphaned
  jobs.
- Endpoints: `/crawl`, `/crawl/jobs[/{id}[/stream]]`, `/pages` (paginated),
  `/pages/search`, `/pages/by-url`, `/pages/{id}[/html]`, `/pages/export`
  (json/csv/md), `/domains`, `/stats`, `/health`, `/metrics`.
- Auto-generated OpenAPI at `/docs`, `/redoc`, `/openapi.json`.
- **MCP server** sharing the same crawl pipeline (`crawl`, `get_page`,
  `get_page_html`, `list_recent`, `search`, `recent_jobs`, `stats`,
  `delete_page`).

### Security
- **SSRF protection**: private/loopback/link-local/metadata addresses refused,
  every redirect hop validated, headless subrequests validated, and **IP-pinned
  connections** to close the DNS-rebinding window (see `SECURITY.md`).
- Constant-time API-key check; fail-closed in production; in-memory rate limiter.

### Observability
- Structured JSON logs, Prometheus `/metrics` (incl. per-vendor/tier block
  counts), optional Sentry, and a DB-backed `/stats` aggregate.

### Frontend (Next.js dashboard)
- Job-based crawling with live SSE progress; Pages (paginated, search, bulk +
  per-row delete, export), Jobs, Domains, and Settings views; raw-HTML and
  Product/metadata on the detail page; dark mode; ⌘K command palette; toasts;
  responsive mobile drawer; loading skeletons.

### Tooling
- 96 unit tests + a live-Postgres integration suite; ruff; GitHub Actions CI
  (lint, unit, integration, web typecheck/build); optional extras
  `[impersonate]`, `[stealth]`, `[pdf]`, `[lang]`, `[sentry]`.

## 0.1.0

- Initial minimal crawling service: REST API, MCP server, Postgres store, and a
  Vercel dashboard.
