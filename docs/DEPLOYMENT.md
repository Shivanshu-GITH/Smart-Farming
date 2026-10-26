# SmartFarm — Deployment Guide

Complete, step-by-step guide to deploying SmartFarm (FastAPI API + Next.js web).

The API is designed to degrade gracefully: **all compute endpoints work with zero
config** (no DB, no keys). Everything below is about turning on persistence,
external data, and a hardened production posture on top of that baseline.

---

## 1. What you are deploying

| Component | Tech | Port | Needs |
|-----------|------|------|-------|
| `apps/api` | FastAPI (Python 3.13), Uvicorn | 8000 | Nothing to boot. Postgres for persistence. |
| `apps/web` | Next.js 15 (React 19) | 3000 | The API URL, baked at build time. |
| Postgres + PostGIS | `postgis/postgis:16-3.4` | 5432 | Only if you want saved fields/plans/login-across-restarts. |
| Redis | `redis:7-alpine` | 6379 | Optional shared cache (falls back to in-process LRU). |

Key facts that shape deployment:

- **Village geodata (≈6 MB, 548k places) is committed to the repo** as gzipped
  JSON under `packages/india-geo/villages/`. Nothing is downloaded at deploy time.
- The API Docker build context **must be the repo root** — it copies `packages/`
  which lives outside `apps/api`.
- `NEXT_PUBLIC_API_URL` is compiled into the client bundle, so the web image must
  be **rebuilt** if the API URL changes.
- SQLite auto-creates its tables on startup; **Postgres uses Alembic migrations**
  (`alembic upgrade head`).

---

## 2. Prerequisites

- **Docker** + **Docker Compose v2** (for the container paths), OR
- **Python 3.13** and **Node 20+** (for the bare-metal path).
- A domain + TLS terminator (Caddy / Nginx / a platform that does TLS for you) for
  a public deployment.

---

## 3. Choose a deployment path

- **Path A — Single VPS with Docker Compose** (recommended, simplest). One box runs
  db + redis + api + web. Best for a pilot / first production.
- **Path B — Managed split deploy.** Web on Vercel, API on Render/Railway/Fly.io,
  a managed Postgres. Best for scaling and zero-ops.
- **Path C — Bare metal / no Docker.** For a dev-prod box or when you can't run
  containers.

---

## 4. Environment variables (full reference)

### API — `apps/api/.env` (copy from `.env.example`)

| Var | Default | Purpose |
|-----|---------|---------|
| `ENVIRONMENT` | `development` | Set to `production`. |
| `DATABASE_URL` | sqlite file | Prod: `postgresql+psycopg://user:pass@host:5432/smartfarm`. Empty = fully stateless. |
| `REDIS_URL` | empty | `redis://host:6379/0`. Empty = in-process cache. |
| `SUPABASE_URL` | empty | `https://<project-ref>.supabase.co`. The API verifies Supabase access tokens against this project's public JWKS — no secret needed. Empty disables login (compute still works; saving returns 401). |
| `SUPABASE_JWT_SECRET` | empty | Only for legacy Supabase projects that still sign with HS256. Leave empty otherwise. |
| `CORS_ORIGINS` | `http://localhost:3000` | Comma-separated list of web origins allowed to call the API. Set to your web domain(s). |
| `ADMIN_TOKEN` | empty | Gates `/admin/*` analytics. Empty disables it. |

**Optional external data providers (all free-tier capable, all skippable):**

