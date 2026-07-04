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
    # data.gov.in API key for live Agmarknet mandi prices (optional).
    data_gov_api_key: str = ""
    anthropic_api_key: str = ""
    # Default to the latest, most capable model for advisory chat.
    advisory_model: str = "claude-opus-4-8"

    # Auth (phone/OTP + JWT). CHANGE jwt_secret in production.
    jwt_secret: str = "dev-insecure-change-me"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24 * 7  # 7 days
    otp_ttl_seconds: int = 300  # OTP valid for 5 minutes
    # In dev (no SMS gateway) the requested OTP is returned in the API response
    # and logged, so you can sign in without a phone. NEVER enable in production.
    otp_dev_mode: bool = True
    # Admin analytics endpoint gate (empty disables /admin/*).
    admin_token: str = ""
    # Shared secret for SSO tokens issued by the Kadapala Groups site (empty
    # disables /auth/sso). Kadapala signs a short JWT with this secret; we verify
    # it and mint our own session. See project integration notes.
    kadapala_sso_secret: str = ""

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
