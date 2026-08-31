# Conversion Engine — web (default) or worker (`docker run ... python -m worker`).

# Stage 1: build the Next.js dashboard (static export served at /app).
FROM node:22-slim AS frontend
WORKDIR /fe
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install deps first for layer caching.
COPY requirements.txt requirements.lock ./
RUN pip install -r requirements.txt -c requirements.lock

COPY engine/ engine/
COPY migrations/ migrations/
COPY alembic.ini server.py app.py worker.py ./
# The built dashboard — engine/app.py mounts it at /app when present.
COPY --from=frontend /fe/out frontend/out/

# Non-root runtime user. UID 1000 matches what Hugging Face Spaces runs
# containers as, so the home directory stays writable there.
RUN useradd --create-home --uid 1000 appuser
USER appuser
ENV HOME=/home/appuser

EXPOSE 8000

# Migrations run before the server. On Render this is preDeployCommand, but a
# platform without a pre-deploy hook (Hugging Face Spaces) has only this
# entrypoint — `alembic upgrade head` is idempotent, so running it on every
# start is safe and keeps the schema correct wherever the image is deployed.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn server:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips=*"]
