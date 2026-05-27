#!/usr/bin/env bash

set -euo pipefail

# Periodic restore verification helper.
# This script restores a backup dump into a non-production verification database
# and runs lightweight sanity checks.

if [[ $# -lt 1 ]]; then
  printf 'Usage: scripts/verify_backup_restore.sh <path-to-full.dump>\n' >&2
  exit 1
fi

DUMP_FILE="$1"
VERIFY_DB_URL="${RESTORE_VERIFY_DATABASE_URL:-}"

if [[ -z "$VERIFY_DB_URL" ]]; then
  printf 'RESTORE_VERIFY_DATABASE_URL is not set.\n' >&2
  exit 1
fi

if [[ ! -f "$DUMP_FILE" ]]; then
  printf 'Dump file not found: %s\n' "$DUMP_FILE" >&2
  exit 1
fi

if ! command -v pg_restore >/dev/null 2>&1; then
  printf 'pg_restore is required but was not found in PATH.\n' >&2
  exit 1
fi

if ! command -v psql >/dev/null 2>&1; then
  printf 'psql is required but was not found in PATH.\n' >&2
  exit 1
fi

export PGSSLMODE="${PGSSLMODE:-require}"

pg_restore "$DUMP_FILE" \
  --clean \
  --if-exists \
  --no-owner \
  --no-privileges \
  --dbname "$VERIFY_DB_URL"

psql "$VERIFY_DB_URL" -v ON_ERROR_STOP=1 -c "SELECT COUNT(*) AS service_jobs_rows FROM service_jobs;"
psql "$VERIFY_DB_URL" -v ON_ERROR_STOP=1 -c "SELECT COUNT(*) AS inventory_rows FROM inventory_items;"
psql "$VERIFY_DB_URL" -v ON_ERROR_STOP=1 -c "SELECT COUNT(*) AS payments_rows FROM payments;"
psql "$VERIFY_DB_URL" -v ON_ERROR_STOP=1 -c "SELECT COUNT(*) AS audit_rows FROM crm_audit_log;"

printf 'Restore verification succeeded for %s\n' "$DUMP_FILE"
