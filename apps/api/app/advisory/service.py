"""Agronomy advisory chat + photo pest-ID.

Grounds the model in the farmer's actual field context (area, region, soil,
climate, NDVI, chosen crops/plan) so answers are specific rather than generic.
Backed by a multi-provider layer (Claude when its key is set, then the free
Gemini/Groq tiers, with OpenAI last — see providers.py). Degrades gracefully
when no provider is configured, matching the rest of the platform.
"""
from __future__ import annotations

import json

from . import providers

SYSTEM_PROMPT = """You are SmartFarm's agronomy advisor for Indian farmers.

Your role:
- Give practical, actionable farming guidance grounded in the field context below.
- Cover crop choice, spacing, multi-layer/companion planting, fertilizer, irrigation,
  pest/disease management, and the crop calendar when relevant.
- Prefer specifics (quantities, timings, local seasons: Kharif/Rabi/Zaid) over generic advice.
- Reply in the same language as the farmer's latest message: the "Reply language"
  line below names it. Do not switch language because of the field's region.
- Be concise and encouraging. Use simple language a smallholder farmer can act on.

Boundaries:
- The soil/satellite figures are ~250 m estimates, not lab results — say so when it matters.
- Always remind the farmer to confirm chemical/fertilizer doses with a local soil test and
  an agricultural extension officer before applying, especially for pesticides.
- If you are unsure, say so rather than inventing figures."""

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
# The web app's UI languages (next-intl locales).
_LANGUAGES = {"en": "English", "hi": "Hindi", "te": "Telugu"}


def advisory_available() -> bool:
    return providers.any_configured()


def active_provider() -> str | None:
    return providers.select_provider()


def vision_available() -> bool:
    return providers.select_provider(vision=True) is not None


def _context_block(context: dict | None) -> str:
    if not context:
        return "No field has been analysed yet; give general guidance and ask for the field details."
    return ("Current field context (JSON):\n```json\n"
            + json.dumps(context, ensure_ascii=False, indent=1)[:4000] + "\n```")


def reply_language(text: str, ui_locale: str | None) -> str:
    """Language to answer in, from the script the farmer wrote in.

    Decided here rather than left to the model, which drifted into Hindi for
    English questions about Indian fields. Too little text to tell (numbers, a
    word or two) falls back to the app's UI language.
    """
    devanagari = sum("ऀ" <= ch <= "ॿ" for ch in text)
    telugu = sum("ఀ" <= ch <= "౿" for ch in text)
    latin = sum(ch.isascii() and ch.isalpha() for ch in text)
    if devanagari or telugu:
        return "Hindi" if devanagari >= telugu else "Telugu"
    if latin >= 6:
        return "English"
    return _LANGUAGES.get(ui_locale or "en", "English")


def _language_line(language: str) -> str:
    line = f"Reply language: {language}."
    if language == "English":
        line += (" (If the message is Hindi or Telugu written in Latin letters, reply in "
                 "that language, also in Latin letters.)")
    return line


async def chat(messages: list[dict], context: dict | None = None,
               language: str | None = None) -> str:
    """Run one advisory turn. `messages` is the running [{role, content}] history;
    `language` is the app's UI locale, the fallback reply language."""
    latest = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
    system = (SYSTEM_PROMPT + "\n\n" + _language_line(reply_language(latest, language))
              + "\n\n" + _context_block(context))
    return await providers.chat(system, messages)


async def diagnose(image_b64: str, media_type: str,
                   note: str | None = None, context: dict | None = None) -> str:
    """Vision diagnosis of a crop photo (pest/disease ID)."""
    if media_type not in _ALLOWED_MEDIA:
        raise ValueError(f"Unsupported image type '{media_type}'")
    text = note.strip() if note else "What is wrong with this crop, and what should I do?"
    if context:
        text += "\n\nField context (JSON): " + json.dumps(context, ensure_ascii=False)[:1500]
    return await providers.diagnose(DIAGNOSE_PROMPT, image_b64, media_type, text)