| Var | Provider | Get a key |
|-----|----------|-----------|
| `OPENWEATHER_API_KEY` | OpenWeather (fallback; Open-Meteo needs no key) | openweathermap.org |
| `SENTINELHUB_CLIENT_ID` / `_SECRET` / `SENTINELHUB_BASE_URL` | NDVI imagery — FREE via Copernicus Data Space | dataspace.copernicus.eu → OAuth clients. Set base URL to `https://sh.dataspace.copernicus.eu`. |
| `DATA_GOV_API_KEY` | Live mandi prices | data.gov.in (instant key). Empty = curated estimates. |
| `ADVISORY_PROVIDER` + one of `ANTHROPIC_API_KEY` / `GEMINI_API_KEY` / `GROQ_API_KEY` / `OPENAI_API_KEY` | AI advisory & photo pest-ID | `auto` order = Claude (paid) → Gemini (free) → Groq (free) → OpenAI (paid). Claude: console.anthropic.com, model via `ANTHROPIC_MODEL` (default `claude-sonnet-5`). Gemini: aistudio.google.com. Groq: console.groq.com. Photo diagnosis needs a vision provider (Claude, Gemini or OpenAI). |

### Web — `apps/web/.env.local` (copy from `.env.local.example`)

| Var | Purpose |
|-----|---------|
| `NEXT_PUBLIC_API_URL` | Public URL of the API (e.g. `https://api.smartfarm.example`). **Baked at build time.** |
| `NEXT_PUBLIC_SUPABASE_URL` | Same Supabase project URL as the API's `SUPABASE_URL`. **Baked at build time.** |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | The project's anon / publishable key (browser-safe). Never put the `service_role` key here. **Baked at build time.** |

### Supabase project setup (one time)

1. **Authentication → Providers:** enable *Email*; enable *Google* and paste the
   Google OAuth client ID/secret (Google Cloud console → Credentials → OAuth client,
   type *Web application*).
2. In that Google OAuth client, add the **Authorized redirect URI**
   `https://<project-ref>.supabase.co/auth/v1/callback`.
3. **Authentication → URL Configuration:** set *Site URL* to your web origin
   (e.g. `https://smartfarm.example`) and add it, plus `http://localhost:3000`
   for dev, to *Redirect URLs*. Sign-in redirects anywhere else are rejected.

---

## 5. Path A — Single VPS with Docker Compose (recommended)

The full-stack compose file is `infra/docker-compose.app.yml`. It builds both
images, runs Alembic migrations on API startup, and wires everything together.

### Step 1 — Get the code on the server
```bash
git clone <your-repo-url> smartfarming
cd smartfarming
```

### Step 2 — Create a secrets file next to the compose file
Compose reads variables from the environment or an `.env` file **next to** the
compose file, i.e. `infra/.env`:
```bash
cat > infra/.env <<'EOF'
SUPABASE_URL=https://<project-ref>.supabase.co
SUPABASE_ANON_KEY=<anon / publishable key>
NEXT_PUBLIC_API_URL=https://api.smartfarm.example
# Optional providers — leave blank to skip:
ANTHROPIC_API_KEY=
GEMINI_API_KEY=
GROQ_API_KEY=
OPENAI_API_KEY=
SENTINELHUB_CLIENT_ID=
SENTINELHUB_CLIENT_SECRET=
DATA_GOV_API_KEY=
EOF
```
> `infra/docker-compose.app.yml` hard-codes `CORS_ORIGINS=http://localhost:3000`
> and the internal `DATABASE_URL`/`REDIS_URL`. For a real domain, edit the `api`
> service's `CORS_ORIGINS` to your web origin (e.g. `https://smartfarm.example`)
> and set `NEXT_PUBLIC_API_URL` to the public API URL (used as a build arg).

### Step 3 — Build and start
```bash
docker compose -f infra/docker-compose.app.yml up --build -d
```
This will:
1. Start Postgres (PostGIS) and Redis, wait for Postgres to be healthy.
2. Build the API image (context = repo root, so `packages/` is included).
3. Run `alembic upgrade head`, then serve Uvicorn on `:8000`.
4. Build the web image with `NEXT_PUBLIC_API_URL` and the Supabase URL/anon key
   baked in, serve on `:3000`.

