"""Module."""
from __future__ import annotations
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict
class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )
    app_name: str = "Election Management & Voting System"
    api_prefix: str = "/api/v1"
    debug: bool = False
    secret_key: str = "change-me-in-production-please-use-a-long-random-string"
    access_token_expire_minutes: int = 120
    jwt_algorithm: str = "HS256"
    database_url: str = "sqlite+aiosqlite:///./data/app.db"
    db_echo: bool = False
    redis_url: str = ""
    min_available_voters: int = 5
    sse_heartbeat_seconds: int = 15
    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")
@lru_cache
def get_settings() -> Settings:
    return Settings()
