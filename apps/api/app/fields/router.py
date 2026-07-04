from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_current_user
from app.core.db import get_session
from app.db.models import User

from . import crud
from .schemas import (
    FieldCreate,
    FieldOut,
    FieldRequest,
    FieldSummary,
    LayoutCreate,
    PlanCreate,
    SavedLayoutOut,
    SavedPlanOut,
)
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


# --- Saved plans for a field ---

@router.post("/{field_id}/plans", response_model=SavedPlanOut,
             status_code=status.HTTP_201_CREATED)
async def save_plan(
    field_id: str, req: PlanCreate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> SavedPlanOut:
    plan = await crud.save_plan(session, user.id, field_id, req.name, req.data)
    if plan is None:
        raise HTTPException(status_code=404, detail="Field not found")
    return SavedPlanOut(**crud.plan_out(plan))


@router.get("/{field_id}/plans", response_model=list[SavedPlanOut])
async def list_plans(
    field_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[SavedPlanOut]:
    plans = await crud.list_plans(session, user.id, field_id)
    if plans is None:
        raise HTTPException(status_code=404, detail="Field not found")
    return [SavedPlanOut(**crud.plan_out(p)) for p in plans]


@router.delete("/{field_id}/plans/{plan_id}", status_code=status.HTTP_204_NO_CONTENT,
               response_class=Response)
async def delete_plan(
    field_id: str, plan_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Response:
    if not await crud.delete_plan(session, user.id, field_id, plan_id):
        raise HTTPException(status_code=404, detail="Plan not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- Saved layouts for a field ---

@router.post("/{field_id}/layouts", response_model=SavedLayoutOut,
             status_code=status.HTTP_201_CREATED)
async def save_layout(
    field_id: str, req: LayoutCreate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> SavedLayoutOut:
    layout = await crud.save_layout(session, user.id, field_id, req.data)
    if layout is None:
        raise HTTPException(status_code=404, detail="Field not found")
    return SavedLayoutOut(**crud.layout_out(layout))


@router.get("/{field_id}/layouts", response_model=list[SavedLayoutOut])
async def list_layouts(
    field_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[SavedLayoutOut]:
    layouts = await crud.list_layouts(session, user.id, field_id)
    if layouts is None:
        raise HTTPException(status_code=404, detail="Field not found")
    return [SavedLayoutOut(**crud.layout_out(L)) for L in layouts]


@router.delete("/{field_id}/layouts/{layout_id}", status_code=status.HTTP_204_NO_CONTENT,
               response_class=Response)
async def delete_layout(
    field_id: str, layout_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Response:
    if not await crud.delete_layout(session, user.id, field_id, layout_id):
        raise HTTPException(status_code=404, detail="Layout not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
