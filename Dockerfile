# Conversion Engine — web (default) or worker (`docker run ... python -m worker`).
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

# Non-root runtime user.
RUN useradd --create-home appuser
USER appuser

EXPOSE 8000

# Migrations run separately (`alembic upgrade head`) before rollout.
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--forwarded-allow-ips=*"]
