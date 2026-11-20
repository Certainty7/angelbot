# syntax=docker/dockerfile:1
# Hardened image: pinned Deno release (no curl|sh), code read-only to the non-root user,
# only /app/data writable.
FROM python:3.12-slim-bookworm AS base

# Deno 2.9+ is required by yt-dlp-ejs for current YouTube challenges. Hashes are the
# published .sha256sum assets of this exact release, not values typed by hand.
ARG DENO_VERSION=v2.9.8
ARG DENO_SHA256_AMD64=e890975bc2549807bbcc0b584ffafda72cc7c93349dd99c80483dd784f6c4609
ARG DENO_SHA256_ARM64=d49596c20b9788cf8f5d8ddf644103d4bde56ed239753f0bdb92ba9361d51905
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    ANGEL_DB_PATH=/app/data/angel.db

# sqlite3 is required by scripts/backup_db.sh; curl/unzip are only needed to fetch Deno and
# are purged in the same layer so they cannot be used later by a compromised process.
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    ca-certificates \
    curl \
    unzip \
    sqlite3 \
    libopus0 \
    procps \
    && ARCH="$(dpkg --print-architecture)" \
    && case "$ARCH" in \
         amd64) DENO_ARCH="x86_64-unknown-linux-gnu"; DENO_SHA="$DENO_SHA256_AMD64" ;; \
         arm64) DENO_ARCH="aarch64-unknown-linux-gnu"; DENO_SHA="$DENO_SHA256_ARM64" ;; \
         *) echo "Unsupported arch: $ARCH" >&2; exit 1 ;; \
       esac \
    && curl -fsSL "https://github.com/denoland/deno/releases/download/${DENO_VERSION}/deno-${DENO_ARCH}.zip" -o /tmp/deno.zip \
    && echo "${DENO_SHA}  /tmp/deno.zip" | sha256sum -c - \
    && unzip -q /tmp/deno.zip -d /usr/local/bin \
    && chmod 0755 /usr/local/bin/deno \
    && deno --version \
    && rm -f /tmp/deno.zip \
    && apt-get purge -y --auto-remove curl unzip \
    && rm -rf /var/lib/apt/lists/*

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

# The database is created by the bot on first boot, so the checkpoint only runs when it exists.
HEALTHCHECK --interval=60s --timeout=10s --start-period=45s --retries=3 \
    CMD sqlite3 -readonly "$ANGEL_DB_PATH" 'PRAGMA quick_check;' >/dev/null 2>&1 || \
        { [ ! -f "$ANGEL_DB_PATH" ] && exit 0; exit 1; }

CMD ["sh", "-c", "python bot.py --checkpoint-db && exec python bot.py"]
