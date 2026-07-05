"""SmartFarm API entrypoint."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from app.admin.router import router as admin_router
from app.advisory.router import router as advisory_router
from app.agronomy.router import router as agronomy_router
from app.auth.router import router as auth_router
from app.core.config import get_settings
from app.core.db import init_db, persistence_available
from app.economics.router import router as economics_router
from app.fields.router import router as fields_router
from app.geo.router import router as geo_router
from app.land_intel.router import router as land_intel_router
from app.layout.router import router as layout_router
from app.reports.router import router as reports_router
from app.resources.router import router as resources_router

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create SQLite tables so login/persistence work with zero setup.
    await init_db()
    yield


app = FastAPI(
    title=settings.app_name,
    version=settings.version,
    description="Precision farm-planning API: field geometry, land intelligence, "
                "crop recommendation, agronomic plans and spatial planting layouts.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# Village directories and layouts are the big payloads (100s of KB) — gzip
# matters for farmers on slow rural connections.
app.add_middleware(GZipMiddleware, minimum_size=2048)


@app.get("/", tags=["meta"])
def root() -> dict:
    return {
        "name": settings.app_name,
        "version": settings.version,
        "persistence": persistence_available(),
        "docs": "/docs",
    }


@app.get("/health", tags=["meta"])
def health() -> dict:
    return {"status": "ok"}


app.include_router(auth_router)
app.include_router(fields_router)
app.include_router(land_intel_router)
app.include_router(agronomy_router)
app.include_router(layout_router)
app.include_router(reports_router)
app.include_router(advisory_router)
app.include_router(economics_router)
app.include_router(resources_router)
app.include_router(admin_router)
app.include_router(geo_router)
