# syntax=docker/dockerfile:1
# Hardened image: pinned Deno release (no curl|sh), code read-only to the non-root user,
# only /app/data writable.
FROM python:3.12-slim-bookworm AS base

ARG DENO_VERSION=v2.1.4
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    ANGEL_DB_PATH=/app/data/angel.db

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    ca-certificates \
    curl \
    unzip \
    libopus0 \
    && rm -rf /var/lib/apt/lists/*

# Pinned Deno archive instead of piping an unverified install script.
RUN ARCH="$(dpkg --print-architecture)" \
    && case "$ARCH" in \
         amd64) DENO_ARCH="x86_64-unknown-linux-gnu" ;; \
         arm64) DENO_ARCH="aarch64-unknown-linux-gnu" ;; \
         *) echo "Unsupported arch: $ARCH" >&2; exit 1 ;; \
       esac \
    && curl -fsSL "https://github.com/denoland/deno/releases/download/${DENO_VERSION}/deno-${DENO_ARCH}.zip" -o /tmp/deno.zip \
    && unzip -q /tmp/deno.zip -d /usr/local/bin \
    && rm -f /tmp/deno.zip \
    && chmod 0755 /usr/local/bin/deno \
    && deno --version

RUN useradd --create-home --shell /usr/sbin/nologin angel

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN python -m compileall -q bot.py angel cogs tools \
    && mkdir -p /app/data \
    && chown -R angel:angel /app/data \
    && chmod 700 /app/data

USER angel

CMD ["sh", "-c", "python bot.py --checkpoint-db && python bot.py"]
