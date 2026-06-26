"""Application configuration, loaded from environment / .env."""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "SmartFarm API"
    version: str = "0.1.0"

    # Persistence / cache (all optional — empty means "run without it")
    database_url: str = ""
    redis_url: str = ""

    # External providers
    openweather_api_key: str = ""
    sentinelhub_client_id: str = ""
    sentinelhub_client_secret: str = ""
    anthropic_api_key: str = ""

    # CORS
    cors_origins: str = "http://localhost:3000"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def persistence_enabled(self) -> bool:
        return bool(self.database_url)


@lru_cache
def get_settings() -> Settings:
    return Settings()
