from __future__ import annotations

import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.core.ratelimit import limiter

from . import service

router = APIRouter(prefix="/advisory", tags=["advisory"])
log = logging.getLogger(__name__)


def _provider_error(exc: Exception) -> HTTPException:
    """A safe error for the browser. Provider exceptions carry request URLs and
    response bodies, so they are logged here and never echoed to the client."""
    if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 429:
        return HTTPException(status_code=503, detail=(
            "The AI advisor is busy (the AI provider's rate limit). "
            "Please try again in a minute."))
    if isinstance(exc, RuntimeError):   # our own messages, e.g. a Claude refusal
        return HTTPException(status_code=502, detail=str(exc))
    log.warning("advisory provider error: %s: %s", type(exc).__name__, exc)
    return HTTPException(status_code=502, detail=(
        "The AI advisor could not answer right now. Please try again shortly."))


class Message(BaseModel):
    role: str = Field(pattern="^(user|assistant)$")
    content: str


class ChatRequest(BaseModel):
    messages: list[Message] = Field(min_length=1)
    context: dict | None = None
    language: str | None = Field(default=None, max_length=8)  # UI locale: en / hi / te


class DiagnoseRequest(BaseModel):
    image_base64: str = Field(min_length=16)
    media_type: str = "image/jpeg"
    note: str | None = None
    context: dict | None = None


@router.get("/status")
def status() -> dict:
    """Whether the advisory chatbot is configured, and which provider is active."""
    return {
        "configured": service.advisory_available(),
        "provider": service.active_provider(),
        "vision": service.vision_available(),
    }


@router.post("/chat", dependencies=[Depends(limiter("advisory-chat", 20, 600))])
async def chat(req: ChatRequest) -> dict:
    """One advisory turn, grounded in the field context."""
    if not service.advisory_available():
        raise HTTPException(
            status_code=503,
            detail="Advisory chatbot is not configured (set ANTHROPIC_API_KEY, "
                   "or GEMINI_API_KEY for the free tier).",
        )
    try:
        reply = await service.chat(
            [m.model_dump() for m in req.messages], req.context, req.language
        )
    except Exception as exc:  # noqa: BLE001 - surface provider errors cleanly
        raise _provider_error(exc) from exc
    return {"reply": reply}


@router.post("/diagnose", dependencies=[Depends(limiter("advisory-diag", 10, 600))])
async def diagnose(req: DiagnoseRequest) -> dict:
    """Identify a pest/disease from a crop photo (vision-capable provider)."""
    if not service.advisory_available():
        raise HTTPException(
            status_code=503,
            detail="Advisory chatbot is not configured (set ANTHROPIC_API_KEY, "
                   "or GEMINI_API_KEY for the free tier).",
        )
    # Accept a data URL and strip the prefix if present.
    data = req.image_base64
    if data.startswith("data:") and "," in data:
        data = data.split(",", 1)[1]
    try:
        reply = await service.diagnose(data, req.media_type, req.note, req.context)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise _provider_error(exc) from exc
    return {"reply": reply}
