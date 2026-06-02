# Security

## SSRF protection

The crawler fetches arbitrary, user-supplied URLs, so it guards against
Server-Side Request Forgery (`app/ssrf.py`), enabled by default
(`BLOCK_PRIVATE_ADDRESSES=true`):

- Every target host is resolved and rejected if it maps to a private,
  loopback, link-local, multicast, reserved, or unspecified address
  (this includes the cloud metadata endpoint `169.254.169.254`).
- Only `http`/`https` schemes are allowed.
- Static fetches follow redirects manually and **re-validate every hop**.
- The headless browser validates **every subrequest** (navigations, iframes,
  scripts, XHR/fetch), not just the top-level navigation.
- A host allowlist (`SSRF_ALLOWLIST`) can exempt known-internal hosts for
  testing.

### DNS rebinding (TOCTOU)

Naively, validation resolves the host and checks the IPs, but the HTTP client
would then perform its *own* DNS resolution at connect time — a Time-of-Check/
Time-of-Use window an attacker with a low-TTL domain could exploit to pass the
check and then land the connection on a private IP.

For **static fetches** this is mitigated: `ssrf.build_async_client` routes every
connection through our own validated resolver (an httpcore network backend that
connects to the IP we just validated). httpcore still performs the TLS handshake
against the original hostname, so SNI and certificate verification remain
correct. The IP that is checked is the IP that is connected to.

**Residual gap:** the headless browser (Playwright, used for JS rendering) and
the optional `curl_cffi` impersonation engine do their own DNS, so there the
crawler relies on per-request/per-subrequest validation rather than IP pinning.
For defence in depth on sensitive deployments, run the crawler in a network
segment where private/internal ranges are firewalled off at egress.

## Other controls

- **Authentication:** `X-API-Key` required on all endpoints when `API_KEY` is
  set, except the unauthenticated infra endpoints `/health`, `/ready`, and
  `/metrics`. `/metrics` is deliberately open so Prometheus can scrape it (it
  exposes only aggregate counters — no URLs or secrets); restrict it at the
  network layer or set `ENABLE_METRICS=false` if that's not acceptable. The
  service refuses to start in production (`ENVIRONMENT=production`) if `API_KEY`
  is empty.
- **Webhook SSRF:** background-job `webhook_url`s are validated the same way as
  crawl targets (rejected if they resolve to a private/internal address), both
  at submit time and again before each delivery.
- **Rate limiting:** optional per-IP/key fixed-window limiter
  (`RATE_LIMIT_PER_MINUTE`), with bounded memory. Infra endpoints
  (`/health`, `/ready`, `/metrics`) are exempt.
- **Resource guards:** response size cap (`MAX_RESPONSE_BYTES`), redirect cap
  (`MAX_REDIRECTS`), and content-type filtering.
- **robots.txt** and `Crawl-delay` are respected by default.

## Reporting

Please report suspected vulnerabilities privately to the repository owner
rather than opening a public issue.
