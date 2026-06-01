# Anti-bot strategy

Many sites sit behind bot-protection (Cloudflare, DataDome, PerimeterX/HUMAN,
Imperva/Incapsula, Akamai, Kasada). A single fetch method can't beat all of
them, so the crawler uses a **tiered, escalating strategy**: it starts cheap and
fast, detects when it's been blocked, and escalates to a stronger engine — then
**remembers per domain** which tier worked so it doesn't pay the escalation cost
twice.

## Tiers

| Tier | Engine | Beats | Needs |
| ---- | ------ | ----- | ----- |
| 0 STATIC | pooled httpx + realistic headers | no protection | built-in |
| 1 IMPERSONATE | `curl_cffi` (real browser TLS/JA3 + HTTP/2 fingerprint) | passive Cloudflare/Akamai TLS checks | `pip install '.[impersonate]'` |
| 2 BROWSER | stealth headless browser (`patchright` if installed) + cookie persistence | JS challenges, `navigator.webdriver` checks | `pip install '.[stealth]'`, `playwright install chromium` |
| 3 SOLVER | FlareSolverr (drives a real browser to clear the challenge) | managed Cloudflare/DDoS-Guard challenges | run FlareSolverr + set `FLARESOLVERR_URL` |

Engines that aren't installed are skipped during escalation, so the crawler
degrades gracefully to whatever is available.

## How escalation works

1. Fetch with the tier suggested by the domain's profile (Tier 0 for unknown
   domains).
2. `BlockDetector` (`app/antibot.py`) classifies the response — status codes
   (403/429/503), vendor fingerprints (`cf-mitigated`, `Server: cloudflare`,
   `geo.captcha-delivery.com`, Incapsula, PerimeterX, Turnstile/hCaptcha…), and
   challenge HTML.
3. If blocked and `ESCALATE_ON_BLOCK=true`, record the block (bumping the
   domain's minimum tier and rotating the proxy) and try the next tier.
4. On success, record which tier worked so future crawls of that host start
   there.

The same logic triggers on **empty/JS-rendered** pages: if static HTML extracts
to nothing, the crawler escalates to the browser tier.

## Configuration

All knobs live in `.env` (see `.env.example`): `ANTIBOT_ENABLED`,
`ESCALATE_ON_BLOCK`, `IMPERSONATE_BROWSER`, `BROWSER_STEALTH`, `PERSIST_COOKIES`,
`PROXY_URL`/`PROXY_POOL`/`PROXY_FROM_TIER`, `FLARESOLVERR_URL`, `ACCEPT_LANGUAGE`.

## Reliability: adaptive concurrency + circuit breaker

Per host (`app/concurrency.py`, `ADAPTIVE_CONCURRENCY`):

- **AIMD concurrency** — the per-host concurrent-request limit grows additively
  on success and halves on a block/429, so healthy hosts get throughput and
  protected hosts get backed off automatically.
- **Circuit breaker** — after `CIRCUIT_BREAKER_THRESHOLD` consecutive blocks a
  host is short-circuited for `CIRCUIT_COOLDOWN` seconds (requests fail fast with
  a "circuit open" error) instead of being hammered.

Background **jobs are reaped** on startup: any job left `running`/`pending` by a
previous process is marked errored so restarts never show stuck jobs.

## Performance

- A **shared, pooled HTTP/2 client** (keep-alive) replaces per-request clients —
  no repeated TCP/TLS handshakes across pages of a host.
- A **TTL DNS cache** removes the double-resolve per request and speeds repeat
  crawls.
- The headless browser **blocks images/media/fonts** and **pools contexts**.
- **Extraction** runs in a process pool when `EXTRACT_WORKERS > 0` for true
  multi-core HTML parsing throughput (threads by default).

## Responsible use

These techniques are for **authorized** scraping (your own sites, permitted
data collection, research). Respect `robots.txt`, site terms, rate limits, and
applicable law. The bypass tiers are opt-in via configuration and the crawler
keeps robots/politeness controls enabled by default.
