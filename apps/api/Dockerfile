# SmartFarm API image. Build context MUST be the repo root so packages/crop-db
# is available at the path the catalogue loader expects (repo-relative).
#   docker build -f apps/api/Dockerfile -t smartfarm-api .
FROM python:3.13-slim

WORKDIR /repo/apps/api

# Dependencies first for layer caching. shapely/pyproj/psycopg[binary] ship
# manylinux wheels that bundle GEOS/PROJ/libpq, so no apt build deps are needed.
COPY apps/api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY apps/api/ .
# The curated crop knowledge base lives outside apps/api and is loaded at runtime.
COPY packages/ /repo/packages/

ENV PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
