"""Application configuration, loaded from environment / .env."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# apps/api — so .env and a relative SQLite file are found wherever the server
# is started from (a relative ".env" silently loaded nothing from another cwd).
API_DIR = Path(__file__).resolve().parents[2]
_SQLITE_RELATIVE = "sqlite+aiosqlite:///./"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=API_DIR / ".env", extra="ignore")

    app_name: str = "SmartFarm API"
    version: str = "0.1.0"
    # "development" or "production" (tune logging / error verbosity).
    environment: str = "development"

    # Persistence / cache (all optional — empty means "run without it")
    database_url: str = ""
    redis_url: str = ""

    @field_validator("database_url")
    @classmethod
    def _anchor_sqlite(cls, v: str) -> str:
        if v.startswith(_SQLITE_RELATIVE):
            return "sqlite+aiosqlite:///" + (API_DIR / v[len(_SQLITE_RELATIVE):]).as_posix()
        return v

    # External providers
    openweather_api_key: str = ""
    sentinelhub_client_id: str = ""
    sentinelhub_client_secret: str = ""
    # Sentinel Hub deployment base URL. Default is the commercial one; for the
    # FREE Copernicus Data Space tier set:
    #   https://sh.dataspace.copernicus.eu
    sentinelhub_base_url: str = "https://services.sentinel-hub.com"
    # OAuth token endpoint. Empty = auto: Copernicus Data Space uses its identity
    # server, the commercial host uses {base}/oauth/token.
    sentinelhub_token_url: str = ""
    # data.gov.in API key for live Agmarknet mandi prices (optional).
    data_gov_api_key: str = ""

    # AI advisory providers — bring your own key; whichever is set gets used.
    # Gemini and Groq have genuinely free tiers; Claude and OpenAI are paid.
    # Priority when advisory_provider="auto": claude -> gemini -> groq -> openai.
    # Claude leads because configuring a paid key is a deliberate choice; remove
    # the key and it falls back to the free tiers on its own.
    advisory_provider: str = "auto"  # auto|claude|gemini|groq|openai
    # Anthropic Claude — paid, multimodal, highest answer quality here.
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-5"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"      # free tier, multimodal
    groq_api_key: str = ""
    groq_model: str = "openai/gpt-oss-20b"      # free tier, text-only here
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"

    # Authentication is delegated to Supabase (email + Google sign-in). The API
    # verifies the Supabase access token on every authenticated request; it never
    # issues its own token.
    #   SUPABASE_URL = https://<project-ref>.supabase.co
    # Tokens are verified against the project's public JWKS (asymmetric ES256 /
    # RS256), so no secret is needed. Legacy HS256-only projects can instead set
    # SUPABASE_JWT_SECRET (Project Settings -> API -> JWT secret).
    supabase_url: str = ""
    supabase_jwt_aud: str = "authenticated"
    supabase_jwt_secret: str = ""

    # Admin analytics endpoint gate (empty disables /admin/*).
    admin_token: str = ""

    # CORS
    cors_origins: str = "http://localhost:3000"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def persistence_enabled(self) -> bool:
        return bool(self.database_url)

    @property
    def auth_enabled(self) -> bool:
        return bool(self.supabase_url)


@lru_cache
def get_settings() -> Settings:
    return Settings()
