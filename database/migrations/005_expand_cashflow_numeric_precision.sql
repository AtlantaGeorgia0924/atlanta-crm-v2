-- Migration: Expand cashflow_summary numeric precision to support large totals
-- Reason: numeric(12,2) max value is 99,999,999.99 - too small for large businesses
-- New: numeric(18,2) max value is 999,999,999,999,999.99
-- Targets the live refresh path in app/core/cashflow_sheet_sync.py

ALTER TABLE cashflow_summary
ALTER COLUMN weekly_paid_profits TYPE numeric(18,2),
ALTER COLUMN weekly_expenses TYPE numeric(18,2),
ALTER COLUMN weekly_net_profit TYPE numeric(18,2),
ALTER COLUMN next_week_allowance TYPE numeric(18,2),
ALTER COLUMN monthly_net_profit TYPE numeric(18,2),
ALTER COLUMN allowances_withdrawn TYPE numeric(18,2),
ALTER COLUMN monthly_net_profit_left TYPE numeric(18,2);

-- Verify changes
SELECT column_name, data_type, numeric_precision, numeric_scale
FROM information_schema.columns
WHERE table_name = 'cashflow_summary' AND table_schema = 'public'
ORDER BY column_name;
