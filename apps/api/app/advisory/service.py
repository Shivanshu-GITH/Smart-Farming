"""Claude-powered agronomy advisory chat.

Grounds the model in the farmer's actual field context (area, region, soil,
climate, NDVI, chosen crops/plan) so answers are specific rather than generic.
Uses the official Anthropic async SDK. Degrades gracefully when no API key is
configured, matching the rest of the platform.
"""
from __future__ import annotations

import json

from app.core.config import get_settings

SYSTEM_PROMPT = """You are SmartFarm's agronomy advisor for Indian farmers.

Your role:
- Give practical, actionable farming guidance grounded in the field context below.
- Cover crop choice, spacing, multi-layer/companion planting, fertilizer, irrigation,
  pest/disease management, and the crop calendar when relevant.
- Prefer specifics (quantities, timings, local seasons: Kharif/Rabi/Zaid) over generic advice.
- If the farmer writes in Hindi or another Indian language, reply in that language.
- Be concise and encouraging. Use simple language a smallholder farmer can act on.

Boundaries:
- The soil/satellite figures are ~250 m estimates, not lab results — say so when it matters.
- Always remind the farmer to confirm chemical/fertilizer doses with a local soil test and
  an agricultural extension officer before applying, especially for pesticides.
- If you are unsure, say so rather than inventing figures."""


def _context_block(context: dict | None) -> str:
    if not context:
        return "No field has been analysed yet; give general guidance and ask for the field details."
    parts = ["Current field context (JSON):", "```json",
             json.dumps(context, ensure_ascii=False, indent=1)[:4000], "```"]
    return "\n".join(parts)


def advisory_available() -> bool:
    return bool(get_settings().anthropic_api_key)


DIAGNOSE_PROMPT = """You are a plant pathologist and pest specialist for Indian farms.

A farmer has sent a photo of a crop (leaf/stem/fruit). Identify the most likely
problem and advise:
- Likely pest/disease (name + confidence in plain words). If the image is unclear
  or healthy, say so — do not invent a diagnosis.
- Key symptoms you can see in the photo.
- Organic/cultural control first, then chemical control with typical Indian product
  names and dosages ONLY as a rough guide.
- Prevention for next season.

Reply in the farmer's language if their note is in one. Be concise and practical.
Always end by advising confirmation with a local agri-extension officer before
spraying any chemical — a photo can mislead."""

_ALLOWED_MEDIA = {"image/jpeg", "image/png", "image/webp", "image/gif"}


async def diagnose(image_b64: str, media_type: str,
                   note: str | None = None, context: dict | None = None) -> str:
    """Vision diagnosis of a crop photo (pest/disease ID)."""
    settings = get_settings()
    if not settings.anthropic_api_key:
        raise RuntimeError("Advisory is not configured (set ANTHROPIC_API_KEY).")
    if media_type not in _ALLOWED_MEDIA:
        raise ValueError(f"Unsupported image type '{media_type}'")

    from anthropic import AsyncAnthropic

    client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    text = note.strip() if note else "What is wrong with this crop, and what should I do?"
    if context:
        text += "\n\nField context (JSON): " + json.dumps(context, ensure_ascii=False)[:1500]

    response = await client.messages.create(
        model=settings.advisory_model,
        max_tokens=1024,
        system=DIAGNOSE_PROMPT,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {
                    "type": "base64", "media_type": media_type, "data": image_b64}},
                {"type": "text", "text": text},
            ],
        }],
    )
    return "".join(b.text for b in response.content if b.type == "text")


async def chat(messages: list[dict], context: dict | None = None) -> str:
    """Run one advisory turn. `messages` is the running [{role, content}] history."""
    settings = get_settings()
    if not settings.anthropic_api_key:
        raise RuntimeError("Advisory is not configured (set ANTHROPIC_API_KEY).")

    from anthropic import AsyncAnthropic

    client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    system = [
        {"type": "text", "text": SYSTEM_PROMPT},
        # Field context is stable within a session — cache it to cut cost.
        {"type": "text", "text": _context_block(context),
         "cache_control": {"type": "ephemeral"}},
    ]

    response = await client.messages.create(
        model=settings.advisory_model,
        max_tokens=1024,
        system=system,
        messages=messages,
    )
    return "".join(b.text for b in response.content if b.type == "text")
