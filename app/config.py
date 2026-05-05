from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql://postgres:postgres@localhost:5432/crawler"
    request_timeout: float = 20.0
    js_render_timeout: float = 30.0
    user_agent: str = "CrawlerBot/0.1 (+https://github.com/proark1/crawler)"
    max_pages_hard_limit: int = 100
    max_depth_hard_limit: int = 5


settings = Settings()
