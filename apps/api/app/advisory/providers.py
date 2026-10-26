"""Multi-provider AI backend for advisory chat and photo diagnosis.

Bring-your-own-key: whichever provider key is configured gets used. Claude
leads when its key is set — configuring a paid key is a deliberate choice —
then the free tiers (Google Gemini, Groq), with paid OpenAI last. Selection
order (advisory_provider="auto"): claude -> gemini -> groq -> openai. Photo
diagnosis only uses vision-capable providers (claude, gemini, openai).

Providers are called over their REST APIs with httpx to avoid pulling in an
SDK per provider. Groq/OpenAI share the OpenAI-compatible schema; Claude uses
Anthropic's Messages API.
"""
from __future__ import annotations

import httpx

from app.core.config import get_settings

VISION_CAPABLE = {"claude", "gemini", "openai"}
_PRIORITY = ("claude", "gemini", "groq", "openai")
_OPENAI_COMPAT = {
    "groq": "https://api.groq.com/openai/v1",
    "openai": "https://api.openai.com/v1",
}


def _configured() -> list[str]:
    """Providers with a key, in default priority order."""
    s = get_settings()
    keys = {
        "claude": s.anthropic_api_key,
        "gemini": s.gemini_api_key,
        "groq": s.groq_api_key,
        "openai": s.openai_api_key,
    }
    return [p for p in _PRIORITY if keys[p]]


def select_provider(*, vision: bool = False) -> str | None:
    configured = _configured()
    if vision:
        configured = [p for p in configured if p in VISION_CAPABLE]
    pref = get_settings().advisory_provider
    if pref and pref != "auto":
        return pref if pref in configured else None
    return configured[0] if configured else None


def any_configured() -> bool:
    return bool(_configured())


# --- chat ---

async def chat(system: str, messages: list[dict]) -> str:
    provider = select_provider()
    if provider is None:
        raise RuntimeError("No advisory provider configured.")
    if provider == "claude":
        return await _claude_chat(system, messages)
    if provider == "gemini":
        return await _gemini_chat(system, messages)
    return await _openai_compat_chat(provider, system, messages)


async def diagnose(system: str, image_b64: str, media_type: str, text: str) -> str:
    provider = select_provider(vision=True)
    if provider is None:
        raise ValueError(
            "Photo diagnosis needs a vision-capable AI provider "
            "(Claude, Gemini or OpenAI).")
    if provider == "claude":
        return await _claude_vision(system, image_b64, media_type, text)
    if provider == "gemini":
        return await _gemini_vision(system, image_b64, media_type, text)
    return await _openai_vision(provider, system, image_b64, media_type, text)


# --- Anthropic Claude (Messages API) ---

_CLAUDE_URL = "https://api.anthropic.com/v1/messages"


def _claude_headers() -> dict:
    return {
        "x-api-key": get_settings().anthropic_api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }


def _claude_body(system: str, messages: list[dict]) -> dict:
    # Thinking off: advisory turns are short and latency-sensitive, and with
    # thinking on max_tokens is shared with the reasoning budget. This mirrors
    # the thinkingBudget=0 we set for Gemini 2.5-flash below.
    return {
        "model": get_settings().anthropic_model,
        "max_tokens": 2048,
        "thinking": {"type": "disabled"},
        "system": system,
        "messages": messages,
    }


def _claude_text(data: dict) -> str:
    if data.get("stop_reason") == "refusal":
        raise RuntimeError(
            "Claude declined to answer this request. Rephrase the question, "
            "or ask a local agri-extension officer.")
    return "".join(b.get("text", "") for b in data.get("content", [])
                   if b.get("type") == "text")


async def _claude_chat(system: str, messages: list[dict]) -> str:
    body = _claude_body(system, [{"role": m["role"], "content": m["content"]}
                                 for m in messages])
    async with httpx.AsyncClient(timeout=40) as client:
        resp = await client.post(_CLAUDE_URL, json=body, headers=_claude_headers())
        resp.raise_for_status()
        return _claude_text(resp.json())


async def _claude_vision(system, image_b64, media_type, text) -> str:
    body = _claude_body(system, [{"role": "user", "content": [
        {"type": "image", "source": {"type": "base64",
                                     "media_type": media_type,
                                     "data": image_b64}},
        {"type": "text", "text": text}]}])
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(_CLAUDE_URL, json=body, headers=_claude_headers())
        resp.raise_for_status()
        return _claude_text(resp.json())


# --- Google Gemini (REST) ---

def _gemini_url() -> str:
    return (f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{get_settings().gemini_model}:generateContent")


def _gemini_headers() -> dict:
    # Header, not ?key=: a URL ends up in exception messages and logs.
    return {"x-goog-api-key": get_settings().gemini_api_key}


def _gemini_gen_config() -> dict:
    # Give room for the answer, and turn off 2.5-flash "thinking" so it doesn't
    # consume the whole output budget (thinkingBudget is ignored by models that
    # don't support it).
    return {"maxOutputTokens": 2048, "thinkingConfig": {"thinkingBudget": 0}}


def _gemini_text(data: dict) -> str:
    return "".join(
        part.get("text", "")
        for cand in data.get("candidates", [])
        for part in cand.get("content", {}).get("parts", []))


async def _gemini_chat(system: str, messages: list[dict]) -> str:
    contents = [
        {"role": "model" if m["role"] == "assistant" else "user",
         "parts": [{"text": m["content"]}]}
        for m in messages
    ]
    body = {
        "system_instruction": {"parts": [{"text": system}]},
        "contents": contents,
        "generationConfig": _gemini_gen_config(),
    }
    async with httpx.AsyncClient(timeout=40) as client:
        resp = await client.post(_gemini_url(), json=body, headers=_gemini_headers())
        resp.raise_for_status()
        return _gemini_text(resp.json())


async def _gemini_vision(system, image_b64, media_type, text) -> str:
    body = {
        "system_instruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [
            {"inline_data": {"mime_type": media_type, "data": image_b64}},
            {"text": text}]}],
        "generationConfig": _gemini_gen_config(),
    }
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(_gemini_url(), json=body, headers=_gemini_headers())
        resp.raise_for_status()
        return _gemini_text(resp.json())


# --- OpenAI-compatible (Groq / OpenAI) ---

def _openai_compat_cfg(provider: str) -> tuple[str, str, str]:
    s = get_settings()
    key = s.groq_api_key if provider == "groq" else s.openai_api_key
    model = s.groq_model if provider == "groq" else s.openai_model
    return _OPENAI_COMPAT[provider], key, model


async def _openai_compat_chat(provider: str, system: str, messages: list[dict]) -> str:
    base, key, model = _openai_compat_cfg(provider)
    body = {"model": model, "max_tokens": 1024,
            "messages": [{"role": "system", "content": system}, *messages]}
    async with httpx.AsyncClient(timeout=40) as client:
        resp = await client.post(f"{base}/chat/completions", json=body,
                                 headers={"Authorization": f"Bearer {key}"})
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]


async def _openai_vision(provider, system, image_b64, media_type, text) -> str:
    base, key, model = _openai_compat_cfg(provider)
    body = {"model": model, "max_tokens": 1024, "messages": [
        {"role": "system", "content": system},
        {"role": "user", "content": [
            {"type": "text", "text": text},
            {"type": "image_url", "image_url": {
                "url": f"data:{media_type};base64,{image_b64}"}}]}]}
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(f"{base}/chat/completions", json=body,
                                 headers={"Authorization": f"Bearer {key}"})
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]
