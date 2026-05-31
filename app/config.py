from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

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

    # Politeness.
    respect_robots: bool = True
    per_host_delay: float = 0.0  # seconds to wait between requests to the same host

    # API key required on every request except /health. Empty string = auth disabled (dev only).
    api_key: str = ""
    # Comma-separated list of allowed CORS origins. "*" allows all (dev only).
    allowed_origins: str = "*"

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]


settings = Settings()
