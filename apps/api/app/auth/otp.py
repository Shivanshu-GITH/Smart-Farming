"""Phone OTP issue/verify.

Codes live in the shared cache (in-process now, Redis later) with a short TTL,
so no schema is needed. In dev there is no SMS gateway: ``issue_otp`` just
returns the code and the router echoes it back (guarded by ``otp_dev_mode``).
"""
from __future__ import annotations

import logging
import secrets

from app.core import cache
from app.core.config import get_settings

log = logging.getLogger("smartfarm.otp")


def _key(phone: str) -> str:
    return f"otp:{phone}"


async def issue_otp(phone: str) -> str:
    code = f"{secrets.randbelow(1_000_000):06d}"
    await cache.set(_key(phone), code, ttl_seconds=get_settings().otp_ttl_seconds)
    # TODO(Stage 4): send via SMS gateway. For now, log for local sign-in.
    log.info("OTP for %s: %s", phone, code)
    return code


async def verify_otp(phone: str, code: str) -> bool:
    stored = await cache.get(_key(phone))
    if stored is not None and secrets.compare_digest(str(stored), code):
        await cache.delete(_key(phone))  # one-time use
        return True
    return False
