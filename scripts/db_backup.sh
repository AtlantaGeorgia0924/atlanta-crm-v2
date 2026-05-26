#!/usr/bin/env bash

set -euo pipefail

usage() {
  cat <<'EOF'
Usage: scripts/db_backup.sh [--url-env ENV_NAME] [--label LABEL] [--output-dir DIR]

Creates a full PostgreSQL backup using pg_dump in custom format and a matching
schema-only SQL dump. The database URL is read from an environment variable.

Options:
  --url-env ENV_NAME   Environment variable containing the Postgres URL.
                       Default: DATABASE_URL
  --label LABEL        Extra label appended to the backup folder name.
  --output-dir DIR     Backup root directory. Default: backups/db
  -h, --help           Show this help text.
EOF
}

sanitize_label() {
  printf '%s' "$1" | tr -cs 'A-Za-z0-9._-' '-'
}

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
URL_ENV="DATABASE_URL"
OUTPUT_DIR="$ROOT_DIR/backups/db"
LABEL="manual"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --url-env)
      URL_ENV="$2"
      shift 2
      ;;
    --label)
      LABEL="$2"
      shift 2
      ;;
    --output-dir)
      OUTPUT_DIR="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      printf 'Unknown argument: %s\n' "$1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

if ! command -v pg_dump >/dev/null 2>&1; then
  printf 'pg_dump is required but was not found in PATH.\n' >&2
  exit 1
fi

DB_URL="${!URL_ENV:-}"
if [[ -z "$DB_URL" ]]; then
  printf 'Environment variable %s is not set.\n' "$URL_ENV" >&2
  exit 1
fi

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
SAFE_LABEL="$(sanitize_label "$LABEL")"
BACKUP_DIR="$OUTPUT_DIR/${STAMP}_${SAFE_LABEL}"

mkdir -p "$BACKUP_DIR"

export PGSSLMODE="${PGSSLMODE:-require}"

pg_dump "$DB_URL" \
  --format=custom \
  --no-owner \
  --no-privileges \
  --file "$BACKUP_DIR/full.dump"

pg_dump "$DB_URL" \
  --schema-only \
  --no-owner \
  --no-privileges \
  --file "$BACKUP_DIR/schema.sql"

cat > "$BACKUP_DIR/manifest.txt" <<EOF
timestamp_utc=$STAMP
label=$SAFE_LABEL
url_env=$URL_ENV
pgsslmode=$PGSSLMODE
full_dump=$BACKUP_DIR/full.dump
schema_dump=$BACKUP_DIR/schema.sql
EOF

printf 'Backup written to %s\n' "$BACKUP_DIR"