### Step 4 — Verify
```bash
curl http://localhost:8000/health          # {"status":"ok"}
curl http://localhost:8000/                 # shows "persistence": true
curl -I http://localhost:3000               # 200
```
Open `http://<server>:8000/docs` for the interactive API.

### Step 5 — Put TLS in front
Do **not** expose 8000/3000 directly. Terminate TLS with Caddy or Nginx and
reverse-proxy:
- `https://smartfarm.example`     → `web:3000`
- `https://api.smartfarm.example` → `api:8000`

Minimal Caddyfile:
```
smartfarm.example {
    reverse_proxy localhost:3000
}
api.smartfarm.example {
    reverse_proxy localhost:8000
}
```
Then make sure `CORS_ORIGINS` (API) = `https://smartfarm.example` and
`NEXT_PUBLIC_API_URL` (web build arg) = `https://api.smartfarm.example`, and
rebuild the web image if you changed it.

### Updating a live deployment
```bash
git pull
docker compose -f infra/docker-compose.app.yml up --build -d
```
Migrations re-run automatically (idempotent). If you changed `NEXT_PUBLIC_API_URL`,
the `--build` is what re-bakes it into the web bundle.

---

## 6. Path B — Managed split deploy

### 6a. Database — managed Postgres
Provision Postgres 16 on Neon / Supabase / Railway / RDS. PostGIS is **not
required** (geometry is stored as GeoJSON). Grab the connection string and convert
the driver prefix to `postgresql+psycopg://…`.

### 6b. API — Render / Railway / Fly.io (Docker)
- **Build:** use `apps/api/Dockerfile` with **build context = repo root**
  (critical — it copies `packages/`). On Render, set Root Directory to the repo
  root and Dockerfile path to `apps/api/Dockerfile`.
- **Start command** (run migrations then serve):
  ```
  sh -c "python -m alembic upgrade head && python -m uvicorn app.main:app --host 0.0.0.0 --port $PORT"
  ```
  (The Dockerfile's default CMD serves on 8000 without migrating — override it as
  above so Postgres migrations run.)
- **Env vars:** set `ENVIRONMENT=production`, `DATABASE_URL`, `SUPABASE_URL`,
  `CORS_ORIGINS=https://<your-vercel-domain>`, plus any
  provider keys and `REDIS_URL` if you added Redis.
- **Health check path:** `/health`.

### 6c. Web — Vercel
- Import the repo, set **Root Directory = `apps/web`**. Framework auto-detects
  Next.js; build `next build`, output served by `next start` (or Vercel's
  serverless output).
- **Environment variables** (Production): `NEXT_PUBLIC_API_URL=https://<api-host>`,
  `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`.
- Redeploy after changing any of them — `NEXT_PUBLIC_*` is build-time only.

### 6d. Wire CORS + auth redirects
- API `CORS_ORIGINS` must include the exact Vercel domain (and any custom domain).
- In Supabase → Authentication → URL Configuration, set *Site URL* to the Vercel /
  custom domain and add it to *Redirect URLs* (see §4, Supabase project setup).

---

## 7. Path C — Bare metal (no Docker)

### API
```bash
cd apps/api
python -m venv .venv && source .venv/Scripts/activate   # or .venv/bin/activate on Linux
pip install -r requirements.txt
cp .env.example .env        # then edit — set DATABASE_URL, SUPABASE_URL, ENVIRONMENT=production
python -m alembic upgrade head   # only if using Postgres
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
```
Run it under a process manager (systemd / supervisor). Put Uvicorn behind Nginx.

### Web
```bash
cd apps/web
npm ci
cp .env.local.example .env.local   # set NEXT_PUBLIC_API_URL + NEXT_PUBLIC_SUPABASE_*
npm run build
npm run start -- -p 3000           # or PORT=3000 npm start
```
Serve under a process manager and reverse-proxy with TLS.

---

## 8. Production hardening checklist

Before real users touch it, confirm **all** of these:

