#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
BASELINE_FILE="$ROOT_DIR/database/validation/025_phase2_core_restructure_baseline.sql"
MIGRATION_FILES=(
  "$ROOT_DIR/database/migrations/025_phase2_core_restructure.sql"
  "$ROOT_DIR/database/migrations/026_transaction_safety_hardening.sql"
)
VALIDATION_FILES=(
  "$ROOT_DIR/database/validation/025_phase2_core_restructure_validation.sql"
  "$ROOT_DIR/database/validation/026_transaction_safety_hardening_validation.sql"
)
ROLLBACK_FILES=(
  "$ROOT_DIR/database/migrations/026_transaction_safety_hardening.rollback.sql"
  "$ROOT_DIR/database/migrations/025_phase2_core_restructure.rollback.sql"
)
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

for migration_file in "${MIGRATION_FILES[@]}"; do
  psql "$STAGING_URL" -v ON_ERROR_STOP=1 -f "$migration_file"
done

for validation_file in "${VALIDATION_FILES[@]}"; do
  validation_name="$(basename "$validation_file" .sql)"
  psql "$STAGING_URL" -v ON_ERROR_STOP=1 -f "$validation_file" > "$ARTIFACT_DIR/${validation_name}.txt"
done

if [[ "$VERIFY_ROLLBACK" == "1" ]]; then
  for rollback_file in "${ROLLBACK_FILES[@]}"; do
    psql "$STAGING_URL" -v ON_ERROR_STOP=1 -f "$rollback_file"
  done
  psql "$STAGING_URL" -v ON_ERROR_STOP=1 -f "$ROLLBACK_VALIDATION_FILE" > "$ARTIFACT_DIR/rollback_validation.txt"
fi

printf 'Phase 2 staging migration completed successfully. Artifacts: %s\n' "$ARTIFACT_DIR"