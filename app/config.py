from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: str = "development"  # "production" enables fail-closed checks

    database_url: str = "postgresql://postgres:postgres@localhost:5432/crawler"
    request_timeout: float = 20.0
    js_render_timeout: float = 30.0
    user_agent: str = "CrawlerBot/0.1 (+https://github.com/proark1/crawler)"
    max_pages_hard_limit: int = 100
    max_depth_hard_limit: int = 5

    # Networking guards.
    max_response_bytes: int = 10 * 1024 * 1024  # skip/cap bodies larger than this
    max_retries: int = 2  # retry transient fetch failures this many times
    crawl_concurrency: int = 4  # workers per site crawl

    # SSRF protection: refuse to fetch private / loopback / link-local addresses.
    block_private_addresses: bool = True
    # Comma-separated hostnames exempt from the block (e.g. for local testing).
    ssrf_allowlist: str = ""
    max_redirects: int = 5

    # JS rendering performance: block images/media/fonts and pool browser contexts.
    block_resources_in_js: bool = True
    js_context_pool_size: int = 2

    # --- Anti-bot / evasion (tiered fetch strategy) ------------------------- #
    # Master switch for realistic headers, block detection, and engine escalation.
    antibot_enabled: bool = True
    # When a fetch looks blocked (Cloudflare/DataDome/403/429/...), escalate to the
    # next stronger engine instead of giving up.
    escalate_on_block: bool = True
    # curl_cffi browser impersonation target (TLS/JA3 + HTTP/2). "" disables the
    # impersonation tier. Examples: chrome, chrome124, safari, edge.
    impersonate_browser: str = "chrome"
    # Realistic default Accept-Language sent with browser-like header profiles.
    accept_language: str = "en-US,en;q=0.9"
    # Apply stealth patches (navigator.webdriver, chrome runtime, etc.) to the
    # headless browser, and use patchright instead of playwright when installed.
    browser_stealth: bool = True
    # Persist and replay cookies per host (helps "challenge once, then allow").
    persist_cookies: bool = True
    # Remember the minimum engine tier that worked per host, to skip re-escalation.
    domain_profile_size: int = 5000

    # Proxies. `proxy_url` is a single proxy; `proxy_pool` is a comma-separated
    # rotation list. Proxied targets are still SSRF-validated.
    proxy_url: str = ""
    proxy_pool: str = ""
    # Tiers (and above) that route through a proxy: 0=static 1=impersonate 2=browser.
    proxy_from_tier: int = 1

    # Optional FlareSolverr endpoint for Cloudflare/DDoS-Guard challenge solving.
    flaresolverr_url: str = ""
    flaresolverr_timeout: float = 60.0

    # Adaptive per-host concurrency (AIMD): start at this many concurrent requests
    # per host, ramp up on success, multiplicatively back off on blocks/429.
    adaptive_concurrency: bool = True
    host_concurrency_start: int = 2
    host_concurrency_max: int = 8

    # Per-host circuit breaker: after this many consecutive blocks, short-circuit
    # the host for `circuit_cooldown` seconds instead of hammering it.
    circuit_breaker_threshold: int = 5
    circuit_cooldown: float = 300.0

    # Extraction workers. 0 = run in threads (default); >0 uses a process pool of
    # this size for true multi-core parsing throughput.
    extract_workers: int = 0

    # HTTP client pool.
    http2: bool = True
    max_keepalive_connections: int = 20
    max_connections: int = 100
    dns_cache_ttl: float = 300.0  # seconds to cache validated DNS results

    # Caching / conditional re-crawl. 0 = always re-fetch.
    recrawl_max_age: float = 0.0  # seconds; serve stored copy if younger than this
    store_html: bool = True  # persist (compressed) raw HTML

    # Extraction.
    extract_metadata: bool = True  # OpenGraph / JSON-LD / canonical / language
    emit_markdown: bool = True  # include a Markdown rendering of the main content
    extract_pdf: bool = True  # extract text from PDF responses (needs the [pdf] extra)
    detect_language: bool = True  # detect language from text (needs the [lang] extra)
    dedup_by_content: bool = True  # in a site crawl, don't re-expand duplicate-content pages

    # Discovery: seed follow-link crawls from sitemap.xml / robots Sitemap: lines.
    use_sitemap: bool = True
    sitemap_max_urls: int = 1000

    # Politeness.
    respect_robots: bool = True
    respect_crawl_delay: bool = True
    per_host_delay: float = 0.0  # extra seconds between requests to the same host

    # Rate limiting (per client IP). 0 = disabled.
    rate_limit_per_minute: int = 0

    # Observability.
    enable_metrics: bool = True
    sentry_dsn: str = ""
    log_level: str = "INFO"
    log_json: bool = True

    # API key required on every request except /health. Empty string = auth disabled (dev only).
    api_key: str = ""
    # Comma-separated list of allowed CORS origins. "*" allows all (dev only).
    allowed_origins: str = "*"

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]

    @property
    def ssrf_allowed_hosts(self) -> set[str]:
        return {h.strip().lower() for h in self.ssrf_allowlist.split(",") if h.strip()}

    @property
    def proxies(self) -> list[str]:
        pool = [p.strip() for p in self.proxy_pool.split(",") if p.strip()]
        if self.proxy_url and self.proxy_url not in pool:
            pool.insert(0, self.proxy_url)
        return pool

    @property
    def is_production(self) -> bool:
        return self.environment.lower() in ("production", "prod")


settings = Settings()
