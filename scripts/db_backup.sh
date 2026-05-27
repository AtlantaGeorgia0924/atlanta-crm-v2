#!/usr/bin/env bash

set -euo pipefail

usage() {
  cat <<'EOF'
Usage: scripts/db_backup.sh [options]

Creates disaster-recovery backups with:
- full PostgreSQL custom dump
- schema-only SQL dump
- CSV exports for key tables (human-readable)

Options:
  --url-env ENV_NAME     Environment variable containing Postgres URL (default: DATABASE_URL)
  --label LABEL          Label appended to backup folder name
  --output-dir DIR       Backup root directory (default: backups/db)
  --csv-tables LIST      Comma-separated table list for CSV export
  --skip-csv             Skip CSV export stage
  --gcs-uri URI          Upload backup directory to GCS (example: gs://my-bucket/db-backups)
  -h, --help             Show this help text
EOF
}

sanitize_label() {
  printf '%s' "$1" | tr -cs 'A-Za-z0-9._-' '-'
}

table_exists() {
  local table_name="$1"
  psql "$DB_URL" -Atqc "SELECT CASE WHEN to_regclass('public.${table_name}') IS NULL THEN '0' ELSE '1' END;" | grep -q '^1$'
}

export_csv_table() {
  local table_name="$1"
  local csv_file="$CSV_DIR/${table_name}.csv"

  if ! table_exists "$table_name"; then
    printf 'Skipping CSV for missing table: %s\n' "$table_name"
    return 0
  fi

  psql "$DB_URL" -v ON_ERROR_STOP=1 -c "\\copy (SELECT * FROM \"${table_name}\") TO '${csv_file}' CSV HEADER"
  printf 'CSV exported: %s\n' "$csv_file"
}

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
URL_ENV="DATABASE_URL"
OUTPUT_DIR="$ROOT_DIR/backups/db"
LABEL="manual"
SKIP_CSV=0
GCS_URI=""
CSV_TABLES="clients,service_jobs,inventory_items,payments,service_payments,sale_payments,inventory_sales,inventory_sale_items,inventory_transactions,inventory_movement_history,stock_adjustment_audit,crm_audit_log,audit_logs"

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
    --csv-tables)
      CSV_TABLES="$2"
      shift 2
      ;;
    --skip-csv)
      SKIP_CSV=1
      shift
      ;;
    --gcs-uri)
      GCS_URI="$2"
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

if ! command -v psql >/dev/null 2>&1; then
  printf 'psql is required but was not found in PATH.\n' >&2
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
CSV_DIR="$BACKUP_DIR/csv"

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

if [[ "$SKIP_CSV" == "0" ]]; then
  mkdir -p "$CSV_DIR"
  IFS=',' read -r -a CSV_TABLE_ARRAY <<< "$CSV_TABLES"
  for table_name in "${CSV_TABLE_ARRAY[@]}"; do
    clean_table="$(printf '%s' "$table_name" | xargs)"
    [[ -z "$clean_table" ]] && continue
    export_csv_table "$clean_table"
  done
fi

if [[ -n "$GCS_URI" ]]; then
  if command -v gsutil >/dev/null 2>&1; then
    gsutil -m cp -r "$BACKUP_DIR" "$GCS_URI/"
  else
    printf 'gsutil was not found in PATH; cannot upload to GCS.\n' >&2
    exit 1
  fi
fi

cat > "$BACKUP_DIR/manifest.txt" <<EOF
timestamp_utc=$STAMP
label=$SAFE_LABEL
url_env=$URL_ENV
pgsslmode=$PGSSLMODE
full_dump=$BACKUP_DIR/full.dump
schema_dump=$BACKUP_DIR/schema.sql
csv_dir=$CSV_DIR
skip_csv=$SKIP_CSV
gcs_uri=${GCS_URI:-none}
EOF

printf 'Backup written to %s\n' "$BACKUP_DIR"
