# Mod sandbox image: single container, mount mods at /mods, SQLite-friendly defaults via env.
#
# Build:
#   Recommended: from repo root — powershell -File docker/mod-sandbox/build.ps1
#                 or bash docker/mod-sandbox/build.sh
#   Optional (Docker 23+):
#     docker build --ignorefile docker/mod-sandbox/context.dockerignore \
#       -f docker/mod-sandbox/Dockerfile -t xcagi-mod-sandbox .
#
# Run: see docker/mod-sandbox/README.md

# syntax=docker/dockerfile:1

FROM python:3.11-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    pkg-config \
    portaudio19-dev \
    && rm -rf /var/lib/apt/lists/*

COPY XCAGI/requirements.txt .

RUN pip wheel --no-cache-dir --no-deps --wheel-dir /wheels -r requirements.txt

FROM python:3.11-slim AS production

LABEL org.opencontainers.image.title="xcagi-mod-sandbox" \
    org.opencontainers.image.description="XCAGI minimal image for mod load/runtime smoke tests"

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONUTF8=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --shell /bin/bash appuser

COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir /wheels/* && rm -rf /wheels

# Whitelist: core app + launcher + shared resources (db_seed, etc.)
COPY --chown=appuser:appuser app /app/app
COPY --chown=appuser:appuser XCAGI/run.py XCAGI/run_fastapi.py /app/XCAGI/
COPY --chown=appuser:appuser resources /app/resources

# 启动期多个模块会在仓库根下 mkdir（如 /app/config、/app/templates）；统一保证 appuser 可写
RUN mkdir -p /app/data /app/uploads /app/logs /mods /app/config /app/templates \
    && chown -R appuser:appuser /app

USER appuser

EXPOSE 5000

# FastAPI is ASGI; use UvicornWorker (root gunicorn_config.py uses gevent for legacy WSGI-style stacks).
HEALTHCHECK --interval=30s --timeout=10s --start-period=90s --retries=3 \
    CMD curl -fsS http://127.0.0.1:5000/health >/dev/null || exit 1

CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "1", "--timeout", "120", "--graceful-timeout", "30", "-k", "uvicorn.workers.UvicornWorker", "XCAGI.run_fastapi:app"]
