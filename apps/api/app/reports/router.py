from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel

from app.fields.schemas import GeoJSONGeometry

from .service import generate_report

router = APIRouter(prefix="/reports", tags=["reports"])


class ReportRequest(BaseModel):
    geometry: GeoJSONGeometry
    crop_ids: list[str] = []


@router.post("/pdf")
async def report_pdf(req: ReportRequest) -> Response:
    """Generate a downloadable PDF report (field + land intel + crop plans)."""
    try:
        pdf = await generate_report(req.geometry.model_dump(), req.crop_ids)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="smartfarm-report.pdf"'},
    )
