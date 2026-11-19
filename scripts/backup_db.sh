#!/usr/bin/env bash
# Atomic SQLite WAL backup + read-only integrity verification.
# Runs safely while the bot is live; keep it OUTSIDE the bot's ReadWritePaths.
set -euo pipefail
umask 077

DB_PATH="${ANGEL_DB_PATH:-/opt/angelbot/data/angel.db}"
BACKUP_DIR="${ANGEL_BACKUP_DIR:-/opt/angelbot/backups}"
RETENTION_DAYS="${ANGEL_BACKUP_RETENTION_DAYS:-14}"

if ! [[ "$RETENTION_DAYS" =~ ^[0-9]+$ ]] || [[ "$RETENTION_DAYS" -lt 1 ]]; then
  echo "[ERROR] ANGEL_BACKUP_RETENTION_DAYS must be a positive integer" >&2
  exit 1
fi

if [[ "$DB_PATH" == *"'"* ]] || [[ "$BACKUP_DIR" == *"'"* ]] || [[ "$BACKUP_DIR" == *$'\n'* ]]; then
  echo "[ERROR] Paths must not contain single quotes or newlines" >&2
  exit 1
fi

if ! command -v sqlite3 >/dev/null 2>&1; then
  echo "[ERROR] sqlite3 CLI is required (apt install sqlite3)" >&2
  exit 1
fi

if [[ ! -f "$DB_PATH" ]]; then
  echo "[ERROR] Database file not found: $DB_PATH" >&2
  exit 1
fi

mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"

STAMP="$(date -u +%Y%m%d_%H%M%S)"
OUT_FILE="${BACKUP_DIR}/angel_${STAMP}.db"

# 1. Online atomic backup with a busy timeout (safe in WAL mode while the bot writes).
sqlite3 -cmd ".timeout 10000" "$DB_PATH" ".backup '${OUT_FILE}'"
chmod 600 "$OUT_FILE"

# 2. Verify the copy in read-only mode (no URI query string, so ?/# in a path is harmless).
INTEGRITY="$(sqlite3 -readonly "$OUT_FILE" 'PRAGMA integrity_check;')"
if [[ "$INTEGRITY" != "ok" ]]; then
  echo "[ERROR] Backup integrity check failed: $INTEGRITY" >&2
  rm -f "$OUT_FILE"
  exit 1
fi

# 3. Prune backups older than the retention window.
find "$BACKUP_DIR" -maxdepth 1 -name 'angel_*.db' -type f -mtime "+${RETENTION_DAYS}" -delete

echo "[OK] Verified backup created: ${OUT_FILE} (integrity_check=ok)"
