"""Test isolation: ignore any developer .env so the suite is deterministic.

Environment variables take priority over the .env file in pydantic-settings, so
forcing these to empty here means tests exercise the graceful/unconfigured paths
regardless of what keys a developer has configured locally. This runs before any
test module (and thus before app import / settings caching).
"""
import os

_FORCE_EMPTY = [
    "GEMINI_API_KEY", "GROQ_API_KEY", "OPENAI_API_KEY",
    "SENTINELHUB_CLIENT_ID", "SENTINELHUB_CLIENT_SECRET",
    "DATA_GOV_API_KEY", "DATABASE_URL", "REDIS_URL",
    "ADMIN_TOKEN", "KADAPALA_SSO_SECRET",
]
for _var in _FORCE_EMPTY:
    os.environ[_var] = ""
