#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
MIGRATION_FILE="$ROOT_DIR/database/migrations/025_phase2_core_restructure.sql"
ROLLBACK_FILE="$ROOT_DIR/database/migrations/025_phase2_core_restructure.rollback.sql"
VALIDATION_FILE="$ROOT_DIR/database/validation/025_phase2_core_restructure_validation.sql"
STAGING_URL="${STAGING_DATABASE_URL:-}"
AUTO_ROLLBACK="${ROLLBACK_AFTER_VALIDATE:-0}"

if ! command -v psql >/dev/null 2>&1; then
  printf 'psql is required but was not found in PATH.\n' >&2
  exit 1
fi

if [[ -z "$STAGING_URL" ]]; then
  printf 'STAGING_DATABASE_URL is not set.\n' >&2
  exit 1
fi

"$ROOT_DIR/scripts/db_backup.sh" --url-env STAGING_DATABASE_URL --label phase2-staging-preflight

export PGSSLMODE="${PGSSLMODE:-require}"

psql "$STAGING_URL" -v ON_ERROR_STOP=1 -f "$MIGRATION_FILE"
psql "$STAGING_URL" -v ON_ERROR_STOP=1 -f "$VALIDATION_FILE"

if [[ "$AUTO_ROLLBACK" == "1" ]]; then
  psql "$STAGING_URL" -v ON_ERROR_STOP=1 -f "$ROLLBACK_FILE"
fi

printf 'Phase 2 staging migration completed successfully.\n'