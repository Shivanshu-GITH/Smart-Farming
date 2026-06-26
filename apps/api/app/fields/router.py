from __future__ import annotations

from fastapi import APIRouter, HTTPException

from .schemas import FieldRequest, FieldSummary
from .service import summarize_field

router = APIRouter(prefix="/fields", tags=["fields"])


@router.post("/summary", response_model=FieldSummary)
async def field_summary(req: FieldRequest) -> FieldSummary:
    """Compute area, perimeter, centroid, bbox and region for a drawn polygon."""
    try:
        result = await summarize_field(req.geometry.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return FieldSummary(**result)
