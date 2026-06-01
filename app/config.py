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

    # Caching / conditional re-crawl. 0 = always re-fetch.
    recrawl_max_age: float = 0.0  # seconds; serve stored copy if younger than this
    store_html: bool = True  # persist (compressed) raw HTML

    # Extraction.
    extract_metadata: bool = True  # OpenGraph / JSON-LD / canonical / language
    emit_markdown: bool = True  # include a Markdown rendering of the main content

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
    def is_production(self) -> bool:
        return self.environment.lower() in ("production", "prod")


settings = Settings()
