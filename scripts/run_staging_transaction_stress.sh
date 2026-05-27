#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
STAGING_URL="${STAGING_DATABASE_URL:-}"
ALLOW_NON_STAGING_URL="${ALLOW_NON_STAGING_URL:-0}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
ARTIFACT_DIR="$ROOT_DIR/backups/staging-validation/${STAMP}_transaction_stress"

mkdir -p "$ARTIFACT_DIR"

if [[ -z "$STAGING_URL" ]]; then
  printf 'STAGING_DATABASE_URL is not set.\n' >&2
  exit 1
fi

if [[ "$ALLOW_NON_STAGING_URL" != "1" ]] && [[ "$STAGING_URL" != *staging* ]]; then
  printf 'Safety check failed: STAGING_DATABASE_URL does not look like a staging URL. Set ALLOW_NON_STAGING_URL=1 to override.\n' >&2
  exit 1
fi

export PGSSLMODE="${PGSSLMODE:-require}"

pass() { printf 'PASS: %s\n' "$1"; }
fail() { printf 'FAIL: %s\n' "$1" >&2; exit 1; }

printf 'Running transaction stress tests against staging only. Artifacts: %s\n' "$ARTIFACT_DIR"

# Test 1: Double checkout submit with same idempotency key.
IFS='|' read -r CHECKOUT_ITEM_ID CHECKOUT_PRICE CHECKOUT_QTY <<< "$(psql "$STAGING_URL" -At -F '|' -c "
  SELECT id::text, GREATEST(COALESCE(selling_price, 0), 1)::text, COALESCE(quantity, 0)::text
  FROM inventory_items
  WHERE COALESCE(quantity, 0) >= 2
  ORDER BY quantity DESC, updated_at DESC NULLS LAST
  LIMIT 1
")"

[[ -z "${CHECKOUT_ITEM_ID:-}" ]] && fail "No inventory item with quantity >= 2 found for checkout stress test"

DUP_KEY="stress-checkout-dup-${STAMP}"

psql "$STAGING_URL" -v ON_ERROR_STOP=1 -c "
SELECT * FROM checkout_inventory_cart_tx(
  jsonb_build_array(jsonb_build_object('item_id', '$CHECKOUT_ITEM_ID', 'quantity', 1, 'unit_price', $CHECKOUT_PRICE)),
  NULL,
  'Stress User',
  NULL,
  0,
  'cash',
  0,
  'Duplicate checkout submit stress test',
  'stress-runner',
  '$DUP_KEY'
);
" > "$ARTIFACT_DIR/double_checkout_a.txt" 2>&1 &
PID_A=$!

psql "$STAGING_URL" -v ON_ERROR_STOP=1 -c "
SELECT * FROM checkout_inventory_cart_tx(
  jsonb_build_array(jsonb_build_object('item_id', '$CHECKOUT_ITEM_ID', 'quantity', 1, 'unit_price', $CHECKOUT_PRICE)),
  NULL,
  'Stress User',
  NULL,
  0,
  'cash',
  0,
  'Duplicate checkout submit stress test',
  'stress-runner',
  '$DUP_KEY'
);
" > "$ARTIFACT_DIR/double_checkout_b.txt" 2>&1 &
PID_B=$!

wait "$PID_A" || true
wait "$PID_B" || true

DUP_SALES_COUNT="$(psql "$STAGING_URL" -At -c "SELECT COUNT(*)::text FROM inventory_sales WHERE checkout_idempotency_key = '$DUP_KEY';")"
[[ "$DUP_SALES_COUNT" == "1" ]] || fail "Expected 1 sale row for duplicate checkout idempotency key, found $DUP_SALES_COUNT"
pass "Double checkout submit idempotency"

# Test 2: Simultaneous stock deduction with different keys should never produce negative stock.
IFS='|' read -r RACE_ITEM_ID RACE_QTY RACE_PRICE <<< "$(psql "$STAGING_URL" -At -F '|' -c "
  SELECT id::text, COALESCE(quantity, 0)::text, GREATEST(COALESCE(selling_price, 0), 1)::text
  FROM inventory_items
  WHERE COALESCE(quantity, 0) >= 1
  ORDER BY quantity ASC, updated_at DESC NULLS LAST
  LIMIT 1
")"

[[ -z "${RACE_ITEM_ID:-}" ]] && fail "No inventory item found for race-condition stock test"

RACE_REQ_QTY="$RACE_QTY"
KEY_ONE="stress-race-1-${STAMP}"
KEY_TWO="stress-race-2-${STAMP}"