- [ ] `ENVIRONMENT=production`.
- [ ] `SUPABASE_URL` (API) and `NEXT_PUBLIC_SUPABASE_URL` (web) point at the **same**
      Supabase project; the web uses only the anon key. The `service_role` key,
      database password and JWT secret are never needed by this app — keep them
      out of every `.env`.
- [ ] Supabase *Site URL* / *Redirect URLs* list only your real web origin(s).
- [ ] `CORS_ORIGINS` lists only your real web origin(s) — no `*`, no localhost in prod.
- [ ] `DATABASE_URL` points at managed Postgres with backups enabled.
- [ ] Ports 8000/3000 are **not** publicly exposed; only the TLS proxy is.
- [ ] `ADMIN_TOKEN` set (or intentionally empty to disable `/admin/*`).
- [ ] Secrets come from the platform's secret store / `infra/.env`, never committed
      (`.env*` is gitignored except `.env.example`).
- [ ] Provider keys are the intended tier (Gemini/Groq free, OpenAI paid).

The API already sends `X-Content-Type-Options`, `X-Frame-Options: DENY`,
`Referrer-Policy`, `no-store` on `/auth/*`, gzip, and has rate limiting
(`app/core/ratelimit.py`) — no extra config needed for those.

---

## 9. Post-deploy smoke test

```bash
API=https://api.smartfarm.example

curl $API/health                      # {"status":"ok"}
curl $API/                            # "persistence": true when DB configured

# Area from a drawn polygon (core compute, no DB/keys needed):
curl -X POST $API/geo/area \
  -H 'Content-Type: application/json' \
  -d '{"geometry":{"type":"Polygon","coordinates":[[[78.4,17.4],[78.4,17.41],[78.41,17.41],[78.41,17.4],[78.4,17.4]]]}}'
```
Then load the web app, draw a field, and confirm the plan + planting layout render.
Check `/docs` for the full endpoint list to smoke-test land intelligence, crop
recommendation, and advisory (if keys are set).

---

## 10. Troubleshooting

| Symptom | Cause / fix |
|---------|-------------|
| `persistence: false` at `/` | `DATABASE_URL` empty or unreachable. Compute still works; saving fields returns 503. |
| Docker API build fails on missing `packages/` | Build context wasn't the repo root. Use `-f apps/api/Dockerfile .` from root (compose already does this). |
| Web calls go to `localhost:8000` in production | `NEXT_PUBLIC_API_URL` wasn't set at **build** time. Rebuild the web image/deploy with the right value. |
| CORS errors in browser console | `CORS_ORIGINS` doesn't exactly match the web origin (scheme + host + port). |
| Sign-in page says auth is not configured | `NEXT_PUBLIC_SUPABASE_URL` / `_ANON_KEY` weren't set at **build** time. Rebuild. |
| Signed in, but saving a field returns 401 | API `SUPABASE_URL` empty or a different project from the web's. |
| Google sign-in ends on "redirect not allowed" / wrong site | Web origin missing from Supabase *Redirect URLs*, or the Supabase callback URL missing from the Google OAuth client. |
| Postgres tables missing | Alembic didn't run. Run `python -m alembic upgrade head` (SQLite auto-creates; Postgres does not). |
| NDVI / mandi / advisory returns fallback data | Corresponding provider key not set — expected, safe degradation. |

---

## 11. Quick reference — commands

```bash
# Full stack up (single box)
docker compose -f infra/docker-compose.app.yml up --build -d

# Just the backing services for local dev
docker compose -f infra/docker-compose.yml up -d

# Migrations (Postgres)
cd apps/api && python -m alembic upgrade head

# Logs
docker compose -f infra/docker-compose.app.yml logs -f api
docker compose -f infra/docker-compose.app.yml logs -f web

# Tear down (keep data)
docker compose -f infra/docker-compose.app.yml down
# Tear down + delete DB/redis volumes (destructive)
docker compose -f infra/docker-compose.app.yml down -v
```
