# SmartFarm 🌱

Precision-agriculture **farm-planning & advisory** platform. A farmer draws their land on a
satellite map, and SmartFarm computes the area, pulls land intelligence (soil, land cover,
climate) for that exact location, then helps them pick crops and a farming style
(single / two-layer / multi-layer / 5-layer) and generates a full agronomic plan plus a
**physical planting layout** showing where every plant goes.

Built for **Kadapala Groups** · pan-India scope.

## Why it's different
Tools like EOSDA, OneSoil and Cropin *monitor* fields that are already planted. SmartFarm
**plans what to plant and lays out each plant** — including multi-layer / 5-layer food-forest
designs — which almost nothing on the market does for Indian smallholders.

## Monorepo layout
```
apps/
  api/            FastAPI backend (the core logic & geospatial IP)
  web/            Next.js PWA frontend (satellite map + planner UI)
packages/
  crop-db/        Curated crop knowledge base (spacing, layers, fertilizer, suitability)
infra/            docker-compose (Postgres+PostGIS, Redis), deploy configs
docs/             Architecture & API notes
```

## Quick start (backend)
```bash
cd apps/api
python -m venv .venv && source .venv/Scripts/activate   # Windows Git Bash
pip install -r requirements.txt
uvicorn app.main:app --reload
# open http://localhost:8000/docs
```

The compute endpoints (geometry, soil, weather, crop recommendation, planting layout) run
**without a database**. Persistence (saving fields/plans) activates when a Postgres+PostGIS
`DATABASE_URL` is configured.

## Quick start (frontend)
```bash
cd apps/web
npm install
npm run dev
# open http://localhost:3000
```

## Status
Phase 0 / Phase 1 scaffolding. See `docs/ARCHITECTURE.md` and the roadmap there.
