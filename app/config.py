from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql://postgres:postgres@localhost:5432/crawler"

    # Networking / fetching
    request_timeout: float = 20.0
    js_render_timeout: float = 30.0
    user_agent: str = "CrawlerBot/0.1 (+https://github.com/proark1/crawler)"
    max_response_bytes: int = 10_000_000  # 10 MB hard cap on a single response body
    max_redirects: int = 5
    fetch_retries: int = 2  # extra attempts on transient network errors

    # Crawl budget
    max_pages_hard_limit: int = 100
    max_depth_hard_limit: int = 5
    crawl_concurrency: int = 8
    js_concurrency: int = 2  # concurrent headless browser contexts
    per_host_delay: float = 0.5  # politeness delay between requests to the same host (s)

    # Politeness / safety
    respect_robots: bool = True
    block_private_addresses: bool = True  # SSRF guard; disable only in trusted envs

    # Security
    # API key required on every request except /health. Empty string = auth disabled (dev only).
    api_key: str = ""
    # Comma-separated list of allowed CORS origins. "*" allows all (dev only).
    allowed_origins: str = "*"

    # Observability
    log_level: str = "INFO"

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]


settings = Settings()