psql "$STAGING_URL" -v ON_ERROR_STOP=1 -c "
SELECT * FROM checkout_inventory_cart_tx(
  jsonb_build_array(jsonb_build_object('item_id', '$RACE_ITEM_ID', 'quantity', $RACE_REQ_QTY, 'unit_price', $RACE_PRICE)),
  NULL,
  'Race User 1',
  NULL,
  0,
  'cash',
  0,
  'Race stock deduction test A',
  'stress-runner',
  '$KEY_ONE'
);
" > "$ARTIFACT_DIR/race_checkout_a.txt" 2>&1 &
RACE_A=$!

psql "$STAGING_URL" -v ON_ERROR_STOP=1 -c "
SELECT * FROM checkout_inventory_cart_tx(
  jsonb_build_array(jsonb_build_object('item_id', '$RACE_ITEM_ID', 'quantity', $RACE_REQ_QTY, 'unit_price', $RACE_PRICE)),
  NULL,
  'Race User 2',
  NULL,
  0,
  'cash',
  0,
  'Race stock deduction test B',
  'stress-runner',
  '$KEY_TWO'
);
" > "$ARTIFACT_DIR/race_checkout_b.txt" 2>&1 &
RACE_B=$!

wait "$RACE_A" || true
wait "$RACE_B" || true

AFTER_RACE_QTY="$(psql "$STAGING_URL" -At -c "SELECT COALESCE(quantity, 0)::text FROM inventory_items WHERE id = '$RACE_ITEM_ID';")"
[[ "${AFTER_RACE_QTY:-0}" =~ ^- ]] && fail "Inventory became negative after concurrent deductions (quantity=$AFTER_RACE_QTY)"
pass "Simultaneous stock deduction never produced negative quantity"

# Test 3: Duplicate idempotency key reuse for payment apply should create one payment record.
IFS='|' read -r PAY_JOB_ID PAY_BALANCE <<< "$(psql "$STAGING_URL" -At -F '|' -c "
  SELECT id::text, GREATEST(COALESCE(amount_charged, 0) - COALESCE(paid_amount, 0), 0)::text
  FROM service_jobs
  WHERE COALESCE(amount_charged, 0) > COALESCE(paid_amount, 0)
  ORDER BY service_date DESC NULLS LAST, created_at DESC NULLS LAST
  LIMIT 1
")"

if [[ -n "${PAY_JOB_ID:-}" && "${PAY_BALANCE:-0}" != "0" ]]; then
  APPLY_AMOUNT="$(python3 - <<'PY'
import os
bal=float(os.environ.get('PAY_BALANCE','0') or 0)
print(f"{min(bal,1.0):.2f}")
PY
)"
  PAY_KEY="stress-payment-dup-${STAMP}"

  psql "$STAGING_URL" -v ON_ERROR_STOP=1 -c "
SELECT * FROM apply_service_payment_tx(
  '$PAY_JOB_ID'::uuid,
  $APPLY_AMOUNT,
  'cash',
  'Duplicate payment idempotency test',
  NULL,
  CURRENT_DATE,
  'stress-runner',
  'Stress Runner',
  '$PAY_KEY'
);
" > "$ARTIFACT_DIR/payment_dup_a.txt"

  psql "$STAGING_URL" -v ON_ERROR_STOP=1 -c "
SELECT * FROM apply_service_payment_tx(
  '$PAY_JOB_ID'::uuid,
  $APPLY_AMOUNT,
  'cash',
  'Duplicate payment idempotency test',
  NULL,
  CURRENT_DATE,
  'stress-runner',
  'Stress Runner',
  '$PAY_KEY'
);
" > "$ARTIFACT_DIR/payment_dup_b.txt"

  PAY_DUP_COUNT="$(psql "$STAGING_URL" -At -c "SELECT COUNT(*)::text FROM payments WHERE idempotency_key = '$PAY_KEY';")"
  [[ "$PAY_DUP_COUNT" == "1" ]] || fail "Expected one payment row for duplicated payment idempotency key, found $PAY_DUP_COUNT"
  pass "Duplicate payment idempotency key reuse"
else
  printf 'SKIP: No eligible service_job found for payment idempotency test\n'
fi

# Test 4: Apply and reverse payment concurrently should maintain valid paid range.
IFS='|' read -r CONC_JOB_ID CONC_AMOUNT <<< "$(psql "$STAGING_URL" -At -F '|' -c "
  SELECT id::text, LEAST(GREATEST(COALESCE(amount_charged, 0) - COALESCE(paid_amount, 0), 0), 1)::text
  FROM service_jobs
  WHERE COALESCE(amount_charged, 0) > COALESCE(paid_amount, 0)
  ORDER BY service_date DESC NULLS LAST, created_at DESC NULLS LAST
  LIMIT 1
