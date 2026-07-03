from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from . import service

router = APIRouter(prefix="/advisory", tags=["advisory"])


class Message(BaseModel):
    role: str = Field(pattern="^(user|assistant)$")
    content: str


class ChatRequest(BaseModel):
    messages: list[Message] = Field(min_length=1)
    context: dict | None = None


@router.get("/status")
def status() -> dict:
    """Whether the Claude advisory chatbot is configured on this server."""
    return {"configured": service.advisory_available()}


@router.post("/chat")
async def chat(req: ChatRequest) -> dict:
    """One advisory turn, grounded in the field context."""
    if not service.advisory_available():
        raise HTTPException(
            status_code=503,
            detail="Advisory chatbot is not configured (set ANTHROPIC_API_KEY).",
        )
    try:
        reply = await service.chat(
            [m.model_dump() for m in req.messages], req.context
        )
    except Exception as exc:  # noqa: BLE001 - surface provider errors cleanly
        raise HTTPException(status_code=502, detail=f"Advisory error: {exc}") from exc
    return {"reply": reply}
