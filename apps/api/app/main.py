"""SmartFarm API entrypoint."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.agronomy.router import router as agronomy_router
from app.core.config import get_settings
from app.fields.router import router as fields_router
from app.land_intel.router import router as land_intel_router
from app.layout.router import router as layout_router

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version=settings.version,
    description="Precision farm-planning API: field geometry, land intelligence, "
                "crop recommendation, agronomic plans and spatial planting layouts.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/", tags=["meta"])
def root() -> dict:
    return {
        "name": settings.app_name,
        "version": settings.version,
        "persistence": settings.persistence_enabled,
        "docs": "/docs",
    }


@app.get("/health", tags=["meta"])
def health() -> dict:
    return {"status": "ok"}


app.include_router(fields_router)
app.include_router(land_intel_router)
app.include_router(agronomy_router)
app.include_router(layout_router)
