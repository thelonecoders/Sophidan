# syntax=docker/dockerfile:1
# Academic Research Suite — web-server container.
# Runs the Flask + Socket.IO server on port 8765. The desktop Qt UI is
# not usable inside a container; use --web mode only.
#
# Network posture: the server binds to 127.0.0.1 *inside the container* by
# default (safe-by-default, matching the desktop app's default). With the
# loopback bind, `docker run -p 8765:8765 …` will NOT forward traffic — to
# publish the port, override the bind address:
#
#     docker run -e ARS_HOST=0.0.0.0 -p 8765:8765 academic-research-suite
#
# Only publish 0.0.0.0 behind an authenticating reverse proxy — the web API
# has no authentication yet (see docs/SECURITY.md).

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    MPLBACKEND=Agg \
    QT_QPA_PLATFORM=offscreen \
    ARS_HOST=127.0.0.1 \
    ARS_WEB_SERVER_PORT=8765

# Minimal system libs for Qt (import-time) and scientific wheels.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 libegl1 libxkbcommon0 libdbus-1-3 libfontconfig1 \
        libglib2.0-0 curl \
    && rm -rf /var/lib/apt/lists/*

# Non-root runtime user (no login shell, own HOME for Qt/matplotlib).
RUN useradd --create-home --shell /usr/sbin/nologin appuser

WORKDIR /app

# Install Python dependencies first for layer caching.
COPY requirements.txt ./
RUN pip install --upgrade pip && pip install -r requirements.txt

# Copy the application source.
COPY . .

# Persistent data (SQLite DB, cache, projects) and a writable matplotlib
# config dir must be owned by the runtime user.
RUN mkdir -p /app/data /tmp/mplconfig \
    && chown -R appuser:appuser /app /tmp/mplconfig

ENV MPLCONFIGDIR=/tmp/mplconfig

# Persistent data volume (SQLite DB, cache, projects).
VOLUME ["/app/data"]

USER appuser

EXPOSE 8765

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8765/api/health || exit 1

# Shell form so ARS_HOST / ARS_WEB_SERVER_PORT can be overridden with
# `docker run -e`. Defaults keep the server on container loopback only
# (see the network-posture note at the top of this file).
CMD ["sh", "-c", "exec python main.py --web --host \"${ARS_HOST:-127.0.0.1}\" --port \"${ARS_WEB_SERVER_PORT:-8765}\""]
