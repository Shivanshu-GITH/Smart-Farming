from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_current_user
from app.core.db import get_session
from app.db.models import User

from . import crud
from .schemas import FieldCreate, FieldOut, FieldRequest, FieldSummary
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


# --- Saved fields (require auth + persistence) ---

@router.post("", response_model=FieldOut, status_code=status.HTTP_201_CREATED)
async def create_field(
    req: FieldCreate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> FieldOut:
    """Persist a drawn polygon as a named field owned by the current user."""
    try:
        field = await crud.create_field(
            session, user.id, req.name, req.geometry.model_dump()
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return FieldOut(**crud.to_out(field))


@router.get("", response_model=list[FieldOut])
async def list_fields(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[FieldOut]:
    fields = await crud.list_fields(session, user.id)
    return [FieldOut(**crud.to_out(f)) for f in fields]


@router.get("/{field_id}", response_model=FieldOut)
async def get_field(
    field_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> FieldOut:
    field = await crud.get_field(session, user.id, field_id)
    if field is None:
        raise HTTPException(status_code=404, detail="Field not found")
    return FieldOut(**crud.to_out(field))


@router.delete(
    "/{field_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_field(
    field_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Response:
    deleted = await crud.delete_field(session, user.id, field_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Field not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