")"

if [[ -n "${CONC_JOB_ID:-}" && "${CONC_AMOUNT:-0}" != "0" ]]; then
  APPLY_KEY="stress-conc-apply-${STAMP}"
  REV_KEY="stress-conc-rev-${STAMP}"

  psql "$STAGING_URL" -v ON_ERROR_STOP=1 -c "
SELECT * FROM apply_service_payment_tx(
  '$CONC_JOB_ID'::uuid,
  $CONC_AMOUNT,
  'cash',
  'Concurrent apply test',
  NULL,
  CURRENT_DATE,
  'stress-runner',
  'Stress Runner',
  '$APPLY_KEY'
);
" > "$ARTIFACT_DIR/concurrent_apply.txt" 2>&1 &
  APPLY_PID=$!

  psql "$STAGING_URL" -v ON_ERROR_STOP=1 -c "
SELECT * FROM reverse_service_payment_tx(
  '$CONC_JOB_ID'::uuid,
  $CONC_AMOUNT,
  'Concurrent reverse test',
  'stress-runner',
  'Stress Runner',
  CURRENT_DATE,
  '$REV_KEY'
);
" > "$ARTIFACT_DIR/concurrent_reverse.txt" 2>&1 &
  REV_PID=$!

  wait "$APPLY_PID" || true
  wait "$REV_PID" || true

  RANGE_OK="$(psql "$STAGING_URL" -At -c "
SELECT CASE WHEN COALESCE(paid_amount, 0) >= 0 AND COALESCE(paid_amount, 0) <= COALESCE(amount_charged, 0)
THEN '1' ELSE '0' END
FROM service_jobs
WHERE id = '$CONC_JOB_ID';
")"
  [[ "$RANGE_OK" == "1" ]] || fail "Concurrent apply/reverse produced invalid paid_amount range"
  pass "Concurrent apply/reverse keeps paid_amount within valid range"
else
  printf 'SKIP: No eligible service_job found for concurrent apply/reverse test\n'
fi

# Test 5: Append-only and audit immutability checks.
LATEST_PAYMENT_ID="$(psql "$STAGING_URL" -At -c "SELECT id::text FROM payments ORDER BY created_at DESC NULLS LAST LIMIT 1;")"
if [[ -n "${LATEST_PAYMENT_ID:-}" ]]; then
  if psql "$STAGING_URL" -v ON_ERROR_STOP=1 -c "UPDATE payments SET notes = 'should fail' WHERE id = '$LATEST_PAYMENT_ID'::uuid;" > "$ARTIFACT_DIR/payments_update_attempt.txt" 2>&1; then
    fail "Payments append-only enforcement failed (UPDATE succeeded)"
  fi
  pass "Payments append-only enforcement"
fi

LATEST_AUDIT_ID="$(psql "$STAGING_URL" -At -c "SELECT id::text FROM audit_logs ORDER BY created_at DESC NULLS LAST LIMIT 1;")"
if [[ -n "${LATEST_AUDIT_ID:-}" ]]; then
  if psql "$STAGING_URL" -v ON_ERROR_STOP=1 -c "UPDATE audit_logs SET action = action WHERE id = '$LATEST_AUDIT_ID'::uuid;" > "$ARTIFACT_DIR/audit_update_attempt.txt" 2>&1; then
    fail "Audit immutability failed (UPDATE succeeded)"
  fi
  pass "Audit immutability enforcement"
fi

# Test 6: Rollback behavior under partial failure.
ROLLBACK_KEY="stress-rollback-${STAMP}"
psql "$STAGING_URL" -v ON_ERROR_STOP=1 -c "
BEGIN;
SELECT * FROM checkout_inventory_cart_tx(
  jsonb_build_array(jsonb_build_object('item_id', '$CHECKOUT_ITEM_ID', 'quantity', 1, 'unit_price', $CHECKOUT_PRICE)),
  NULL,
  'Rollback User',
  NULL,
  0,
  'cash',
  0,
  'Rollback simulation',
  'stress-runner',
  '$ROLLBACK_KEY'
);
ROLLBACK;
" > "$ARTIFACT_DIR/rollback_simulation.txt"

ROLLBACK_COUNT="$(psql "$STAGING_URL" -At -c "SELECT COUNT(*)::text FROM inventory_sales WHERE checkout_idempotency_key = '$ROLLBACK_KEY';")"
[[ "$ROLLBACK_COUNT" == "0" ]] || fail "Rollback simulation left persisted checkout rows"
pass "Rollback behavior for checkout transaction"

printf 'All staging transaction stress checks completed. Artifacts: %s\n' "$ARTIFACT_DIR"
