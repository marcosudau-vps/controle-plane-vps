FROM selfhost/caddy-cloudflare:local AS caddybin

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl docker-cli docker-compose zstd \
    && rm -rf /var/lib/apt/lists/*

COPY --from=caddybin /usr/bin/caddy /usr/bin/caddy
COPY pyproject.toml /app/pyproject.toml
COPY requirements-runtime.lock /app/requirements-runtime.lock
COPY control_plane /app/control_plane
COPY alembic.ini /app/alembic.ini
COPY migrations /app/migrations

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements-runtime.lock \
    && pip install --no-cache-dir --no-deps .

EXPOSE 8765

CMD ["uvicorn", "control_plane.api:app", "--host", "0.0.0.0", "--port", "8765"]
