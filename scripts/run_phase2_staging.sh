#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
BASELINE_FILE="$ROOT_DIR/database/validation/025_phase2_core_restructure_baseline.sql"
MIGRATION_FILE="$ROOT_DIR/database/migrations/025_phase2_core_restructure.sql"
ROLLBACK_FILE="$ROOT_DIR/database/migrations/025_phase2_core_restructure.rollback.sql"
VALIDATION_FILE="$ROOT_DIR/database/validation/025_phase2_core_restructure_validation.sql"
ROLLBACK_VALIDATION_FILE="$ROOT_DIR/database/validation/025_phase2_core_restructure_rollback_validation.sql"
STAGING_URL="${STAGING_DATABASE_URL:-}"
VERIFY_ROLLBACK="${VERIFY_ROLLBACK:-1}"
RUN_BASELINE="${RUN_BASELINE:-1}"

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
ARTIFACT_DIR="$ROOT_DIR/backups/staging-validation/${STAMP}_phase2_core_restructure"

if ! command -v psql >/dev/null 2>&1; then
  printf 'psql is required but was not found in PATH.\n' >&2
  exit 1
fi

if [[ -z "$STAGING_URL" ]]; then
  printf 'STAGING_DATABASE_URL is not set.\n' >&2
  exit 1
fi

mkdir -p "$ARTIFACT_DIR"

"$ROOT_DIR/scripts/db_backup.sh" --url-env STAGING_DATABASE_URL --label phase2-staging-preflight

export PGSSLMODE="${PGSSLMODE:-require}"

if [[ "$RUN_BASELINE" == "1" ]]; then
  psql "$STAGING_URL" -v ON_ERROR_STOP=1 -f "$BASELINE_FILE" > "$ARTIFACT_DIR/baseline.txt"
fi

psql "$STAGING_URL" -v ON_ERROR_STOP=1 -f "$MIGRATION_FILE"
psql "$STAGING_URL" -v ON_ERROR_STOP=1 -f "$VALIDATION_FILE" > "$ARTIFACT_DIR/post_migration_validation.txt"

if [[ "$VERIFY_ROLLBACK" == "1" ]]; then
  psql "$STAGING_URL" -v ON_ERROR_STOP=1 -f "$ROLLBACK_FILE"
  psql "$STAGING_URL" -v ON_ERROR_STOP=1 -f "$ROLLBACK_VALIDATION_FILE" > "$ARTIFACT_DIR/rollback_validation.txt"
fi

printf 'Phase 2 staging migration completed successfully. Artifacts: %s\n' "$ARTIFACT_DIR"