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

### Known limitation: DNS rebinding

Validation resolves the host and checks the IPs, but `httpx` and the browser
perform their own DNS resolution at connect time. This leaves a narrow
Time-of-Check/Time-of-Use window: an attacker who controls a domain with a
very low TTL could, in principle, pass validation and then have the connection
land on a private IP.

Exploitation requires attacker-controlled DNS **and** winning a race against
our check, so the practical risk is low. Fully eliminating it requires pinning
the connection to the validated IP while preserving TLS SNI/Host via a custom
transport, which is intentionally out of scope.

**Recommended hardening for sensitive deployments:** run the crawler in a
network segment where private/internal ranges are firewalled off at egress, so
rebinding has nothing to reach even if the race is won.

## Other controls

- **Authentication:** `X-API-Key` required on all endpoints except `/health`
  when `API_KEY` is set; the service refuses to start in production
  (`ENVIRONMENT=production`) if `API_KEY` is empty.
- **Rate limiting:** optional per-IP/key fixed-window limiter
  (`RATE_LIMIT_PER_MINUTE`), with bounded memory.
- **Resource guards:** response size cap (`MAX_RESPONSE_BYTES`), redirect cap
  (`MAX_REDIRECTS`), and content-type filtering.
- **robots.txt** and `Crawl-delay` are respected by default.

## Reporting

Please report suspected vulnerabilities privately to the repository owner
rather than opening a public issue.
